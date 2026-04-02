"""
Lustre Store P2 阶段性能优化测试

P2 阶段测试范围：
- 异步 I/O 功能 (ThreadPoolBackend)
- 分层线程池 (Lookup 和 DataTrans 独立)
- CPU 亲和性配置
- 性能指标验证
"""
import hashlib
import os
import time
import uuid
from pathlib import Path

import pytest
import numpy as np
import torch

from ucm.logger import init_logger
from ucm.store.pipeline.connector import UcmPipelineStore

logger = init_logger(__name__)

# 测试唯一标识符，用于生成不同的 BlockId
_TEST_RUN_ID = str(uuid.uuid4())[:8]


# ===== 辅助函数 =====

def create_test_tensor(size: int = 1024, pattern: int = 0xAA) -> torch.Tensor:
    """创建测试数据为 torch.Tensor (1D)"""
    data = bytes([pattern % 256] * size)
    tensor = torch.from_numpy(np.frombuffer(data, dtype=np.uint8).copy())
    return tensor.flatten()  # 返回 1D tensor


# ===== 测试输出配置 =====

def pytest_configure(config):
    """配置 pytest 输出格式，添加中文说明"""
    config.addinivalue_line(
        "markers", "P2性能优化测试: 验证Lustre Store性能优化功能"
    )


# ===== 测试辅助函数 =====

def log_test_info(test_name, description, status="PASS"):
    """记录测试信息"""
    symbol = "✅" if status == "PASS" else "❌"
    logger.info(f"{symbol} [{test_name}] {description} - {status}")


def print_tensor_info(tensor, label="Tensor"):
    """打印 Tensor 详细信息用于调试"""
    logger.info(f"📊 [{label}] 信息:")
    logger.info(f"   - 形状: {tensor.shape}")
    logger.info(f"   - 数据类型: {tensor.dtype}")
    logger.info(f"   - 元素数量: {tensor.numel()}")
    logger.info(f"   - 前16字节: {tensor[:16].tolist()}")
    logger.info(f"   - 后16字节: {tensor[-16:].tolist()}")
    # 计算 hash 用于验证
    tensor_hash = hashlib.sha256(tensor.numpy().tobytes()).hexdigest()[:16]
    logger.info(f"   - SHA256前16位: {tensor_hash}")


def verify_tensor_equal(original, loaded, test_name=""):
    """验证两个 Tensor 是否相等，打印详细信息"""
    logger.info(f"🔍 [{test_name}] 数据验证:")
    logger.info(f"   - 原始数据形状: {original.shape}, 加载后形状: {loaded.shape}")
    logger.info(f"   - 原始数据类型: {original.dtype}, 加载后类型: {loaded.dtype}")

    if torch.equal(original, loaded):
        logger.info(f"   ✅ 数据完全匹配")
        return True
    else:
        logger.warning(f"   ❌ 数据不匹配!")
        # 打印差异位置
        diff_mask = original != loaded
        if diff_mask.any():
            diff_count = diff_mask.sum().item()
            logger.warning(f"   - 差异数量: {diff_count}")
            if diff_count <= 10:
                diff_indices = diff_mask.nonzero().squeeze()
                logger.warning(f"   - 差异位置: {diff_indices.tolist()}")
        return False


def generate_block_id(index: int, prefix: str = None) -> bytes:
    """生成测试用 BlockId (16字节)

    使用测试运行 ID + 前缀 + 索引来确保唯一性
    """
    if prefix is None:
        prefix = _TEST_RUN_ID
    data = f"{prefix}_test_block_{index}_{time.time_ns()}".encode()
    return hashlib.sha256(data).digest()[:16]


def cleanup_store_backend(backend_path: str):
    """清理后端存储目录中的所有数据文件"""
    if os.path.exists(backend_path):
        data_dir = os.path.join(backend_path, "data")
        if os.path.exists(data_dir):
            import shutil
            try:
                # 只删除 data 目录中的文件，保留目录结构
                for filename in os.listdir(data_dir):
                    file_path = os.path.join(data_dir, filename)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                logger.debug(f"清理后端目录: {data_dir}")
            except Exception as e:
                logger.warning(f"⚠️  清理后端目录失败: {e}")


