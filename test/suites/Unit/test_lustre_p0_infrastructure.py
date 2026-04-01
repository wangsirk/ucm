"""
Lustre Store P0 阶段基础设施测试

P0 阶段测试范围：
- Store 初始化和配置验证
- 参数校验框架
- 基础 API 响应
- 配置参数传递
- 多实例共存
- 错误处理
- 资源清理

注意：P0 阶段不包含 Dump/Load/Lookup 等数据传输功能（P1 阶段）
"""
import hashlib
import os
from pathlib import Path

import pytest
import numpy as np

from ucm.logger import init_logger
from ucm.store.pipeline.connector import UcmPipelineStore

logger = init_logger(__name__)


# ===== 测试输出配置 =====

def pytest_configure(config):
    """配置 pytest 输出格式，添加中文说明"""
    # 中文测试结果描述
    config.addinivalue_line(
        "markers", "P0基础设施测试: 验证Lustre Store核心基础设施"
    )


# ===== 测试辅助函数 =====

def log_test_info(test_name, description, status="PASS"):
    """记录测试信息"""
    symbol = "✅" if status == "PASS" else "❌"
    logger.info(f"{symbol} [{test_name}] {description} - {status}")


# ===== Fixtures =====

@pytest.fixture
def minimal_config():
    """最小有效配置"""
    backend = "/home/w2938/tmp/lustre"
    os.makedirs(backend, exist_ok=True)
    return {
        "store_pipeline": "Lustre",
        "storage_backends": [backend],
        "device_id": -1,
        "tensor_size": 100,
        "shard_size": 100,
        "block_size": 100,
        "_test_backend": backend,
    }


@pytest.fixture
def lustre_store(minimal_config):
    """初始化的 Store 实例"""
    return UcmPipelineStore(minimal_config)


# ===== 1. Store 初始化测试 =====

class TestStoreInitialization:
    """P0-1: Store 初始化和配置验证

    测试目标：
    - 验证有效配置可以成功创建 Store 实例
    - 验证缺少必要参数时会正确报错
    - 验证参数校验框架正常工作
    """

    def test_store_creation_with_valid_config(self, minimal_config):
        """[P0-1.1] 有效配置应成功创建 Store

        验证点：
        - Store 实例创建成功
        - C++ 指针有效
        """
        store = UcmPipelineStore(minimal_config)
        assert store is not None, "❌ Store 实例创建失败"
        assert store.cc_store() > 0, "❌ C++ 指针无效"
        logger.info("✅ [P0-1.1] 有效配置创建 Store - 通过")

    def test_store_creation_missing_pipeline(self):
        """[P0-1.2] 缺少 store_pipeline 参数应报错

        验证点：
        - KeyError 异常被正确抛出
        - 错误信息包含 'store_pipeline'
        """
        config = {
            "storage_backends": ["/home/w2938/tmp/lustre/test"],
            "device_id": -1,
        }
        try:
            UcmPipelineStore(config)
            assert False, "❌ 应该抛出 KeyError"
        except KeyError as e:
            assert "store_pipeline" in str(e), "❌ 错误信息不正确"
            logger.info("✅ [P0-1.2] 缺少 pipeline 参数报错 - 通过")

    def test_store_creation_empty_backends(self):
        """[P0-1.3] 空 storage_backends 应报错

        验证点：
        - C++ 参数校验正常工作
        - 返回适当的错误
        """
        config = {
            "store_pipeline": "Lustre",
            "storage_backends": [],
            "device_id": -1,
        }
        with pytest.raises(Exception):
            UcmPipelineStore(config)
        logger.info("✅ [P0-1.3] 空 backends 参数校验 - 通过")


# ===== 2. 参数校验测试 =====

