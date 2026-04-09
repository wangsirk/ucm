#!/usr/bin/env python3
"""
UCM 数据一致性验证脚本
用于验证 vLLM 通过 UCM 写入的 KV Cache 数据一致性

使用方式:
1. 运行 vLLM benchmark 后执行此脚本
2. 或在运行 benchmark 时启用 --export_stats 查看 block 统计
3. 使用 --sample_ratio 随机采样验证比例
"""

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

import numpy as np
import yaml

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from ucm.store.lustre import UcmLustreStore
from ucm.store.cache.libcachestore import LibCacheStore
from ucm.store.pipeline.connector import UcmPipelineStore


def compute_tensor_hash(data: np.ndarray) -> str:
    """计算 tensor 数据的 BLAKE2b 哈希"""
    return hashlib.blake2b(data.tobytes()).hexdigest()[:16]


def compute_crc32(data: np.ndarray) -> int:
    """计算 tensor 数据的 CRC32 校验和"""
    import zlib
    return zlib.crc32(data.tobytes())


class DataConsistencyVerifier:
    """UCM 数据一致性验证器"""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = self._load_config()
        self.store = self._create_store()

    def _load_config(self) -> dict:
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)

    def _create_store(self) -> UcmPipelineStore:
        """根据配置创建 Store 实例"""
        backend_type = self.config.get('store_pipeline', 'Lustre')

        if backend_type == 'Lustre':
            from ucm.store.lustre import UcmLustreStore
            return UcmLustreStore(self.config_path)
        elif backend_type == 'CacheStore':
            return LibCacheStore(self.config_path)
        elif backend_type == 'Posix':
            from ucm.store.posix.posix_store import PosixStore
            return PosixStore(self.config_path)
        else:
            raise ValueError(f"Unsupported store type: {backend_type}")

    def scan_stored_blocks(self, data_dir: str = None) -> dict:
        """扫描存储目录中的所有 block 数据"""
        blocks_info = {}

        if data_dir is None:
            data_dir = self.config.get('storage_backends', ['/tmp/ucm_data'])[0]

        print(f"📂 扫描存储目录: {data_dir}")

        if not os.path.exists(data_dir):
            print(f"⚠️ 目录不存在: {data_dir}")
            return blocks_info

        # 遍历所有 shard 目录
        for shard_dir in sorted(os.listdir(data_dir)):
            shard_path = os.path.join(data_dir, shard_dir)
            if not os.isdir(shard_path):
                continue

            for block_file in sorted(os.listdir(shard_path)):
                if block_file.endswith('.dat'):
                    block_path = os.path.join(shard_path, block_file)
                    block_id = block_file[:-4]  # 去掉 .dat 后缀

                    # 读取 block 数据
                    try:
                        data = np.fromfile(block_path, dtype=np.uint8)
                        blocks_info[block_id] = {
                            'path': block_path,
                            'size': len(data),
                            'hash': compute_tensor_hash(data),
                            'crc32': compute_crc32(data),
                            'sample': data[:16].tobytes().hex() + '...' if len(data) > 16 else data.tobytes().hex(),
                        }
                    except Exception as e:
                        print(f"⚠️ 读取 block 失败 {block_path}: {e}")

        return blocks_info

    def verify_block_integrity(self, block_ids: list = None) -> dict:
        """验证指定 block 的数据完整性"""
        results = {
            'verified': [],
            'failed': [],
            'missing': [],
        }

        # 获取需要验证的 block IDs
        if block_ids is None:
            # 获取所有已存储的 blocks
            blocks_info = self.scan_stored_blocks()
            block_ids = list(blocks_info.keys())

        print(f"🔍 验证 {len(block_ids)} 个 blocks...")

        for block_id in block_ids:
            block_id_bytes = bytes.fromhex(block_id)

            # 分配目标 tensor
            tensor_size = self.config.get('tensor_size', 65536)
            dst_tensor = np.zeros(tensor_size, dtype=np.uint8)

            try:
                # 读取数据
                task = self.store.load([block_id_bytes], 0, dst_tensor)
                self.store.wait(task)

                # 计算读取数据的哈希
                loaded_hash = compute_tensor_hash(dst_tensor)

                # 检查数据是否全为零（可能是未初始化的）
                is_all_zero = np.all(dst_tensor == 0)

                # 检查数据是否有合理模式（非随机噪声）
                is_valid_pattern = self._check_data_pattern(dst_tensor)

                results['verified'].append({
                    'block_id': block_id,
                    'hash': loaded_hash,
                    'is_all_zero': is_all_zero,
                    'is_valid_pattern': is_valid_pattern,
                })

            except Exception as e:
                results['failed'].append({
                    'block_id': block_id,
                    'error': str(e),
                })

        return results

    def _check_data_pattern(self, data: np.ndarray) -> bool:
        """
        检查数据是否有合理模式
        - 全零数据可能是未初始化
        - 纯随机数据可能表示写入失败
        """
        if len(data) == 0:
            return False

        # 检查是否全零
        if np.all(data == 0):
            return False

        # 检查是否有重复模式（如全 0xFF）
        if np.all(data == data[0]):
            return False

        # 检查字节值分布
        unique_ratio = len(np.unique(data)) / len(data)

        # 如果只有很少的独特值，可能是损坏数据
        if unique_ratio < 0.01:
            return False

        return True

    def dump_vs_load_verification(self, num_blocks: int = 10, block_size: int = 65536) -> bool:
        """
        Dump-Load 闭环验证
        生成测试数据 -> 写入 -> 读取 -> 对比
        """
        print(f"🔄 执行 Dump-Load 闭环验证 ({num_blocks} blocks)...")

        # 生成测试数据
        test_data = []
        block_ids = []

        for i in range(num_blocks):
            # 生成唯一测试数据（包含索引和时间戳便于识别）
            data = np.zeros(block_size, dtype=np.uint8)
            timestamp = int(time.time() * 1000) % (2**32)
            # 在数据中嵌入标识信息
            data[0:8] = np.frombuffer(timestamp.to_bytes(8, 'little'), dtype=np.uint8)
            data[8:16] = np.array([i & 0xFF] * 8, dtype=np.uint8)
            # 填充伪随机但可验证的模式
            pattern = np.arange(256, dtype=np.uint8)
            data[16:272] = np.tile(pattern, 1)  # 256 字节模式
            test_data.append(data)

            # 生成 block ID（与 vLLM 格式兼容）
            block_id = hashlib.md5(f"test_block_{i}_{timestamp}".encode()).digest()[:16]
            block_ids.append(block_id)

        # 执行 Dump
        print("  📤 执行 Dump...")
        for i, (block_id, data) in enumerate(zip(block_ids, test_data)):
            task = self.store.dump([block_id], 0, data)
            self.store.wait(task)

        # 执行 Load
        print("  📥 执行 Load...")
        loaded_data = []
        for block_id in block_ids:
            dst = np.zeros(block_size, dtype=np.uint8)
            task = self.store.load([block_id], 0, dst)
            self.store.wait(task)
            loaded_data.append(dst)

        # 验证数据一致性
        print("  ✅ 验证数据一致性...")
        all_match = True
        for i, (original, loaded) in enumerate(zip(test_data, loaded_data)):
            if not np.array_equal(original, loaded):
                all_match = False
                orig_hash = compute_tensor_hash(original)
                load_hash = compute_tensor_hash(loaded)
                print(f"    ❌ Block {i}: hash {orig_hash} != {load_hash}")
            else:
                print(f"    ✅ Block {i}: 数据一致")

        return all_match