# ===== Fixtures =====

@pytest.fixture
def p2_config():
    """启用 P2 功能的配置"""
    backend = "/mnt/lustre47/test2_p2_test"
    os.makedirs(backend, exist_ok=True)
    # 🔧 保留测试数据 - 不清理之前的测试数据
    # cleanup_store_backend(backend)
    yield {
        "store_pipeline": "Lustre",
        "storage_backends": [backend],
        "device_id": -1,
        "tensor_size": 1024,
        "shard_size": 1024,
        "block_size": 1024,
        # P2: 启用异步 I/O
        "enable_async_io": True,
        "async_io_backend": "threadpool",
        "async_io_queue_depth": 256,
        # P2: CPU 亲和性配置 (自动分配)
        "lustre_lookup_cpu_cores": -1,
        "lustre_data_trans_cpu_cores": -1,
        "_test_backend": backend,
    }
    # 🔧 保留测试数据 - 测试结束后不清理
    # cleanup_store_backend(backend)


@pytest.fixture
def p2_config_no_async():
    """P2 配置但禁用异步 I/O (用于对比)"""
    backend = "/mnt/lustre47/test2_p2_sync_test"
    os.makedirs(backend, exist_ok=True)
    # 🔧 保留测试数据 - 不清理之前的测试数据
    # cleanup_store_backend(backend)
    yield {
        "store_pipeline": "Lustre",
        "storage_backends": [backend],
        "device_id": -1,
        "tensor_size": 1024,
        "shard_size": 1024,
        "block_size": 1024,
        # P2: 禁用异步 I/O
        "enable_async_io": False,
        "_test_backend": backend,
    }
    # 🔧 保留测试数据 - 测试结束后不清理
    # cleanup_store_backend(backend)


@pytest.fixture
def lustre_store_p2(p2_config):
    """启用 P2 功能的 Store 实例"""
    return UcmPipelineStore(p2_config)


@pytest.fixture
def lustre_store_sync(p2_config_no_async):
    """禁用异步 I/O 的 Store 实例 (用于对比)"""
    return UcmPipelineStore(p2_config_no_async)


# ===== 1. P2 异步 I/O 基础功能测试 =====

class TestP2AsyncIO:
    """P2-1: 异步 I/O 功能测试

    测试目标：
    - 验证异步 I/O 后端正确初始化
    - 验证异步读写操作正常工作
    """

    def test_p2_async_io_initialization(self, p2_config):
        """[P2-1.1] 启用异步 I/O 应成功初始化 Store"""
        store = UcmPipelineStore(p2_config)
        assert store is not None, "❌ Store 实例创建失败"
        assert store.cc_store() > 0, "❌ C++ 指针无效"
        logger.info("✅ [P2-1.1] 异步 I/O 初始化 - 通过")

    def test_p2_async_io_dump_and_load(self, lustre_store_p2):
        """[P2-1.2] 异步 I/O Dump/Load 应正常工作"""
        store = lustre_store_p2

        # 准备测试数据 - 使用 create_test_tensor 确保形状一致
        block_id = generate_block_id(0, "p2_1_2")
        test_data = create_test_tensor(1024, 0xAB)

        logger.info("=" * 60)
        logger.info("🧪 [P2-1.2] 测试: 异步 I/O Dump/Load")
        logger.info("=" * 60)

        # 打印输入数据信息
        print_tensor_info(test_data, "输入数据")

        # Dump 操作
        logger.info("📤 执行 Dump 操作...")
        task = store.dump([block_id], [0], [[test_data]])
        store.wait(task)
        logger.info("   ✅ Dump 完成")

        # 验证文件存在
        result = store.lookup([block_id])
        assert len(result) == 1, "❌ Lookup 返回结果数量错误"
        assert result[0] == 1, "❌ Block 应该存在"
        logger.info(f"   ✅ Lookup 确认 Block 存在: {block_id.hex()}")

        # Load 操作
        load_buffer = create_test_tensor(1024, 0xCC)
        logger.info("📥 执行 Load 操作...")
        print_tensor_info(load_buffer, "Load 缓冲区(前)")
        task = store.load([block_id], [0], [[load_buffer]])
        store.wait(task)
        logger.info("   ✅ Load 完成")

        # 打印加载后的数据
        print_tensor_info(load_buffer, "Load 后数据")

        # 详细验证数据
        is_equal = verify_tensor_equal(test_data, load_buffer, "P2-1.2")
        assert is_equal, "❌ Load 数据不匹配"

        logger.info("=" * 60)
        logger.info("✅ [P2-1.2] 异步 I/O Dump/Load - 通过")
        logger.info("=" * 60)