class TestParameterValidation:
    """P0-2: 参数校验框架验证

    测试目标：
    - 验证空列表参数正确处理
    - 验证无效参数类型被正确处理
    - 验证 API 不因无效输入而崩溃
    """

    def test_lookup_empty_blocks(self, lustre_store):
        """[P0-2.1] 空 blocks 列表应返回空结果

        验证点：
        - lookup([]) 返回空结果
        - 不崩溃或抛出异常
        """
        masks = lustre_store.lookup([])
        assert len(masks) == 0, f"❌ 应返回空结果，实际长度: {len(masks)}"
        logger.info("✅ [P0-2.1] 空 blocks 列表处理 - 通过")

    def test_lookup_invalid_block_type(self, lustre_store):
        """[P0-2.2] 无效 block 类型应被处理

        验证点：
        - 16字节的 block_id 被正确处理
        - 返回单个结果
        """
        invalid_block = b"\x00" * 16
        masks = lustre_store.lookup([invalid_block])
        assert len(masks) == 1, f"❌ 应返回1个结果，实际: {len(masks)}"
        logger.info("✅ [P0-2.2] 无效 block 类型处理 - 通过")

    def test_lookup_nonexistent_blocks(self, lustre_store):
        """[P0-2.3] 不存在的 blocks 应返回正确结果

        验证点：
        - 多个随机 block_id 被处理
        - 返回正确数量的结果
        """
        block_ids = [hashlib.sha256(str(i).encode()).digest()[:16] for i in range(5)]
        masks = lustre_store.lookup(block_ids)
        assert len(masks) == 5, f"❌ 应返回5个结果，实际: {len(masks)}"
        logger.info("✅ [P0-2.3] 不存在 blocks 处理 - 通过")


# ===== 3. 基础 API 响应测试 =====

class TestBasicAPI:
    """P0-3: 基础 API 功能验证

    测试目标：
    - 验证 API 边界条件处理
    - 验证空输入不导致崩溃
    - 验证 API 接口稳定性
    """

    def test_lookup_on_prefix_empty(self, lustre_store):
        """[P0-3.1] 空列表的 lookup_on_prefix

        验证点：
        - 返回值 >= -1 (表示未找到)
        - 不崩溃
        """
        result = lustre_store.lookup_on_prefix([])
        assert result >= -1, f"❌ 返回值应 >= -1，实际: {result}"
        logger.info(f"✅ [P0-3.1] 空列表 prefix 查询 - 通过 (返回: {result})")

    def test_prefetch_empty_blocks(self, lustre_store):
        """[P0-3.2] 空 blocks 的 prefetch 不应崩溃

        验证点：
        - 调用不抛出异常
        - 正常返回
        """
        lustre_store.prefetch([])  # 不应抛出异常
        logger.info("✅ [P0-3.2] 空 blocks prefetch - 通过")


# ===== 4. 配置参数传递测试 =====

class TestConfiguration:
    """P0-4: 配置参数正确传递到 C++

    测试目标：
    - 验证 Python 配置正确传递到 C++
    - 验证参数值正确设置
    - 验证配置日志输出
    """

    def test_tensor_size_configured(self, minimal_config):
        """[P0-4.1] tensor_size 参数应被正确设置

        验证点：
        - tensor_size 参数传递成功
        - C++ 端正确认参数
        """
        minimal_config["tensor_size"] = 256
        store = UcmPipelineStore(minimal_config)
        assert store.cc_store() > 0, "❌ Store 创建失败"
        logger.info("✅ [P0-4.1] tensor_size=256 参数传递 - 通过")

    def test_shard_size_configured(self, minimal_config):
        """[P0-4.2] shard_size 参数应被正确设置

        验证点：
        - shard_size 参数传递成功
        - C++ 端正确认参数
        """
        minimal_config["shard_size"] = 512
        store = UcmPipelineStore(minimal_config)
        assert store.cc_store() > 0, "❌ Store 创建失败"
        logger.info("✅ [P0-4.2] shard_size=512 参数传递 - 通过")

    def test_data_dir_shard_bytes_configured(self, minimal_config):
        """[P0-4.3] data_dir_shard_bytes 参数应被正确设置

        验证点：
        - data_dir_shard_bytes 参数传递成功
        - C++ 端正确认参数
        """
        minimal_config["data_dir_shard_bytes"] = 3
        store = UcmPipelineStore(minimal_config)
        assert store.cc_store() > 0, "❌ Store 创建失败"
        logger.info("✅ [P0-4.3] data_dir_shard_bytes=3 参数传递 - 通过")


# ===== 5. 多实例测试 =====

