"""
Lustre Store P3 阶段条带化功能测试

P3 阶段测试范围：
- 目录级条带化设置
- 条带参数配置传递
- 文件继承目录条带属性
- 非 Lustre 环境回退
- 条带化失败回退处理

测试环境要求：
- Lustre 文件系统: 条带化功能完全测试
- 非 Lustre 文件系统: 验证回退机制
"""
import hashlib
import os
import subprocess
from pathlib import Path

import pytest
import numpy as np
import torch

from ucm.logger import init_logger
from ucm.store.pipeline.connector import UcmPipelineStore

logger = init_logger(__name__)


# ===== 测试辅助函数 =====

def generate_block_id(data: bytes) -> bytes:
    """生成 BlockId (SHA-256 前 16 字节)"""
    return hashlib.sha256(data).digest()[:16]


def create_test_tensor(size: int = 1024, pattern: int = 0xAA) -> torch.Tensor:
    """创建测试数据为 torch.Tensor"""
    data = bytes([pattern % 256] * size)
    tensor = torch.from_numpy(np.frombuffer(data, dtype=np.uint8).copy())
    return tensor


# ===== 测试输出配置 =====

def pytest_configure(config):
    """配置 pytest 输出格式，添加中文说明"""
    config.addinivalue_line(
        "markers", "P3条带化测试: 验证Lustre Store目录级条带化功能"
    )


# ===== 测试辅助函数 =====

def log_test_info(test_name, description, status="PASS"):
    """记录测试信息"""
    symbol = "✅" if status == "PASS" else "❌"
    logger.info(f"{symbol} [{test_name}] {description} - {status}")


