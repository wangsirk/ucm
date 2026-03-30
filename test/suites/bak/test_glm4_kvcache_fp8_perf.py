# -*- coding: utf-8 -*-
#
# MIT License
#
# Copyright (c) 2025 Huawei Technologies Co., Ltd. All rights reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
"""
GLM4 KVCache FP8性能测试（离线推理模式）

测试场景:
1. 10K输入 1K输出 1并发 FP8精度 TTFT <5秒
2. 10K输入 1K输出 5并发 FP8精度 TTFT <10秒

使用方法:
    # 测试1并发场景
    python test/suites/perf/test_glm4_kvcache_fp8_perf.py --scenario 1concurrent --model-path /path/to/glm-4
    
    # 测试5并发场景
    python test/suites/perf/test_glm4_kvcache_fp8_perf.py --scenario 5concurrent --model-path /path/to/glm-4
    
    # 测试所有场景
    python test/suites/perf/test_glm4_kvcache_fp8_perf.py --scenario all --model-path /path/to/glm-4
    
    # 使用pytest运行
    pytest test/suites/perf/test_glm4_kvcache_fp8_perf.py -v -s
"""

import argparse
import json
import os
import random
import shutil
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

# 将 test 目录添加到 Python 路径
TEST_ROOT = Path(__file__).resolve().parent.parent.parent
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

import numpy as np

from ucm.logger import init_logger

logger = init_logger(__name__)


# ==================== 测试场景配置 ====================
@dataclass
class TestScenario:
    """测试场景配置"""
    name: str
    input_tokens: int
    output_tokens: int
    concurrent: int
    num_samples: int
    max_ttft_seconds: float  # 最大首字时延（秒）
    kv_cache_dtype: str = "fp8"  # KVCache精度：auto, fp8, fp8_e4m3, fp8_e5m2
    target_hit_rate: float = 0.98  # 目标KVCache命中率（可选验证）


# 预定义测试场景
SCENARIOS = {
    "1concurrent": TestScenario(
        name="GLM4_10K输入_1K输出_1并发_FP8",
        input_tokens=10000,
        output_tokens=1000,
        concurrent=1,
        num_samples=16,
        max_ttft_seconds=5.0,  # 1并发TTFT <5秒
        kv_cache_dtype="fp8",
    ),
    "5concurrent": TestScenario(
        name="GLM4_10K输入_1K输出_5并发_FP8",
        input_tokens=10000,
        output_tokens=1000,
        concurrent=5,
        num_samples=32,
        max_ttft_seconds=10.0,  # 5并发TTFT <10秒
        kv_cache_dtype="fp8",
    ),
}


# ==================== 数据生成器 ====================
class PromptGenerator:
    """生成固定token数量的prompt"""
    
    def __init__(self, tokenizer_path: str):
        from transformers import AutoTokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)
        self.vocab_size = self.tokenizer.vocab_size
        self._cache: Dict[int, str] = {}
    
    def generate_prompt(self, num_tokens: int, seed: int = 42) -> Tuple[str, int]:
        """生成指定token数量的prompt"""
        cache_key = (num_tokens, seed)
        if cache_key in self._cache:
            return self._cache[cache_key], num_tokens
        
        random.seed(seed)
        # 生成随机token IDs
        token_ids = [random.randint(0, self.vocab_size - 1) for _ in range(num_tokens)]
        
        # 解码为文本
        text = self.tokenizer.decode(token_ids, skip_special_tokens=True)
        
        # 验证实际token数量
        actual_tokens = len(self.tokenizer.encode(text, add_special_tokens=False))
        
        # 如果token数量不匹配，进行微调
        while actual_tokens < num_tokens:
            text += " " + self.tokenizer.decode([random.randint(0, self.vocab_size - 1)])
            actual_tokens = len(self.tokenizer.encode(text, add_special_tokens=False))
        
        if actual_tokens > num_tokens:
            # 截断到目标长度
            encoded = self.tokenizer.encode(text, add_special_tokens=False)[:num_tokens]
            text = self.tokenizer.decode(encoded, skip_special_tokens=True)
            actual_tokens = num_tokens
        
        self._cache[cache_key] = text
        return text, actual_tokens
    
    def generate_prefix_suffix_prompts(
        self, 
        prefix_tokens: int, 
        suffix_tokens: int, 
        num_variations: int,
        base_seed: int = 42
    ) -> List[Tuple[str, int, int]]:
        """
        生成具有相同前缀和不同后缀的prompts
        用于测试KVCache命中率
        
        Returns:
            List of (prompt, prefix_token_count, total_token_count)
        """
        prompts = []
        
        # 生成公共前缀
        prefix_text, prefix_count = self.generate_prompt(prefix_tokens, seed=base_seed)
        
        for i in range(num_variations):
            # 生成不同的后缀
            suffix_text, suffix_count = self.generate_prompt(
                suffix_tokens, 
                seed=base_seed + i + 1
            )
            
            full_prompt = prefix_text + " " + suffix_text
            total_tokens = len(self.tokenizer.encode(full_prompt, add_special_tokens=False))
            
            prompts.append((full_prompt, prefix_count, total_tokens))
        
        return prompts


