#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TTFT 测试脚本 - Semaphore 并发控制方式（与 vLLM 官方 benchmark 一致）

用法:
    # 基本测试
    python test_ttft_api_semaphore.py --num-requests 10 --concurrency 4 --input-tokens 100

    # 自定义服务地址
    python test_ttft_api_semaphore.py --base-url http://localhost:7800/v1 --model /path/to/model

    # 保存结果到 JSON
    python test_ttft_api_semaphore.py --num-requests 50 --output results.json

    # 设置 KVCache 命中率 50%
    python test_ttft_api_semaphore.py --num-requests 50 --cache-hit-ratio 0.5

    # 禁用预热（不推荐，可能导致实际命中率低于预期）
    python test_ttft_api_semaphore.py --num-requests 50 --cache-hit-ratio 0.5 --no-warmup

与原版区别:
    - 使用 Semaphore 动态控制并发，而非固定分批
    - 所有任务同时创建，Semaphore 自动控制并发数
    - 更高效的资源利用，无需等待整批完成
    - 支持设置 KVCache 命中率（通过 prefix sharing 方式）

KVCache 命中率实现原理（与 vLLM 官方测试一致）:
    - 命中 cache 的请求：使用完全相同的 prompt（100% 命中 KVCache）
    - 未命中 cache 的请求：每个请求使用完全不同的 prompt（0% 命中 KVCache）
    - 例如 50% 命中率：5 个请求相同，5 个请求完全不同
    - 测试前会自动预热 cache，确保 cached_prompt 已在 cache 中
