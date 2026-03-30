#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lustre Store 流程验证测试脚本

该脚本用于验证 Lustre Store 是否正确安装并能够正常工作。
当输入指定 token 后，运转到 lustre store 底层存储时仅打印一条语句向上返回。
"""

import sys
import torch
import numpy as np

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
        "storage_backends": ["/home/w2938/test/lustre_store"],  # 模拟的 Lustre 存储路径
        "device_id": -1,  # CPU only
        "block_size": 512,
        "tensor_size": 512,
        "shard_size": 512,
        "stripe_count": 0,
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
    # BlockId 必须是 16 字节，所以每个 block_id 需要填充到 16 字节
    block_ids = [b"test_block_001\x00", b"test_block_002\x00", b"test_block_003\x00"]
    shard_index = [0, 0, 0]
    
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
    # 创建模拟的 tensor 数据
    dummy_tensor = [[torch.randn(1, 1024) for _ in range(1)] for _ in range(len(block_ids))]
    dump_task = store.dump(block_ids, shard_index, dummy_tensor)
    print(f"dump 任务创建: task_id={dump_task.task_id}")
    print("✅ dump 流程完成 (打印语句并返回)")
    
    # 测试 load (模拟从存储读取 token 数据)
    print("\n--- 测试 load ---")
    dst_tensor = [[torch.randn(1, 1024) for _ in range(1)] for _ in range(len(block_ids))]
    load_task = store.load(block_ids, shard_index, dst_tensor)
    print(f"load 任务创建: task_id={load_task.task_id}")
    print("✅ load 流程完成 (打印语句并返回)")
    
    # 测试 wait 和 check
    print("\n--- 测试 wait/check ---")
    store.wait(load_task)
    print("✅ wait 流程完成")
    
    is_complete = store.check(load_task)
    print(f"check 结果: {is_complete}")
    print("✅ check 流程完成")
    
    # 测试 load_data 和 dump_data (低级接口)
    print("\n--- 测试 load_data/dump_data ---")
    dummy_addr = np.array([[0x1000, 0x2000], [0x3000, 0x4000], [0x5000, 0x6000]])
    
    load_data_task = store.load_data(block_ids, shard_index, dummy_addr)
    print(f"load_data 任务创建: task_id={load_data_task.task_id}")
    
    dump_data_task = store.dump_data(block_ids, shard_index, dummy_addr)
    print(f"dump_data 任务创建: task_id={dump_data_task.task_id}")
    print("✅ load_data/dump_data 流程完成")
    
    return True


def test_direct_import():
    """测试直接导入 Lustre Store 模块"""
    print("\n" + "=" * 60)
    print("步骤4: 测试直接导入模块")
    print("=" * 60)
    
    try:
        from ucm.store.lustre import UcmLustreStore
        print(f"✅ 直接导入成功: {UcmLustreStore}")
        
        # 直接创建实例
        config = {"storage_backends": ["/tmp/test"]}
        store = UcmLustreStore(config)
        print(f"✅ 直接创建实例成功: {store}")
        return True
    except Exception as e:
        print(f"❌ 直接导入失败: {e}")
        return False


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
    
    # 测试4: 直接导入
    results.append(("直接导入", test_direct_import()))
    
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