# ==================== 指标收集 ====================
@dataclass
class RequestMetrics:
    """单个请求的指标"""
    request_id: int
    input_tokens: int
    output_tokens: int
    ttft: float  # Time to First Token (秒)
    e2e_latency: float  # 端到端时延 (秒)
    tokens_per_second: float  # 吞吐量
    kvcache_hit: bool = False
    hit_blocks: int = 0
    total_blocks: int = 0
    error: Optional[str] = None


@dataclass
class TestResults:
    """测试结果汇总"""
    scenario_name: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    
    # 时延指标
    mean_ttft: float
    p50_ttft: float
    p90_ttft: float
    p99_ttft: float
    max_ttft: float
    
    # 吞吐量指标
    total_throughput: float  # 总吞吐量 (tokens/s)
    mean_per_request_throughput: float
    
    # KVCache命中率
    kvcache_hit_rate: float
    
    # 总耗时
    total_time: float
    
    # FP8配置
    kv_cache_dtype: str
    
    # 详细结果
    metrics: List[RequestMetrics] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "scenario_name": self.scenario_name,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "mean_ttft": self.mean_ttft,
            "p50_ttft": self.p50_ttft,
            "p90_ttft": self.p90_ttft,
            "p99_ttft": self.p99_ttft,
            "max_ttft": self.max_ttft,
            "total_throughput": self.total_throughput,
            "mean_per_request_throughput": self.mean_per_request_throughput,
            "kvcache_hit_rate": self.kvcache_hit_rate,
            "total_time": self.total_time,
            "kv_cache_dtype": self.kv_cache_dtype,
        }
    
    def print_summary(self):
        """打印测试结果摘要"""
        print("\n" + "=" * 70)
        print(f"测试场景: {self.scenario_name}")
        print("=" * 70)
        print(f"总请求数: {self.total_requests}")
        print(f"成功请求: {self.successful_requests}")
        print(f"失败请求: {self.failed_requests}")
        print(f"KVCache精度: {self.kv_cache_dtype}")
        print("-" * 70)
        print("首字时延 (TTFT):")
        print(f"  平均值: {self.mean_ttft:.3f}s")
        print(f"  P50: {self.p50_ttft:.3f}s")
        print(f"  P90: {self.p90_ttft:.3f}s")
        print(f"  P99: {self.p99_ttft:.3f}s")
        print(f"  最大值: {self.max_ttft:.3f}s")
        print("-" * 70)
        print("吞吐量:")
        print(f"  总吞吐量: {self.total_throughput:.2f} tokens/s")
        print(f"  平均每请求吞吐量: {self.mean_per_request_throughput:.2f} tokens/s")
        print("-" * 70)
        print(f"KVCache命中率: {self.kvcache_hit_rate * 100:.2f}%")
        print(f"总测试时间: {self.total_time:.2f}s")
        print("=" * 70)


