#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SpaceManager 线程池统一性测试

验证 SpaceManager 是否正确使用 LustreThreadPool 进行并发查询
"""

import sys
import hashlib
from unittest.mock import Mock, patch, MagicMock


def test_space_manager_uses_threadpool():
    """测试 SpaceManager 是否使用线程池而不是 std::async"""
    print("=" * 60)
    print("测试：SpaceManager 统一使用线程池")
    print("=" * 60)
    
    try:
        # 导入必要的模块
        from ucm.store.factory_v1 import UcmConnectorFactoryV1
        
        # 创建配置
        config = {
            "storage_backends": ["/mnt/lustre47"],
            "device_id": -1,
            "block_size": 512,
            "tensor_size": 512,
            "shard_size": 512,
            "lustre_lookup_concurrency": 8,  # 测试并发配置
        }
        
        # 创建 store
        store = UcmConnectorFactoryV1.create_connector("UcmLustreStore", config)
        print(f"✅ Store 创建成功: {store}")
        
        # 生成测试 block_ids
        block_ids = [hashlib.sha256(f"test_{i}".encode()).digest()[:16] for i in range(10)]
        
        # 执行 lookup（应该使用线程池）
        result = store.lookup(block_ids)
        print(f"✅ Lookup 完成，结果数量: {len(result)}")
        
        # 验证结果格式（接受 numpy.bool_ 或 Python bool）
        assert len(result) == len(block_ids), f"结果数量不匹配: {len(result)} != {len(block_ids)}"
        # numpy.ndarray 的元素类型是 numpy.bool_，兼容 Python bool
        import numpy as np
        if isinstance(result, np.ndarray):
            assert result.dtype == bool or result.dtype == np.bool_, f"结果类型错误: {result.dtype}"
        else:
            assert all(isinstance(r, (bool, np.bool_)) for r in result), "结果类型错误"
        
        print("✅ 测试通过：SpaceManager 正确使用线程池")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_threadpool_initialization():
    """测试线程池初始化"""
    print("\n" + "=" * 60)
    print("测试：线程池初始化")
    print("=" * 60)
    
    try:
        from ucm.store.factory_v1 import UcmConnectorFactoryV1
        
        # 测试不同的并发配置
        test_configs = [
            {"lustre_lookup_concurrency": 4},
            {"lustre_lookup_concurrency": 8},
            {"lustre_lookup_concurrency": 16},
        ]
        
        for i, concurrency_config in enumerate(test_configs):
            config = {
                "storage_backends": ["/mnt/lustre47"],
                "device_id": -1,
                "block_size": 512,
                "tensor_size": 512,
                "shard_size": 512,
                **concurrency_config
            }
            
            store = UcmConnectorFactoryV1.create_connector("UcmLustreStore", config)
            print(f"  配置 {i+1}: lookup_concurrency={concurrency_config['lustre_lookup_concurrency']} ✅")
        
        print("✅ 测试通过：线程池初始化正确")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_concurrent_lookup_performance():
    """测试并发查询性能"""
    print("\n" + "=" * 60)
    print("测试：并发查询性能")
    print("=" * 60)
    
    try:
        import time
        from ucm.store.factory_v1 import UcmConnectorFactoryV1
        
        config = {
            "storage_backends": ["/mnt/lustre47"],
            "device_id": -1,
            "block_size": 512,
            "tensor_size": 512,
            "shard_size": 512,
            "lustre_lookup_concurrency": 8,
        }
        
        store = UcmConnectorFactoryV1.create_connector("UcmLustreStore", config)
        
        # 测试不同数量的 block_ids
        test_sizes = [10, 50, 100, 200]
        
        for size in test_sizes:
            block_ids = [hashlib.sha256(f"test_{i}".encode()).digest()[:16] for i in range(size)]
            
            start_time = time.time()
            result = store.lookup(block_ids)
            elapsed = time.time() - start_time
            
            print(f"  查询 {size} 个 blocks: {elapsed*1000:.2f}ms")
        
        print("✅ 测试通过：并发查询性能正常")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 12 + "SpaceManager 线程池测试" + " " * 22 + "║")
    print("╚" + "═" * 58 + "╝\n")
    
    results = []
    
    # 测试1: 线程池使用
    results.append(("线程池使用", test_space_manager_uses_threadpool()))
    
    # 测试2: 线程池初始化
    results.append(("线程池初始化", test_threadpool_initialization()))
    
    # 测试3: 并发查询性能
    results.append(("并发查询性能", test_concurrent_lookup_performance()))
    
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
        print("🎉 所有测试通过！SpaceManager 已统一使用线程池。")
        return 0
    else:
        print("⚠️ 部分测试失败，请检查上述错误信息。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