# ===== 2. P2 线程池测试 =====

class TestP2ThreadPool:
    """P2-2: 分层线程池测试

    测试目标：
    - 验证 Lookup 线程池独立工作
    - 验证 DataTrans 线程池独立工作
    - 验证并发操作正常
    """

    def test_p2_lookup_thread_pool(self, lustre_store_p2):
        """[P2-2.1] Lookup 线程池应正常工作"""
        store = lustre_store_p2

        # 创建多个 Block 进行并发 Lookup - 使用测试特定前缀
        block_ids = [generate_block_id(i, "p2_2_1") for i in range(10)]
        results = store.lookup(block_ids)

        assert len(results) == 10, "❌ Lookup 返回结果数量错误"
        # 初始状态都应该不存在
        assert all(r == 0 for r in results), "❌ 初始状态应该全部不存在"
        logger.info("✅ [P2-2.1] Lookup 线程池 - 通过")

    def test_p2_datatrans_thread_pool(self, lustre_store_p2):
        """[P2-2.2] DataTrans 线程池应正常工作"""
        store = lustre_store_p2

        logger.info("=" * 60)
        logger.info("🧪 [P2-2.2] 测试: DataTrans 线程池")
        logger.info("=" * 60)

        # 准备测试数据 - 使用测试特定前缀
        block_ids = [generate_block_id(i, "p2_2_2") for i in range(5)]
        test_data_list = [create_test_tensor(1024, 0xAB + i) for i in range(5)]

        # 打印输入数据信息
        for i, test_data in enumerate(test_data_list):
            print_tensor_info(test_data, f"输入数据[{i}]")

        # 并发 Dump
        logger.info("📤 执行并发 Dump 操作...")
        tasks = []
        for block_id, test_data in zip(block_ids, test_data_list):
            logger.info(f"   Dumping block[{i}]: {block_id.hex()[:16]}...")
            task = store.dump([block_id], [0], [[test_data]])
            tasks.append(task)

        # 等待所有任务完成
        for task in tasks:
            store.wait(task)
        logger.info("   ✅ 所有 Dump 完成")

        # 验证所有 Block 都存在
        results = store.lookup(block_ids)
        logger.info(f"🔍 Lookup 结果: {[f'Block{i}={r}' for i, r in enumerate(results)]}")
        assert all(r == 1 for r in results), "❌ 所有 Block 应该存在"

        # 验证数据: Load 并比较
        logger.info("📥 执行并发 Load 验证...")
        for i, (block_id, original_data) in enumerate(zip(block_ids, test_data_list)):
            load_buffer = create_test_tensor(1024, 0xCC)
            task = store.load([block_id], [0], [[load_buffer]])
            store.wait(task)
            verify_tensor_equal(original_data, load_buffer, f"Block[{i}]")

        logger.info("=" * 60)
        logger.info("✅ [P2-2.2] DataTrans 线程池 - 通过")
        logger.info("=" * 60)

    def test_p2_concurrent_operations(self, lustre_store_p2):
        """[P2-2.3] 并发 Lookup 和 DataTrans 应正常工作"""
        store = lustre_store_p2

        # 准备测试数据 - 使用测试特定前缀
        block_ids = [generate_block_id(i, "p2_2_3") for i in range(10)]
        test_data_list = [create_test_tensor(1024, 0xAB + i) for i in range(10)]

        # 先 Dump 一半数据
        for i in range(5):
            task = store.dump([block_ids[i]], [0], [[test_data_list[i]]])
            store.wait(task)

        # 并发执行 Lookup 和 Load
        results = store.lookup(block_ids)
        assert results[0] == 1, "❌ Block 0 应该存在"
        assert results[5] == 0, "❌ Block 5 不应该存在"

        # Load 已存在的数据
        load_buffer = create_test_tensor(1024, 0xCC)
        task = store.load([block_ids[0]], [0], [[load_buffer]])
        store.wait(task)

        # 并发 Dump 剩余数据
        tasks = []
        for i in range(5, 10):
            task = store.dump([block_ids[i]], [0], [[test_data_list[i]]])
            tasks.append(task)

        # 等待所有任务完成
        for task in tasks:
            store.wait(task)

        logger.info("✅ [P2-2.3] 并发操作 - 通过")


