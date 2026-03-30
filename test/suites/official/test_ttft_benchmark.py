# -*- coding: utf-8 -*-
"""
TTFT (Time To First Token) 基准测试

本测试用例用于对比测试裸推TTFT和存在UCM TTFT的具体指标。
支持配置:
- 输入长度 (input_tokens)
- 并发请求数 (num_concurrent)
- KVCache命中率 (target_hit_rate)

TTFT统计方式参考vllm官方代码:
    ttft = output.metrics.first_token_time - output.metrics.arrival_time

使用方法:
    # 运行裸推测试(无UCM)
    python test/suites/official/test_ttft_benchmark.py --mode baseline --model-path /path/to/model
    
    # 运行UCM测试
    python test/suites/official/test_ttft_benchmark.py --mode ucm --model-path /path/to/model --ucm-config /path/to/ucm_config.yaml
    
    # 自定义参数
    python test/suites/official/test_ttft_benchmark.py \
        --mode ucm \
        --model-path /path/to/model \
        --input-tokens 1024 \
        --num-concurrent 8 \
        --target-hit-rate 0.5 \
        --num-samples 100
    
    # 使用pytest运行
    pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
    pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
"""

import argparse
import contextlib
import json
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

# 将 test 目录添加到 Python 路径
TEST_ROOT = Path(__file__).resolve().parent.parent.parent
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from transformers import AutoTokenizer

# ==================== 数据类定义 ====================
@dataclass
class TTFTMetrics:
    """TTFT指标数据类"""
    request_id: int
    input_tokens: int
    ttft_ms: float  # TTFT，毫秒
    arrival_time: float
    first_token_time: float
    cache_hit: bool = False
    cached_tokens: int = 0
    total_tokens: int = 0
    error: Optional[str] = None

    @property
    def cache_hit_rate(self) -> float:
        """计算缓存命中率"""
        if self.total_tokens == 0:
            return 0.0
        return self.cached_tokens / self.total_tokens

@dataclass
class BenchmarkResult:
    """基准测试结果"""
    mode: str  # baseline 或 ucm
    input_tokens: int
    num_concurrent: int
    target_hit_rate: float
    num_samples: int
    total_requests: int
    successful_requests: int
    failed_requests: int
    ttft_metrics: List[TTFTMetrics] = field(default_factory=list)
    
    # 统计指标
    mean_ttft_ms: float = 0.0
    median_ttft_ms: float = 0.0
    std_ttft_ms: float = 0.0
    min_ttft_ms: float = 0.0
    max_ttft_ms: float = 0.0
    p50_ttft_ms: float = 0.0
    p90_ttft_ms: float = 0.0
    p99_ttft_ms: float = 0.0
    
    # 缓存统计
    actual_hit_rate: float = 0.0
    total_cached_tokens: int = 0
    total_input_tokens: int = 0
    
    def calculate_statistics(self):
        """计算统计指标"""
        if not self.ttft_metrics:
            return
        
        ttfts = [m.ttft_ms for m in self.ttft_metrics if m.error is None]
        if not ttfts:
            return
        
        self.mean_ttft_ms = statistics.mean(ttfts)
        self.median_ttft_ms = statistics.median(ttfts)
        self.std_ttft_ms = statistics.stdev(ttfts) if len(ttfts) > 1 else 0.0
        self.min_ttft_ms = min(ttfts)
        self.max_ttft_ms = max(ttfts)
        self.p50_ttft_ms = np.percentile(ttfts, 50)
        self.p90_ttft_ms = np.percentile(ttfts, 90)
        self.p99_ttft_ms = np.percentile(ttfts, 99)
        
        # 计算缓存统计
        total_cached = sum(m.cached_tokens for m in self.ttft_metrics)
        total_input = sum(m.total_tokens for m in self.ttft_metrics)
        if total_input > 0:
            self.actual_hit_rate = total_cached / total_input
        self.total_cached_tokens = total_cached
        self.total_input_tokens = total_input
    
    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "mode": self.mode,
            "config": {
                "input_tokens": self.input_tokens,
                "num_concurrent": self.num_concurrent,
                "target_hit_rate": self.target_hit_rate,
                "num_samples": self.num_samples,
            },
            "summary": {
                "total_requests": self.total_requests,
                "successful_requests": self.successful_requests,
                "failed_requests": self.failed_requests,
            },
            "ttft_statistics": {
                "mean_ms": round(self.mean_ttft_ms, 3),
                "median_ms": round(self.median_ttft_ms, 3),
                "std_ms": round(self.std_ttft_ms, 3),
                "min_ms": round(self.min_ttft_ms, 3),
                "max_ms": round(self.max_ttft_ms, 3),
                "p50_ms": round(self.p50_ttft_ms, 3),
                "p90_ms": round(self.p90_ttft_ms, 3),
                "p99_ms": round(self.p99_ttft_ms, 3),
            },
            "cache_statistics": {
                "actual_hit_rate": round(self.actual_hit_rate, 4),
                "total_cached_tokens": self.total_cached_tokens,
                "total_input_tokens": self.total_input_tokens,
            },
        }


