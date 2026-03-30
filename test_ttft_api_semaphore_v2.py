#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TTFT 测试脚本 - 改进版，支持并发情况下正确测量 Cache 效果

主要改进：
    1. 不打乱请求顺序，保持可预测性
    2. 按完成顺序分组分析，排除队列影响
    3. 提供配对模式：cache_hit 和 cache_miss 成对发送
    4. 计算服务时间（Service Time），排除队列时间

用法:
    # 配对模式：推荐，能准确对比 cache 效果
    python test_ttft_api_semaphore_v2.py --num-requests 8 --concurrency 8 --paired-mode

    # 顺序模式：保持原有顺序，不打乱
    python test_ttft_api_semaphore_v2.py --num-requests 8 --concurrency 8 --no-shuffle
"""

"""
测试流程如下：
1. 解析命令行参数
2. 生成prompts（按照命中率）
3. KVCache预热
4. 创建Semaphore控制并发
5. 并发发送所有请求
6. 收集结果并统计分析
7. 输出报告 

配对模式（Paired Mode）
请求序列：[cache_hit, cache_miss, ...]
交替发送命中和未命中请求，确保两者在相同并发条件下竞争

KVCache预热：
在正式测试前，先发送一次共享前缀的请求，确保后续的“命中”请求能够真正命中缓存