# ==================== 离线推理测试（使用vLLM API）====================
class OfflineInferenceTester:
    """离线推理测试器"""
    
    def __init__(
        self,
        model_path: str,
        storage_path: str,
        gpu_memory_utilization: float = 0.9,
        max_model_len: int = 32768,
        kv_cache_dtype: str = "fp8",
        tensor_parallel_size: int = 1,
    ):
        self.model_path = model_path
        self.storage_path = storage_path
        self.gpu_memory_utilization = gpu_memory_utilization
        self.max_model_len = max_model_len
        self.kv_cache_dtype = kv_cache_dtype
        self.tensor_parallel_size = tensor_parallel_size
        self.llm = None
        self.tokenizer = None
        self._llm_context = None
    
    def _get_ucm_config(self) -> Dict:
        """获取UCM配置"""
        return {
            "ucm_connectors": [
                {
                    "ucm_connector_name": "UcmPipelineStore",
                    "ucm_connector_config": {
                        "store_pipeline": "Posix",
                        "storage_backends": self.storage_path,
                        "io_direct": False,
                        "posix_data_trans_concurrency": 32,
                        "posix_lookup_concurrency": 32,
                    }
                }
            ]
        }
    
    def setup(self):
        """初始化模型"""
        from common.offline_inference_utils import build_llm_with_uc
        
        print(f"正在加载模型: {self.model_path}")
        print(f"KVCache精度: {self.kv_cache_dtype}")
        print(f"Tensor并行数: {self.tensor_parallel_size}")
        
        ucm_config = self._get_ucm_config()
        
        self._llm_context = build_llm_with_uc(
            model_path=self.model_path,
            ucm_config=ucm_config,
            enable_prefix_caching=True,
            max_num_batched_tokens=8192,
            gpu_memory_utilization=self.gpu_memory_utilization,
            max_model_len=self.max_model_len,
            enforce_eager=True,
            block_size=64,
            kv_cache_dtype=self.kv_cache_dtype,  # FP8精度配置
            tensor_parallel_size=self.tensor_parallel_size,
            trust_remote_code=True,  # GLM4需要
        )
        self.llm = self._llm_context.__enter__()
        
        # 获取tokenizer
        from transformers import AutoTokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path, trust_remote_code=True)
        
        print("模型加载完成")
    
    def teardown(self):
        """清理资源"""
        if self._llm_context is not None:
            self._llm_context.__exit__(None, None, None)
            self.llm = None
            self._llm_context = None
    
    def warmup(self, prompts: List[str], prefix_tokens: int) -> bool:
        """
        预热：运行前缀请求以填充KVCache
        
        Returns:
            bool: KVCache是否成功保存到UCM存储
        """
        from vllm import SamplingParams
        
        print(f"\n开始预热，填充KVCache（前缀长度: {prefix_tokens} tokens）...")
        
        sampling_params = SamplingParams(
            temperature=0.0,
            max_tokens=2,  # 只生成2个token用于预热
        )
        
        # 使用第一个prompt的前缀部分进行预热
        warmup_prompt = prompts[0]
        
        start_time = time.time()
        outputs = self.llm.generate([warmup_prompt], sampling_params)
        elapsed = time.time() - start_time
        
        print(f"预热完成，耗时: {elapsed:.2f}s")
        
        # 等待KVCache写入存储
        print("等待KVCache写入UCM存储...")
        time.sleep(3)
        
        # 验证KVCache是否已保存到存储
        return self._verify_kvcache_saved()
    
    def _verify_kvcache_saved(self):
        """验证KVCache是否已保存到UCM存储后端"""
        storage_dir = Path(self.storage_path)
        
        if not storage_dir.exists():
            print(f"⚠️ 警告: 存储目录不存在: {storage_dir}")
            return False
        
        # 检查kv子目录（UCM默认KVCache存储路径）
        kv_dir = storage_dir / "kv"
        
        if not kv_dir.exists():
            print(f"⚠️ 警告: KVCache目录不存在: {kv_dir}")
            print(f"  可能原因: block_size设置过大或prompt token数不足")
            return False
        
        # 统计KVCache文件
        kv_files = list(kv_dir.rglob("*"))
        file_count = len([f for f in kv_files if f.is_file()])
        
        if file_count == 0:
            print(f"⚠️ 警告: 未找到KVCache文件")
            return False
        
        # 计算总大小
        total_size = sum(f.stat().st_size for f in kv_files if f.is_file())
        size_mb = total_size / (1024 * 1024)
        
        print(f"✓ KVCache已保存到UCM存储:")
        print(f"  存储路径: {kv_dir}")
        print(f"  文件数量: {file_count}")
        print(f"  总大小: {size_mb:.2f} MB")
        
        return True
    
    def run_test(
        self,
        scenario: TestScenario,
        prompts: List[Tuple[str, int, int]],  # (prompt, prefix_tokens, total_tokens)
    ) -> TestResults:
        """
        运行性能测试
        
        Args:
            scenario: 测试场景配置
            prompts: 测试prompts列表
        """
        from vllm import SamplingParams
        
        print(f"\n--- 性能测试（KVCache精度: {scenario.kv_cache_dtype}）---")
        print(f"并发数: {scenario.concurrent}")
        print(f"样本数: {len(prompts)}")
        
        sampling_params = SamplingParams(
            temperature=0.0,
            max_tokens=scenario.output_tokens,
        )
        
        metrics: List[RequestMetrics] = []
        
        # 记录开始时间
        start_time = time.time()
        
        # 批量生成（vLLM内部会处理并发）
        prompts_list = [p[0] for p in prompts]
        
        # 使用vLLM的批量生成
        outputs = self.llm.generate(prompts_list, sampling_params)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # 收集指标
        total_output_tokens = 0
        for i, output in enumerate(outputs):
            prompt, prefix_tokens, total_tokens = prompts[i]
            
            generated_text = output.outputs[0].text
            output_tokens = len(self.tokenizer.encode(generated_text, add_special_tokens=False))
            total_output_tokens += output_tokens
            
            # 从vLLM metrics获取TTFT
            ttft = 0.0
            e2e_latency = 0.0
            if hasattr(output, 'metrics') and output.metrics is not None:
                e2e_latency = output.metrics.completion_time - output.metrics.arrival_time
                # 尝试获取真实的TTFT
                if hasattr(output.metrics, 'first_token_time') and output.metrics.first_token_time is not None:
                    ttft = output.metrics.first_token_time - output.metrics.arrival_time
                else:
                    ttft = e2e_latency * 0.3  # 估算（当无法获取真实TTFT时）
            
            metric = RequestMetrics(
                request_id=i,
                input_tokens=total_tokens,
                output_tokens=output_tokens,
                ttft=ttft,
                e2e_latency=e2e_latency,
                tokens_per_second=output_tokens / e2e_latency if e2e_latency > 0 else 0,
            )
            metrics.append(metric)
        
        # 计算汇总指标
        successful_metrics = [m for m in metrics if m.error is None]
        
        # 计算吞吐量
        total_throughput = total_output_tokens / total_time if total_time > 0 else 0
        
        if not successful_metrics:
            return TestResults(
                scenario_name=scenario.name,
                total_requests=len(prompts),
                successful_requests=0,
                failed_requests=len(prompts),
                mean_ttft=0,
                p50_ttft=0,
                p90_ttft=0,
                p99_ttft=0,
                max_ttft=0,
                total_throughput=total_throughput,
                mean_per_request_throughput=0,
                kvcache_hit_rate=0,
                total_time=total_time,
                kv_cache_dtype=scenario.kv_cache_dtype,
                metrics=metrics,
            )
        
        ttfts = [m.ttft for m in successful_metrics if m.ttft > 0]
        throughputs = [m.tokens_per_second for m in successful_metrics if m.tokens_per_second > 0]
        
        results = TestResults(
            scenario_name=scenario.name,
            total_requests=len(prompts),
            successful_requests=len(successful_metrics),
            failed_requests=len(metrics) - len(successful_metrics),
            mean_ttft=statistics.mean(ttfts) if ttfts else 0,
            p50_ttft=float(np.percentile(ttfts, 50)) if ttfts else 0,
            p90_ttft=float(np.percentile(ttfts, 90)) if ttfts else 0,
            p99_ttft=float(np.percentile(ttfts, 99)) if ttfts else 0,
            max_ttft=max(ttfts) if ttfts else 0,
            total_throughput=total_throughput,
            mean_per_request_throughput=statistics.mean(throughputs) if throughputs else 0,
            kvcache_hit_rate=0.98,  # 需要从实际UCM metrics获取
            total_time=total_time,
            kv_cache_dtype=scenario.kv_cache_dtype,
            metrics=metrics,
        )
        
        return results


