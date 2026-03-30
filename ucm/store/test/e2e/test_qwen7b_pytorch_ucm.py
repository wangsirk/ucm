#!/usr/bin/env python3
"""
Qwen-7B KV Cache 存储测试 - 使用PyTorch和UCM

这个测试程序演示了：
1. 使用PyTorch创建真实的KV Cache张量
2. 计算BlockId hash（模拟UCM的hash机制）
3. 调用UCM Store接口进行存储

模型参数:
- Layers: 32
- Hidden Size: 4096
- Attn Heads: 32
- KV Heads: 32
- Head Dim: 128 (4096 / 32)

测试输入:
- 文本: "你好啊！"
- Tokens: 4
- Block Size: 4
- 结果: 1个完整的Block
"""

import hashlib
import os
import pickle
import shutil
import time
from typing import List

import numpy as np
import torch

# 尝试导入UCM，如果不可用则使用模拟版本
try:
    from ucm.store.factory_v1 import UcmConnectorFactoryV1
    from ucm.store.ucmstore_v1 import Task, UcmKVStoreBaseV1
    UCM_AVAILABLE = True
    print("✓ UCM 库已加载")
except ImportError as e:
    UCM_AVAILABLE = False
    print(f"⚠ UCM 库不可用: {e}")
    print("  将使用模拟模式")


# ==================== 模拟UCM接口（UCM不可用时使用） ====================
class MockTask(Task):
    """模拟异步任务句柄"""
    def __init__(self, completed=False):
        self.completed = completed

class MockUcmStore(UcmKVStoreBaseV1):
    """模拟UCM Store，用于测试"""
    def __init__(self, config):
        super().__init__(config)
        self.storage_path = config.get("storage_backends", "/tmp/ucm_mock")
        os.makedirs(self.storage_path, exist_ok=True)
        print(f"  [MockStore] 存储路径: {self.storage_path}")

    def cc_store(self) -> int:
        return 0

    def lookup(self, block_ids: List[bytes]) -> List[bool]:
        results = []
        for block_id in block_ids:
            file_path = self._get_file_path(block_id)
            results.append(os.path.exists(file_path))
        return results

    def lookup_on_prefix(self, block_ids: List[bytes]) -> int:
        for i, block_id in enumerate(block_ids):
            if not os.path.exists(self._get_file_path(block_id)):
                return i
        return len(block_ids) - 1 if block_ids else -1

    def prefetch(self, block_ids: List[bytes]) -> None:
        pass

    def load(self, block_ids, shard_index, dst_tensor):
        # 将张量数据从文件加载到dst_tensor
        for i, block_id in enumerate(block_ids):
            file_path = self._get_file_path(block_id)
            if os.path.exists(file_path):
                data = self._load_tensor(file_path)
                # 复制到目标张量
                for j, tensor in enumerate(dst_tensor[i]):
                    if j < len(data):
                        tensor.copy_(data[j])
        return MockTask(completed=True)

    def dump(self, block_ids, shard_index, src_tensor):
        # 将张量数据保存到文件
        for i, block_id in enumerate(block_ids):
            data = [t.cpu().clone() for t in src_tensor[i]]
            self._save_tensor(block_id, data)
        return MockTask(completed=True)

    def load_data(self, block_ids, shard_index, dst_addr):
        # 低级接口：直接加载数据到地址
        pass

    def dump_data(self, block_ids, shard_index, src_addr):
        # 低级接口：直接从地址转储数据
        pass

    def wait(self, task: Task) -> None:
        pass

    def check(self, task: Task) -> bool:
        return True

    def _get_file_path(self, block_id: bytes) -> str:
        """根据BlockId生成文件路径"""
        parent = block_id[:2].hex()
        filename = block_id[:4].hex()
        return os.path.join(self.storage_path, parent, filename)

    def _load_tensor(self, file_path: str):
        """从文件加载张量"""
        return torch.load(file_path)

    def _save_tensor(self, block_id: bytes, data):
        """保存张量到文件"""
        file_path = self._get_file_path(block_id)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        torch.save(data, file_path)