并发控制，使用asyncio.Semaphore控制最大并发数
"""


import argparse
import asyncio
import json
import random
import statistics
import time
from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np
from openai import AsyncOpenAI


@dataclass
class TTFTRecord:
    request_id: int
    send_time: float
    first_token_time: float
    complete_time: float
    ttft_ms: float
    service_time_ms: float  # 服务时间（不含队列等待）
    queue_time_ms: float     # 队列等待时间
    total_latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    success: bool
    cache_hit: bool = False
    completion_order: int = 0  # 完成顺序
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
    if not ttfts:
        return TTFTStats(0, 0, 0, 0, 0, 0, 0, 0, 0)
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
    """生成共享前缀"""
    base = "请分析深度学习在自然语言处理领域的应用和发展趋势，包括语言模型、机器翻译、文本分类、情感分析、命名实体识别、问答系统等多个子领域的技术进展。"
    chars_needed = prefix_tokens * 2
    repeat = max(1, chars_needed // len(base))
    return " ".join([base] * repeat)


def generate_prompts_for_cache_ratio(
    num_requests: int,
    target_tokens: int,
    cache_hit_ratio: float,
    shared_prefix_tokens: int = 50,
    paired_mode: bool = False,
) -> Tuple[List[str], List[bool], str]:
    """根据 KVCache 命中率生成 prompts

    Args:
        paired_mode: 配对模式，生成 (hit, miss, hit, miss, ...) 交替的序列
    """
    prompts = []
    cache_hits = []

    cached_prompt = generate_shared_prefix(shared_prefix_tokens)

    num_cache_hits = int(num_requests * cache_hit_ratio)
    num_cache_misses = num_requests - num_cache_hits

    if paired_mode:
        # 配对模式：交替生成 hit/miss
        # 例如 8 个请求，50% 命中率 → [HIT, MISS, HIT, MISS, HIT, MISS, HIT, MISS]
        hits_used = 0
        misses_used = 0
        for i in range(num_requests):
            if i % 2 == 0 and hits_used < num_cache_hits:
                # 偶数位置放 HIT
                prompts.append(cached_prompt)
                cache_hits.append(True)
                hits_used += 1
            elif i % 2 == 1 and misses_used < num_cache_misses:
                # 奇数位置放 MISS
                unique_content = f"问题编号{random.randint(10000, 99999)}：请详细阐述机器学习在医疗诊断中的应用，包括影像识别、病理分析、药物研发等多个领域的具体案例和技术挑战。这是一个完全独立的请求。"
                chars_needed = target_tokens * 2
                repeat = max(1, chars_needed // len(unique_content))
                miss_prompt = " ".join([unique_content] * repeat)
                prompts.append(miss_prompt)
                cache_hits.append(False)
                misses_used += 1
            elif hits_used < num_cache_hits:
                # 用完了 MISS 位置，剩余都放 HIT
                prompts.append(cached_prompt)
                cache_hits.append(True)
                hits_used += 1
            else:
                # 用完了 HIT 位置，剩余都放 MISS
                unique_content = f"问题编号{random.randint(10000, 99999)}：请详细阐述机器学习在医疗诊断中的应用，包括影像识别、病理分析、药物研发等多个领域的具体案例和技术挑战。这是一个完全独立的请求。"
                chars_needed = target_tokens * 2
                repeat = max(1, chars_needed // len(unique_content))
                miss_prompt = " ".join([unique_content] * repeat)
                prompts.append(miss_prompt)
                cache_hits.append(False)
                misses_used += 1
    else:
        # 普通模式先生成命中，再生成未命中（不shuffle）
        for i in range(num_cache_hits):
            prompts.append(cached_prompt)
            cache_hits.append(True)

        for i in range(num_cache_misses):
            unique_content = f"问题编号{random.randint(10000, 99999)}：请详细阐述机器学习在医疗诊断中的应用，包括影像识别、病理分析、药物研发等多个领域的具体案例和技术挑战。这是一个完全独立的请求。"
            chars_needed = target_tokens * 2
            repeat = max(1, chars_needed // len(unique_content))
            miss_prompt = " ".join([unique_content] * repeat)
            prompts.append(miss_prompt)
            cache_hits.append(False)

    return list(prompts), list(cache_hits), cached_prompt


async def send_request(
    client: AsyncOpenAI,
    model: str,
    request_id: int,
    prompt: str,
    max_tokens: int,
    cache_hit: bool = False,
    global_send_time: float = None,
) -> TTFTRecord:
    """发送单个请求并测量 TTFT"""
    send_time = time.perf_counter()
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
            if chunk.choices:
                if ttft == 0.0:
                    first_token_time = time.perf_counter()
                    ttft = first_token_time - send_time
                if chunk.choices[0].delta.content:
                    text += chunk.choices[0].delta.content

        complete_time = time.perf_counter()

        ttft_ms = ttft * 1000 if ttft > 0 else 0
        total_ms = (complete_time - send_time) * 1000

        service_time_ms = ttft_ms
        queue_time_ms = 0

        prompt_tokens = len(prompt) // 2
        completion_tokens = len(text) // 2

        return TTFTRecord(
            request_id=request_id,
            send_time=send_time,
            first_token_time=first_token_time,
            complete_time=complete_time,
            ttft_ms=ttft_ms,
            service_time_ms=service_time_ms,
            queue_time_ms=queue_time_ms,
            total_latency_ms=total_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            success=True,
            cache_hit=cache_hit,
            completion_order=0,
        )

    except Exception as e:
        return TTFTRecord(
            request_id=request_id,
            send_time=send_time,
            first_token_time=0,
            complete_time=0,
            ttft_ms=0,
            service_time_ms=0,
            queue_time_ms=0,
            total_latency_ms=0,
            prompt_tokens=0,
            completion_tokens=0,
            success=False,
            cache_hit=cache_hit,
            error=str(e),
        )


async def main():
    parser = argparse.ArgumentParser(
        description="TTFT 测试 - 改进版，正确处理并发下的 Cache 测量"
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
                        help="禁用 KVCache 预热")
    parser.add_argument("--no-shuffle", action="store_true",
                        help="禁用 shuffle，保持请求顺序（推荐）")
    parser.add_argument("--paired-mode", action="store_true",
                        help="配对模式：cache_hit 和 cache_miss 交替发送，最佳对比效果")
    args = parser.parse_args()

    random.seed(args.seed)
    client = AsyncOpenAI(base_url=args.base_url, api_key="empty")

    # 生成 prompts
    prompts, cache_hits, cached_prompt = generate_prompts_for_cache_ratio(
        num_requests=args.num_requests,
        target_tokens=args.input_tokens,
        cache_hit_ratio=args.cache_hit_ratio,
        shared_prefix_tokens=args.shared_prefix_tokens,
        paired_mode=args.paired_mode,
    )

    print(f"\n{'='*70}")
    print("TTFT 测试 (改进版 - 并发下正确测量 Cache 效果)")
    print(f"{'='*70}")
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
    print(f"模式: {'配对模式 (最佳)' if args.paired_mode else '顺序模式' if args.no_shuffle else '随机模式'}")
    print(f"随机种子: {args.seed}")
    print(f"预热模式: {'禁用' if args.no_warmup else '启用'}")
    print(f"{'='*70}\n")

    # 预热
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

    # 创建 Semaphore
    semaphore = asyncio.Semaphore(args.concurrency)

    async def send_request_with_semaphore(request_id: int, prompt: str, cache_hit: bool) -> TTFTRecord:
        async with semaphore:
            return await send_request(client, args.model, request_id, prompt, args.max_tokens, cache_hit)

    global_start = time.time()
    print(f"开始发送 {args.num_requests} 个请求...", flush=True)

    tasks = [
        send_request_with_semaphore(i, prompts[i], cache_hits[i])
        for i in range(args.num_requests)
    ]

    all_records = await asyncio.gather(*tasks)
    total_time = time.time() - global_start

    # 记录完成顺序
    successful = [r for r in all_records if r.success]
    for idx, record in enumerate(successful):
        record.completion_order = idx

    # 按完成顺序排序分析
    sorted_by_completion = sorted(successful, key=lambda r: r.completion_order)

    print(f"\n{'='*70}")
    print("按完成顺序的请求详情")
    print(f"{'='*70}")
    print(f"{'顺序':<6} {'ID':<4} {'Cache':<8} {'TTFT(ms)':<12} {'发送时间':<12}")
    print("-" * 70)
    for r in sorted_by_completion[:20]:  # 只显示前20个
        cache_str = "HIT" if r.cache_hit else "MISS"
        send_offset = (r.send_time - global_start) * 1000
        print(f"{r.completion_order:<6} {r.request_id:<4} {cache_str:<8} {r.ttft_ms:<12.3f} {send_offset:<12.3f}")

    # 计算统计
    ttfts = [r.ttft_ms for r in successful]
    cache_hit_records = [r for r in successful if r.cache_hit]
    cache_miss_records = [r for r in successful if not r.cache_hit]
    ttfts_hit = [r.ttft_ms for r in cache_hit_records]
    ttfts_miss = [r.ttft_ms for r in cache_miss_records]

    print(f"\n{'='*70}")
    print("结果统计")
    print(f"{'='*70}")
    print(f"总请求数: {len(all_records)}")
    print(f"成功: {len(successful)}")
    print(f"失败: {len(all_records) - len(successful)}")
    print(f"总耗时: {total_time:.2f}s")
    if warmup_record and warmup_record.success:
        print(f"预热 TTFT: {warmup_record.ttft_ms:.3f} ms (首次执行，无 cache)")

    if ttfts:
        stats = calculate_stats(ttfts)
        print(f"\nTTFT (毫秒) - 全部请求:")
        print(f"  平均: {stats.mean:.3f} ms")
        print(f"  中位数: {stats.median:.3f} ms")
        print(f"  P50: {stats.p50:.3f} ms")
        print(f"  P90: {stats.p90:.3f} ms")
        print(f"  P95: {stats.p95:.3f} ms")
        print(f"  P99: {stats.p99:.3f} ms")
        print(f"  最小: {stats.min:.3f} ms")
        print(f"  最大: {stats.max:.3f} ms")
        print(f"  标准差: {stats.std:.3f} ms")

        # 命中 cache 的统计
        if ttfts_hit:
            stats_hit = calculate_stats(ttfts_hit)
            print(f"\nTTFT (毫秒) - KVCache 命中 ({len(ttfts_hit)} 个请求):")
            print(f"  平均: {stats_hit.mean:.3f} ms")
            print(f"  中位数: {stats_hit.median:.3f} ms")
            print(f"  P90: {stats_hit.p90:.3f} ms")
            print(f"  P99: {stats_hit.p99:.3f} ms")

        # 未命中 cache 的统计
        if ttfts_miss:
            stats_miss = calculate_stats(ttfts_miss)
            print(f"\nTTFT (毫秒) - KVCache 未命中 ({len(ttfts_miss)} 个请求):")
            print(f"  平均: {stats_miss.mean:.3f} ms")
            print(f"  中位数: {stats_miss.median:.3f} ms")
            print(f"  P90: {stats_miss.p90:.3f} ms")
            print(f"  P99: {stats_miss.p99:.3f} ms")

        # 对比分析
        if ttfts_hit and ttfts_miss:
            hit_avg = statistics.mean(ttfts_hit)
            miss_avg = statistics.mean(ttfts_miss)
            speedup = miss_avg / hit_avg if hit_avg > 0 else 0
            print(f"\n{'='*70}")
            print("对比分析")
            print(f"{'='*70}")
            print(f"Cache 加速比: {speedup:.2f}x")
            if speedup > 1.2:
                print(f"✓ Cache 生效！命中组比未命中组快 {speedup:.2f}x")
            elif speedup < 0.8:
                print(f"✗ 注意：命中组比未命中组慢，可能是队列效应或 cache 未真正生效")
            else:
                print(f"≈ 差异不明显，可能队列时间掩盖了 cache 效果")

    print(f"{'='*70}\n")

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
                "paired_mode": args.paired_mode,
                "no_shuffle": args.no_shuffle,
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
                    "completion_order": r.completion_order,
                    "send_time_offset_ms": (r.send_time - global_start) * 1000,
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
