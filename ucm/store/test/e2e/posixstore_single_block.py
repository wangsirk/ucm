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
POSIX存储后端数据验证测试 - 单block_id模式
仅生成一个block_id，用于验证存储目录结构和文件命名规则
"""
import os
import secrets
import shutil

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
    # 测试参数
    # 使用 Lustre 客户端挂载点作为存储路径
    backends = ["/mnt/lustre/data_verify"]
    block_size = 65536  # 64KB
    data_trans_concur = 4
    lookup_concur = 4
    io_direct = False
    
    # 清理旧数据
    if os.path.exists(backends[0]):
        shutil.rmtree(backends[0])
    os.makedirs(backends[0], exist_ok=True)
    
    print("=" * 70)
    print("POSIX 存储后端数据验证测试 - 单block_id模式")
    print("=" * 70)
    print(f"存储路径: {backends[0]}")
    print(f"块大小: {block_size / 1024:.0f} KB")
    
    # 生成单个 block_id (16字节随机数)
    block_id = secrets.token_bytes(16)
    shard_idx = 0
    
    print("\n" + "=" * 70)
    print("Block ID 信息:")
    print("=" * 70)
    print(f"  原始字节 (hex): {block_id.hex()}")
    print(f"  字节长度: {len(block_id)} bytes")
    print(f"  十六进制字符数: {len(block_id.hex())} chars")
    
    # 打印字节序列详情
    print("\n  字节序列详情:")
    byte_list = list(block_id)
    print(f"    字节列表 (十进制): {byte_list}")
    print(f"    字节列表 (十六进制): {[hex(b) for b in byte_list]}")
    print(f"    字节列表 (0x格式): {[f'0x{b:02x}' for b in byte_list]}")
    
    # 分组显示字节序列
    print("\n  字节序列分组显示:")
    for i in range(0, len(block_id), 4):
        chunk = block_id[i:i+4]
        hex_str = ' '.join(f'{b:02x}' for b in chunk)
        dec_str = ' '.join(f'{b:3d}' for b in chunk)
        print(f"    字节[{i:2d}-{i+3:2d}]: hex={hex_str}  dec=[{dec_str}]")
    
    # 计算预期的文件路径
    file_name = block_id.hex()  # 32字符十六进制文件名
    shard_dir = file_name[:3]    # 前3字符作为子目录名
    expected_path = f"{backends[0]}/{shard_dir}/{file_name}"
    
    print("\n" + "=" * 70)
    print("预期存储路径分析:")
    print("=" * 70)
    print(f"  存储后端路径: {backends[0]}")
    print(f"  子目录名 (文件名前3字符): {shard_dir}")
    print(f"  文件名 (block_id hex): {file_name}")
    print(f"  完整文件路径: {expected_path}")
    
    worker = setup(
        backends, block_size, data_trans_concur, lookup_concur, io_direct, True
    )
    scheduler = setup(
        backends, block_size, data_trans_concur, lookup_concur, io_direct, False
    )
    
    # 创建对齐的缓冲区并填充数据
    raw_data1 = aligned_array(block_size)
    raw_data2 = aligned_array(block_size)
    raw_data1[:] = np.arange(block_size, dtype=np.uint8)  # 填充顺序数据: 0, 1, 2, ..., 255, 0, 1, ...
    data1 = [[raw_data1.ctypes.data]]
    data2 = [[raw_data2.ctypes.data]]
    
    print("\n" + "=" * 70)
    print("写入数据信息:")
    print("=" * 70)
    print(f"  数据大小: {block_size} bytes")
    print(f"  数据样本 (前16字节): {raw_data1[:16].tolist()}")
    
    # Lookup阶段 1 (应该不存在)
    print("\n" + "=" * 70)
    print("步骤1: Lookup (写入前)")
    print("=" * 70)
    founds = scheduler.lookup([block_id])
    print(f"  查找结果: {founds[0]} (预期: False)")
    assert not founds[0], "Block should not exist before dump"
    
    # Dump阶段 (写入缓存)
    print("\n" + "=" * 70)
    print("步骤2: Dump (写入数据)")
    print("=" * 70)
    handle = worker.dump_data([block_id], [shard_idx], data1)
    worker.wait(handle)
    print(f"  写入完成!")
    
    # 检查实际生成的目录结构
    print("\n" + "=" * 70)
    print("实际存储目录结构:")
    print("=" * 70)
    
    # 列出存储根目录下的子目录
    subdirs = [d for d in os.listdir(backends[0]) if os.path.isdir(os.path.join(backends[0], d))]
    print(f"  根目录下的子目录数量: {len(subdirs)}")
    print(f"  根目录下的子目录样本 (前10个): {sorted(subdirs)[:10]}")
    
    # 检查目标子目录
    target_subdir = os.path.join(backends[0], shard_dir)
    if os.path.exists(target_subdir):
        files = os.listdir(target_subdir)
        print(f"\n  目标子目录 {shard_dir}:")
        print(f"    路径: {target_subdir}")
        print(f"    文件数量: {len(files)}")
        print(f"    文件列表: {files}")
        
        # 检查目标文件
        target_file = os.path.join(target_subdir, file_name)
        if os.path.exists(target_file):
            file_size = os.path.getsize(target_file)
            print(f"\n  目标文件:")
            print(f"    路径: {target_file}")
            print(f"    大小: {file_size} bytes (预期: {block_size} bytes)")
            print(f"    匹配预期路径: {target_file == expected_path}")
        else:
            print(f"\n  警告: 目标文件不存在: {target_file}")
    else:
        print(f"\n  警告: 目标子目录不存在: {target_subdir}")
    
    # Lookup阶段 2 (应该存在)
    print("\n" + "=" * 70)
    print("步骤3: Lookup (写入后)")
    print("=" * 70)
    founds = scheduler.lookup([block_id])
    print(f"  查找结果: {founds[0]} (预期: True)")
    assert founds[0], "Block should exist after dump"
    
    # Load阶段 (读取缓存)
    print("\n" + "=" * 70)
    print("步骤4: Load (读取数据)")
    print("=" * 70)
    handle = worker.load_data([block_id], [shard_idx], data2)
    worker.wait(handle)
    print(f"  读取完成!")
    
    # 数据一致性验证
    print("\n" + "=" * 70)
    print("步骤5: 数据验证")
    print("=" * 70)
    data_match = np.array_equal(raw_data1, raw_data2)
    print(f"  写入数据样本 (前16字节): {raw_data1[:16].tolist()}")
    print(f"  读取数据样本 (前16字节): {raw_data2[:16].tolist()}")
    print(f"  数据一致性: {data_match}")
    
    print("\n" + "=" * 70)
    print("存储路径生成规则总结:")
    print("=" * 70)
    print(f"""
  1. Block ID 生成:
     - 使用 secrets.token_bytes(16) 生成 16 字节随机数
     - {block_id.hex()}

  2. 文件名生成:
     - 将 block_id 转换为十六进制字符串
     - 文件名 = block_id.hex()
     - {file_name}

  3. 子目录名生成:
     - 取文件名的前 3 个字符作为子目录名
     - 子目录名 = file_name[:3]
     - {shard_dir}

  4. 完整路径:
     - 路径 = {{storage_backend}}/{{shard_dir}}/{{file_name}}
     - {expected_path}

  5. 写入临时文件:
     - 写入过程中使用 .tmp 后缀
     - 临时文件: {{path}}.tmp
     - 写入完成后重命名为正式文件
""")
    
    print("=" * 70)
    if data_match:
        print("✓ POSIX 存储后端单block_id验证测试通过!")
    else:
        print("✗ POSIX 存储后端单block_id验证测试失败!")
    print("=" * 70)
    
    return 0 if data_match else 1


if __name__ == "__main__":
    os.environ["UC_LOGGER_LEVEL"] = "info"
    exit(main())