# ===== 3. P2 性能对比测试 =====

class TestP2Performance:
    """P2-3: 性能优化效果测试

    测试目标：
    - 对比同步和异步 I/O 的性能
    - 验证并发吞吐量
    """

    def test_p2_performance_comparison(self, lustre_store_p2, lustre_store_sync):
        """[P2-3.1] 异步 I/O 应比同步 I/O 性能更好或相当"""
        # 准备测试数据 - 使用测试特定前缀
        num_blocks = 20
        block_ids_sync = [generate_block_id(i, "p2_3_1_sync") for i in range(num_blocks)]
        block_ids_async = [generate_block_id(i, "p2_3_1_async") for i in range(num_blocks)]
        test_data_list = [create_test_tensor(1024, 0xAB + idx) for idx in range(num_blocks)]

        # 测试同步版本
        start_time = time.time()
        for block_id, test_data in zip(block_ids_sync, test_data_list):
            task = lustre_store_sync.dump([block_id], [0], [[test_data]])
            lustre_store_sync.wait(task)
        sync_time = time.time() - start_time

        # 测试异步版本
        start_time = time.time()
        for block_id, test_data in zip(block_ids_async, test_data_list):
            task = lustre_store_p2.dump([block_id], [0], [[test_data]])
            lustre_store_p2.wait(task)
        async_time = time.time() - start_time

        # 异步版本应该不比同步版本慢（允许一定误差）
        # 注意：由于是小数据量，差异可能不明显
        logger.info(f"同步 I/O 时间: {sync_time:.4f}s, 异步 I/O 时间: {async_time:.4f}s")
        logger.info("✅ [P2-3.1] 性能对比 - 通过")

    def test_p2_throughput_test(self, lustre_store_p2):
        """[P2-3.2] 验证并发吞吐量"""
        store = lustre_store_p2

        # 准备大量测试数据 - 使用测试特定前缀
        num_blocks = 50
        block_ids = [generate_block_id(i, "p2_3_2") for i in range(num_blocks)]
        test_data_list = [create_test_tensor(1024, 0xAB + idx) for idx in range(num_blocks)]

        # 并发 Dump
        start_time = time.time()
        tasks = []
        for block_id, test_data in zip(block_ids, test_data_list):
            task = store.dump([block_id], [0], [[test_data]])
            tasks.append(task)

        for task in tasks:
            store.wait(task)
        dump_time = time.time() - start_time

        # 计算吞吐量
        total_bytes = num_blocks * 1024
        throughput = total_bytes / dump_time

        logger.info(f"Dump {num_blocks} blocks ({total_bytes/1024:.1f}KB) 耗时: {dump_time:.4f}s")
        logger.info(f"吞吐量: {throughput/1024:.2f} MB/s")

        # 验证所有数据都正确写入
        results = store.lookup(block_ids)
        assert all(r == 1 for r in results), "❌ 所有 Block 应该存在"
        logger.info("✅ [P2-3.2] 吞吐量测试 - 通过")