"""

import argparse
import asyncio
import json
import random
import statistics
import time
from dataclasses import dataclass
from typing import List, Tuple

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
    cache_hit: bool = False  # 是否命中 KVCache
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


def generate_shared_prefix(prefix_tokens: int) -> str:
    """生成共享前缀
    
    Args:
        prefix_tokens: 前缀的 token 数量
    """
    base = "请分析深度学习在自然语言处理领域的应用和发展趋势，包括语言模型、机器翻译、文本分类、情感分析、命名实体识别、问答系统等多个子领域的技术进展。"
    # 粗略估算：每个汉字约 0.5-0.7 token
    chars_needed = prefix_tokens * 2
    repeat = max(1, chars_needed // len(base))
    return " ".join([base] * repeat)


def generate_prompt_with_prefix(
    shared_prefix: str,
    unique_suffix: str = "",
    total_target_tokens: int = 100,
) -> str:
    """生成带共享前缀的 prompt
    
    Args:
        shared_prefix: 共享前缀内容
        unique_suffix: 唯一后缀，用于生成不同的 prompt（控制 KVCache 命中）
        total_target_tokens: 总目标 token 数量
    """
    # 如果没有唯一后缀，直接返回共享前缀（完全命中 cache）
    if not unique_suffix:
        return shared_prefix
    
    # 有唯一后缀时，拼接前缀和后缀
    # 前缀部分会命中 cache，后缀部分不会
    return shared_prefix + " " + unique_suffix


def generate_prompts_for_cache_ratio(
    num_requests: int,
    target_tokens: int,
    cache_hit_ratio: float,
    shared_prefix_tokens: int = 50,
) -> Tuple[List[str], List[bool], str]:
    """根据 KVCache 命中率生成 prompts（vLLM 官方方式）

    原理（与 vLLM 官方测试一致）：
    - 命中 cache 的请求：使用完全相同的 prompt（100% 命中 KVCache）
    - 未命中 cache 的请求：每个请求使用完全不同的 prompt（0% 命中 KVCache）

    例如 50% 命中率，10 个请求：
        - 5 个 cache_hit:  完全相同的 prompt "请分析深度学习..."
        - 5 个 cache_miss: 完全不同的 prompt (每个都独特)

    注意：此方法需要先预热 cache，确保 cached_prompt 已在 cache 中

    Args:
        num_requests: 总请求数
        target_tokens: 目标 token 数量
        cache_hit_ratio: KVCache 命中率 (0.0 - 1.0)
        shared_prefix_tokens: cache 命中 prompt 的 token 数量

    Returns:
        prompts: prompt 列表
        cache_hits: 是否预期命中 cache 的标记列表
        cached_prompt: 用于预热的 prompt（cache_hit 请求使用）
    """
    prompts = []
    cache_hits = []

    # 生成 cache 命中用的 prompt（所有 cache_hit 请求共用）
    cached_prompt = generate_shared_prefix(shared_prefix_tokens)

    # 计算命中和未命中的请求数
    num_cache_hits = int(num_requests * cache_hit_ratio)
    num_cache_misses = num_requests - num_cache_hits

    # 生成命中 cache 的请求：所有请求使用完全相同的 prompt
    for i in range(num_cache_hits):
        prompts.append(cached_prompt)
        cache_hits.append(True)

    # 生成未命中 cache 的请求：每个请求使用完全不同的 prompt
    for i in range(num_cache_misses):
        # 生成完全独特的 prompt，与 cached_prompt 没有任何重叠
        unique_content = f"问题编号{random.randint(10000, 99999)}：请详细阐述机器学习在医疗诊断中的应用，包括影像识别、病理分析、药物研发等多个领域的具体案例和技术挑战。这是一个完全独立的请求。"
        # 重复以达到目标 token 数量
        chars_needed = target_tokens * 2
        repeat = max(1, chars_needed // len(unique_content))
        miss_prompt = " ".join([unique_content] * repeat)
        prompts.append(miss_prompt)
        cache_hits.append(False)

    # 打乱顺序，使命中和未命中的请求混合
    combined = list(zip(prompts, cache_hits))
    random.shuffle(combined)
    prompts, cache_hits = zip(*combined)

    return list(prompts), list(cache_hits), cached_prompt


async def send_request(
    client: AsyncOpenAI,
    model: str,
    request_id: int,
    prompt: str,
    max_tokens: int,
    cache_hit: bool = False,
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
            cache_hit=cache_hit,
        )

    except Exception as e:
        return TTFTRecord(
            request_id=request_id,
            ttft_ms=0,
            total_latency_ms=0,
            prompt_tokens=0,
            completion_tokens=0,
            success=False,
            cache_hit=cache_hit,
            error=str(e),
        )


async def main():
    parser = argparse.ArgumentParser(
        description="TTFT 测试 - Semaphore 并发控制（与 vLLM 官方 benchmark 一致）"
    )
    parser.add_argument("--base-url", type=str, default="http://localhost:7800/v1",
                        help="vLLM 服务地址")
    parser.add_argument("--model", type=str, default="/home/w2938/model",
                        help="模型名称")
    parser.add_argument("--num-requests", type=int, default=8,
                        help="请求数量")
    parser.add_argument("--concurrency", type=int, default=8,
                        help="最大并发数（Semaphore 控制）")
    parser.add_argument("--input-tokens", type=int, default=100,
                        help="输入 prompt tokens 数量（估算）")
    parser.add_argument("--max-tokens", type=int, default=64,
                        help="最大输出 tokens 数量")
    parser.add_argument("--cache-hit-ratio", type=float, default=0.5,
                        help="KVCache 命中率 (0.0 - 1.0)，默认 0.5")
    parser.add_argument("--shared-prefix-tokens", type=int, default=50,
                        help="共享前缀的 token 数量（用于 KVCache 命中）")
    parser.add_argument("--output", type=str, default=None,
                        help="输出 JSON 文件路径")
    parser.add_argument("--seed", type=int, default=42,
                        help="随机种子（用于复现结果）")
    parser.add_argument("--no-warmup", action="store_true",
                        help="禁用 KVCache 预热（默认启用预热以确保 cache 命中）")
    args = parser.parse_args()

    # 设置随机种子
    random.seed(args.seed)

    client = AsyncOpenAI(base_url=args.base_url, api_key="empty")

    # 根据 cache_hit_ratio 生成 prompts（vLLM 官方方式）
    prompts, cache_hits, cached_prompt = generate_prompts_for_cache_ratio(
        num_requests=args.num_requests,
        target_tokens=args.input_tokens,
        cache_hit_ratio=args.cache_hit_ratio,
        shared_prefix_tokens=args.shared_prefix_tokens,
    )

    print(f"\n{'='*60}")
    print("TTFT 测试 (Semaphore 并发控制 - 客户端计时)")
    print(f"{'='*60}")
    print(f"服务地址: {args.base_url}")
    print(f"模型: {args.model}")
    print(f"请求数: {args.num_requests}")
    print(f"最大并发: {args.concurrency}")
    print(f"Prompt tokens: ~{args.input_tokens}")
    print(f"Max tokens: {args.max_tokens}")
    print(f"KVCache 命中率: {args.cache_hit_ratio * 100:.1f}%")
    print(f"  - 命中请求数: {sum(cache_hits)}")
    print(f"  - 未命中请求数: {len(cache_hits) - sum(cache_hits)}")
    print(f"Cache 命中 prompt tokens: ~{args.shared_prefix_tokens}")
    print(f"随机种子: {args.seed}")
    print(f"预热模式: {'禁用' if args.no_warmup else '启用'}")
    print(f"{'='*60}\n")

    # KVCache 预热：发送 cached_prompt，确保 cache 中有数据
    warmup_record = None
    if not args.no_warmup and args.cache_hit_ratio > 0:
        print(f"正在进行 KVCache 预热...", flush=True)
        warmup_record = await send_request(
            client, args.model, -1, cached_prompt, args.max_tokens, cache_hit=True
        )
        if warmup_record.success:
            print(f"预热完成: TTFT = {warmup_record.ttft_ms:.3f} ms", flush=True)
        else:
            print(f"预热失败: {warmup_record.error}", flush=True)
        print()

    # 创建 Semaphore 控制最大并发数
    semaphore = asyncio.Semaphore(args.concurrency)

    async def send_request_with_semaphore(request_id: int, prompt: str, cache_hit: bool) -> TTFTRecord:
        """带 Semaphore 控制的请求函数"""
        async with semaphore:  # 获取信号量，自动控制并发
            return await send_request(client, args.model, request_id, prompt, args.max_tokens, cache_hit)

    start_time = time.time()

    print(f"开始发送 {args.num_requests} 个请求...", flush=True)

    # 一次性创建所有任务，Semaphore 自动控制并发
    tasks = [
        send_request_with_semaphore(i, prompts[i], cache_hits[i])
        for i in range(args.num_requests)
    ]

    # 等待所有任务完成
    all_records = await asyncio.gather(*tasks)

    total_time = time.time() - start_time

    # 统计
    successful = [r for r in all_records if r.success]
    ttfts = [r.ttft_ms for r in successful]
    
    # 分别统计命中和未命中的 TTFT
    cache_hit_records = [r for r in successful if r.cache_hit]
    cache_miss_records = [r for r in successful if not r.cache_hit]
    ttfts_hit = [r.ttft_ms for r in cache_hit_records]
    ttfts_miss = [r.ttft_ms for r in cache_miss_records]

    print(f"\n{'='*60}")
    print("结果")
    print(f"{'='*60}")
    print(f"总请求数: {len(all_records)}")
    print(f"成功: {len(successful)}")
    print(f"失败: {len(all_records) - len(successful)}")
    print(f"总耗时: {total_time:.2f}s")
    if warmup_record and warmup_record.success:
        print(f"预热 TTFT: {warmup_record.ttft_ms:.3f} ms (首次执行，无 cache)")

    if ttfts:
        stats = calculate_stats(ttfts)
        print(f"\nTTFT (毫秒) [客户端计时] - 全部请求:")
        print(f"  平均: {stats.mean:.3f} ms")
        print(f"  中位数: {stats.median:.3f} ms")
        print(f"  P50: {stats.p50:.3f} ms")
        print(f"  P90: {stats.p90:.3f} ms")
        print(f"  P95: {stats.p95:.3f} ms")
        print(f"  P99: {stats.p99:.3f} ms")
        print(f"  最小: {stats.min:.3f} ms")
        print(f"  最大: {stats.max:.3f} ms")
        print(f"  标准差: {stats.std:.3f} ms")

        # 命中 cache 的 TTFT 统计
        if ttfts_hit:
            stats_hit = calculate_stats(ttfts_hit)
            print(f"\nTTFT (毫秒) - KVCache 命中 ({len(ttfts_hit)} 个请求):")
            print(f"  平均: {stats_hit.mean:.3f} ms")
            print(f"  中位数: {stats_hit.median:.3f} ms")
            print(f"  P90: {stats_hit.p90:.3f} ms")
            print(f"  P99: {stats_hit.p99:.3f} ms")

        # 未命中 cache 的 TTFT 统计
        if ttfts_miss:
            stats_miss = calculate_stats(ttfts_miss)
            print(f"\nTTFT (毫秒) - KVCache 未命中 ({len(ttfts_miss)} 个请求):")
            print(f"  平均: {stats_miss.mean:.3f} ms")
            print(f"  中位数: {stats_miss.median:.3f} ms")
            print(f"  P90: {stats_miss.p90:.3f} ms")
            print(f"  P99: {stats_miss.p99:.3f} ms")

        avg_total = statistics.mean([r.total_latency_ms for r in successful])
        print(f"\n总延迟平均: {avg_total:.3f} ms")

        total_in = sum(r.prompt_tokens for r in successful)
        total_out = sum(r.completion_tokens for r in successful)
        print(f"输出吞吐: {total_out / total_time:.2f} tokens/s")

    print(f"{'='*60}\n")

    # 保存结果
    if args.output:
        stats = calculate_stats(ttfts) if ttfts else None
        stats_hit = calculate_stats(ttfts_hit) if ttfts_hit else None
        stats_miss = calculate_stats(ttfts_miss) if ttfts_miss else None
        
        result = {
            "config": {
                "base_url": args.base_url,
                "model": args.model,
                "num_requests": args.num_requests,
                "concurrency": args.concurrency,
                "input_tokens": args.input_tokens,
                "max_tokens": args.max_tokens,
                "cache_hit_ratio": args.cache_hit_ratio,
                "shared_prefix_tokens": args.shared_prefix_tokens,
                "seed": args.seed,
                "concurrency_mode": "semaphore",
                "warmup_enabled": not args.no_warmup,
            },
            "summary": {
                "total_requests": len(all_records),
                "successful": len(successful),
                "failed": len(all_records) - len(successful),
                "cache_hit_count": len(cache_hit_records),
                "cache_miss_count": len(cache_miss_records),
                "total_time_s": total_time,
                "warmup_ttft_ms": warmup_record.ttft_ms if warmup_record and warmup_record.success else None,
            },
            "ttft_ms": {
                "all": {
                    "mean": stats.mean if stats else 0,
                    "median": stats.median if stats else 0,
                    "p90": stats.p90 if stats else 0,
                    "p99": stats.p99 if stats else 0,
                    "min": stats.min if stats else 0,
                    "max": stats.max if stats else 0,
                } if stats else {},
                "cache_hit": {
                    "mean": stats_hit.mean if stats_hit else 0,
                    "median": stats_hit.median if stats_hit else 0,
                    "p90": stats_hit.p90 if stats_hit else 0,
                    "p99": stats_hit.p99 if stats_hit else 0,
                } if stats_hit else {},
                "cache_miss": {
                    "mean": stats_miss.mean if stats_miss else 0,
                    "median": stats_miss.median if stats_miss else 0,
                    "p90": stats_miss.p90 if stats_miss else 0,
                    "p99": stats_miss.p99 if stats_miss else 0,
                } if stats_miss else {},
            },
            "records": [
                {
                    "id": r.request_id,
                    "ttft_ms": r.ttft_ms,
                    "total_latency_ms": r.total_latency_ms,
                    "cache_hit": r.cache_hit,
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