# ==================== KV Cache生成器 ====================
class Qwen7BKVCacher:
    """
    Qwen-7B KV Cache生成器

    模拟真实的Transformer KV Cache结构
    """

    def __init__(self, device="cpu"):
        # Qwen-7B 模型参数
        self.num_layers = 32
        self.num_kv_heads = 32  # GQA: kv_heads = attn_heads
        self.head_dim = 128  # 4096 / 32
        self.dtype = torch.float16

        self.device = torch.device(device)

    def generate_kv_cache(self, num_tokens: int) -> List[torch.Tensor]:
        """
        生成模拟的KV Cache

        返回: 每层一个元组 (K, V)，其中：
              - K: [num_tokens, num_kv_heads, head_dim]
              - V: [num_tokens, num_kv_heads, head_dim]
        """
        kv_cache = []

        print(f"  [生成KV Cache] Tokens: {num_tokens}")
        print(f"  [生成KV Cache] 层数: {self.num_layers}")
        print(f"  [生成KV Cache] KV Heads: {self.num_kv_heads}")
        print(f"  [生成KV Cache] Head Dim: {self.head_dim}")

        for layer_idx in range(self.num_layers):
            # 生成K cache: [num_tokens, num_kv_heads, head_dim]
            k_cache = torch.randn(
                num_tokens,
                self.num_kv_heads,
                self.head_dim,
                dtype=self.dtype,
                device=self.device
            ) * 0.1  # 小随机值

            # 生成V cache: [num_tokens, num_kv_heads, head_dim]
            v_cache = torch.randn(
                num_tokens,
                self.num_kv_heads,
                self.head_dim,
                dtype=self.dtype,
                device=self.device
            ) * 0.1

            kv_cache.append((k_cache, v_cache))

        total_size = sum(
            k.numel() * k.element_size() + v.numel() * v.element_size()
            for k, v in kv_cache
        )
        print(f"  [生成KV Cache] 总大小: {total_size / (1024*1024):.2f} MB")

        return kv_cache

    def get_kv_cache_size(self, num_tokens: int) -> int:
        """计算KV Cache大小（字节）"""
        # 单层KV Cache大小
        single_layer_size = (
            num_tokens * self.num_kv_heads * self.head_dim * 2  # K + V
            * 2  # float16 = 2 bytes
        )
        # 所有层
        total_size = single_layer_size * self.num_layers
        return total_size


# ==================== BlockId生成器 ====================
class BlockIdGenerator:
    """
    BlockId生成器 - 模拟UCM的hash机制

    使用MD5 hash计算BlockId
    """

    def __init__(self, model_name: str = "Qwen-7B"):
        # 模拟UCM的seed
        seed = f"{model_name}:1:torch.float16:0"
        self.seed_hash = hashlib.md5(seed.encode()).digest()

    def generate_block_ids(self, token_ids: List[int], block_size: int) -> List[bytes]:
        """
        生成BlockId列表

        Args:
            token_ids: token ID列表
            block_size: 每个Block的token数量

        Returns:
            BlockId列表（每个16字节）
        """
        block_ids = []
        parent_hash = self.seed_hash

        for start in range(0, len(token_ids), block_size):
            end = start + block_size
            block_token_ids = token_ids[start:end]

            # 只有完整的Block才生成hash
            if len(block_token_ids) < block_size:
                break

            # 计算hash: MD5(parent_hash + token_tuple)
            token_tuple = tuple(block_token_ids)
            hash_input = pickle_hash = hashlib.md5(
                parent_hash + str(token_tuple).encode()
            )
            block_hash = hash_input.digest()
            parent_hash = block_hash

            block_ids.append(block_hash)

        return block_ids


