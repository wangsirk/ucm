"""
Lustre Store P0 阶段单元测试

pytest 测试风格，与项目其他测试保持一致
"""
import hashlib
import os
import tempfile
import numpy as np
from pathlib import Path

import pytest
import torch

from ucm.logger import init_logger
from ucm.store.pipeline.connector import UcmPipelineStore

logger = init_logger(__name__)


def tensor_hash(tensor: torch.Tensor) -> bytes:
    """Calculate the hash value of the tensor as 16-byte bytes."""
    tensor_bytes = tensor.clone().detach().cpu().numpy().tobytes()
    hash_object = hashlib.blake2b(tensor_bytes, digest_size=16)
    return hash_object.digest()


@pytest.fixture
def lustre_config():
    """Fixture 提供测试配置"""
    backend = tempfile.mkdtemp()
    return {
        "store_pipeline": "Lustre",  # 必需：指定使用 Lustre pipeline
        "storage_backends": [backend],
        "device_id": -1,  # CPU only
        "tensor_size": 100,
        "shard_size": 100,
        "block_size": 100,
        "io_direct": False,
        "lustre_data_trans_concurrency": 4,
        "lustre_lookup_concurrency": 2,
        "timeout_ms": 30000,
        "data_dir_shard_bytes": 2,
        "stripe_count": 0,
        "stripe_size": 0,
        "_test_backend": backend,  # 用于测试检查
    }


@pytest.fixture
def lustre_store(lustre_config):
    """Fixture 提供初始化的 Store 实例"""
    return UcmPipelineStore(lustre_config)


# ===== 1. 参数校验测试 =====

def test_lookup_empty_blocks(lustre_store):
    """[P0-1.1] 参数校验: 空 blocks 列表应该正常处理"""
    masks = lustre_store.lookup([])
    assert len(masks) == 0  # numpy array 大小检查


def test_lookup_nonexistent_blocks(lustre_store):
    """[P0-1.2] 参数校验: 不存在的 blocks 应该返回 False"""
    # 生成 16 字节的随机 block_id
    block_ids = [hashlib.sha256(str(i).encode()).digest()[:16] for i in range(5)]
    masks = lustre_store.lookup(block_ids)
    assert not np.any(masks)  # 所有都应该不存在


# ===== 2. 文件操作测试 =====

def test_file_dump_and_lookup(lustre_store):
    """[P0-2.1] 文件操作: Dump 和 Lookup 基本功能"""
    src_data = torch.randint(0, 1000, (1, 100), dtype=torch.int32)
    block_id = tensor_hash(src_data)

    # Dump 数据
    task = lustre_store.dump(
        block_ids=[block_id],
        shard_index=[0],
        src_tensor=[[src_data]]
    )
    lustre_store.wait(task)  # wait() 返回 None

    # Lookup 验证
    masks = lustre_store.lookup([block_id])
    assert masks[0] == True  # numpy bool


# ===== 3. 目录结构测试 =====

def test_data_directory_created(lustre_store, lustre_config):
    """[P0-3.1] 目录结构: 数据目录应该自动创建"""
    backend = lustre_config["storage_backends"][0]
    data_dir = os.path.join(backend, "data")
    assert os.path.exists(data_dir), f"Data directory not found: {data_dir}"


def test_shard_directory_created(lustre_store, lustre_config):
    """[P0-3.2] 目录结构: 分片目录应该自动创建"""
    backend = lustre_config["storage_backends"][0]
    shard_dir = os.path.join(backend, "data", "00", "00")
    assert os.path.exists(shard_dir), f"Shard directory not found: {shard_dir}"


# ===== 4. 幂等性测试 =====

