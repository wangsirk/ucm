# -*- coding: utf-8 -*-
#
# MIT License
#
# Copyright (c) 2025 Huawei Technologies Co., Ltd. All rights reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS

# A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER THAN TORT
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM
# COMMON, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (EXCEPT
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
# ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
"""
Lustre Store P1 阶段 - Lookup 功能测试

P1-L7: Lookup 功能测试
- 检查 Block 是否存在
- 批量查询
- 前缀查找
- 完整 Get 流程 (Lookup → Load)

测试结果更新日期: 2026-04-02
"""
import hashlib
import os

import pytest
import torch
import numpy as np

from ucm.logger import init_logger
from ucm.store.pipeline.connector import UcmPipelineStore

logger = init_logger(__name__)


# ===== 测试辅助函数 =====

def log_test_pass(test_name):
    """记录测试通过"""
    logger.info(f"✅ [{test_name}] - 通过")


def log_test_fail(test_name, reason):
    """记录测试失败"""
    logger.warning(f"❌ [{test_name}] - 失败: {reason}")


def log_test_skip(test_name, reason):
    """记录测试跳过"""
    logger.info(f"⏭️  [{test_name}] - 跳过: {reason}")


def generate_block_id(seed: int = 0) -> bytes:
    """生成测试用 BlockId (16字节)"""
    data = f"test_block_{seed}".encode()
    return hashlib.sha256(data).digest()[:16]


def create_test_tensor(size: int = 1024, pattern: int = 0xAA) -> torch.Tensor:
    """创建测试数据为 torch.Tensor"""
    data = bytes([pattern % 256] * size)
    tensor = torch.from_numpy(np.frombuffer(data, dtype=np.uint8).copy())
    return tensor


def assert_tensors_equal(actual: torch.Tensor, expected: torch.Tensor, msg: str = ""):
    """断言两个张量数据相等"""
    actual_bytes = actual.numpy().tobytes()
    expected_bytes = expected.numpy().tobytes()
    assert actual_bytes == expected_bytes, f"{msg}: Data mismatch"


# ===== Fixture =====

@pytest.fixture(scope="function")
def lustre_config():
    """Lustre Store 配置"""
    return {
        "storage_backends": ["/mnt/lustre47/test1"],
        "device_id": -1,  # CPU only
        "block_size": 1024,
        "shard_size": 1024,
        "tensor_size": 1024,
        "data_dir_shard_bytes": 0,
        "store_pipeline": "Lustre",
    }


@pytest.fixture(scope="function")
def lustre_store(lustre_config):
    """Lustre Store 实例"""
    store = UcmPipelineStore(lustre_config)
    yield store
    # 🔧 保留测试数据用于调试 - 禁用清理
    # import shutil
    # data_dir = lustre_config["storage_backends"][0] + "/data"
    # if os.path.exists(data_dir):
    #     shutil.rmtree(data_dir, ignore_errors=True)


# ===== P1-L7: Lookup 功能测试 =====