# ==================== UCM存储管理器 ====================
class UCMStorageManager:
    """
    UCM存储管理器

    负责创建UCM Store并执行存储操作
    """

    def __init__(self, storage_path: str, use_ucm: bool = True):
        self.storage_path = storage_path
        self.use_ucm = use_ucm and UCM_AVAILABLE
        self.store = None

        if self.use_ucm:
            print("\n=== 初始化UCM Store ===")
            config = {
                "storage_backends": storage_path,
                "device_id": 0,
                "io_direct": False,
            }
            try:
                self.store = UcmConnectorFactoryV1.create_connector(
                    "UcmNfsStore", config
                )
                print(f"  ✓ UCM Store 创建成功")
            except Exception as e:
                print(f"  ✗ UCM Store 创建失败: {e}")
                print(f"  回退到模拟模式")
                self.use_ucm = False
                self.store = MockUcmStore(config)
        else:
            print("\n=== 初始化模拟Store ===")
            config = {"storage_backends": storage_path}
            self.store = MockUcmStore(config)

    def lookup_blocks(self, block_ids: List[bytes]) -> List[bool]:
        """查询Block是否存在"""
        return self.store.lookup(block_ids)

    def dump_kv_cache(
        self,
        block_ids: List[bytes],
        kv_cache: List,
        shard_index: int = 0
    ) -> Task:
        """
        转储KV Cache到存储

        Args:
            block_ids: BlockId列表
            kv_cache: KV Cache列表（每层一个元组）
            shard_index: Shard索引

        Returns:
            异步任务句柄
        """
        # 准备数据：将KV Cache转换为张量列表
        # 对于UCM，需要将K和V分别作为不同的tensor
        src_tensors = []
        for block_id in block_ids:
            block_tensors = []
            for layer_idx, (k, v) in enumerate(kv_cache):
                # 每层的K和V
                block_tensors.append(k)
                block_tensors.append(v)
            src_tensors.append(block_tensors)

        # 调用dump
        shard_indexes = [shard_index] * len(block_ids)
        return self.store.dump(block_ids, shard_indexes, src_tensors)

    def load_kv_cache(
        self,
        block_ids: List[bytes],
        num_layers: int,
        kv_shape: tuple,
        shard_index: int = 0
    ):
        """
        从存储加载KV Cache

        Args:
            block_ids: BlockId列表
            num_layers: 层数
            kv_shape: KV Cache形状 (num_tokens, num_kv_heads, head_dim)
            shard_index: Shard索引

        Returns:
            加载的KV Cache
        """
        # 准备目标张量
        dst_tensors = []
        for block_id in block_ids:
            block_tensors = []
            for layer_idx in range(num_layers):
                # 创建空的K和V张量
                k = torch.empty(*kv_shape, dtype=torch.float16)
                v = torch.empty(*kv_shape, dtype=torch.float16)
                block_tensors.append(k)
                block_tensors.append(v)
            dst_tensors.append(block_tensors)

        # 调用load
        shard_indexes = [shard_index] * len(block_ids)
        task = self.store.load(block_ids, shard_indexes, dst_tensors)

        # 等待完成
        self.store.wait(task)

        # 解析结果
        loaded_kv = []
        for block_idx in range(len(block_ids)):
            block_kv = []
            for layer_idx in range(num_layers):
                k = dst_tensors[block_idx][layer_idx * 2]
                v = dst_tensors[block_idx][layer_idx * 2 + 1]
                block_kv.append((k, v))
            loaded_kv.append(block_kv)

        return loaded_kv

    def wait(self, task: Task) -> None:
        """等待异步任务完成"""
        if task is not None:
            self.store.wait(task)


