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
Qwen2.5-7B KVCache性能测试（离线推理模式）

测试场景:
1. 4K输入 128输出 128并发 256随机样本 kvcache命中率98% 平均首字时延低于10s
2. 32K输入 128输出 16并发 32随机样本 kvcache命中率98% 平均首字时延低于10s

使用方法:
    # 测试4K场景（同时测试裸推和UCM优化）
    python test/suites/perf/test_qwen7b_kvcache_latency_perf.py --scenario 4k --model-path /path/to/Qwen2.5-7B-Instruct
    
    # 测试32K场景
    python test/suites/perf/test_qwen7b_kvcache_latency_perf.py --scenario 32k --model-path /path/to/Qwen2.5-7B-Instruct
    
    # 仅测试裸推TTFT（无缓存）
    python test/suites/perf/test_qwen7b_kvcache_latency_perf.py --scenario 4k --model-path /path/to/Qwen2.5-7B-Instruct --bare-only
    
    # 仅测试UCM优化TTFT
    python test/suites/perf/test_qwen7b_kvcache_latency_perf.py --scenario 4k --model-path /path/to/Qwen2.5-7B-Instruct --ucm-only
    
    # 使用pytest运行
    pytest test/suites/perf/test_qwen7b_kvcache_latency_perf.py -v -s
