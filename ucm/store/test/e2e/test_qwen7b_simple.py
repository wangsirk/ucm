#!/usr/bin/env python3
"""
Qwen-7B 模型 KV Cache 存储测试

模型参数:
- Layers: 32
- Hidden Size: 4096
- Attn Heads: 32
- KV Heads: 32
- Head Dim: 128 (4096 / 32)

测试参数:
- 输入文本: "你好啊！" (4 tokens)
- block_size: 4 tokens
- 因此: 1个完整的Block
"""

import os
import shutil
import secrets
import time
import struct


def calculate_kv_cache_size():
    """
    计算 KV Cache 大小

    Qwen-7B 参数:
    - num_layers = 32
    - num_kv_heads = 32
    - head_dim = hidden_size / attn_heads = 4096 / 32 = 128
    - block_size = 4 tokens

    单个token的KV Cache (fp16):
    - K cache: num_kv_heads × head_dim = 32 × 128 = 4096
    - V cache: num_kv_heads × head_dim = 32 × 128 = 4096
    - 总计: 8192 元素 × 2 bytes (fp16) = 16384 bytes = 16 KB

    单个Shard (1层) 的KV Cache (block_size个tokens):
    - 16 KB × 4 = 64 KB

    单个Block (所有层) 的KV Cache:
    - 64 KB × 32 layers = 2 MB
    """
    num_layers = 32
    num_kv_heads = 32
    head_dim = 128
    block_size = 4
    dtype_size = 2  # fp16

    # 单token的KV Cache大小
    single_token_kv = (num_kv_heads * head_dim * 2) * dtype_size  # K + V

    # 单个Shard的大小（1层，block_size个tokens）
    shard_size = single_token_kv * block_size

    # 单个Block的大小（所有层）
    block_size_bytes = shard_size * num_layers

    print(f"=== KV Cache 大小计算 ===")
    print(f"单token KV Cache: {single_token_kv / 1024:.2f} KB")
    print(f"单Shard KV Cache (1层, {block_size} tokens): {shard_size / 1024:.2f} KB")
    print(f"单Block KV Cache ({num_layers}层): {block_size_bytes / (1024 * 1024):.2f} MB")
    print()

    return shard_size, block_size_bytes


def generate_test_data(size_bytes):
    """
    生成测试数据: 顺序数据 [0, 1, 2, ..., 255, 0, 1, ...]

    Args:
        size_bytes: 数据大小（字节）

    Returns:
        bytes: 测试数据
    """
    data = bytearray(size_bytes)
    for i in range(size_bytes):
        data[i] = i % 256
    return bytes(data)


def generate_block_id():
    """
    生成随机BlockId (16字节)

    Returns:
        bytes: 16字节的随机BlockId
    """
    return secrets.token_bytes(16)


def construct_file_path(storage_path, block_id):
    """
    根据BlockId构造文件路径

    路径格式: {storage_path}/{block_id[:2]}/{block_id[:4]}

    Args:
        storage_path: 存储根路径
        block_id: 16字节的BlockId

    Returns:
        str: 文件路径
    """
    file_name = block_id[:4].hex()
    parent_dir = block_id[:2].hex()
    return os.path.join(storage_path, parent_dir, file_name)


def lookup(storage_path, block_id):
    """
    检查Block是否存在（模拟UCM的Lookup操作）

    Args:
        storage_path: 存储根路径
        block_id: BlockId

    Returns:
        bool: True=存在(HIT), False=不存在(MISS)
    """
    file_path = construct_file_path(storage_path, block_id)
    return os.path.exists(file_path)


def dump(storage_path, block_id, data):
    """
    将数据写入存储（模拟UCM的Dump操作）

    Args:
        storage_path: 存储根路径
        block_id: BlockId
        data: 要写入的数据
    """
    file_path = construct_file_path(storage_path, block_id)
    parent_dir = os.path.dirname(file_path)

    # 创建父目录
    os.makedirs(parent_dir, exist_ok=True)

    # 写入数据
    with open(file_path, 'wb') as f:
        f.write(data)

    print(f"  [Dump] 写入文件: {file_path}")
    print(f"  [Dump] 数据大小: {len(data) / (1024 * 1024):.2f} MB")


def load(storage_path, block_id):
    """
    从存储读取数据（模拟UCM的Load操作）

    Args:
        storage_path: 存储根路径
        block_id: BlockId

    Returns:
        bytes: 读取的数据，如果文件不存在返回None
    """
    file_path = construct_file_path(storage_path, block_id)

    if not os.path.exists(file_path):
        return None

    with open(file_path, 'rb') as f:
        data = f.read()

    print(f"  [Load] 读取文件: {file_path}")
    print(f"  [Load] 数据大小: {len(data) / (1024 * 1024):.2f} MB")

    return data


def verify_data(original_data, loaded_data):
    """
    验证数据一致性

    Args:
        original_data: 原始数据
        loaded_data: 加载的数据

    Returns:
        bool: True=数据一致, False=数据不一致
    """
    if len(original_data) != len(loaded_data):
        print(f"  [验证] 失败: 长度不匹配 ({len(original_data)} vs {len(loaded_data)})")
        return False

    # 逐字节比较
    for i in range(len(original_data)):
        if original_data[i] != loaded_data[i]:
            print(f"  [验证] 失败: 字节{i}不匹配 ({original_data[i]} vs {loaded_data[i]})")
            return False

    print(f"  [验证] 成功: 数据完全一致 ({len(original_data)} bytes)")
    return True