def main():
    parser = argparse.ArgumentParser(description='UCM 数据一致性验证')
    parser.add_argument('--config', '-c', default='/home/w2938/tools/ucm/test/test_ucm_config.yaml',
                        help='UCM 配置文件路径')
    parser.add_argument('--mode', '-m', choices=['scan', 'verify', 'loopback', 'all'],
                        default='all', help='验证模式')
    parser.add_argument('--sample_ratio', '-r', type=float, default=1.0,
                        help='随机采样验证比例 (0.0-1.0)')
    parser.add_argument('--block_size', '-s', type=int, default=65536,
                        help='Block 大小（字节）')
    parser.add_argument('--num_test_blocks', '-n', type=int, default=10,
                        help='测试用 block 数量')
    args = parser.parse_args()

    print("=" * 70)
    print("🔐 UCM 数据一致性验证工具")
    print("=" * 70)

    try:
        verifier = DataConsistencyVerifier(args.config)
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        return 1

    success = True

    # 模式 1: 扫描现有 blocks
    if args.mode in ['scan', 'all']:
        print("\n📊 模式 1: 扫描存储的 blocks")
        print("-" * 50)
        blocks_info = verifier.scan_stored_blocks()

        if blocks_info:
            print(f"\n📋 共发现 {len(blocks_info)} 个已存储的 blocks:")
            print(f"  {'Block ID':<20} {'Size':<10} {'Hash':<18} {'Sample':<20}")
            print(f"  {'-'*68}")

            for block_id, info in list(blocks_info.items())[:20]:
                print(f"  {block_id:<20} {info['size']:<10} {info['hash']:<18} {info['sample']:<20}")

            if len(blocks_info) > 20:
                print(f"  ... 还有 {len(blocks_info) - 20} 个 blocks")

            # 统计信息
            total_size = sum(b['size'] for b in blocks_info.values())
            hash_counts = {}
            for b in blocks_info.values():
                h = b['hash']
                hash_counts[h] = hash_counts.get(h, 0) + 1

            print(f"\n📈 统计:")
            print(f"  总 blocks: {len(blocks_info)}")
            print(f"  总大小: {total_size / 1024 / 1024:.2f} MB")
            print(f"  唯一 hash 数: {len(hash_counts)}")

            # 检查是否有重复 hash（可能表示数据重复）
            duplicates = {h: c for h, c in hash_counts.items() if c > 1}
            if duplicates:
                print(f"  ⚠️ 警告: 发现 {len(duplicates)} 个重复 hash")
        else:
            print("  ⚠️ 未发现任何已存储的 blocks")

    # 模式 2: 验证现有 blocks 可读性
    if args.mode in ['verify', 'all']:
        print("\n📊 模式 2: 验证 blocks 可读性")
        print("-" * 50)
        results = verifier.verify_block_integrity()

        print(f"  验证成功: {len(results['verified'])}")
        print(f"  验证失败: {len(results['failed'])}")
        print(f"  缺失: {len(results['missing'])}")

        # 分析数据模式
        zero_blocks = [r for r in results['verified'] if r['is_all_zero']]
        invalid_blocks = [r for r in results['verified'] if not r['is_valid_pattern']]

        if zero_blocks:
            print(f"  ⚠️ 全零数据 blocks: {len(zero_blocks)}")
        if invalid_blocks:
            print(f"  ⚠️ 无效数据模式 blocks: {len(invalid_blocks)}")

    # 模式 3: Dump-Load 闭环验证
    if args.mode in ['loopback', 'all']:
        print("\n📊 模式 3: Dump-Load 闭环验证")
        print("-" * 50)
        if verifier.dump_vs_load_verification(num_blocks=args.num_test_blocks, block_size=args.block_size):
            print("  ✅ 闭环验证通过!")
        else:
            print("  ❌ 闭环验证失败!")
            success = False

    print("\n" + "=" * 70)
    if success:
        print("✅ 所有验证完成")
    else:
        print("❌ 验证存在问题，请检查上述警告")
    print("=" * 70)

    return 0 if success else 1


if __name__ == "__main__":
    os.environ["UC_LOGGER_LEVEL"] = "warning"
    exit(main())