def test_dump_idempotency(lustre_store):
    """[P0-4.1] 幂等性: 相同 block 多次 dump 应该成功"""
    src_data = torch.randint(0, 1000, (1, 100), dtype=torch.int32)
    block_id = tensor_hash(src_data)

    # 第一次 Dump
    task1 = lustre_store.dump(
        block_ids=[block_id],
        shard_index=[0],
        src_tensor=[[src_data]]
    )
    lustre_store.wait(task1)

    # 第二次 Dump (相同数据) - 应该成功（幂等性）
    task2 = lustre_store.dump(
        block_ids=[block_id],
        shard_index=[0],
        src_tensor=[[src_data]]
    )
    lustre_store.wait(task2)  # 不应抛出异常


# ===== 5. 数据一致性测试 =====

def test_dump_load_consistency(lustre_store):
    """[P0-5.1] 数据一致性: Load 数据应该与 Dump 数据一致"""
    src_data = torch.randint(0, 1000, (1, 100), dtype=torch.int32)
    block_id = tensor_hash(src_data)

    # Dump
    dump_task = lustre_store.dump(
        block_ids=[block_id],
        shard_index=[0],
        src_tensor=[[src_data]]
    )
    lustre_store.wait(dump_task)

    # Load
    dst_tensor = [[torch.zeros_like(src_data)]]
    load_task = lustre_store.load(
        block_ids=[block_id],
        shard_index=[0],
        dst_tensor=dst_tensor
    )
    lustre_store.wait(load_task)

    # 验证数据一致性
    assert torch.equal(src_data, dst_tensor[0][0])


# ===== 6. 多 block 操作测试 =====

def test_multiple_blocks_dump_and_load(lustre_store):
    """[P0-6.1] 多 block: 同时处理多个 block"""
    num_blocks = 5
    src_data_list = [torch.randint(0, 1000, (1, 100), dtype=torch.int32) for _ in range(num_blocks)]
    block_ids = [tensor_hash(data) for data in src_data_list]

    # Dump 多个 blocks
    dump_tasks = [
        lustre_store.dump(
            block_ids=[block_id],
            shard_index=[0],
            src_tensor=[[data]]
        )
        for block_id, data in zip(block_ids, src_data_list)
    ]

    for task in dump_tasks:
        lustre_store.wait(task)

    # Lookup 验证
    masks = lustre_store.lookup(block_ids)
    assert np.all(masks)  # 所有都应该存在


# ===== 7. 错误处理测试 =====

def test_lookup_invalid_block_returns_false(lustre_store):
    """[P0-7.1] 错误处理: 查询不存在的 block 应该返回 False"""
    fake_block_id = b"0" * 16  # 无效的 block ID (16 bytes)
    masks = lustre_store.lookup([fake_block_id])
    assert masks[0] == False  # numpy bool 比较


# ===== 8. 并发安全性测试 (基础) =====

def test_concurrent_same_block_safe():
    """[P0-8.1] 并发安全: 多次 dump 相同 block 应该安全"""
    config = {
        "store_pipeline": "Lustre",  # 必需
        "storage_backends": [tempfile.mkdtemp()],
        "device_id": -1,
        "tensor_size": 100,
        "shard_size": 100,
        "block_size": 100,
        "data_dir_shard_bytes": 2,
    }

    # 创建两个 store 实例 (模拟两个进程)
    store1 = UcmPipelineStore(config)
    store2 = UcmPipelineStore(config)

    src_data = torch.randint(0, 1000, (1, 100), dtype=torch.int32)
    block_id = tensor_hash(src_data)

    # 并发 Dump
    task1 = store1.dump(
        block_ids=[block_id],
        shard_index=[0],
        src_tensor=[[src_data]]
    )
    task2 = store2.dump(
        block_ids=[block_id],
        shard_index=[0],
        src_tensor=[[src_data]]
    )

    # 等待完成 - 不应抛出异常
    store1.wait(task1)
    store2.wait(task2)

    # 验证至少一个成功（通过检查 block 是否存在）
    masks1 = store1.lookup([block_id])
    masks2 = store2.lookup([block_id])
    assert masks1[0] == True or masks2[0] == True