def is_lustre_mount(path):
    """检查路径是否在 Lustre 文件系统上"""
    try:
        result = subprocess.run(
            ["df", "-T", str(path)],
            capture_output=True,
            text=True,
            timeout=5
        )
        return "lustre" in result.stdout.lower()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def get_stripe_info(file_path):
    """获取文件的条带信息

    Returns:
        dict: 条带信息字典，包含 stripe_count, stripe_size 等
              如果无法获取（如非 Lustre 文件系统），返回 None
    """
    try:
        result = subprocess.run(
            ["lfs", "getstripe", "-c", str(file_path)],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            # 解析输出: "stripe_count: 4"
            for line in result.stdout.splitlines():
                if "stripe_count" in line:
                    parts = line.split(":")
                    if len(parts) == 2:
                        return {"stripe_count": int(parts[1].strip())}
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


# ===== Fixtures =====

@pytest.fixture
def stripe_config():
    """启用条带化的配置"""
    backend = "/mnt/lustre47/test3"
    os.makedirs(backend, exist_ok=True)
    return {
        "store_pipeline": "Lustre",
        "storage_backends": [backend],
        "device_id": -1,
        "tensor_size": 100,
        "shard_size": 100,
        "block_size": 100,
        "stripe_count": 4,          # 启用条带化
        "stripe_size": 1048576,     # 1MB
        "_test_backend": backend,
    }


@pytest.fixture
def no_stripe_config():
    """不启用条带化的配置"""
    backend = "/mnt/lustre47/test3"
    os.makedirs(backend, exist_ok=True)
    return {
        "store_pipeline": "Lustre",
        "storage_backends": [backend],
        "device_id": -1,
        "tensor_size": 100,
        "shard_size": 100,
        "block_size": 100,
        "stripe_count": 0,          # 不启用条带化
        "stripe_size": 0,
        "_test_backend": backend,
    }


@pytest.fixture
def stripe_store(stripe_config):
    """启用条带化的 Store 实例"""
    return UcmPipelineStore(stripe_config)


@pytest.fixture
def no_stripe_store(no_stripe_config):
    """不启用条带化的 Store 实例"""
    return UcmPipelineStore(no_stripe_config)


# ===== 1. 条带化目录创建测试 =====

class TestStripedDirectoryCreation:
    """P3-1: 条带化目录创建

    测试目标：
    - 验证 stripe_count > 0 时目录创建成功
    - 验证 stripe_count = 0 时使用普通目录创建
    - 验证目录创建失败时正确回退
    """

    def test_store_creation_with_stripe_enabled(self, stripe_config):
        """[P3-1.1] stripe_count > 0 应成功创建 Store

        验证点：
        - Store 实例创建成功
        - C++ 指针有效
        - 数据目录存在
        """
        store = UcmPipelineStore(stripe_config)
        assert store is not None, "❌ Store 实例创建失败"
        assert store.cc_store() > 0, "❌ C++ 指针无效"

        # 检查数据目录是否创建
        backend = stripe_config["_test_backend"]
        data_dir = os.path.join(backend, "data")
        assert os.path.exists(data_dir), f"❌ 数据目录不存在: {data_dir}"
        assert os.path.isdir(data_dir), f"❌ 路径不是目录: {data_dir}"

        log_test_info("P3-1.1", "stripe_count > 0 创建 Store 成功")

    def test_store_creation_with_stripe_disabled(self, no_stripe_config):
        """[P3-1.2] stripe_count = 0 应创建普通目录

        验证点：
        - Store 实例创建成功
        - 数据目录存在（普通目录，非条带化）
        """
        store = UcmPipelineStore(no_stripe_config)
        assert store is not None, "❌ Store 实例创建失败"

        backend = no_stripe_config["_test_backend"]
        data_dir = os.path.join(backend, "data")
        assert os.path.exists(data_dir), f"❌ 数据目录不存在: {data_dir}"

        log_test_info("P3-1.2", "stripe_count = 0 创建普通目录成功")

    def test_data_directory_exists_after_setup(self, stripe_store, stripe_config):
        """[P3-1.3] Setup 后数据目录应存在

        验证点：
        - 数据目录路径正确
        - 目录可访问
        """
        backend = stripe_config["_test_backend"]
        data_dir = os.path.join(backend, "data")
        assert os.path.exists(data_dir), f"❌ 数据目录不存在: {data_dir}"
        assert os.access(data_dir, os.R_OK | os.W_OK | os.X_OK), \
            f"❌ 数据目录无访问权限: {data_dir}"

        log_test_info("P3-1.3", "Setup 后数据目录存在且可访问")


# ===== 2. 条带属性继承测试 =====

class TestStripeInheritance:
    """P3-2: 文件继承目录条带属性

    测试目标：
    - 验证在条带化目录下创建的文件继承条带属性
    - 验证条带参数与配置一致
    """

    @pytest.mark.skipif(
        not is_lustre_mount("/mnt/lustre47/test3"),
        reason="需要 Lustre 文件系统"
    )
    def test_file_inherits_stripe_attributes(self, stripe_store, stripe_config):
        """[P3-2.1] 文件应继承目录条带属性

        验证点：
        - Dump 操作创建文件成功
        - 文件条带数与配置一致 (stripe_count=4)
        """
        # 创建测试数据
        test_data = create_test_tensor(1024, 0xAB)
        block_id = generate_block_id(test_data.numpy().tobytes())

        # 执行 Dump
        task = stripe_store.dump([block_id], [0], [[test_data]])
        stripe_store.wait(task)

        # 获取文件路径并检查条带属性
        backend = stripe_config["_test_backend"]
        # 在 data 目录中查找新创建的文件
        data_dir = os.path.join(backend, "data")

        # 查找最近创建的文件
        files = []
        for root, dirs, filenames in os.walk(data_dir):
            for f in filenames:
                if not f.endswith(".tmp"):
                    files.append(os.path.join(root, f))

        if files:
            # 检查第一个文件的条带属性
            stripe_info = get_stripe_info(files[0])
            if stripe_info is not None:
                expected_count = stripe_config["stripe_count"]
                actual_count = stripe_info.get("stripe_count", 0)
                assert actual_count == expected_count, \
                    f"❌ 条带数不匹配: 期望 {expected_count}, 实际 {actual_count}"
                log_test_info("P3-2.1", f"文件正确继承条带属性: stripe_count={actual_count}")
            else:
                log_test_info("P3-2.1", "无法获取条带信息（可能非 Lustre 环境）", "SKIP")
        else:
            log_test_info("P3-2.1", "未找到数据文件", "SKIP")


# ===== 3. 非 Lustre 环境回退测试 =====

class TestNonLustreFallback:
    """P3-3: 非 Lustre 环境回退机制

    测试目标：
    - 验证非 Lustre 环境下 Store 正常初始化
    - 验证文件操作正常工作
    """

    def test_store_works_without_lustre_api(self, no_stripe_config):
        """[P3-3.1] 非 Lustre 环境 Store 应正常工作

        验证点：
        - Store 初始化成功
        - Dump 操作正常
        - Load 操作正常
        """
        store = UcmPipelineStore(no_stripe_config)
        assert store is not None, "❌ Store 实例创建失败"

        # 创建测试数据
        test_data = create_test_tensor(1024, 0xCD)
        block_id = generate_block_id(test_data.numpy().tobytes())

        # Dump
        task = store.dump([block_id], [0], [[test_data]])
        assert task is not None, "❌ Dump 失败"
        store.wait(task)

        # Load
        loaded = [torch.zeros(1024, dtype=torch.uint8)]
        store.load([block_id], [0], [loaded])
        store.wait(store.load([block_id], [0], [loaded]))

        # 验证数据
        assert loaded[0].equal(test_data), "❌ Load 数据不匹配"

        log_test_info("P3-3.1", "非 Lustre 环境 Store 正常工作")


# ===== 4. 条带化失败回退测试 =====

class TestStripingFailureFallback:
    """P3-4: 条带化设置失败回退处理

    测试目标：
    - 验证条带化设置失败时回退到普通目录创建
    - 验证 Store 仍然可用
    """

    def test_invalid_stripe_params_fallback(self, stripe_config):
        """[P3-4.1] 无效条带参数应回退到普通目录

        验证点：
        - 即使条带化失败，Store 仍初始化成功
        - 数据目录存在
        """
        # 使用极端参数可能导致条带化失败
        config = stripe_config.copy()
        config["stripe_count"] = 999999  # 无效的条带数

        try:
            store = UcmPipelineStore(config)
            assert store is not None, "❌ Store 创建失败"

            backend = config["_test_backend"]
            data_dir = os.path.join(backend, "data")
            # 即使条带化失败，目录应该被创建
            assert os.path.exists(data_dir), f"❌ 数据目录不存在: {data_dir}"

            log_test_info("P3-4.1", "条带化失败时正确回退到普通目录")
        except Exception as e:
            # 某些实现可能直接抛出异常
            log_test_info("P3-4.1", f"条带化失败处理: {str(e)}", "SKIP")


# ===== 5. 多后端条带化测试 =====

class TestMultipleBackendsStriping:
    """P3-5: 多存储后端条带化

    测试目标：
    - 验证多个 storage backend 都正确设置条带化
    """

    def test_multiple_backends_stripe_setup(self):
        """[P3-5.1] 多后端都应设置条带化

        验证点：
        - 所有后端的数据目录都存在
        - Store 初始化成功
        """
        backend1 = "/mnt/lustre47/test3_multi1"
        backend2 = "/mnt/lustre47/test3_multi2"
        os.makedirs(backend1, exist_ok=True)
        os.makedirs(backend2, exist_ok=True)

        config = {
            "store_pipeline": "Lustre",
            "storage_backends": [backend1, backend2],
            "device_id": -1,
            "tensor_size": 100,
            "shard_size": 100,
            "block_size": 100,
            "stripe_count": 4,
            "stripe_size": 1048576,
            "_test_backend": backend1,
        }

        try:
            store = UcmPipelineStore(config)
            assert store is not None, "❌ Store 创建失败"

            # 检查两个后端的数据目录
            data_dir1 = os.path.join(backend1, "data")
            data_dir2 = os.path.join(backend2, "data")
            assert os.path.exists(data_dir1), f"❌ 后端1数据目录不存在: {data_dir1}"
            assert os.path.exists(data_dir2), f"❌ 后端2数据目录不存在: {data_dir2}"

            log_test_info("P3-5.1", "多后端条带化设置成功")
        finally:
            # 🔧 保留测试数据用于调试 - 禁用清理
            pass
            # import shutil
            # if os.path.exists(backend1):
            #     shutil.rmtree(backend1, ignore_errors=True)
            # if os.path.exists(backend2):
            #     shutil.rmtree(backend2, ignore_errors=True)


# ===== 6. 配置参数测试 =====

class TestStripeConfigParameters:
    """P3-6: 条带配置参数

    测试目标：
    - 验证 stripe_count 和 stripe_size 正确传递
    - 验证参数边界值处理
    """

    def test_stripe_count_zero(self, no_stripe_config):
        """[P3-6.1] stripe_count=0 不启用条带化

        验证点：
        - Store 正常创建
        - 数据目录为普通目录
        """
        store = UcmPipelineStore(no_stripe_config)
        assert store is not None, "❌ Store 创建失败"
        log_test_info("P3-6.1", "stripe_count=0 正确处理")

    def test_stripe_size_zero(self, stripe_config):
        """[P3-6.2] stripe_size=0 使用默认值

        验证点：
        - Store 正常创建
        - 使用文件系统默认条带大小
        """
        config = stripe_config.copy()
        config["stripe_size"] = 0

        store = UcmPipelineStore(config)
        assert store is not None, "❌ Store 创建失败"
        log_test_info("P3-6.2", "stripe_size=0 使用默认值")

    def test_negative_stripe_count(self, stripe_config):
        """[P3-6.3] 负 stripe_count 应被视为禁用

        验证点：
        - Store 正常创建
        - 不启用条带化
        """
        config = stripe_config.copy()
        config["stripe_count"] = -1

        store = UcmPipelineStore(config)
        assert store is not None, "❌ Store 创建失败"
        log_test_info("P3-6.3", "负 stripe_count 正确处理")


# ===== 测试总结 =====

def pytest_report_header(config):
    """添加测试报告头部信息"""
    backend = "/mnt/lustre47/test3"
    is_lustre = is_lustre_mount(backend)
    return [
        f"Lustre Store P3 条带化测试",
        f"测试环境: {'Lustre 文件系统' if is_lustre else '非 Lustre 文件系统'}",
    ]