# ==================== Prompt生成器 ====================
class PromptGenerator:
    """
    生成用于测试KVCache命中率的prompts
    
    通过控制前缀和后缀的比例来模拟不同的KVCache命中率:
    - 50%命中率: 50%的tokens来自公共前缀，50%来自唯一后缀
    """
    
    def __init__(self, tokenizer_path: str):
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)
        self.vocab_size = self.tokenizer.vocab_size
        self._cache: Dict[Tuple[int, int], str] = {}
    
    def _generate_random_text(self, num_tokens: int, seed: int) -> Tuple[str, int]:
        """生成指定token数量的随机文本"""
        cache_key = (num_tokens, seed)
        if cache_key in self._cache:
            return self._cache[cache_key], num_tokens
        
        random.seed(seed)
        # 生成随机token IDs
        token_ids = [random.randint(0, self.vocab_size - 1) for _ in range(num_tokens)]
        
        # 解码为文本
        text = self.tokenizer.decode(token_ids, skip_special_tokens=True)
        
        # 验证并调整token数量
        actual_tokens = len(self.tokenizer.encode(text, add_special_tokens=False))
        
        while actual_tokens < num_tokens:
            text += " " + self.tokenizer.decode([random.randint(0, self.vocab_size - 1)])
            actual_tokens = len(self.tokenizer.encode(text, add_special_tokens=False))
        
        if actual_tokens > num_tokens:
            encoded = self.tokenizer.encode(text, add_special_tokens=False)[:num_tokens]
            text = self.tokenizer.decode(encoded, skip_special_tokens=True)
            actual_tokens = num_tokens
        
        self._cache[cache_key] = text
        return text, actual_tokens
    
    def generate_prompts_with_hit_rate(
        self,
        total_tokens: int,
        target_hit_rate: float,
        num_prompts: int,
        base_seed: int = 42
    ) -> List[Tuple[str, int, int]]:
        """
        生成具有指定命中率特征的prompts
        
        Args:
            total_tokens: 每个prompt的总token数
            target_hit_rate: 目标KVCache命中率 (0.0 - 1.0)
            num_prompts: 需要生成的prompt数量
            base_seed: 随机种子基数
            
        Returns:
            List of (prompt_text, prefix_tokens, total_tokens)
        """
        prompts = []
        
        # 计算前缀和后缀的token数量
        prefix_tokens = int(total_tokens * target_hit_rate)
        suffix_tokens = total_tokens - prefix_tokens
        
        # 生成公共前缀(所有prompts共享这部分)
        prefix_text, actual_prefix = self._generate_random_text(prefix_tokens, seed=base_seed)
        
        for i in range(num_prompts):
            # 每个prompt有不同的后缀
            suffix_text, actual_suffix = self._generate_random_text(
                suffix_tokens, 
                seed=base_seed + i + 1000
            )
            
            full_prompt = prefix_text + " " + suffix_text
            actual_total = len(self.tokenizer.encode(full_prompt, add_special_tokens=False))
            
            prompts.append((full_prompt, actual_prefix, actual_total))
        
        return prompts


# ==================== LLM构建器 ====================
@contextlib.contextmanager
def build_llm_baseline(model_path: str):
    """构建基线LLM(无UCM)"""
    from vllm import LLM
    from vllm.config import ObservabilityConfig
    
    # 启用metrics收集以获取TTFT信息
    observability_config = ObservabilityConfig(
        show_hidden_metrics_for_version="0.9.3",  # 启用隐藏的metrics
    )
    
    llm_args = {
        "model": model_path,
        "max_model_len": 8192,
        "gpu_memory_utilization": 0.8,
        "max_num_batched_tokens": 32768,
        "block_size": 16,
        "enforce_eager": True,
        "trust_remote_code": True,
        "observability_config": observability_config,
    }
    
    llm = LLM(**llm_args)
    try:
        yield llm
    finally:
        del llm