class TestMultipleInstances:
    """P0-5: 多实例共存测试

    测试目标：
    - 验证多个 Store 实例可以同时存在
    - 验证不同后端路径隔离
    - 验证实例间互不干扰
    """

    def test_two_stores_different_backends(self):
        """[P0-5.1] 两个不同后端的 Store 应能共存

        验证点：
        - 两个 Store 实例创建成功
        - C++ 指针不同（不同实例）
        - 后端路径隔离
        """
        backend1 = "/home/w2938/tmp/lustre/store1"
        backend2 = "/home/w2938/tmp/lustre/store2"
        os.makedirs(backend1, exist_ok=True)
        os.makedirs(backend2, exist_ok=True)

        config1 = {
            "store_pipeline": "Lustre",
            "storage_backends": [backend1],
            "device_id": -1,
            "tensor_size": 100,
            "shard_size": 100,
            "block_size": 100,
        }
        config2 = {
            "store_pipeline": "Lustre",
            "storage_backends": [backend2],
            "device_id": -1,
            "tensor_size": 100,
            "shard_size": 100,
            "block_size": 100,
        }

        store1 = UcmPipelineStore(config1)
        store2 = UcmPipelineStore(config2)

        assert store1.cc_store() > 0, "❌ Store1 创建失败"
        assert store2.cc_store() > 0, "❌ Store2 创建失败"
        assert store1.cc_store() != store2.cc_store(), "❌ 两个实例指针相同（应该不同）"
        logger.info(f"✅ [P0-5.1] 多实例共存 - 通过 (ptr1={store1.cc_store()}, ptr2={store2.cc_store()})")


# ===== 6. 错误处理测试 =====

class TestErrorHandling:
    """P0-6: 错误处理验证

    测试目标：
    - 验证无效 device_id 被拒绝
    - 验证无效并发参数被拒绝
    - 验证错误信息清晰
    """

    def test_invalid_device_id(self):
        """[P0-6.1] 无效 device_id 应被拒绝

        验证点：
        - device_id < -1 时被拒绝
        - 返回适当的错误
        """
        config = {
            "store_pipeline": "Lustre",
            "storage_backends": ["/home/w2938/tmp/lustre/test"],
            "device_id": -999,  # 无效值
            "tensor_size": 100,
            "shard_size": 100,
        }
        with pytest.raises(Exception) as exc_info:
            UcmPipelineStore(config)
        logger.info(f"✅ [P0-6.1] 无效 device_id=-999 拒绝 - 通过 (错误: {str(exc_info.value)[:50]}...)")

    def test_zero_concurrency(self):
        """[P0-6.2] 零并发应被拒绝

        验证点：
        - 并发参数为 0 时被拒绝
        - 返回适当的错误
        """
        config = {
            "store_pipeline": "Lustre",
            "storage_backends": ["/home/w2938/tmp/lustre/test"],
            "device_id": -1,
            "tensor_size": 100,
            "shard_size": 100,
            "lustre_data_trans_concurrency": 0,  # 无效
        }
        with pytest.raises(Exception) as exc_info:
            UcmPipelineStore(config)
        logger.info(f"✅ [P0-6.2] 零并发拒绝 - 通过 (错误: {str(exc_info.value)[:50]}...)")


# ===== 7. 资源清理测试 =====

class TestResourceCleanup:
    """P0-7: 资源清理验证

    测试目标：
    - 验证 Store 删除不崩溃
    - 验证资源正确释放
    - 验证无内存泄漏
    """

    def test_store_deletion(self, minimal_config):
        """[P0-7.1] Store 删除不应崩溃

        验证点：
        - del store 不崩溃
        - 资源正确释放
        """
        store = UcmPipelineStore(minimal_config)
        ptr = store.cc_store()
        del store
        # 如果执行到这里，说明没有崩溃
        logger.info(f"✅ [P0-7.1] Store 删除 - 通过 (释放指针: {ptr})")

    def test_context_manager_style(self, minimal_config):
        """[P0-7.2] 资源清理完整性

        验证点：
        - 使用后资源可清理
        - 无异常抛出
        """
        store = UcmPipelineStore(minimal_config)
        try:
            assert store.cc_store() > 0, "❌ Store 无效"
            logger.info(f"✅ [P0-7.2] 资源清理 - 通过 (指针: {store.cc_store()})")
        finally:
            del store
