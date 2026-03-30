# -*- coding: utf-8 -*-
"""
调试脚本：检查vLLM服务的metrics属性结构
用于诊断TTFT为0的问题

支持两种模式：
1. 在线模式 (online): 通过 OpenAI API 连接服务，使用客户端计时
2. 离线模式 (offline): 使用 vLLM 原生 API，从 output.metrics 获取 TTFT
"""

import sys
from pathlib import Path
import httpx
import time
import json
import statistics
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

import numpy as np

# 将 test 目录添加到 Python 路径
TEST_ROOT = Path(__file__).resolve().parent.parent.parent
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from common.llm_connection.openai_connector import OpenAIConn
from common.llm_connection.token_counter import HuggingFaceTokenizer


@dataclass
class TTFTRecord:
    """TTFT 记录"""
    request_id: int
    ttft_ms: float
    total_time_ms: float
    prompt_tokens: int
    completion_tokens: int
    success: bool
    error: str = ""
    num_cached_tokens: int = 0
    # 来自 vLLM output.metrics 的时间戳
    arrival_time: float = 0.0
    first_token_time: float = 0.0


class OnlineServiceMetricsInspector:
    """检查vLLM在线服务的metrics结构（通过 OpenAI API，客户端计时）"""
    
    def __init__(self, base_url: str, api_key: str, model: str):
        """
        初始化
        
        Args:
            base_url: Base URL of vLLM服务地址
            api_key: API key (如果需要)
            model: 模型名称 (用于获取tokenizer信息)
        """
        self.base_url = base_url.rstrip()
        self.api_key = api_key or "EMPTY"
        self.model = model
        
        # 初始化tokenizer和连接器
        self.tokenizer = HuggingFaceTokenizer(model)
        self.connector = OpenAIConn(
            base_url=base_url,
            tokenizer=self.tokenizer,
            api_key=api_key,
            model=model
        )
        self.token_counter = self.tokenizer
    
    def inspect_single_request(self, prompt: str, max_tokens: int = 10) -> None:
        """
        检查单个请求的metrics
        
        Args:
            prompt: 输入提示
            max_tokens: 最大生成token数
        """
        from common.llm_connection.LLMBase import LLMRequest
        
        request_start_time = time.time()
        
        # 使用stream_chat来获取流式响应
        req = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens
        )
        
        # 记录请求开始时间
        print(f"\nRequest started at {time.strftime('%H:%M:%S')}")
        
        first_chunk_time = None
        chunks = []
        
        try:
            for chunk in self.connector.stream_chat(req):
                if first_chunk_time is None and chunk.text:
                    first_chunk_time = time.time()
                chunks.append(chunk)
                print(f"Chunk: {chunk.text[:50] if chunk.text else '(empty)'}...")
        except Exception as e:
            print(f"Request failed: {e}")
            return
        
        total_time = time.time() - request_start_time
        ttft_ms = (first_chunk_time - request_start_time) * 1000 if first_chunk_time else 0
        
        print(f"\n=== Response Info ===")
        print(f"Total time: {total_time * 1000:.3f} ms")
        print(f"TTFT: {ttft_ms:.3f} ms")
        
        # 合并所有chunk的文本
        full_text = "".join(chunk.text for chunk in chunks if chunk.text)
        print(f"\nGenerated text: {full_text[:100]}...")
        
        # 统计token
        total_tokens = sum(chunk.num_tokens for chunk in chunks if chunk.num_tokens)
        print(f"\nTotal tokens: {total_tokens}")


    
    def run_benchmark(
        self,
        num_requests: int = 5,
        input_tokens: int = 256,
        max_tokens: int = 32,
        num_concurrent: int = 1,
        output_json: str = None
    ):
        """
        运行基准测试
        
        Args:
            num_requests: 请求数量
            input_tokens: 输入token数
            max_tokens: 最大输出token数
            num_concurrent: 并发数
            output_json: 输出JSON文件路径
        
        Returns:
            results: List[Dict] - metrics字典列表
        """
        from common.llm_connection.LLMBase import LLMRequest
        
        results = []
        
        print(f"\nStarting benchmark with {num_requests} requests...")
        print(f"Model: {self.model}")
        print(f"Base URL: {self.base_url}")
        print(f"Input tokens: {input_tokens}")
        print(f"Max tokens: {max_tokens}")
        print(f"Concurrent: {num_concurrent}")
        
        try:
            for i in range(num_requests):
                prompt = self.token_counter.get_some_tokens(
                    input_tokens, seed=i
                )
                
                # 发送请求
                request_start_time = time.time()
                
                req = LLMRequest(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens
                )
                
                first_chunk_time = None
                chunks = []
                
                try:
                    for chunk in self.connector.stream_chat(req):
                        if first_chunk_time is None and chunk.text:
                            first_chunk_time = time.time()
                        chunks.append(chunk)
                except Exception as e:
                    print(f"Request {i} failed: {e}")
                    continue
                
                total_time = time.time() - request_start_time
                ttft_ms = (first_chunk_time - request_start_time) * 1000 if first_chunk_time else 0
                
                # 统计token
                total_tokens = sum(chunk.num_tokens for chunk in chunks if chunk.num_tokens)
                
                results.append({
                    "request_id": i,
                    "prompt": prompt[:50] if prompt else "...",
                    "input_tokens": input_tokens,
                    "max_tokens": max_tokens,
                    "ttft_ms": ttft_ms,
                    "total_time_ms": total_time * 1000,
                    "total_tokens": total_tokens
                })
                
                # 打印进度
                if (i + 1) % max(1, num_requests // 5) == 0:
                    print(f"Progress: {i+1}/{num_requests} requests completed")
            
            print(f"\nAll requests completed")
            
            # 计算统计信息
            if results:
                ttfts = [r["ttft_ms"] for r in results]
                successful_requests = len(ttfts)
                failed_requests = num_requests - len(ttfts)
                
                if successful_requests > 0:
                    mean_ttft = statistics.mean(ttfts)
                    median_ttft = statistics.median(ttfts)
                    std_ttft = statistics.stdev(ttfts) if len(ttfts) > 1 else 0.0
                    min_ttft = min(ttfts)
                    max_ttft = max(ttfts)
                    p50_ttft = np.percentile(ttfts, 50)
                    p90_ttft = np.percentile(ttfts, 90)
                    p99_ttft = np.percentile(ttfts, 99)
                
                    print(f"\nTTFT Statistics:")
                    print(f"  Mean: {mean_ttft:.3f} ms")
                    print(f"  Median: {median_ttft:.3f} ms")
                    print(f"  Std: {std_ttft:.3f} ms")
                    print(f"  Min: {min_ttft:.3f} ms")
                    print(f"  Max: {max_ttft:.3f} ms")
                    print(f"  P50: {p50_ttft:.3f} ms")
                    print(f"  P90: {p90_ttft:.3f} ms")
                    print(f"  P99: {p99_ttft:.3f} ms")
                    
                    # 计算缓存统计
                    total_cached = sum(r.get("total_cached_tokens", 0) for r in results)
                    total_input = sum(r.get("total_input_tokens", 0) for r in results)
                    actual_hit_rate = total_cached / total_input if total_input > 0 else 0.0
                    
                    print(f"\nCache statistics:")
                    print(f"  Actual hit rate: {actual_hit_rate * 100:.2f}%")
                    print(f"  total cached tokens: {total_cached}")
                    print(f"  total input tokens: {total_input}")
                
                # 保存结果到JSON文件
                if output_json:
                    with open(output_json, 'w') as f:
                        json.dump(results, f, indent=2)
                    print(f"\nResults saved to {output_json}")
            else:
                print("No results collected")
            
            return results
            
        except Exception as e:
            print(f"Error during benchmark: {e}")
            return []


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="调试vLLM在线服务metrics")
    parser.add_argument("--base-url", type=str, required=True, help="vLLM服务地址")
    parser.add_argument("--api-key", type=str, default="EMPTY", help="API key (如果需要)")
    parser.add_argument("--model", type=str, required=True, help="模型名称")
    parser.add_argument("--num-requests", type=int, default=5, help="请求数量")
    parser.add_argument("--input-tokens", type=int, default=256, help="输入token数")
    parser.add_argument("--max-tokens", type=int, default=32, help="最大输出token数")
    parser.add_argument("--num-concurrent", type=int, default=1, help="并发数")
    parser.add_argument("--output-json", type=str, default=None, help="输出JSON文件路径")
    
    args = parser.parse_args()
    
    inspector = OnlineServiceMetricsInspector(args.base_url, args.api_key, args.model)
    inspector.run_benchmark(
        num_requests=args.num_requests,
        input_tokens=args.input_tokens,
        max_tokens=args.max_tokens,
        num_concurrent=args.num_concurrent,
        output_json=args.output_json
    )