@contextlib.contextmanager
def build_llm_with_ucm(model_path: str, ucm_config_path: str):
    """构建带UCM的LLM"""
    from vllm import LLM
    from vllm.config import KVTransferConfig, ObservabilityConfig
    from vllm.engine.arg_utils import EngineArgs
    
    ktc = KVTransferConfig(
        kv_connector="UCMConnector",
        kv_connector_module_path="ucm.integration.vllm.ucm_connector",
        kv_role="kv_both",
        kv_connector_extra_config={"UCM_CONFIG_FILE": ucm_config_path},
    )
    
    # 启用metrics收集以获取TTFT信息
    observability_config = ObservabilityConfig(
        show_hidden_metrics_for_version="0.9.3",
    )
    
    llm_args = EngineArgs(
        model=model_path,
        kv_transfer_config=ktc,
        max_model_len=8192,
        gpu_memory_utilization=0.8,
        max_num_batched_tokens=32768,
        block_size=16,
        enforce_eager=True,
        trust_remote_code=True,
        enable_prefix_caching=True,
        observability_config=observability_config,
    )
    
    llm = LLM(**{k: v for k, v in vars(llm_args).items() if not k.startswith('_')})
    try:
        yield llm
    finally:
        del llm


# ==================== 测试执行器 ====================
class TTFTBenchmark:
    """TTFT基准测试执行器"""
    
    def __init__(
        self,
        model_path: str,
        mode: str = "baseline",
        ucm_config_path: Optional[str] = None,
        input_tokens: int = 512,
        num_concurrent: int = 4,
        target_hit_rate: float = 0.5,
        num_samples: int = 50,
        output_tokens: int = 64,
    ):
        self.model_path = model_path
        self.mode = mode
        self.ucm_config_path = ucm_config_path
        self.input_tokens = input_tokens
        self.num_concurrent = num_concurrent
        self.target_hit_rate = target_hit_rate
        self.num_samples = num_samples
        self.output_tokens = output_tokens
        
        self.prompt_generator = PromptGenerator(model_path)
        self.result = BenchmarkResult(
            mode=mode,
            input_tokens=input_tokens,
            num_concurrent=num_concurrent,
            target_hit_rate=target_hit_rate,
            num_samples=num_samples,
            total_requests=0,
            successful_requests=0,
            failed_requests=0,
        )
    
    def _extract_ttft_from_output(self, output, request_id: int) -> TTFTMetrics:
        """
        从LLM输出中提取TTFT指标
        
        参考vllm官方代码的TTFT统计方式:
            ttft = output.metrics.first_token_time - output.metrics.arrival_time
        """
        metrics = TTFTMetrics(
            request_id=request_id,
            input_tokens=len(output.prompt_token_ids) if output.prompt_token_ids else 0,
            ttft_ms=0.0,
            arrival_time=0.0,
            first_token_time=0.0,
        )
        
        try:
            if output.metrics is not None:
                # 参考vllm官方代码的TTFT计算方式
                arrival_time = output.metrics.arrival_time
                first_token_time = output.metrics.first_token_time
                
                if arrival_time is not None and first_token_time is not None:
                    ttft_seconds = first_token_time - arrival_time
                    metrics.ttft_ms = ttft_seconds * 1000  # 转换为毫秒
                    metrics.arrival_time = arrival_time
                    metrics.first_token_time = first_token_time
                
                # 获取缓存命中信息
                if hasattr(output, 'num_cached_tokens') and output.num_cached_tokens is not None:
                    metrics.cached_tokens = output.num_cached_tokens
                    metrics.cache_hit = output.num_cached_tokens > 0
                
                metrics.total_tokens = metrics.input_tokens
        except Exception as e:
            metrics.error = str(e)
        
        return metrics
    
    def run_batch(
        self,
        llm,
        prompts: List[str],
        batch_id: int
    ) -> List[TTFTMetrics]:
        """执行一批推理请求"""
        from vllm import SamplingParams
        
        sampling_params = SamplingParams(
            max_tokens=self.output_tokens,
            temperature=0.0,
            ignore_eos=False,
        )
        
        metrics_list = []
        
        try:
            # 执行推理
            outputs = llm.generate(prompts, sampling_params)
            
            # 提取TTFT指标
            for i, output in enumerate(outputs):
                request_id = batch_id * self.num_concurrent + i
                ttft_metrics = self._extract_ttft_from_output(output, request_id)
                metrics_list.append(ttft_metrics)
                
        except Exception as e:
            # 记录失败
            for i in range(len(prompts)):
                request_id = batch_id * self.num_concurrent + i
                metrics_list.append(TTFTMetrics(
                    request_id=request_id,
                    input_tokens=0,
                    ttft_ms=0.0,
                    arrival_time=0.0,
                    first_token_time=0.0,
                    error=str(e)
                ))
        
        return metrics_list
    
    def run(self) -> BenchmarkResult:
        """运行基准测试"""
        print(f"\n{'='*60}")
        print(f"TTFT Benchmark Test - Mode: {self.mode.upper()}")
        print(f"{'='*60}")
        print(f"Configuration:")
        print(f"  Model Path: {self.model_path}")
        print(f"  Input Tokens: {self.input_tokens}")
        print(f"  Output Tokens: {self.output_tokens}")
        print(f"  Concurrent Requests: {self.num_concurrent}")
        print(f"  Target Hit Rate: {self.target_hit_rate * 100}%")
        print(f"  Total Samples: {self.num_samples}")
        if self.mode == "ucm" and self.ucm_config_path:
            print(f"  UCM Config: {self.ucm_config_path}")
        print(f"{'='*60}\n")
        
        # 生成prompts
        print("Generating prompts with target hit rate...")
        prompt_data = self.prompt_generator.generate_prompts_with_hit_rate(
            total_tokens=self.input_tokens,
            target_hit_rate=self.target_hit_rate,
            num_prompts=self.num_samples,
            base_seed=42
        )
        prompts = [p[0] for p in prompt_data]
        print(f"Generated {len(prompts)} prompts\n")
        
        # 构建LLM
        if self.mode == "ucm":
            if not self.ucm_config_path:
                raise ValueError("UCM mode requires --ucm-config parameter")
            llm_context = build_llm_with_ucm(self.model_path, self.ucm_config_path)
        else:
            llm_context = build_llm_baseline(self.model_path)
        
        all_metrics = []
        
        with llm_context as llm:
            # 预热: 先运行一批请求来填充缓存
            print("Warming up with initial requests...")
            warmup_prompts = prompts[:min(self.num_concurrent, len(prompts))]
            _ = self.run_batch(llm, warmup_prompts, batch_id=-1)
            print("Warmup complete.\n")
            
            # 分批执行测试
            num_batches = (len(prompts) + self.num_concurrent - 1) // self.num_concurrent
            print(f"Running {len(prompts)} requests in {num_batches} batches...")
            
            start_time = time.time()
            
            for batch_id in range(num_batches):
                start_idx = batch_id * self.num_concurrent
                end_idx = min(start_idx + self.num_concurrent, len(prompts))
                batch_prompts = prompts[start_idx:end_idx]
                
                batch_metrics = self.run_batch(llm, batch_prompts, batch_id)
                all_metrics.extend(batch_metrics)
                
                print(f"  Batch {batch_id + 1}/{num_batches} completed: {len(batch_metrics)} requests")
            
            end_time = time.time()
            total_time = end_time - start_time
        
        # 统计结果
        self.result.total_requests = len(all_metrics)
        self.result.successful_requests = sum(1 for m in all_metrics if m.error is None)
        self.result.failed_requests = sum(1 for m in all_metrics if m.error is not None)
        self.result.ttft_metrics = all_metrics
        self.result.calculate_statistics()
        
        # 打印结果
        self._print_results(total_time)
        
        return self.result
    
    def _print_results(self, total_time: float):
        """打印测试结果"""
        print(f"\n{'='*60}")
        print("BENCHMARK RESULTS")
        print(f"{'='*60}")
        
        print(f"\nTest Configuration:")
        print(f"  Mode: {self.result.mode.upper()}")
        print(f"  Input Tokens: {self.result.input_tokens}")
        print(f"  Concurrent Requests: {self.result.num_concurrent}")
        print(f"  Target Hit Rate: {self.result.target_hit_rate * 100}%")
        print(f"  Total Samples: {self.result.num_samples}")
        
        print(f"\nRequest Summary:")
        print(f"  Total Requests: {self.result.total_requests}")
        print(f"  Successful: {self.result.successful_requests}")
        print(f"  Failed: {self.result.failed_requests}")
        print(f"  Total Time: {total_time:.2f}s")
        
        print(f"\nTTFT Statistics (milliseconds):")
        print(f"  Mean: {self.result.mean_ttft_ms:.3f} ms")
        print(f"  Median: {self.result.median_ttft_ms:.3f} ms")
        print(f"  Std Dev: {self.result.std_ttft_ms:.3f} ms")
        print(f"  Min: {self.result.min_ttft_ms:.3f} ms")
        print(f"  Max: {self.result.max_ttft_ms:.3f} ms")
        print(f"  P50: {self.result.p50_ttft_ms:.3f} ms")
        print(f"  P90: {self.result.p90_ttft_ms:.3f} ms")
        print(f"  P99: {self.result.p99_ttft_ms:.3f} ms")
        
        print(f"\nCache Statistics:")
        print(f"  Actual Hit Rate: {self.result.actual_hit_rate * 100:.2f}%")
        print(f"  Total Cached Tokens: {self.result.total_cached_tokens}")
        print(f"  Total Input Tokens: {self.result.total_input_tokens}")
        
        print(f"\n{'='*60}\n")