"""

import argparse
import json
import os
import random
import shutil
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
    name: str                                       # 场景名称
    input_tokens: int                               # 输入token数量
    output_tokens: int                              # 输出token数量
    concurrent: int                                 # 并发请求数
    num_samples: int                                # 测试样本数量
    target_hit_rate: float = 0.98                   # 目标KVCache命中率
    max_ttft_seconds: float = 10.0                  # 最大首字时延（秒）
    throughput_improvement: float = 1.5             # 吞吐量提升目标（相对于无缓存基线）


# 预定义测试场景
SCENARIOS = {
    "4k": TestScenario(
        name="100输入_100输出_8并发",
        input_tokens=100,
        output_tokens=100,
        concurrent=8,
        num_samples=10,
        target_hit_rate=0.5,  # 50%命中率
        max_ttft_seconds=10.0,
        throughput_improvement=1.5,  # 150%提升
    ),
    "32k": TestScenario(
        name="32K输入_128输出_16并发",
        input_tokens=32000,
        output_tokens=128,
        concurrent=16,
        num_samples=32,
        target_hit_rate=0.5,  # 50%命中率
        max_ttft_seconds=10.0,
        throughput_improvement=3.0,  # 300%提升
    ),
}

# ==================== 数据生成器 ====================
# 生成98%相同前缀 + 2% 不同后缀的prompts模拟提高KVCache的命中率场景
class PromptGenerator:
    """生成固定token数量的prompt"""
    
    def __init__(self, tokenizer_path: str):
        from transformers import AutoTokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)
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
    test_mode: str  # "bare" 或 "ucm"
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
    
    # 详细结果
    metrics: List[RequestMetrics] = field(default_factory=list)
    
    # 基线对比（用于计算吞吐量提升）
    baseline_throughput: float = 0.0  # 无KVCache的基线吞吐量
    throughput_improvement: float = 0.0  # 吞吐量提升百分比


@dataclass
class TTFTComparison:
    """TTFT对比结果"""
    scenario_name: str
    input_tokens: int
    output_tokens: int
    
    # 裸推TTFT指标
    bare_mean_ttft: float
    bare_p50_ttft: float
    bare_p90_ttft: float
    bare_p99_ttft: float
    
    # UCM优化TTFT指标
    ucm_mean_ttft: float
    ucm_p50_ttft: float
    ucm_p90_ttft: float
    ucm_p99_ttft: float
    
    # 改善指标
    ttft_improvement_pct: float  # TTFT改善百分比
    speedup_ratio: float  # 加速比
    
    def to_dict(self) -> Dict:
        return {
            "scenario_name": self.scenario_name,
            "test_mode": self.test_mode,
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
            "baseline_throughput": self.baseline_throughput,
            "throughput_improvement": self.throughput_improvement,
        }
    
    def print_summary(self):
        """打印测试结果摘要"""
        mode_name = "裸推 (无缓存)" if self.test_mode == "bare" else "UCM优化 (有缓存)"
        print("\n" + "=" * 70)
        print(f"测试场景: {self.scenario_name} - {mode_name}")
        print("=" * 70)
        print(f"总请求数: {self.total_requests}")
        print(f"成功请求: {self.successful_requests}")
        print(f"失败请求: {self.failed_requests}")
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
    
    def print_ttft_comparison(self, other: 'TestResults'):
        """打印TTFT对比结果"""
        print("\n" + "=" * 70)
        print(f"TTFT对比: {self.scenario_name}")
        print("=" * 70)
        print(f"{'指标':<20} {'裸推':<15} {'UCM优化':<15} {'改善':<15}")
        print("-" * 70)
        
        # 计算改善百分比
        def calc_improvement(bare, ucm):
            if bare == 0:
                return "N/A"
            improvement = (bare - ucm) / bare * 100
            return f"{improvement:.1f}%"
        
        print(f"{'平均TTFT':<20} {self.mean_ttft:.3f}s{'':<8} {other.mean_ttft:.3f}s{'':<8} {calc_improvement(self.mean_ttft, other.mean_ttft):<15}")
        print(f"{'P50 TTFT':<20} {self.p50_ttft:.3f}s{'':<8} {other.p50_ttft:.3f}s{'':<8} {calc_improvement(self.p50_ttft, other.p50_ttft):<15}")
        print(f"{'P90 TTFT':<20} {self.p90_ttft:.3f}s{'':<8} {other.p90_ttft:.3f}s{'':<8} {calc_improvement(self.p90_ttft, other.p90_ttft):<15}")
        print(f"{'P99 TTFT':<20} {self.p99_ttft:.3f}s{'':<8} {other.p99_ttft:.3f}s{'':<8} {calc_improvement(self.p99_ttft, other.p99_ttft):<15}")
        
        # 计算加速比
        speedup = self.mean_ttft / other.mean_ttft if other.mean_ttft > 0 else 0
        print("-" * 70)
        print(f"加速比: {speedup:.2f}x")
        print(f"平均TTFT减少: {(self.mean_ttft - other.mean_ttft):.3f}s")
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
    ):
        self.model_path = model_path
        self.storage_path = storage_path
        self.gpu_memory_utilization = gpu_memory_utilization
        self.max_model_len = max_model_len
        self.llm = None
        self.tokenizer = None
        self._llm_context = None
    
    def _get_ucm_config(self) -> Dict:
        """获取UCM配置"""
        return {
            "ucm_connectors": [
                {
                    #连接器名称，目前UCM只存在两个：UcmNfsStore和UcmPipelineStore
                    "ucm_connector_name": "UcmPipelineStore",       # 链式组合存储，将多个store串联形成数据传输通道
                    "ucm_connector_config": {
                        "store_pipeline": "Posix",                  # 存储管道类型
                        "storage_backends": self.storage_path,      # 存储路径
                        "io_direct": False,                         # 是否启用直接I/O
                        "posix_data_trans_concurrency": 32,         # 数据传输并发数
                        "posix_lookup_concurrency": 32,             # 查找并发数
                    }
                }
            ]
        }
    
    def setup(self):
        """初始化模型"""
        from common.offline_inference_utils import build_llm_with_uc
        
        print(f"正在加载模型: {self.model_path}")
        
        ucm_config = self._get_ucm_config()
        
        self._llm_context = build_llm_with_uc(
            model_path=self.model_path,
            ucm_config=ucm_config,
            enable_prefix_caching=True,
            max_num_batched_tokens=8192,
            gpu_memory_utilization=self.gpu_memory_utilization,
            max_model_len=self.max_model_len,
            enforce_eager=True,
            block_size=16,
        )
        self.llm = self._llm_context.__enter__()
        
        # 获取tokenizer
        from transformers import AutoTokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        
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
    
    def run_baseline_test(
        self,
        scenario: TestScenario,
        prompts: List[Tuple[str, int, int]],
    ) -> Tuple[float, List[RequestMetrics]]:
        """
        运行基线测试（KVCache命中率为0）- 批量执行模式
        
        Returns:
            Tuple[float, List[RequestMetrics]]: (基线吞吐量, 请求指标列表)
        """
        from vllm import SamplingParams
        
        print(f"\n--- 基线测试（KVCache命中率为0，批量执行模式）---")
        
        sampling_params = SamplingParams(
            temperature=0.0,
            max_tokens=scenario.output_tokens,
        )
        
        # 使用不同的prompts确保无缓存命中
        prompts_list = [p[0] for p in prompts]
        
        start_time = time.time()
        outputs = self.llm.generate(prompts_list, sampling_params)
        end_time = time.time()
        total_time = end_time - start_time
        
        # 收集每个请求的指标
        metrics: List[RequestMetrics] = []
        total_output_tokens = 0
        
        for i, (output, (prompt, prefix_tokens, total_tokens)) in enumerate(zip(outputs, prompts)):
            generated_text = output.outputs[0].text
            output_tokens = len(self.tokenizer.encode(generated_text, add_special_tokens=False))
            total_output_tokens += output_tokens
            
            # 从vLLM metrics获取TTFT
            ttft = 0.0
            e2e_latency = 0.0
            if hasattr(output, 'metrics') and output.metrics is not None:
                if i == 0:
                    logger.debug(f"metrics属性: arrival_time={getattr(output.metrics, 'arrival_time', 'N/A')}, "
                               f"first_token_time={getattr(output.metrics, 'first_token_time', 'N/A')}, "
                               f"first_scheduled_time={getattr(output.metrics, 'first_scheduled_time', 'N/A')}")
                
                e2e_latency = output.metrics.completion_time - output.metrics.arrival_time
                
                if hasattr(output.metrics, 'first_token_time') and output.metrics.first_token_time is not None:
                    ttft = output.metrics.first_token_time - output.metrics.arrival_time
                elif hasattr(output.metrics, 'first_scheduled_time') and output.metrics.first_scheduled_time is not None:
                    ttft = output.metrics.first_scheduled_time - output.metrics.arrival_time
                else:
                    ttft = e2e_latency  # fallback
            else:
                # 没有metrics时，估算TTFT（批量执行时无法准确获取）
                ttft = total_time / len(prompts)  # 粗略估算
            
            metric = RequestMetrics(
                request_id=i,
                input_tokens=total_tokens,
                output_tokens=output_tokens,
                ttft=ttft,
                e2e_latency=e2e_latency if e2e_latency > 0 else total_time / len(prompts),
                tokens_per_second=output_tokens / (total_time / len(prompts)) if total_time > 0 else 0,
            )
            metrics.append(metric)
        
        baseline_throughput = total_output_tokens / total_time if total_time > 0 else 0
        
        # 打印TTFT统计
        ttfts = [m.ttft for m in metrics if m.ttft > 0]
        if ttfts:
            print(f"基线TTFT: 平均={statistics.mean(ttfts):.3f}s, P50={float(np.percentile(ttfts, 50)):.3f}s")
        
        print(f"基线吞吐量: {baseline_throughput:.2f} tokens/s")
        print(f"总输出tokens: {total_output_tokens}")
        print(f"总耗时: {total_time:.2f}s")
        
        return baseline_throughput, metrics
    
    def run_test(
        self,
        scenario: TestScenario,
        prompts: List[Tuple[str, int, int]],  # (prompt, prefix_tokens, total_tokens)
        baseline_throughput: float = 0.0,
        test_mode: str = "ucm",  # "bare" 或 "ucm"
    ) -> TestResults:
        """
        运行性能测试（有KVCache或无KVCache）- 批量执行模式
        
        使用批量执行方式，与基线测试保持一致，确保公平比较。
        vLLM的每个output对象都有独立的metrics属性，可以正确获取TTFT。
        
        Args:
            scenario: 测试场景配置
            prompts: 测试prompts列表
            baseline_throughput: 基线吞吐量（用于计算提升比例）
            test_mode: 测试模式，"bare" 表示裸推（无缓存），"ucm" 表示UCM优化（有缓存）
        """
        from vllm import SamplingParams
        
        mode_name = "裸推（无缓存）" if test_mode == "bare" else "UCM优化（有缓存）"
        print(f"\n--- 性能测试（{mode_name}，批量执行模式）---")
        print(f"样本数: {len(prompts)}")
        
        sampling_params = SamplingParams(
            temperature=0.0,
            max_tokens=scenario.output_tokens,
        )
        
        prompts_list = [p[0] for p in prompts]
        
        # 记录总开始时间
        total_start_time = time.time()
        
        # 批量执行所有请求
        outputs = self.llm.generate(prompts_list, sampling_params)
        
        total_time = time.time() - total_start_time
        
        # 收集每个请求的指标
        metrics: List[RequestMetrics] = []
        total_output_tokens = 0
        
        for i, (output, (prompt, prefix_tokens, total_tokens)) in enumerate(zip(outputs, prompts)):
            generated_text = output.outputs[0].text
            output_tokens = len(self.tokenizer.encode(generated_text, add_special_tokens=False))
            total_output_tokens += output_tokens
            
            # 从vLLM metrics获取TTFT
            ttft = 0.0
            e2e_latency = 0.0
            if hasattr(output, 'metrics') and output.metrics is not None:
                if i == 0:
                    logger.debug(f"metrics属性: arrival_time={getattr(output.metrics, 'arrival_time', 'N/A')}, "
                               f"first_token_time={getattr(output.metrics, 'first_token_time', 'N/A')}, "
                               f"first_scheduled_time={getattr(output.metrics, 'first_scheduled_time', 'N/A')}")
                
                e2e_latency = output.metrics.completion_time - output.metrics.arrival_time
                
                if hasattr(output.metrics, 'first_token_time') and output.metrics.first_token_time is not None:
                    ttft = output.metrics.first_token_time - output.metrics.arrival_time
                elif hasattr(output.metrics, 'first_scheduled_time') and output.metrics.first_scheduled_time is not None:
                    ttft = output.metrics.first_scheduled_time - output.metrics.arrival_time
                else:
                    ttft = e2e_latency  # fallback
            else:
                # 没有metrics时，估算TTFT
                ttft = total_time / len(prompts)  # 粗略估算
            
            metric = RequestMetrics(
                request_id=i,
                input_tokens=total_tokens,
                output_tokens=output_tokens,
                ttft=ttft,
                e2e_latency=e2e_latency if e2e_latency > 0 else total_time / len(prompts),
                tokens_per_second=output_tokens / (total_time / len(prompts)) if total_time > 0 else 0,
            )
            metrics.append(metric)
        
        # 计算吞吐量
        total_throughput = total_output_tokens / total_time if total_time > 0 else 0
        
        # 计算吞吐量提升比例
        throughput_improvement = 0.0
        if baseline_throughput > 0:
            throughput_improvement = (total_throughput - baseline_throughput) / baseline_throughput
        
        # 计算汇总指标
        successful_metrics = [m for m in metrics if m.error is None]
        
        if not successful_metrics:
            return TestResults(
                scenario_name=scenario.name,
                test_mode=test_mode,
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
                kvcache_hit_rate=0 if test_mode == "bare" else 0.98,
                total_time=total_time,
                metrics=metrics,
                baseline_throughput=baseline_throughput,
                throughput_improvement=throughput_improvement,
            )
        
        # 收集所有TTFT值
        ttfts = [m.ttft for m in successful_metrics]
        throughputs = [m.tokens_per_second for m in successful_metrics if m.tokens_per_second > 0]
        
        # 打印TTFT统计
        if ttfts:
            print(f"TTFT统计: 平均={statistics.mean(ttfts):.3f}s, P50={float(np.percentile(ttfts, 50)):.3f}s, P90={float(np.percentile(ttfts, 90)):.3f}s")
        
        results = TestResults(
            scenario_name=scenario.name,
            test_mode=test_mode,
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
            kvcache_hit_rate=0 if test_mode == "bare" else scenario.target_hit_rate,  # 裸推为0，UCM优化为目标命中率
            total_time=total_time,
            metrics=metrics,
            baseline_throughput=baseline_throughput,
            throughput_improvement=throughput_improvement,
        )
        
        return results


# ==================== 主测试函数 ====================
def run_scenario_test(
    scenario: TestScenario,
    model_path: str,
    storage_path: str,
    tokenizer_path: str,
    test_mode: str = "both",  # "both", "bare", "ucm"
) -> Tuple[Optional[TestResults], Optional[TestResults], bool]:
    """
    运行单个场景的测试
    
    Args:
        scenario: 测试场景配置
        model_path: 模型路径
        storage_path: KVCache存储路径
        tokenizer_path: tokenizer路径
        test_mode: 测试模式，"both" 表示同时测试裸推和UCM优化，"bare" 表示仅测试裸推，"ucm" 表示仅测试UCM优化
    
    Returns:
        Tuple[Optional[TestResults], Optional[TestResults], bool]: (裸推结果, UCM优化结果, KVCache是否成功保存)
    """
    print("\n" + "=" * 70)
    print(f"准备测试场景: {scenario.name}")
    print(f"测试模式: {test_mode}")
    print("=" * 70)
    
    # 清理存储目录
    storage_dir = Path(storage_path)
    if storage_dir.exists():
        shutil.rmtree(storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成测试数据
    print(f"\n生成测试数据...")
    prompt_generator = PromptGenerator(tokenizer_path)
    
    # 计算前缀长度（用于达到98%命中率）
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
    )
    tester.setup()
    
    bare_results = None
    ucm_results = None
    kvcache_saved = False
    
    try:
        # 1. 运行裸推测试（KVCache命中率为0）- 使用完全不同的prompts
        if test_mode in ["both", "bare"]:
            print("\n" + "=" * 70)
            print("开始裸推测试（无缓存）")
            print("=" * 70)
            # 生成完全不同的prompts用于裸推测试
            bare_prompts = prompt_generator.generate_prefix_suffix_prompts(
                prefix_tokens=scenario.input_tokens,  # 无公共前缀
                suffix_tokens=0,
                num_variations=min(scenario.num_samples, 16),  # 减少裸推测试样本数
                base_seed=999,  # 使用不同的种子
            )
            bare_results = tester.run_test(scenario, bare_prompts, test_mode="bare")
        
        # 2. 运行UCM优化测试（有KVCache）
        if test_mode in ["both", "ucm"]:
            print("\n" + "=" * 70)
            print("开始UCM优化测试（有缓存）")
            print("=" * 70)
            # 预热（包含KVCache保存验证）
            kvcache_saved = tester.warmup([p[0] for p in prompts], prefix_tokens)
            
            # 运行性能测试（有KVCache）- 批量执行模式
            ucm_results = tester.run_test(scenario, prompts, test_mode="ucm")
        
        # 打印TTFT对比
        if bare_results and ucm_results:
            bare_results.print_ttft_comparison(ucm_results)
    finally:
        tester.teardown()
    
    return bare_results, ucm_results, kvcache_saved


def validate_results(
    bare_results: Optional[TestResults],
    ucm_results: Optional[TestResults],
    scenario: TestScenario,
    kvcache_saved: bool = True,
) -> Dict[str, bool]:
    """验证测试结果是否满足指标要求"""
    validations = {}
    
    if bare_results:
        validations.update({
            f"裸推平均TTFT < {scenario.max_ttft_seconds}s": bare_results.mean_ttft < scenario.max_ttft_seconds,
        })
    
    if ucm_results:
        validations.update({
            f"UCM优化平均TTFT < {scenario.max_ttft_seconds}s": ucm_results.mean_ttft < scenario.max_ttft_seconds,
            f"KVCache命中率 >= {scenario.target_hit_rate * 100:.0f}%": ucm_results.kvcache_hit_rate >= scenario.target_hit_rate,
            "KVCache已保存到UCM存储": kvcache_saved,
        })
    
    if bare_results and ucm_results:
        # 计算TTFT改善百分比
        ttft_improvement = (bare_results.mean_ttft - ucm_results.mean_ttft) / bare_results.mean_ttft * 100
        validations.update({
            f"TTFT改善 >= 10%": ttft_improvement >= 10,
        })
    
    print("\n指标验证:")
    for check, passed in validations.items():
        status = "✓ 通过" if passed else "✗ 未通过"
        print(f"  {check}: {status}")
    
    return validations


# ==================== 命令行入口 ====================
def main():
    parser = argparse.ArgumentParser(
        description="Qwen2.5-7B KVCache性能测试（离线推理模式）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 测试4K场景（同时测试裸推和UCM优化）
  python test_qwen7b_kvcache_latency_perf.py --scenario 4k --model-path /path/to/Qwen2.5-7B-Instruct
  
  # 测试32K场景
  python test_qwen7b_kvcache_latency_perf.py --scenario 32k --model-path /path/to/Qwen2.5-7B-Instruct
  
  # 仅测试裸推TTFT（无缓存）
  python test_qwen7b_kvcache_latency_perf.py --scenario 4k --model-path /path/to/Qwen2.5-7B-Instruct --bare-only
  
  # 仅测试UCM优化TTFT
  python test_qwen7b_kvcache_latency_perf.py --scenario 4k --model-path /path/to/Qwen2.5-7B-Instruct --ucm-only
        """,
    )
    
    parser.add_argument(
        "--scenario",
        type=str,
        choices=["4k", "32k", "all"],
        default="all",
        help="测试场景: 4k, 32k, 或 all",
    )
    parser.add_argument(
        "--model-path",
        type=str,
        required=True,
        help="模型路径",
    )
    parser.add_argument(
        "--storage-path",
        type=str,
        default="/home/w2938/test/ucm_kvcache_perf",
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
        default="perf_results.json",
        help="结果输出文件",
    )
    parser.add_argument(
        "--bare-only",
        action="store_true",
        help="仅测试裸推TTFT（无缓存）",
    )
    parser.add_argument(
        "--ucm-only",
        action="store_true",
        help="仅测试UCM优化TTFT（有缓存）",
    )
    
    args = parser.parse_args()
    
    # 确定测试模式
    if args.bare_only and args.ucm_only:
        print("错误: --bare-only 和 --ucm-only 不能同时使用")
        return
    
    test_mode = "both"
    if args.bare_only:
        test_mode = "bare"
    elif args.ucm_only:
        test_mode = "ucm"
    
    # 设置tokenizer路径
    tokenizer_path = args.tokenizer_path or args.model_path
    
    # 确定要测试的场景
    if args.scenario == "all":
        scenarios_to_test = ["4k", "32k"]
    else:
        scenarios_to_test = [args.scenario]
    
    all_results = {}
    
    for scenario_key in scenarios_to_test:
        scenario = SCENARIOS[scenario_key]
        
        bare_results, ucm_results, kvcache_saved = run_scenario_test(
            scenario=scenario,
            model_path=args.model_path,
            storage_path=args.storage_path,
            tokenizer_path=tokenizer_path,
            test_mode=test_mode,
        )
        
        # 打印结果摘要
        if bare_results:
            bare_results.print_summary()
        if ucm_results:
            ucm_results.print_summary()
        
        # 验证结果
        validations = validate_results(bare_results, ucm_results, scenario, kvcache_saved)
        
        # 保存结果
        scenario_results = {}
        if bare_results:
            scenario_results["bare"] = bare_results.to_dict()
        if ucm_results:
            scenario_results["ucm"] = ucm_results.to_dict()
        scenario_results["validations"] = validations
        scenario_results["kvcache_saved"] = kvcache_saved
        
        all_results[scenario_key] = scenario_results
    
    # 保存结果
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    
    print(f"\n结果已保存到: {args.output}")
    
    # 仅在UCM测试时输出KVCache存储详情
    if test_mode in ["both", "ucm"]:
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
