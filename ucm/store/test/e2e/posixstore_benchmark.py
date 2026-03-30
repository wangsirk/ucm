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
POSIX存储后端压力测试和高性能测试脚本

测试类型：
1. 压力测试 (Stress Test) - 大量数据写入/读取，测试系统稳定性
2. 高性能测试 (Performance Test) - 测试最大带宽和延迟

使用方法：
  python posixstore_benchmark.py --test-type stress
  python posixstore_benchmark.py --test-type performance
  python posixstore_benchmark.py --test-type all
"""
import argparse
import os
import secrets
import shutil
import statistics
import time
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from ucm.store.pipeline.connector import UcmKVStoreBaseV1, UcmPipelineStore


@dataclass
class TestConfig:
    """测试配置"""
    backends: List[str]
    block_size: int
    batch_size: int
    batch_number: int
    data_trans_concur: int
    lookup_concur: int
    io_direct: bool
    

@dataclass
class TestResult:
    """测试结果"""
    total_files: int
    total_data_mb: float
    total_time_s: float
    dump_bandwidth_mbps: float
    load_bandwidth_mbps: float
    dump_latencies_ms: List[float]
    load_latencies_ms: List[float]
    lookup_latencies_ms: List[float]


def setup(config: TestConfig, worker: bool) -> UcmKVStoreBaseV1:
    """初始化存储实例"""
    store_config = {}
    store_config["store_pipeline"] = "Posix"
    store_config["storage_backends"] = config.backends
    store_config["tensor_size"] = config.block_size
    store_config["shard_size"] = config.block_size
    store_config["block_size"] = config.block_size
    store_config["posix_data_trans_concurrency"] = config.data_trans_concur
    store_config["posix_lookup_concurrency"] = config.lookup_concur
    store_config["io_direct"] = config.io_direct
    store_config["device_id"] = 0 if worker else -1
    return UcmPipelineStore(store_config)


def aligned_array(size: int, alignment: int = 4096, dtype=np.uint8):
    """创建对齐的数组"""
    extra = alignment
    buf = np.empty(size + extra, dtype=dtype)
    address = buf.ctypes.data
    offset = (alignment - (address % alignment)) % alignment
    aligned_view = buf[offset: offset + size]
    return aligned_view


def run_stress_test(config: TestConfig) -> TestResult:
    """
    压力测试：大量数据写入/读取，测试系统稳定性
    """
    print("\n" + "=" * 70)
    print("压力测试 (Stress Test)")
    print("=" * 70)
    print(f"块大小: {config.block_size / 1024:.0f} KB")
    print(f"批次大小: {config.batch_size}")
    print(f"批次数量: {config.batch_number}")
    print(f"总数据量: {config.block_size * config.batch_size * config.batch_number / 1024 / 1024:.2f} MB")
    print("=" * 70)
    
    # 清理旧数据
    for backend in config.backends:
        if os.path.exists(backend):
            shutil.rmtree(backend)
        os.makedirs(backend, exist_ok=True)
    
    worker = setup(config, worker=True)
    scheduler = setup(config, worker=False)
    
    data_size = config.block_size * config.batch_size
    raw_data1 = [aligned_array(config.block_size) for _ in range(config.batch_size)]
    raw_data2 = [aligned_array(config.block_size) for _ in range(config.batch_size)]
    data1 = [[d.ctypes.data] for d in raw_data1]
    data2 = [[d.ctypes.data] for d in raw_data2]
    
    dump_latencies = []
    load_latencies = []
    lookup_latencies = []
    total_dump_time = 0
    total_load_time = 0
    success_count = 0
    
    start_time = time.perf_counter()
    
    for idx in range(config.batch_number):
        block_ids = [secrets.token_bytes(16) for _ in range(config.batch_size)]
        shard_idxes = [0 for _ in range(config.batch_size)]
        
        # Lookup
        tp = time.perf_counter()
        founds = scheduler.lookup(block_ids)
        lookup_latencies.append((time.perf_counter() - tp) * 1000)
        assert not any(founds)
        
        # Dump
        tp = time.perf_counter()
        handle = worker.dump_data(block_ids, shard_idxes, data1)
        worker.wait(handle)
        dump_time = time.perf_counter() - tp
        dump_latencies.append(dump_time * 1000)
        total_dump_time += dump_time
        
        # Lookup after dump
        tp = time.perf_counter()
        founds = scheduler.lookup(block_ids)
        lookup_latencies.append((time.perf_counter() - tp) * 1000)
        assert all(founds)
        
        # Load
        tp = time.perf_counter()
        handle = worker.load_data(block_ids, shard_idxes, data2)
        worker.wait(handle)
        load_time = time.perf_counter() - tp
        load_latencies.append(load_time * 1000)
        total_load_time += load_time
        
        # 验证数据
        all_match = all(np.array_equal(raw_data1[i], raw_data2[i]) for i in range(config.batch_size))
        if all_match:
            success_count += 1
        
        # 显示进度
        bw_dump = data_size / dump_time / 1e6
        bw_load = data_size / load_time / 1e6
        print(f"[{idx+1:03}/{config.batch_number:03}] "
              f"dump={dump_time*1000:.2f}ms ({bw_dump:.0f}MB/s), "
              f"load={load_time*1000:.2f}ms ({bw_load:.0f}MB/s)")
    
    total_time = time.perf_counter() - start_time
    total_files = config.batch_size * config.batch_number
    total_data_mb = data_size * config.batch_number / 1024 / 1024
    
    return TestResult(
        total_files=total_files,
        total_data_mb=total_data_mb,
        total_time_s=total_time,
        dump_bandwidth_mbps=total_data_mb / total_dump_time,
        load_bandwidth_mbps=total_data_mb / total_load_time,
        dump_latencies_ms=dump_latencies,
        load_latencies_ms=load_latencies,
        lookup_latencies_ms=lookup_latencies
    )


def run_performance_test(config: TestConfig) -> TestResult:
    """
    高性能测试：测试最大带宽和延迟
    使用更大的数据块和更高的并发
    """
    print("\n" + "=" * 70)
    print("高性能测试 (Performance Test)")
    print("=" * 70)
    print(f"块大小: {config.block_size / 1024:.0f} KB")
    print(f"批次大小: {config.batch_size}")
    print(f"批次数量: {config.batch_number}")
    print(f"并发数: {config.data_trans_concur}")
    print(f"DirectIO: {config.io_direct}")
    print("=" * 70)
    
    # 清理旧数据
    for backend in config.backends:
        if os.path.exists(backend):
            shutil.rmtree(backend)
        os.makedirs(backend, exist_ok=True)
    
    worker = setup(config, worker=True)
    scheduler = setup(config, worker=False)
    
    data_size = config.block_size * config.batch_size
    raw_data1 = [aligned_array(config.block_size) for _ in range(config.batch_size)]
    raw_data2 = [aligned_array(config.block_size) for _ in range(config.batch_size)]
    data1 = [[d.ctypes.data] for d in raw_data1]
    data2 = [[d.ctypes.data] for d in raw_data2]
    
    dump_latencies = []
    load_latencies = []
    lookup_latencies = []
    total_dump_time = 0
    total_load_time = 0
    
    # 预热
    print("预热中...")
    warmup_ids = [secrets.token_bytes(16) for _ in range(min(10, config.batch_size))]
    if warmup_ids:
        handle = worker.dump_data(warmup_ids, [0] * len(warmup_ids), data1[:len(warmup_ids)])
        worker.wait(handle)
    
    print("开始性能测试...")
    start_time = time.perf_counter()
    
    for idx in range(config.batch_number):
        block_ids = [secrets.token_bytes(16) for _ in range(config.batch_size)]
        shard_idxes = [0 for _ in range(config.batch_size)]
        
        # Dump
        tp = time.perf_counter()
        handle = worker.dump_data(block_ids, shard_idxes, data1)
        worker.wait(handle)
        dump_time = time.perf_counter() - tp
        dump_latencies.append(dump_time * 1000)
        total_dump_time += dump_time
        
        # Load
        tp = time.perf_counter()
        handle = worker.load_data(block_ids, shard_idxes, data2)
        worker.wait(handle)
        load_time = time.perf_counter() - tp
        load_latencies.append(load_time * 1000)
        total_load_time += load_time
        
        bw_dump = data_size / dump_time / 1e6
        bw_load = data_size / load_time / 1e6
        print(f"[{idx+1:03}/{config.batch_number:03}] "
              f"dump={dump_time*1000:.2f}ms ({bw_dump:.0f}MB/s), "
              f"load={load_time*1000:.2f}ms ({bw_load:.0f}MB/s)")
    
    total_time = time.perf_counter() - start_time
    total_files = config.batch_size * config.batch_number
    total_data_mb = data_size * config.batch_number / 1024 / 1024
    
    return TestResult(
        total_files=total_files,
        total_data_mb=total_data_mb,
        total_time_s=total_time,
        dump_bandwidth_mbps=total_data_mb / total_dump_time,
        load_bandwidth_mbps=total_data_mb / total_load_time,
        dump_latencies_ms=dump_latencies,
        load_latencies_ms=load_latencies,
        lookup_latencies_ms=lookup_latencies
    )


def print_results(result: TestResult, test_name: str):
    """打印测试结果"""
    print("\n" + "=" * 70)
    print(f"{test_name} 结果汇总")
    print("=" * 70)
    print(f"总文件数: {result.total_files}")
    print(f"总数据量: {result.total_data_mb:.2f} MB")
    print(f"总耗时: {result.total_time_s:.2f} s")
    print("")
    print("带宽指标:")
    print(f"  平均Dump带宽: {result.dump_bandwidth_mbps:.2f} MB/s")
    print(f"  平均Load带宽: {result.load_bandwidth_mbps:.2f} MB/s")
    print("")
    
    if result.dump_latencies_ms:
        print("Dump延迟统计:")
        print(f"  平均: {statistics.mean(result.dump_latencies_ms):.2f} ms")
        print(f"  最小: {min(result.dump_latencies_ms):.2f} ms")
        print(f"  最大: {max(result.dump_latencies_ms):.2f} ms")
        if len(result.dump_latencies_ms) > 1:
            print(f"  标准差: {statistics.stdev(result.dump_latencies_ms):.2f} ms")
        print("")
    
    if result.load_latencies_ms:
        print("Load延迟统计:")
        print(f"  平均: {statistics.mean(result.load_latencies_ms):.2f} ms")
        print(f"  最小: {min(result.load_latencies_ms):.2f} ms")
        print(f"  最大: {max(result.load_latencies_ms):.2f} ms")
        if len(result.load_latencies_ms) > 1:
            print(f"  标准差: {statistics.stdev(result.load_latencies_ms):.2f} ms")
        print("")
    
    if result.lookup_latencies_ms:
        print("Lookup延迟统计:")
        print(f"  平均: {statistics.mean(result.lookup_latencies_ms):.2f} ms")
        print(f"  最小: {min(result.lookup_latencies_ms):.2f} ms")
        print(f"  最大: {max(result.lookup_latencies_ms):.2f} ms")
    
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="POSIX存储后端压力测试和高性能测试")
    parser.add_argument("--test-type", choices=["stress", "performance", "all"], 
                        default="all", help="测试类型")
    parser.add_argument("--storage-path", default="./build/data_benchmark",
                        help="存储路径")
    parser.add_argument("--block-size-kb", type=int, default=64,
                        help="块大小 (KB)")
    parser.add_argument("--batch-size", type=int, default=64,
                        help="批次大小")
    parser.add_argument("--batch-number", type=int, default=10,
                        help="批次数量")
    parser.add_argument("--concurrency", type=int, default=8,
                        help="并发数")
    parser.add_argument("--io-direct", action="store_true",
                        help="启用DirectIO")
    args = parser.parse_args()
    
    block_size = args.block_size_kb * 1024
    
    # 压力测试配置（较小数据块，大量批次）
    stress_config = TestConfig(
        backends=[args.storage_path],
        block_size=block_size,
        batch_size=args.batch_size,
        batch_number=args.batch_number,
        data_trans_concur=args.concurrency,
        lookup_concur=args.concurrency,
        io_direct=args.io_direct
    )
    
    # 高性能测试配置（较大数据块，高并发）
    perf_config = TestConfig(
        backends=[args.storage_path + "_perf"],
        block_size=block_size * 4,  # 更大的块
        batch_size=args.batch_size * 2,  # 更大的批次
        batch_number=max(5, args.batch_number // 2),
        data_trans_concur=args.concurrency * 2,  # 更高的并发
        lookup_concur=args.concurrency * 2,
        io_direct=True  # 启用DirectIO
    )
    
    results = {}
    
    if args.test_type in ["stress", "all"]:
        results["stress"] = run_stress_test(stress_config)
        print_results(results["stress"], "压力测试")
    
    if args.test_type in ["performance", "all"]:
        results["performance"] = run_performance_test(perf_config)
        print_results(results["performance"], "高性能测试")
    
    return 0


if __name__ == "__main__":
    os.environ["UC_LOGGER_LEVEL"] = "info"
    exit(main())