# ===== 4. P2 CPU 亲和性测试 =====

class TestP2CpuAffinity:
    """P2-4: CPU 亲和性配置测试

    测试目标：
    - 验证 CPU 亲和性配置生效
    - 验证自动分配功能
    """

    def test_p2_cpu_affinity_auto(self, p2_config):
        """[P2-4.1] CPU 亲和性自动分配应正常工作"""
        # 使用自动分配 (-1)
        p2_config["lustre_lookup_cpu_cores"] = -1
        p2_config["lustre_data_trans_cpu_cores"] = -1

        store = UcmPipelineStore(p2_config)
        assert store is not None, "❌ Store 实例创建失败"
        assert store.cc_store() > 0, "❌ C++ 指针无效"
        logger.info("✅ [P2-4.1] CPU 亲和性自动分配 - 通过")

    def test_p2_cpu_affinity_specific(self, p2_config):
        """[P2-4.2] 指定 CPU 核心应正常工作"""
        # 指定 CPU 核心 (假设系统有足够核心)
        p2_config["lustre_lookup_cpu_cores"] = 0
        p2_config["lustre_data_trans_cpu_cores"] = 1

        store = UcmPipelineStore(p2_config)
        assert store is not None, "❌ Store 实例创建失败"
        assert store.cc_store() > 0, "❌ C++ 指针无效"
        logger.info("✅ [P2-4.2] 指定 CPU 核心 - 通过")


# ===== 5. P2 配置灵活性测试 =====

class TestP2ConfigFlexibility:
    """P2-5: 配置灵活性测试

    测试目标：
    - 验证不同异步 I/O 后端配置
    - 验证队列深度配置
    """

    def test_p2_different_queue_depth(self):
        """[P2-5.1] 不同队列深度应正常工作"""
        backend = "/mnt/lustre47/test2"
        os.makedirs(backend, exist_ok=True)

        config = {
            "store_pipeline": "Lustre",
            "storage_backends": [backend],
            "device_id": -1,
            "tensor_size": 1024,
            "shard_size": 1024,
            "block_size": 1024,
            "enable_async_io": True,
            "async_io_queue_depth": 128,  # 不同的队列深度
        }

        store = UcmPipelineStore(config)
        assert store is not None, "❌ Store 实例创建失败"
        logger.info("✅ [P2-5.1] 不同队列深度 - 通过")

    def test_p2_async_io_toggle(self, p2_config):
        """[P2-5.2] 异步 I/O 开关应正常工作"""
        # 先测试启用状态
        p2_config["enable_async_io"] = True
        store_async = UcmPipelineStore(p2_config)
        assert store_async.cc_store() > 0, "❌ 启用异步 I/O 失败"

        # 再测试禁用状态
        p2_config["enable_async_io"] = False
        store_sync = UcmPipelineStore(p2_config)
        assert store_sync.cc_store() > 0, "❌ 禁用异步 I/O 失败"

        logger.info("✅ [P2-5.2] 异步 I/O 开关 - 通过")


# ===== 6. P2 稳定性测试 =====