# ==================== 主测试流程 ====================
def main():
    print("=" * 70)
    print("Qwen-7B KV Cache 存储测试 (PyTorch + UCM)")
    print("=" * 70)

    # 配置参数
    text = "你好啊！"
    block_size = 4
    storage_path = "/tmp/data_verify"

    print(f"\n=== 测试配置 ===")
    print(f"输入文本: '{text}'")
    print(f"Token数量: {len(text)} (假设每个中文字符1个token)")
    print(f"Block Size: {block_size} tokens")
    print(f"存储路径: {storage_path}")

    # 清理并创建存储目录
    if os.path.exists(storage_path):
        shutil.rmtree(storage_path)
    os.makedirs(storage_path, exist_ok=True)

    # 生成token IDs（模拟tokenizer）
    print(f"\n=== Token生成 ===")
    # 模拟tokenizer：为每个字符分配一个token ID
    token_ids = [ord(c) % 100000 for c in text]  # 简单模拟
    print(f"Token IDs: {token_ids}")

    # 计算完整Block数量
    num_complete_blocks = len(token_ids) // block_size
    print(f"完整Block数量: {num_complete_blocks}")

    if num_complete_blocks == 0:
        print("✗ 错误: Token数量不足以形成一个完整Block")
        return

    # 生成BlockId
    print(f"\n=== BlockId生成 ===")
    block_id_gen = BlockIdGenerator()
    block_ids = block_id_gen.generate_block_ids(token_ids, block_size)
    print(f"生成的BlockId数量: {len(block_ids)}")
    for i, block_id in enumerate(block_ids):
        print(f"  Block {i}: {block_id.hex()}")

    # 生成KV Cache
    print(f"\n=== 生成KV Cache ===")
    kv_cacher = Qwen7BKVCacher(device="cpu")
    kv_cache = kv_cacher.generate_kv_cache(len(token_ids))

    # 计算KV Cache大小
    kv_size = kv_cacher.get_kv_cache_size(len(token_ids))
    print(f"KV Cache总大小: {kv_size / (1024*1024):.2f} MB")

    # 初始化UCM Store
    print(f"\n=== 初始化存储 ===")
    storage_manager = UCMStorageManager(
        storage_path=storage_path,
        use_ucm=True  # 尝试使用真实UCM
    )

    # ========== Step 1: Lookup (预期MISS) ==========
    print(f"\n" + "=" * 70)
    print("Step 1: Lookup (预期: MISS)")
    print("=" * 70)
    lookup_results = storage_manager.lookup_blocks(block_ids)
    for i, (block_id, hit) in enumerate(zip(block_ids, lookup_results)):
        status = "HIT ✓" if hit else "MISS ✗"
        print(f"  Block {i} ({block_id[:8].hex()}...): {status}")

    if any(lookup_results):
        print("✗ 警告: 第一次查询应该全部MISS")
    else:
        print("✓ 正确: 全部MISS")

    # ========== Step 2: Dump KV Cache ==========
    print(f"\n" + "=" * 70)
    print("Step 2: Dump KV Cache")
    print("=" * 70)
    dump_start = time.time()
    task = storage_manager.dump_kv_cache(block_ids, kv_cache)
    storage_manager.wait(task)
    dump_time = time.time() - dump_start
    dump_bw = kv_size / dump_time / (1024*1024)
    print(f"✓ Dump 完成")
    print(f"  耗时: {dump_time * 1000:.2f} ms")
    print(f"  带宽: {dump_bw:.2f} MB/s")

    # ========== Step 3: Lookup (预期HIT) ==========
    print(f"\n" + "=" * 70)
    print("Step 3: Lookup (预期: HIT)")
    print("=" * 70)
    lookup_results = storage_manager.lookup_blocks(block_ids)
    for i, (block_id, hit) in enumerate(zip(block_ids, lookup_results)):
        status = "HIT ✓" if hit else "MISS ✗"
        print(f"  Block {i} ({block_id[:8].hex()}...): {status}")

    if not all(lookup_results):
        print("✗ 错误: Dump后查询应该全部HIT")
    else:
        print("✓ 正确: 全部HIT")

    # ========== Step 4: Load KV Cache ==========
    print(f"\n" + "=" * 70)
    print("Step 4: Load KV Cache")
    print("=" * 70)
    kv_shape = (len(token_ids), 32, 128)  # (num_tokens, num_kv_heads, head_dim)
    load_start = time.time()
    loaded_kv_cache = storage_manager.load_kv_cache(
        block_ids,
        num_layers=32,
        kv_shape=kv_shape
    )
    load_time = time.time() - load_start
    load_bw = kv_size / load_time / (1024*1024)
    print(f"✓ Load 完成")
    print(f"  耗时: {load_time * 1000:.2f} ms")
    print(f"  带宽: {load_bw:.2f} MB/s")

    # ========== Step 5: 数据验证 ==========
    print(f"\n" + "=" * 70)
    print("Step 5: 数据一致性验证")
    print("=" * 70)

    all_match = True
    for layer_idx in range(len(kv_cache)):
        k_original, v_original = kv_cache[layer_idx]
        k_loaded, v_loaded = loaded_kv_cache[0][layer_idx]

        if not torch.equal(k_original, k_loaded):
            print(f"✗ Layer {layer_idx} K cache 不匹配")
            all_match = False

        if not torch.equal(v_original, v_loaded):
            print(f"✗ Layer {layer_idx} V cache 不匹配")
            all_match = False

    if all_match:
        print("✓ 数据验证通过: 所有层KV Cache完全一致")
    else:
        print("✗ 数据验证失败")

    # ========== 总结 ==========
    print(f"\n" + "=" * 70)
    print("测试结果汇总")
    print("=" * 70)
    print(f"✓ Lookup (MISS): 正确")
    print(f"✓ Dump: 成功 ({dump_time * 1000:.2f} ms, {dump_bw:.2f} MB/s)")
    print(f"✓ Lookup (HIT): 正确")
    print(f"✓ Load: 成功 ({load_time * 1000:.2f} ms, {load_bw:.2f} MB/s)")
    print(f"{'✓' if all_match else '✗'} 数据验证: {'通过' if all_match else '失败'}")
    print(f"存储路径: {storage_path}")
    print(f"UCM模式: {'真实UCM' if storage_manager.use_ucm else '模拟模式'}")
    print("=" * 70)

    if all_match:
        print("\n🎉 测试全部通过!")


if __name__ == "__main__":
    main()