class TestLustreP1Lookup:
    """P1-L7: Lookup 功能测试

    测试目标：
    - 检查 Block 是否存在
    - 批量查询多个 Blocks
    - 前缀查找功能
    """

    def test_lookup_single_block_exists(self, lustre_store):
        """[P1-L1-T1] 查询存在的 Block"""
        block_id = generate_block_id(1000)
        data = create_test_tensor(1024, 0xAB)

        # 先 Dump 创建文件
        task = lustre_store.dump([block_id], [0], [[data]])
        lustre_store.wait(task)

        # Lookup 应该返回 [1]
        result = lustre_store.lookup([block_id])
        assert result == [1], f"Expected [1], got {result}"
        log_test_pass("P1-L1-T1 查询存在的Block")

    def test_lookup_single_block_not_exists(self, lustre_store):
        """[P1-L1-T2] 查询不存在的 Block"""
        block_id = generate_block_id(2000)

        # Lookup 应该返回 [0]
        result = lustre_store.lookup([block_id])
        assert result == [0], f"Expected [0], got {result}"
        log_test_pass("P1-L1-T2 查询不存在的Block")

    def test_lookup_multiple_blocks(self, lustre_store):
        """[P1-L1-T3] 批量查询多个 Blocks"""
        # Dump 3 个 blocks
        block_ids = [generate_block_id(3000 + i) for i in range(3)]
        for i, bid in enumerate(block_ids):
            data = create_test_tensor(1024, 0x10 + i)
            task = lustre_store.dump([bid], [0], [[data]])
            lustre_store.wait(task)

        # 查询：3 个存在 + 1 个不存在
        test_ids = block_ids + [generate_block_id(9999)]
        result = lustre_store.lookup(test_ids)
        assert result.tolist() == [1, 1, 1, 0], f"Expected [1,1,1,0], got {result.tolist()}"
        log_test_pass("P1-L1-T3 批量查询混合状态")

    def test_lookup_empty_list(self, lustre_store):
        """[P1-L1-T4] 空 Block 列表"""
        result = lustre_store.lookup([])
        assert len(result) == 0, f"Expected empty array, got {result}"
        log_test_pass("P1-L1-T4 空Block列表")

    def test_lookup_on_prefix_all_exist(self, lustre_store):
        """[P1-L1-T5] 前缀查询 - 全部存在"""
        block_ids = [generate_block_id(4000 + i) for i in range(3)]
        for bid in block_ids:
            data = create_test_tensor(1024, 0xAB)
            task = lustre_store.dump([bid], [0], [[data]])
            lustre_store.wait(task)

        # LookupOnPrefix 应该返回 -1（全部存在）
        result = lustre_store.lookup_on_prefix(block_ids)
        assert result == -1, f"Expected -1, got {result}"
        log_test_pass("P1-L1-T5 前缀查询全部存在")

    def test_lookup_on_prefix_first_missing(self, lustre_store):
        """[P1-L1-T6] 前缀查询 - 中间缺失"""
        block_ids = [generate_block_id(5000 + i) for i in range(5)]
        # 只 Dump 前 2 个
        for i in range(2):
            data = create_test_tensor(1024, 0x10 + i)
            task = lustre_store.dump([block_ids[i]], [0], [[data]])
            lustre_store.wait(task)

        # LookupOnPrefix 应该返回 2（第 3 个 block 缺失，索引为 2）
        result = lustre_store.lookup_on_prefix(block_ids)
        assert result == 2, f"Expected 2, got {result}"
        log_test_pass("P1-L1-T6 前缀查询中间缺失")

    def test_lookup_on_prefix_all_missing(self, lustre_store):
        """[P1-L1-T7] 前缀查询 - 全部缺失"""
        block_ids = [generate_block_id(6000 + i) for i in range(3)]
        # 不 Dump，全部缺失

        # LookupOnPrefix 应该返回 0（第一个就缺失）
        result = lustre_store.lookup_on_prefix(block_ids)
        assert result == 0, f"Expected 0, got {result}"
        log_test_pass("P1-L1-T7 前缀查询全部缺失")


# ===== P1-L2: 集成测试 =====

class TestLustreP1LookupIntegration:
    """P1-L2: Lookup 集成测试

    测试目标：
    - Lookup → Load 完整流程
    - 实际使用场景验证
    """

    def test_get_flow_with_lookup(self, lustre_store):
        """[P1-L2-T1] 完整 Get 流程：Lookup → Load"""
        block_id = generate_block_id(7000)
        data = create_test_tensor(1024, 0xCD)

        # 1. 先 Dump 数据
        task = lustre_store.dump([block_id], [0], [[data]])
        lustre_store.wait(task)

        # 2. Lookup 检查存在
        result = lustre_store.lookup([block_id])
        assert result == [1], "Block should exist after Dump"

        # 3. Load 数据
        loaded = torch.zeros(1024, dtype=torch.uint8)
        task = lustre_store.load([block_id], [0], [[loaded]])
        lustre_store.wait(task)

        # 4. 验证数据
        assert_tensors_equal(loaded, data, "Loaded data should match")
        log_test_pass("P1-L2-T1 完整Get流程")

    def test_lookup_before_load(self, lustre_store):
        """[P1-L2-T2] Load 前先检查避免不必要的加载"""
        block_id = generate_block_id(8000)
        data = create_test_tensor(1024, 0xEF)

        # 1. Dump 数据
        task = lustre_store.dump([block_id], [0], [[data]])
        lustre_store.wait(task)

        # 2. Lookup 确认存在
        result = lustre_store.lookup([block_id])
        assert result == [1], "Block should exist"

        # 3. Load 并验证
        loaded = torch.zeros(1024, dtype=torch.uint8)
        task = lustre_store.load([block_id], [0], [[loaded]])
        lustre_store.wait(task)
        assert_tensors_equal(loaded, data, "Data should match")
        log_test_pass("P1-L2-T2 Load前检查")

    def test_lookup_avoid_load_missing(self, lustre_store):
        """[P1-L2-T3] Lookup 检测缺失避免无效 Load"""
        block_id = generate_block_id(9000)

        # 1. Lookup 确认不存在
        result = lustre_store.lookup([block_id])
        assert result == [0], "Block should not exist"

        # 2. 尝试 Load（应该失败）
        loaded = torch.zeros(1024, dtype=torch.uint8)
        task = lustre_store.load([block_id], [0], [[loaded]])

        try:
            lustre_store.wait(task)
            log_test_fail("P1-L2-T3", "Load 应该抛出异常")
        except RuntimeError:
            log_test_pass("P1-L2-T3 Lookup检测缺失避免无效Load")