# ==================== 命令行接口 ====================
def parse_args():
    parser = argparse.ArgumentParser(
        description="TTFT Benchmark Test for UCM vs Baseline comparison",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "--mode",
        type=str,
        choices=["baseline", "ucm"],
        default="baseline",
        help="Test mode: 'baseline' for raw inference, 'ucm' for inference with UCM cache"
    )
    parser.add_argument(
        "--model-path",
        type=str,
        required=True,
        help="Path to the model"
    )
    parser.add_argument(
        "--ucm-config",
        type=str,
        default=None,
        help="Path to UCM config file (required for 'ucm' mode)"
    )
    parser.add_argument(
        "--input-tokens",
        type=int,
        default=100,
        help="Number of input tokens per request (default: 512)"
    )
    parser.add_argument(
        "--output-tokens",
        type=int,
        default=64,
        help="Number of output tokens per request (default: 64)"
    )
    parser.add_argument(
        "--num-concurrent",
        type=int,
        default=8,
        help="Number of concurrent requests (default: 4)"
    )
    parser.add_argument(
        "--target-hit-rate",
        type=float,
        default=0.5,
        help="Target KVCache hit rate, 0.5 means 50%% (default: 0.5)"
    )
    parser.add_argument(
        "--num-samples",
        type=int,
        default=10,
        help="Number of test samples (default: 50)"
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default=None,
        help="Path to save results as JSON file"
    )
    
    return parser.parse_args()