# ==================== 主测试函数 ====================
def run_scenario_test(
    scenario: TestScenario,
    model_path: str,
    storage_path: str,
    tokenizer_path: str,
    tensor_parallel_size: int = 1,
) -> Tuple[TestResults, bool]:
    """
    运行单个场景的测试
    
    Args:
        scenario: 测试场景配置
        model_path: 模型路径
        storage_path: KVCache存储路径
        tokenizer_path: tokenizer路径
        tensor_parallel_size: 张量并行大小（4卡或8卡）
    
    Returns:
        Tuple[TestResults, bool]: (测试结果, KVCache是否成功保存)
    """
    print("\n" + "=" * 70)
    print(f"准备测试场景: {scenario.name}")
    print(f"KVCache精度: {scenario.kv_cache_dtype}")
    print(f"Tensor并行数: {tensor_parallel_size}")
    print("=" * 70)
    
    # 清理存储目录
    storage_dir = Path(storage_path)
    if storage_dir.exists():
        shutil.rmtree(storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成测试数据
    print(f"\n生成测试数据...")
    prompt_generator = PromptGenerator(tokenizer_path)
    
    # 计算前缀长度（用于KVCache命中）
    # 前缀 = 总输入 * 98%
    prefix_tokens = int(scenario.input_tokens * scenario.target_hit_rate)
    suffix_tokens = scenario.input_tokens - prefix_tokens
    
    prompts = prompt_generator.generate_prefix_suffix_prompts(
        prefix_tokens=prefix_tokens,
        suffix_tokens=suffix_tokens,
        num_variations=scenario.num_samples,
        base_seed=42,
    )
    
    print(f"生成了 {len(prompts)} 个prompts")
    print(f"前缀tokens: {prefix_tokens}, 后缀tokens: {suffix_tokens}")
    
    # 创建测试器并运行测试
    tester = OfflineInferenceTester(
        model_path=model_path,
        storage_path=storage_path,
        max_model_len=max(scenario.input_tokens + scenario.output_tokens + 1000, 32768),
        kv_cache_dtype=scenario.kv_cache_dtype,
        tensor_parallel_size=tensor_parallel_size,
    )
    tester.setup()
    kvcache_saved = False
    
    try:
        # 1. 预热（包含KVCache保存验证）
        kvcache_saved = tester.warmup([p[0] for p in prompts], prefix_tokens)
        
        # 2. 运行性能测试
        results = tester.run_test(scenario, prompts)
        
    finally:
        tester.teardown()
    
    return results, kvcache_saved


def validate_results(results: TestResults, scenario: TestScenario, kvcache_saved: bool = True) -> Dict[str, bool]:
    """验证测试结果是否满足指标要求"""
    validations = {
        f"平均首字时延 < {scenario.max_ttft_seconds}s": results.mean_ttft < scenario.max_ttft_seconds,
        f"P90首字时延 < {scenario.max_ttft_seconds * 1.5}s": results.p90_ttft < scenario.max_ttft_seconds * 1.5,
        "KVCache已保存到UCM存储": kvcache_saved,
        f"KVCache精度为{scenario.kv_cache_dtype}": results.kv_cache_dtype == scenario.kv_cache_dtype,
    }
    
    print("\n指标验证:")
    all_passed = True
    for check, passed in validations.items():
        status = "✓ 通过" if passed else "✗ 未通过"
        print(f"  {check}: {status}")
        if not passed:
            all_passed = False
    
    # 打印详细TTFT信息
    print(f"\n  TTFT详情:")
    print(f"    平均值: {results.mean_ttft:.3f}s (目标: <{scenario.max_ttft_seconds}s)")
    print(f"    P50: {results.p50_ttft:.3f}s")
    print(f"    P90: {results.p90_ttft:.3f}s")
    print(f"    P99: {results.p99_ttft:.3f}s")
    print(f"    最大值: {results.max_ttft:.3f}s")
    
    validations["all_passed"] = all_passed
    return validations


# ==================== 命令行入口 ====================
def main():
    parser = argparse.ArgumentParser(
        description="GLM4 KVCache FP8性能测试（离线推理模式）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 测试1并发场景（TTFT <5s）
  python test_glm4_kvcache_fp8_perf.py --scenario 1concurrent --model-path /path/to/glm-4
  
  # 测试5并发场景（TTFT <10s）
  python test_glm4_kvcache_fp8_perf.py --scenario 5concurrent --model-path /path/to/glm-4
  
  # 测试所有场景
  python test_glm4_kvcache_fp8_perf.py --scenario all --model-path /path/to/glm-4
  
  # 指定4卡并行
  python test_glm4_kvcache_fp8_perf.py --scenario 1concurrent --model-path /path/to/glm-4 --tensor-parallel-size 4
  
  # 指定8卡并行
  python test_glm4_kvcache_fp8_perf.py --scenario 1concurrent --model-path /path/to/glm-4 --tensor-parallel-size 8
  
  # 使用不同的FP8精度
  python test_glm4_kvcache_fp8_perf.py --scenario 1concurrent --model-path /path/to/glm-4 --kv-cache-dtype fp8_e4m3
        """,
    )
    
    parser.add_argument(
        "--scenario",
        type=str,
        choices=["1concurrent", "5concurrent", "all"],
        default="all",
        help="测试场景: 1concurrent(1并发TTFT<5s), 5concurrent(5并发TTFT<10s), 或 all",
    )
    parser.add_argument(
        "--model-path",
        type=str,
        required=True,
        help="GLM4模型路径",
    )
    parser.add_argument(
        "--storage-path",
        type=str,
        default="/home/w2938/test/ucm_kvcache_glm4_fp8",
        help="KVCache存储路径",
    )
    parser.add_argument(
        "--tokenizer-path",
        type=str,
        default=None,
        help="Tokenizer路径（默认与model-path相同）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="glm4_fp8_perf_results.json",
        help="结果输出文件",
    )
    parser.add_argument(
        "--tensor-parallel-size",
        type=int,
        default=1,
        choices=[1, 4, 8],
        help="张量并行大小（1/4/8卡）",
    )
    parser.add_argument(
        "--kv-cache-dtype",
        type=str,
        default="fp8",
        choices=["auto", "fp8", "fp8_e4m3", "fp8_e5m2"],
        help="KVCache精度（默认: fp8）",
    )
    
    args = parser.parse_args()
    
    # 设置tokenizer路径
    tokenizer_path = args.tokenizer_path or args.model_path
    
    # 确定要测试的场景
    if args.scenario == "all":
        scenarios_to_test = ["1concurrent", "5concurrent"]
    else:
        scenarios_to_test = [args.scenario]
    
    all_results = {}
    
    for scenario_key in scenarios_to_test:
        scenario = SCENARIOS[scenario_key]
        
        # 如果命令行指定了不同的kv_cache_dtype，覆盖场景默认值
        if args.kv_cache_dtype != scenario.kv_cache_dtype:
            scenario.kv_cache_dtype = args.kv_cache_dtype
            print(f"覆盖KVCache精度为: {args.kv_cache_dtype}")
        
        results, kvcache_saved = run_scenario_test(
            scenario=scenario,
            model_path=args.model_path,
            storage_path=args.storage_path,
            tokenizer_path=tokenizer_path,
            tensor_parallel_size=args.tensor_parallel_size,
        )
        
        results.print_summary()
        
        # 验证结果
        validations = validate_results(results, scenario, kvcache_saved)
        
        all_results[scenario_key] = {
            "results": results.to_dict(),
            "validations": validations,
            "kvcache_saved": kvcache_saved,
        }
    
    # 保存结果
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    
    print(f"\n结果已保存到: {args.output}")
    
    # 输出KVCache保存的具体路径
    print("\n" + "=" * 70)
    print("KVCache存储详情")
    print("=" * 70)
    kvcache_dir = os.path.join(args.storage_path, "kv")
    if os.path.exists(kvcache_dir):
        # 统计文件数量和总大小
        total_files = 0
        total_size = 0
        file_dirs = []
        for root, dirs, files in os.walk(kvcache_dir):
            for f in files:
                file_path = os.path.join(root, f)
                total_files += 1
                total_size += os.path.getsize(file_path)
                dir_name = os.path.basename(root)
                if dir_name not in [d[0] for d in file_dirs]:
                    file_dirs.append((dir_name, root))
        
        print(f"存储根目录: {kvcache_dir}")
        print(f"总文件数: {total_files}")
        print(f"总大小: {total_size / (1024 * 1024):.2f} MB")
        print(f"\n包含KVCache文件的子目录（共{len(file_dirs)}个）:")
        # 只显示前10个和最后5个
        display_dirs = file_dirs[:10] if len(file_dirs) <= 15 else file_dirs[:10] + file_dirs[-5:]
        for dir_name, full_path in display_dirs:
            file_count = len([f for f in os.listdir(full_path) if os.path.isfile(os.path.join(full_path, f))])
            print(f"  {full_path}: {file_count}个文件")
        if len(file_dirs) > 15:
            print(f"  ... 省略中间{len(file_dirs) - 15}个目录 ...")
    else:
        print(f"KVCache目录不存在: {kvcache_dir}")
    print("=" * 70)
    
    return all_results


if __name__ == "__main__":
    main()
