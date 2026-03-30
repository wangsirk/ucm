#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TTFT 测试脚本 - 客户端计时方式（与 vLLM 官方 benchmark 一致）

用法:
    # 基本测试
    python test_ttft_api.py --num-requests 10 --concurrency 4 --input-tokens 100

    # 自定义服务地址
    python test_ttft_api.py --base-url http://localhost:7800/v1 --model /path/to/model

    # 保存结果到 JSON
    python test_ttft_api.py --num-requests 50 --output results.json
"""

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass
from typing import List

import numpy as np
from openai import AsyncOpenAI


@dataclass
class TTFTRecord:
    request_id: int
    ttft_ms: float
    total_latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    success: bool
    error: str = ""


@dataclass
class TTFTStats:
    mean: float
    median: float
    p50: float
    p90: float
    p95: float
    p99: float
    min: float
    max: float
    std: float


def calculate_stats(ttfts: List[float]) -> TTFTStats:
    """计算 TTFT 统计"""
    return TTFTStats(
        mean=statistics.mean(ttfts),
        median=statistics.median(ttfts),
        p50=np.percentile(ttfts, 50),
        p90=np.percentile(ttfts, 90),
        p95=np.percentile(ttfts, 95),
        p99=np.percentile(ttfts, 99),
        min=min(ttfts),
        max=max(ttfts),
        std=statistics.stdev(ttfts) if len(ttfts) > 1 else 0,
    )


def generate_prompt(target_tokens: int) -> str:
    """生成约指定 token 数量的 prompt"""
    base = "请分析深度学习在自然语言处理领域的应用和发展趋势。"
    # 粗略估算：每个汉字约 0.5-0.7 token
    chars_needed = target_tokens * 2
    repeat = max(1, chars_needed // len(base))
    return " ".join([base] * repeat)


async def send_request(
    client: AsyncOpenAI,
    model: str,
    request_id: int,
    prompt: str,
    max_tokens: int,
) -> TTFTRecord:
    """发送单个请求并测量 TTFT（客户端计时，与 vLLM 官方 benchmark 一致）"""
    st = time.perf_counter() 
    first_token_time = None
    text = ""
    ttft = 0.0

    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.0,
            stream=True,
        )

        async for chunk in stream:
            # 与 vLLM 官方 benchmark 一致：只要收到 choices 就记录 TTFT
            # 即使 content 为空字符串也记录（首个 chunk 到达时刻）
            if chunk.choices:
                if ttft == 0.0:  # 首个 token（包括空 content）
                    ttft = time.perf_counter() - st
                # 累加实际内容
                if chunk.choices[0].delta.content:
                    text += chunk.choices[0].delta.content

        end_time = time.perf_counter()

        ttft_ms = ttft * 1000 if ttft > 0 else 0
        total_ms = (end_time - st) * 1000

        # 估算 token 数（粗略）
        prompt_tokens = len(prompt) // 2
        completion_tokens = len(text) // 2

        return TTFTRecord(
            request_id=request_id,
            ttft_ms=ttft_ms,
            total_latency_ms=total_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            success=True,
        )

    except Exception as e:
        return TTFTRecord(
            request_id=request_id,
            ttft_ms=0,
            total_latency_ms=0,
            prompt_tokens=0,
            completion_tokens=0,
            success=False,
            error=str(e),
        )


async def main():
    parser = argparse.ArgumentParser(
        description="TTFT 测试 - 客户端计时方式（与 vLLM 官方 benchmark 一致）"
    )
    parser.add_argument("--base-url", type=str, default="http://localhost:7800/v1",
                        help="vLLM 服务地址")
    parser.add_argument("--model", type=str, default="/home/w2938/model",
                        help="模型名称")
    parser.add_argument("--num-requests", type=int, default=8,
                        help="请求数量")
    parser.add_argument("--concurrency", type=int, default=8,
                        help="并发数")
    parser.add_argument("--input-tokens", type=int, default=100,
                        help="输入 prompt tokens 数量（估算）")
    parser.add_argument("--max-tokens", type=int, default=64,
                        help="最大输出 tokens 数量")
    parser.add_argument("--output", type=str, default=None,
                        help="输出 JSON 文件路径")
    args = parser.parse_args()

    client = AsyncOpenAI(base_url=args.base_url, api_key="empty")
    prompt = generate_prompt(args.input_tokens)

    print(f"\n{'='*60}")
    print("TTFT 测试 (在线模式 - 客户端计时)")
    print(f"{'='*60}")
    print(f"服务地址: {args.base_url}")
    print(f"模型: {args.model}")
    print(f"请求数: {args.num_requests}")
    print(f"并发: {args.concurrency}")
    print(f"Prompt tokens: ~{args.input_tokens}")
    print(f"Max tokens: {args.max_tokens}")
    print(f"{'='*60}\n")

    all_records: List[TTFTRecord] = []
    batches = (args.num_requests + args.concurrency - 1) // args.concurrency

    start_time = time.time()

    for batch_idx in range(batches):
        start = batch_idx * args.concurrency
        end = min(start + args.concurrency, args.num_requests)
        req_ids = list(range(start, end))

        print(f"批次 {batch_idx + 1}/{batches} ({len(req_ids)} 请求)...", flush=True)

        tasks = [
            send_request(client, args.model, i, prompt, args.max_tokens)
            for i in req_ids
        ]
        batch_records = await asyncio.gather(*tasks)
        all_records.extend(batch_records)

        success = sum(1 for r in batch_records if r.success)
        print(f"  完成: {success}/{len(req_ids)} 成功")

    total_time = time.time() - start_time

    # 统计
    successful = [r for r in all_records if r.success]
    ttfts = [r.ttft_ms for r in successful]

    print(f"\n{'='*60}")
    print("结果")
    print(f"{'='*60}")
    print(f"总请求数: {len(all_records)}")
    print(f"成功: {len(successful)}")
    print(f"失败: {len(all_records) - len(successful)}")
    print(f"总耗时: {total_time:.2f}s")

    if ttfts:
        stats = calculate_stats(ttfts)
        print(f"\nTTFT (毫秒) [客户端计时]:")
        print(f"  平均: {stats.mean:.3f} ms")
        print(f"  中位数: {stats.median:.3f} ms")
        print(f"  P50: {stats.p50:.3f} ms")
        print(f"  P90: {stats.p90:.3f} ms")
        print(f"  P95: {stats.p95:.3f} ms")
        print(f"  P99: {stats.p99:.3f} ms")
        print(f"  最小: {stats.min:.3f} ms")
        print(f"  最大: {stats.max:.3f} ms")
        print(f"  标准差: {stats.std:.3f} ms")

        avg_total = statistics.mean([r.total_latency_ms for r in successful])
        print(f"\n总延迟平均: {avg_total:.3f} ms")

        total_in = sum(r.prompt_tokens for r in successful)
        total_out = sum(r.completion_tokens for r in successful)
        print(f"输出吞吐: {total_out / total_time:.2f} tokens/s")

    print(f"{'='*60}\n")

    # 保存结果
    if args.output:
        stats = calculate_stats(ttfts) if ttfts else None
        result = {
            "config": {
                "base_url": args.base_url,
                "model": args.model,
                "num_requests": args.num_requests,
                "concurrency": args.concurrency,
                "input_tokens": args.input_tokens,
                "max_tokens": args.max_tokens,
            },
            "summary": {
                "total_requests": len(all_records),
                "successful": len(successful),
                "failed": len(all_records) - len(successful),
            },
            "ttft_ms": {
                "mean": stats.mean if stats else 0,
                "median": stats.median if stats else 0,
                "p90": stats.p90 if stats else 0,
                "p99": stats.p99 if stats else 0,
                "min": stats.min if stats else 0,
                "max": stats.max if stats else 0,
            } if stats else {},
            "records": [
                {
                    "id": r.request_id,
                    "ttft_ms": r.ttft_ms,
                    "success": r.success,
                    "error": r.error,
                }
                for r in all_records
            ],
        }
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"结果已保存: {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