def main():
    args = parse_args()
    
    # 验证参数
    if args.mode == "ucm" and not args.ucm_config:
        print("Error: --ucm-config is required when using 'ucm' mode")
        sys.exit(1)
    
    if not os.path.exists(args.model_path):
        print(f"Error: Model path does not exist: {args.model_path}")
        sys.exit(1)
    
    if args.ucm_config and not os.path.exists(args.ucm_config):
        print(f"Error: UCM config file does not exist: {args.ucm_config}")
        sys.exit(1)
    
    # 运行基准测试
    benchmark = TTFTBenchmark(
        model_path=args.model_path,
        mode=args.mode,
        ucm_config_path=args.ucm_config,
        input_tokens=args.input_tokens,
        num_concurrent=args.num_concurrent,
        target_hit_rate=args.target_hit_rate,
        num_samples=args.num_samples,
        output_tokens=args.output_tokens,
    )
    
    result = benchmark.run()
    
    # 保存结果到JSON文件
    if args.output_json:
        with open(args.output_json, 'w') as f:
            json.dump(result.to_dict(), f, indent=2)
        print(f"Results saved to: {args.output_json}")


# ==================== Pytest接口 ====================
import pytest

@pytest.fixture
def default_model_path():
    """默认模型路径fixture"""
    return os.getenv("MODEL_PATH", "/home/w2938/model")

@pytest.fixture
def default_ucm_config():
    """默认UCM配置文件fixture"""
    return os.getenv("UCM_CONFIG", "test/test_ucm_config.yaml")