def main():
    """主测试流程"""
    print("=" * 70)
    print("Qwen-7B KV Cache 存储测试")
    print("=" * 70)
    print()

    # 配置参数
    storage_path = "/mnt/lustre/data_verify"
    text = "你好啊！你是谁？"
    block_size_tokens = 4

    print(f"=== 测试配置 ===")
    print(f"输入文本: '{text}'")
    print(f"Token数量: {len(text)} (假设每个中文字符1个token)")
    print(f"Block Size: {block_size_tokens} tokens")
    print(f"存储路径: {storage_path}")
    print(f"存储类型: Lustre 文件系统")
    print()

    # 计算KV Cache大小
    shard_size, block_size_bytes = calculate_kv_cache_size()

    # 清理并创建存储目录
    if os.path.exists(storage_path):
        shutil.rmtree(storage_path)
    os.makedirs(storage_path)

    # 生成测试BlockId
    block_id = generate_block_id()
    print(f"=== 生成 BlockId ===")
    print(f"BlockId: {block_id.hex()}")
    print()

    # 生成测试数据
    test_data = generate_test_data(block_size_bytes)
    print(f"=== 生成测试数据 ===")
    print(f"数据大小: {len(test_data) / (1024 * 1024):.2f} MB")
    print(f"数据模式: 顺序数据 [0, 1, 2, ..., 255, 0, 1, ...]")
    print()

    # ========== Step 1: Lookup (预期 MISS) ==========
    print("=" * 70)
    print("Step 1: Lookup (预期: MISS)")
    print("=" * 70)
    hit = lookup(storage_path, block_id)
    print(f"  [Lookup] BlockId: {block_id.hex()}")
    print(f"  [Lookup] 结果: {'HIT ✓' if hit else 'MISS ✗'}")

    if hit:
        print("  [错误] 第一次查询应该是MISS!")
        return False
    print()

    # ========== Step 2: Dump ==========
    print("=" * 70)
    print("Step 2: Dump (写入KV Cache)")
    print("=" * 70)
    start_time = time.time()
    dump(storage_path, block_id, test_data)
    dump_time = time.time() - start_time
    print(f"  [Dump] 耗时: {dump_time * 1000:.2f} ms")
    print(f"  [Dump] 带宽: {len(test_data) / (1024 * 1024) / dump_time:.2f} MB/s")
    print()

    # ========== Step 3: Lookup (预期 HIT) ==========
    print("=" * 70)
    print("Step 3: Lookup (预期: HIT)")
    print("=" * 70)
    hit = lookup(storage_path, block_id)
    print(f"  [Lookup] BlockId: {block_id.hex()}")
    print(f"  [Lookup] 结果: {'HIT ✓' if hit else 'MISS ✗'}")

    if not hit:
        print("  [错误] Dump后查询应该是HIT!")
        return False
    print()

    # ========== Step 4: Load ==========
    print("=" * 70)
    print("Step 4: Load (读取KV Cache)")
    print("=" * 70)
    start_time = time.time()
    loaded_data = load(storage_path, block_id)
    load_time = time.time() - start_time
    print(f"  [Load] 耗时: {load_time * 1000:.2f} ms")

    if loaded_data is None:
        print("  [错误] 加载失败!")
        return False

    print(f"  [Load] 带宽: {len(loaded_data) / (1024 * 1024) / load_time:.2f} MB/s")
    print()

    # ========== Step 5: 数据验证 ==========
    print("=" * 70)
    print("Step 5: 数据一致性验证")
    print("=" * 70)
    success = verify_data(test_data, loaded_data)
    print()

    # ========== 总结 ==========
    print("=" * 70)
    print("测试结果汇总")
    print("=" * 70)
    print(f"✓ Lookup (MISS): 正确")
    print(f"✓ Dump: 成功 ({dump_time * 1000:.2f} ms, {len(test_data) / (1024 * 1024) / dump_time:.2f} MB/s)")
    print(f"✓ Lookup (HIT): 正确")
    print(f"✓ Load: 成功 ({load_time * 1000:.2f} ms, {len(loaded_data) / (1024 * 1024) / load_time:.2f} MB/s)")
    print(f"{'✓' if success else '✗'} 数据验证: {'通过' if success else '失败'}")
    print(f"存储路径: {storage_path}")
    print("=" * 70)

    if success:
        print("\n🎉 测试全部通过!")

        # 显示文件结构
        print(f"\n=== 文件结构 ===")
        for root, dirs, files in os.walk(storage_path):
            level = root.replace(storage_path, '').count(os.sep)
            indent = ' ' * 2 * level
            print(f'{indent}{os.path.basename(root)}/')
            subindent = ' ' * 2 * (level + 1)
            for file in files:
                size = os.path.getsize(os.path.join(root, file))
                print(f'{subindent}{file} ({size / (1024 * 1024):.2f} MB)')
    else:
        print("\n❌ 测试失败!")

    return success


if __name__ == "__main__":
    main()
