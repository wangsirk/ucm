#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lustre Store 流程验证测试脚本

该脚本用于验证 Lustre Store 是否正确安装并能够正常工作。
当输入指定 token 后，运转到 lustre store 底层存储时仅打印一条语句向上返回。
"""

import sys
import hashlib
import torch
import numpy as np


def generate_block_id(seed: int = 0) -> bytes:
    """生成测试用 BlockId (16字节)"""
    data = f"test_block_{seed}".encode()
    return hashlib.sha256(data).digest()[:16]

def test_lustre_store_registration():
    """测试 Lustre Store 是否已在工厂中注册"""
    print("=" * 60)
    print("步骤1: 检查 Lustre Store 是否已注册")
    print("=" * 60)
    
    from ucm.store.factory_v1 import UcmConnectorFactoryV1
    
    registered_stores = list(UcmConnectorFactoryV1._registry.keys())
    print(f"已注册的 Store 列表: {registered_stores}")
    
    if "UcmLustreStore" in registered_stores:
        print("✅ UcmLustreStore 已成功注册!")
        return True
    else:
        print("❌ UcmLustreStore 未注册!")
        return False


def test_lustre_store_creation():
    """测试 Lustre Store 实例是否能正常创建"""
    print("\n" + "=" * 60)
    print("步骤2: 测试 Lustre Store 实例创建")
    print("=" * 60)
    
    from ucm.store.factory_v1 import UcmConnectorFactoryV1
    
    config = {
        "storage_backends": ["/mnt/lustre47/demo"],  # Lustre 客户端存储路径
        "device_id": -1,  # CPU only
        "block_size": 512,
        "tensor_size": 512,
        "shard_size": 512,
        "stripe_count": 0,  # 不启用条带化
        "stripe_size": 0,
    }
    
    try:
        store = UcmConnectorFactoryV1.create_connector("UcmLustreStore", config)
        print(f"✅ Store 创建成功: {store}")
        return store
    except Exception as e:
        print(f"❌ Store 创建失败: {e}")
        return None


def test_lustre_store_flow(store):
    """测试 Lustre Store 的完整流程：lookup -> load -> dump"""
    print("\n" + "=" * 60)
    print("步骤3: 测试 Lustre Store 流程 (lookup/load/dump)")
    print("=" * 60)
    
    # 模拟 block_ids (token 对应的 block hash)
    # 使用与单元测试相同的方式生成 16 字节 BlockId
    block_ids = [generate_block_id(i) for i in range(3)]
    shard_index = [0, 1, 2]  # 每个 block 不同的 shard 索引
    
    # 测试 lookup
    print("\n--- 测试 lookup ---")
    print(f"输入 block_ids: {block_ids}")
    result = store.lookup(block_ids)
    print(f"lookup 结果: {result}")
    print("✅ lookup 流程完成 (打印语句并返回)")
    
    # 测试 lookup_on_prefix
    print("\n--- 测试 lookup_on_prefix ---")
    prefix_result = store.lookup_on_prefix(block_ids)
    print(f"lookup_on_prefix 结果: {prefix_result}")
    print("✅ lookup_on_prefix 流程完成")
    
    # 测试 prefetch
    print("\n--- 测试 prefetch ---")
    store.prefetch(block_ids)
    print("✅ prefetch 流程完成")
    
    # 测试 dump (模拟将 token 数据写入存储)
    print("\n--- 测试 dump ---")
    # 创建模拟的 tensor 数据 (1D uint8 tensor)
    import numpy as np
    dummy_tensor = [[torch.from_numpy(np.frombuffer(bytes([0xAA] * 512), dtype=np.uint8).copy())] for _ in range(len(block_ids))]

    # 打印写入前的数据
    print("\n📝 写入前的数据:")
    for i, (bid, tensor) in enumerate(zip(block_ids, dummy_tensor)):
        data_bytes = tensor[0].numpy().tobytes()[:32]  # 只打印前32字节
        print(f"  Block[{i}] BlockId: {bid.hex()[:16]}...")
        print(f"    数据前32字节: {data_bytes.hex()}")

    dump_task = store.dump(block_ids, shard_index, dummy_tensor)
    print(f"dump 任务创建: task_id={dump_task.task_id}")
    print("✅ dump 流程完成 (打印语句并返回)")
    
    # 测试 load (模拟从存储读取 token 数据)
    print("\n--- 测试 load ---")
    # 初始化目标 tensor 为全0
    dst_tensor = [[torch.from_numpy(np.frombuffer(bytes([0x00] * 512), dtype=np.uint8).copy())] for _ in range(len(block_ids))]

    # 打印读取前的数据 (应该是全0)
    print("\n📖 读取前的数据 (预期全0):")
    for i, (bid, tensor) in enumerate(zip(block_ids, dst_tensor)):
        data_bytes = tensor[0].numpy().tobytes()[:32]  # 只打印前32字节
        print(f"  Block[{i}] BlockId: {bid.hex()[:16]}...")
        print(f"    数据前32字节: {data_bytes.hex()}")

    load_task = store.load(block_ids, shard_index, dst_tensor)
    print(f"load 任务创建: task_id={load_task.task_id}")

    # 测试 wait - 等待 load 完成
    print("\n--- 测试 wait ---")
    store.wait(load_task)
    print("✅ wait 流程完成")

    # 打印读取后的数据
    print("\n📖 读取后的数据:")
    for i, (bid, tensor) in enumerate(zip(block_ids, dst_tensor)):
        data_bytes = tensor[0].numpy().tobytes()[:32]  # 只打印前32字节
        print(f"  Block[{i}] BlockId: {bid.hex()[:16]}...")
        print(f"    数据前32字节: {data_bytes.hex()}")

    return True


def main():
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 10 + "Lustre Store 流程验证测试" + " " * 22 + "║")
    print("╚" + "═" * 58 + "╝")
    
    results = []
    
    # 测试1: 检查注册
    results.append(("注册检查", test_lustre_store_registration()))
    
    # 测试2: 创建实例
    store = test_lustre_store_creation()
    results.append(("实例创建", store is not None))
    
    # 测试3: 流程测试
    if store:
        results.append(("流程测试", test_lustre_store_flow(store)))

    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False
    
    print("=" * 60)
    if all_passed:
        print("🎉 所有测试通过! Lustre Store 已正确安装并可正常使用。")
        return 0
    else:
        print("⚠️ 部分测试失败，请检查上述错误信息。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