class TestTTFTBenchmark:
    """TTFT基准测试类 - Pytest接口"""
    
    def test_baseline_ttft(self, default_model_path):
        """测试基线TTFT(无UCM)"""
        benchmark = TTFTBenchmark(
            model_path=default_model_path,
            mode="baseline",
            input_tokens=256,
            num_concurrent=2,
            target_hit_rate=0.5,
            num_samples=10,
            output_tokens=32,
        )
        
        result = benchmark.run()
        
        # 验证结果
        assert result.total_requests > 0
        assert result.successful_requests > 0
        assert result.mean_ttft_ms > 0
        
        print(f"\nBaseline TTFT Mean: {result.mean_ttft_ms:.3f} ms")
    
    def test_ucm_ttft(self, default_model_path, default_ucm_config):
        """测试UCM TTFT"""
        # 检查UCM配置文件是否存在
        if not os.path.exists(default_ucm_config):
            pytest.skip(f"UCM config file not found: {default_ucm_config}")
        
        benchmark = TTFTBenchmark(
            model_path=default_model_path,
            mode="ucm",
            ucm_config_path=default_ucm_config,
            input_tokens=256,
            num_concurrent=2,
            target_hit_rate=0.5,
            num_samples=10,
            output_tokens=32,
        )
        
        result = benchmark.run()
        
        # 验证结果
        assert result.total_requests > 0
        assert result.successful_requests > 0
        assert result.mean_ttft_ms > 0
        
        print(f"\nUCM TTFT Mean: {result.mean_ttft_ms:.3f} ms")
    
    def test_ttft_comparison(self, default_model_path, default_ucm_config):
        """对比测试基线TTFT和UCM TTFT"""
        # 检查UCM配置文件是否存在
        if not os.path.exists(default_ucm_config):
            pytest.skip(f"UCM config file not found: {default_ucm_config}")
        
        # 测试配置
        test_config = {
            "input_tokens": 512,
            "num_concurrent": 4,
            "target_hit_rate": 0.5,
            "num_samples": 20,
            "output_tokens": 64,
        }
        
        # 运行基线测试
        baseline_benchmark = TTFTBenchmark(
            model_path=default_model_path,
            mode="baseline",
            **test_config
        )
        baseline_result = baseline_benchmark.run()
        
        # 运行UCM测试
        ucm_benchmark = TTFTBenchmark(
            model_path=default_model_path,
            mode="ucm",
            ucm_config_path=default_ucm_config,
            **test_config
        )
        ucm_result = ucm_benchmark.run()
        
        # 打印对比结果
        print(f"\n{'='*60}")
        print("TTFT COMPARISON RESULTS")
        print(f"{'='*60}")
        print(f"\nConfiguration:")
        print(f"  Input Tokens: {test_config['input_tokens']}")
        print(f"  Concurrent Requests: {test_config['num_concurrent']}")
        print(f"  Target Hit Rate: {test_config['target_hit_rate'] * 100}%")
        print(f"  Samples: {test_config['num_samples']}")
        
        print(f"\nBaseline (No UCM):")
        print(f"  Mean TTFT: {baseline_result.mean_ttft_ms:.3f} ms")
        print(f"  Median TTFT: {baseline_result.median_ttft_ms:.3f} ms")
        print(f"  P99 TTFT: {baseline_result.p99_ttft_ms:.3f} ms")
        
        print(f"\nWith UCM:")
        print(f"  Mean TTFT: {ucm_result.mean_ttft_ms:.3f} ms")
        print(f"  Median TTFT: {ucm_result.median_ttft_ms:.3f} ms")
        print(f"  P99 TTFT: {ucm_result.p99_ttft_ms:.3f} ms")
        print(f"  Actual Hit Rate: {ucm_result.actual_hit_rate * 100:.2f}%")
        
        # 计算TTFT改善比例
        if baseline_result.mean_ttft_ms > 0:
            improvement = (baseline_result.mean_ttft_ms - ucm_result.mean_ttft_ms) / baseline_result.mean_ttft_ms * 100
            print(f"\nTTFT Improvement: {improvement:.1f}%")
        
        print(f"\n{'='*60}\n")
        
        # 验证UCM应该有一定的缓存命中率
        assert ucm_result.actual_hit_rate > 0, "UCM should have some cache hit rate"


if __name__ == "__main__":
    main()