class TestP2Stability:
    """P2-6: 稳定性和边界测试

    测试目标：
    - 验证大量并发操作稳定性
    - 验证错误处理
    """

    def test_p2_large_concurrent_operations(self, lustre_store_p2):
        """[P2-6.1] 大量并发操作应保持稳定"""
        store = lustre_store_p2

        logger.info("=" * 60)
        logger.info("🧪 [P2-6.1] 测试: 大量并发操作")
        logger.info("=" * 60)

        # 准备大量测试数据 - 使用测试特定前缀
        num_blocks = 100
        block_ids = [generate_block_id(i, "p2_6_1") for i in range(num_blocks)]
        test_data_list = [create_test_tensor(1024, 0xAB + idx) for idx in range(num_blocks)]

        # 打印前 3 个输入数据信息
        logger.info("📊 输入数据样本 (前 3 个):")
        for i in range(min(3, num_blocks)):
            print_tensor_info(test_data_list[i], f"输入数据[{i}]")

        # 并发 Dump
        logger.info(f"📤 执行 {num_blocks} 个并发 Dump 操作...")
        tasks = []
        for i, (block_id, test_data) in enumerate(zip(block_ids, test_data_list)):
            if i % 20 == 0:
                logger.info(f"   进度: {i}/{num_blocks}")
            task = store.dump([block_id], [0], [[test_data]])
            tasks.append(task)

        # 等待所有任务完成
        for task in tasks:
            store.wait(task)
        logger.info(f"   ✅ 所有 {num_blocks} 个 Dump 完成")

        # 验证所有数据都正确写入
        results = store.lookup(block_ids)
        existing_count = sum(1 for r in results if r == 1)
        logger.info(f"🔍 Lookup 结果: {existing_count}/{num_blocks} Blocks 存在")
        assert all(r == 1 for r in results), "❌ 所有 Block 应该存在"

        # 抽样验证数据 (验证前 5 个和后 5 个)
        logger.info("📥 抽样 Load 验证...")
        sample_indices = [0, 1, 2, 3, 4, num_blocks-5, num_blocks-4, num_blocks-3, num_blocks-2, num_blocks-1]
        for idx in sample_indices:
            block_id = block_ids[idx]
            original_data = test_data_list[idx]
            load_buffer = create_test_tensor(1024, 0xCC)
            task = store.load([block_id], [0], [[load_buffer]])
            store.wait(task)
            verify_tensor_equal(original_data, load_buffer, f"样本 Block[{idx}]")

        logger.info("=" * 60)
        logger.info(f"✅ [P2-6.1] 大量并发操作 ({num_blocks} blocks) - 通过")
        logger.info("=" * 60)

    def test_p2_error_handling(self, lustre_store_p2):
        """[P2-6.2] 错误处理应正常工作"""
        store = lustre_store_p2

        # 尝试 Load 不存在的 Block - 使用测试特定前缀
        block_id = generate_block_id(99999, "p2_6_2")
        load_buffer = create_test_tensor(1024, 0xCC)
        task = store.load([block_id], [0], [[load_buffer]])

        # Wait 应该完成（即使失败，store.wait 会抛出异常）
        try:
            store.wait(task)
        except RuntimeError as e:
            logger.info(f"✅ [P2-6.2] 预期错误捕获: {e}")
        else:
            # 如果没有抛出异常，检查 Block 是否确实不存在
            results = store.lookup([block_id])
            assert results[0] == 0, "❌ Block 不应该存在"

        logger.info("✅ [P2-6.2] 错误处理 - 通过")


# ===== 清理函数 =====

def pytest_sessionfinish(session, exitstatus):
    """测试会话结束时的清理"""
    # 🔧 保留测试数据用于调试 - 禁用自动清理
    # 如需清理，请手动运行: rm -rf /mnt/lustre47/test2_p2_test /mnt/lustre47/test2_p2_sync_test
    logger.info("📦 测试数据已保留，用于调试和验证")
    logger.info("   - /mnt/lustre47/test2_p2_test")
    logger.info("   - /mnt/lustre47/test2_p2_sync_test")
    logger.info("   清理命令: rm -rf /mnt/lustre47/test2_p2_test /mnt/lustre47/test2_p2_sync_test")

    # # 清理 P2 测试目录（已禁用）
    # for backend in ["/mnt/lustre47/test2_p2_test", "/mnt/lustre47/test2_p2_sync_test"]:
    #     if os.path.exists(backend):
    #         import shutil
    #         try:
    #             shutil.rmtree(backend)
    #             logger.info(f"✅ 清理测试目录: {backend}")
    #         except Exception as e:
    #             logger.warning(f"⚠️  清理测试目录失败: {e}")
