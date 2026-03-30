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
POSIX存储后端测试 - 小规模版本
适用于磁盘空间受限的环境

测试参数对比：
原始版本：block_size=1MB, batch_size=1024, batch_number=64, 总数据量=64GB
小规模版：block_size=64KB, batch_size=64, batch_number=10, 总数据量=40MB
"""
import os
import secrets
import time

import numpy as np

from ucm.store.pipeline.connector import UcmKVStoreBaseV1, UcmPipelineStore


def setup(
    backends: list[str],
    block_size: int,
    data_trans_concur: int,
    lookup_concur: int,
    io_direct: bool,
    worker: bool,
) -> UcmKVStoreBaseV1:
    config = {}
    config["store_pipeline"] = "Posix"
    config["storage_backends"] = backends
    config["tensor_size"] = block_size
    config["shard_size"] = block_size
    config["block_size"] = block_size
    config["posix_data_trans_concurrency"] = data_trans_concur
    config["posix_lookup_concurrency"] = lookup_concur
    config["io_direct"] = io_direct
    config["device_id"] = 0 if worker else -1
    return UcmPipelineStore(config)


def aligned_array(size, alignment=4096, dtype=np.uint8):
    extra = alignment
    buf = np.empty(size + extra, dtype=dtype)
    address = buf.ctypes.data
    offset = (alignment - (address % alignment)) % alignment
    aligned_view = buf[offset : offset + size]
    return aligned_view


def main():
    # 小规模测试参数（总数据量约40MB）
    backends = ["./build/data"]
    block_size = 65536  # 64KB (原: 1MB)
    data_trans_concur = 4
    lookup_concur = 4
    io_direct = False  # 小数据量关闭直IO
    batch_number = 10  # 减少批次数(原: 64)
    batch_size = 64    # 减少批次大小 (原: 1024)
    
    print("=" * 60)
    print("POSIX 存储后端测试 - 小规模版本")
    print("=" * 60)
    print(f"存储路径: {backends[0]}")
    print(f"块大小: {block_size / 1024:.0f} KB")
    print(f"批次大小: {batch_size}")
    print(f"批次数量: {batch_number}")
    print(f"每轮数据量: {block_size * batch_size / 1024 / 1024:.2f} MB")
    print(f"预计总数据量: {block_size * batch_size * batch_number / 1024 / 1024:.2f} MB")
    print("=" * 60)
    
    worker = setup(
        backends, block_size, data_trans_concur, lookup_concur, io_direct, True
    )
    scheduler = setup(
        backends, block_size, data_trans_concur, lookup_concur, io_direct, False
    )
    
    data_size = block_size * batch_size
    raw_data1 = [aligned_array(block_size) for _ in range(batch_size)]
    raw_data2 = [aligned_array(block_size) for _ in range(batch_size)]
    data1 = [[d.ctypes.data] for d in raw_data1]
    data2 = [[d.ctypes.data] for d in raw_data2]
    
    total_dump_time = 0
    total_load_time = 0
    success_count = 0
    
    for idx in range(batch_number):
        block_ids = [secrets.token_bytes(16) for _ in range(batch_size)]
        shard_idxes = [0 for _ in range(batch_size)]

        # Lookup阶段 1 (0% 命中)
        tp = time.perf_counter()
        founds = scheduler.lookup(block_ids)
        cost_fully_lookup1 = time.perf_counter() - tp
        if any(founds):
            print(f"[{idx:03}/{batch_number:03}] WARNING: 初始Lookup发现已存在的块")
        assert not any(founds)

        # Prefix Lookup阶段 1
        tp = time.perf_counter()
        found_idx = scheduler.lookup_on_prefix(block_ids)
        cost_prefix_lookup1 = time.perf_counter() - tp
        assert found_idx == -1

        # Dump阶段 (写入缓存)
        tp = time.perf_counter()
        handle = worker.dump_data(block_ids, shard_idxes, data1)
        worker.wait(handle)
        cost_dump = time.perf_counter() - tp
        total_dump_time += cost_dump

        # Lookup阶段 2 (100% 命中)
        tp = time.perf_counter()
        founds = scheduler.lookup(block_ids)
        cost_fully_lookup2 = time.perf_counter() - tp
        if not all(founds):
            print(f"[{idx:03}/{batch_number:03}] ERROR: Dump后Lookup未找到所有块")
        assert all(founds)

        # Prefix Lookup阶段 2
        tp = time.perf_counter()
        found_idx = scheduler.lookup_on_prefix(block_ids)
        cost_prefix_lookup2 = time.perf_counter() - tp
        assert found_idx == batch_size - 1

        # Load阶段 (读取缓存)
        tp = time.perf_counter()
        handle = worker.load_data(block_ids, shard_idxes, data2)
        worker.wait(handle)
        cost_load = time.perf_counter() - tp
        total_load_time += cost_load

        # 数据一致性验证
        for i in range(batch_size):
            if not np.array_equal(raw_data1[i], raw_data2[i]):
                print(f"[{idx:03}/{batch_number:03}] ERROR: 数据不一致 at index {i}")
                break
        else:
            success_count += 1

        bw_dump = data_size / cost_dump
        bw_load = data_size / cost_load
        print(
            f"[{idx:03}/{batch_number:03}] "
            f"lookup1={cost_fully_lookup1 * 1e3:.2f}ms, "
            f"lookup2={cost_fully_lookup2 * 1e3:.2f}ms, "
            f"dump={cost_dump * 1e3:.2f}ms, "
            f"load={cost_load * 1e3:.2f}ms, "
            f"bw_dump={bw_dump / 1e6:.2f}MB/s, "
            f"bw_load={bw_load / 1e6:.2f}MB/s"
        )

    print("=" * 60)
    print("测试结果汇总:")
    print(f"  成功批次: {success_count}/{batch_number}")
    print(f"  平均Dump带宽: {data_size * batch_number / total_dump_time / 1e6:.2f} MB/s")
    print(f"  平均Load带宽: {data_size * batch_number / total_load_time / 1e6:.2f} MB/s")
    print("=" * 60)
    
    if success_count == batch_number:
        print("✓ POSIX 存储后端测试通过!")
    else:
        print("✗ POSIX 存储后端测试失败!")


if __name__ == "__main__":
    os.environ["UC_LOGGER_LEVEL"] = "info"
    main()
