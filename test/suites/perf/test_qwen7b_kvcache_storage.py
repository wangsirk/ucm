# -*- coding: utf-8 -*-
#
# MIT License
#
# Copyright (c) 2025 Huawei Technologies Co., Ltd. All rights reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
"""
Qwen2.5-7B KVCache存储测试（离线推理模式）

本脚本专注于KVCache存储统计，不进行性能基准测试。
主要统计以下信息：
- 总KVCache大小
- 目录数量
- 文件数量
- 每个文件大小分布

测试场景:
1. 100输入 128输出
2. 32K输入 128输出

使用方法:
    # 测试100场景
    python test/suites/perf/test_qwen7b_kvcache_storage.py --scenario 100 --model-path /path/to/Qwen2.5-7B-Instruct
    
    # 测试32K场景
    python test/suites/perf/test_qwen7b_kvcache_storage.py --scenario 32k --model-path /path/to/Qwen2.5-7B-Instruct
    
    # 测试所有场景
    python test/suites/perf/test_qwen7b_kvcache_storage.py --scenario all --model-path /path/to/Qwen2.5-7B-Instruct
"""

import argparse
import os
import random
import shutil
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 将 test 目录添加到 Python 路径
TEST_ROOT = Path(__file__).resolve().parent.parent.parent
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from ucm.logger import init_logger

logger = init_logger(__name__)


# ==================== 测试场景配置 ====================
@dataclass
class TestScenario:
    """测试场景配置"""
    name: str                                       # 场景名称
    input_tokens: int                               # 输入token数量
    output_tokens: int                              # 输出token数量
    num_samples: int                                # 测试样本数量
    prefix_ratio: float = 0.98                      # 前缀占比（用于KVCache命中）


# 预定义测试场景
SCENARIOS = {
    "100": TestScenario(
        name="100输入_100输出",
        input_tokens=35,
        output_tokens=16,
        num_samples=2,
        prefix_ratio=0.5,
    ),
    "32k": TestScenario(
        name="32K输入_128输出",
        input_tokens=32000,
        output_tokens=128,
        num_samples=32,
        prefix_ratio=0.98,
    ),
}



# ==================== KVCache存储统计 ====================
@dataclass
class KVCacheStorageStats:
    """KVCache存储统计信息"""
    storage_path: str                               # 存储根路径
    total_size_bytes: int = 0                       # 总大小（字节）
    total_files: int = 0                            # 总文件数
    total_dirs: int = 0                             # 总目录数
    file_size_distribution: Dict[str, int] = None   # 文件大小分布
    dir_file_counts: Dict[str, int] = None          # 每个目录的文件数
    file_sizes: List[int] = None                    # 所有文件大小列表
    file_paths: List[str] = None                    # 所有文件完整路径列表
    block_ids: List[str] = None                     # 所有block ID列表（文件名）
    
    def __post_init__(self):
        if self.file_size_distribution is None:
            self.file_size_distribution = defaultdict(int)
        if self.dir_file_counts is None:
            self.dir_file_counts = {}
        if self.file_sizes is None:
            self.file_sizes = []
        if self.file_paths is None:
            self.file_paths = []
        if self.block_ids is None:
            self.block_ids = []
    
    @property
    def total_size_mb(self) -> float:
        """总大小（MB）"""
        return self.total_size_bytes / (1024 * 1024)
    
    @property
    def avg_file_size(self) -> float:
        """平均文件大小（字节）"""
        return self.total_size_bytes / self.total_files if self.total_files > 0 else 0
    
    @property
    def min_file_size(self) -> int:
        """最小文件大小（字节）"""
        return min(self.file_sizes) if self.file_sizes else 0
    
    @property
    def max_file_size(self) -> int:
        """最大文件大小（字节）"""
        return max(self.file_sizes) if self.file_sizes else 0
    
    def print_summary(self):
        """打印统计摘要"""
        print("\n" + "=" * 70)
        print("KVCache存储统计")
        print("=" * 70)
        print(f"存储路径: {self.storage_path}")
        print(f"总KVCache大小: {self.total_size_mb:.2f} MB ({self.total_size_bytes:,} bytes)")
        print(f"目录数量: {self.total_dirs}")
        print(f"文件数量: {self.total_files}")
        print("-" * 70)
        print("文件大小统计:")
        print(f"  平均文件大小: {self.avg_file_size:.2f} bytes")
        print(f"  最小文件大小: {self.min_file_size:,} bytes")
        print(f"  最大文件大小: {self.max_file_size:,} bytes")
        print("-" * 70)
        print("文件大小分布:")
        for size_range, count in sorted(self.file_size_distribution.items()):
            print(f"  {size_range}: {count} 个文件")
        print("-" * 70)
        print(f"每个目录平均文件数: {self.total_files / self.total_dirs:.2f}" if self.total_dirs > 0 else "  无目录")
        
        # 打印Block ID和文件路径详情
        print("-" * 70)
        print("Block ID 和文件路径详情:")
        print(f"  共 {len(self.block_ids)} 个Block")
        for i, (block_id, file_path, file_size) in enumerate(zip(self.block_ids, self.file_paths, self.file_sizes)):
            print(f"  [{i+1}] Block ID: {block_id}")
            print(f"      文件路径: {file_path}")
            print(f"      文件大小: {file_size:,} bytes ({file_size / 1024:.2f} KB)")
        print("=" * 70)


def get_size_range(size_bytes: int) -> str:
    """根据文件大小返回大小范围字符串"""
    if size_bytes < 1024:
        return "< 1KB"
    elif size_bytes < 10 * 1024:
        return "1KB - 10KB"
    elif size_bytes < 100 * 1024:
        return "10KB - 100KB"
    elif size_bytes < 1024 * 1024:
        return "100KB - 1MB"
    else:
        return "> 1MB"


def analyze_kvcache_storage(storage_path: str) -> KVCacheStorageStats:
    """分析KVCache存储目录"""
    stats = KVCacheStorageStats(storage_path=storage_path)
    kv_dir = Path(storage_path) / "kv"
    
    if not kv_dir.exists():
        print(f"⚠️ KVCache目录不存在: {kv_dir}")
        return stats
    
    # 收集所有文件信息，用于排序
    all_files_info = []
    
    # 遍历所有文件和目录
    for root, dirs, files in os.walk(kv_dir):
        # 统计目录（只统计非空目录）
        if len(dirs) > 0:
            stats.total_dirs += len(dirs)
        
        # 统计当前目录的文件数
        dir_path = os.path.relpath(root, kv_dir)
        stats.dir_file_counts[dir_path] = len(files)
        
        # 统计文件
        for f in files:
            file_path = os.path.join(root, f)
            file_size = os.path.getsize(file_path)
            
            # 收集文件信息
            all_files_info.append((file_path, f, file_size))
            
            stats.total_files += 1
            stats.total_size_bytes += file_size
            stats.file_sizes.append(file_size)
            
            # 文件大小分布
            size_range = get_size_range(file_size)
            stats.file_size_distribution[size_range] += 1
    
    # 按文件名（block_id）排序后添加到stats
    all_files_info.sort(key=lambda x: x[1])  # 按文件名排序
    for file_path, block_id, file_size in all_files_info:
        stats.file_paths.append(file_path)
        stats.block_ids.append(block_id)
    
    # 修正目录数统计：只统计包含文件的叶子目录
    stats.total_dirs = len([d for d, c in stats.dir_file_counts.items() if c > 0 or d == '.'])
    
    return stats


# ==================== 数据生成器 ====================
class PromptGenerator:
    """生成固定token数量的prompt"""
    
    def __init__(self, tokenizer_path: str):
        from transformers import AutoTokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)
        self.vocab_size = self.tokenizer.vocab_size
        self._cache: Dict[int, str] = {}
    
    def generate_prompt(self, num_tokens: int, seed: int = 42) -> Tuple[str, int]:
        """生成指定token数量的prompt"""
        cache_key = (num_tokens, seed)
        if cache_key in self._cache:
            return self._cache[cache_key], num_tokens
        
        random.seed(seed)
        # 生成随机token IDs
        token_ids = [random.randint(0, self.vocab_size - 1) for _ in range(num_tokens)]
        
        # 解码为文本
        text = self.tokenizer.decode(token_ids, skip_special_tokens=True)
        
        # 验证实际token数量
        actual_tokens = len(self.tokenizer.encode(text, add_special_tokens=False))
        
        # 如果token数量不匹配，进行微调
        while actual_tokens < num_tokens:
            text += " " + self.tokenizer.decode([random.randint(0, self.vocab_size - 1)])
            actual_tokens = len(self.tokenizer.encode(text, add_special_tokens=False))
        
        if actual_tokens > num_tokens:
            # 截断到目标长度
            encoded = self.tokenizer.encode(text, add_special_tokens=False)[:num_tokens]
            text = self.tokenizer.decode(encoded, skip_special_tokens=True)
            actual_tokens = num_tokens
        
        self._cache[cache_key] = text
        return text, actual_tokens
    
    def generate_prefix_suffix_prompts(
        self, 
        prefix_tokens: int, 
        suffix_tokens: int, 
        num_variations: int,
        base_seed: int = 42
    ) -> List[Tuple[str, int, int]]:
        """
        生成具有相同前缀和不同后缀的prompts
        用于测试KVCache命中率
        
        Returns:
            List of (prompt, prefix_token_count, total_token_count)
        """
        prompts = []
        
        # 生成公共前缀
        prefix_text, prefix_count = self.generate_prompt(prefix_tokens, seed=base_seed)
        
        for i in range(num_variations):
            # 生成不同的后缀
            suffix_text, suffix_count = self.generate_prompt(
                suffix_tokens, 
                seed=base_seed + i + 1
            )
            
            full_prompt = prefix_text + " " + suffix_text
            total_tokens = len(self.tokenizer.encode(full_prompt, add_special_tokens=False))
            
            prompts.append((full_prompt, prefix_count, total_tokens))
        
        return prompts


# ==================== 离线推理测试（使用vLLM API）====================
class OfflineInferenceTester:
    """离线推理测试器"""
    
    def __init__(
        self,
        model_path: str,
        storage_path: str,
        gpu_memory_utilization: float = 0.9,
        max_model_len: int = 32768,
    ):
        self.model_path = model_path
        self.storage_path = storage_path
        self.gpu_memory_utilization = gpu_memory_utilization
        self.max_model_len = max_model_len
        self.llm = None
        self.tokenizer = None
        self._llm_context = None
    
    def _get_ucm_config(self) -> Dict:
        """获取UCM配置"""
        return {
            "ucm_connectors": [
                {
                    # 连接器名称，目前UCM只存在两个：UcmNfsStore和UcmPipelineStore
                    "ucm_connector_name": "UcmPipelineStore",       # 链式组合存储，将多个store串联形成数据传输通道
                    "ucm_connector_config": {
                        "store_pipeline": "Posix",                  # 存储管道类型
                        "storage_backends": self.storage_path,      # 存储路径
                        "io_direct": False,                         # 是否启用直接I/O
                        "posix_data_trans_concurrency": 32,         # 数据传输并发数
                        "posix_lookup_concurrency": 32,             # 查找并发数
                    }
                }
            ]
        }
    
    def setup(self):
        """初始化模型"""
        from common.offline_inference_utils import build_llm_with_uc
        
        print(f"正在加载模型: {self.model_path}")
        
        ucm_config = self._get_ucm_config()
        
        self._llm_context = build_llm_with_uc(
            model_path=self.model_path,
            ucm_config=ucm_config,
            enable_prefix_caching=True,
            max_num_batched_tokens=8192,
            gpu_memory_utilization=self.gpu_memory_utilization,
            max_model_len=self.max_model_len,
            enforce_eager=True,
            block_size=16,
        )
        self.llm = self._llm_context.__enter__()
        
        # 获取tokenizer
        from transformers import AutoTokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        
        print("模型加载完成")
    
    def teardown(self):
        """清理资源"""
        if self._llm_context is not None:
            self._llm_context.__exit__(None, None, None)
            self.llm = None
            self._llm_context = None
    
    def run_inference_and_save_kvcache(
        self,
        scenario: TestScenario,
        prompts: List[Tuple[str, int, int]],
    ) -> bool:
        """
        运行推理并保存KVCache到UCM存储
        
        Returns:
            bool: KVCache是否成功保存到UCM存储
        """
        from vllm import SamplingParams
        
        print(f"\n开始推理，输入tokens: {scenario.input_tokens}, 输出tokens: {scenario.output_tokens}")
        print(f"样本数: {len(prompts)}")
        
        sampling_params = SamplingParams(
            temperature=0.0,
            max_tokens=scenario.output_tokens,
        )
        
        prompts_list = [p[0] for p in prompts]
        
        start_time = time.time()
        outputs = self.llm.generate(prompts_list, sampling_params)
        elapsed = time.time() - start_time
        
        print(f"推理完成，耗时: {elapsed:.2f}s")
        
        # 统计输出token数
        total_output_tokens = 0
        for i, output in enumerate(outputs):
            generated_text = output.outputs[0].text
            output_tokens = len(self.tokenizer.encode(generated_text, add_special_tokens=False))
            total_output_tokens += output_tokens
        
        print(f"总输出tokens: {total_output_tokens}")
        
        # 计算预期的Block数量
        # 注意：UCM当前实现中，只有输入tokens（Prefill阶段）会被缓存到存储
        # 输出tokens（Decode阶段）不会被持久化到外部存储
        # 因此预期Block数 = floor(输入tokens / block_size)
        block_size = 16  # vLLM默认block_size
        input_tokens = scenario.input_tokens
        expected_blocks = input_tokens // block_size
        
        print(f"预期Block数量: {expected_blocks} (基于输入 {input_tokens} tokens, block_size={block_size})")
        print(f"注意: 输出tokens({scenario.output_tokens})不会产生持久化block")
        
        # 轮询等待KVCache写入存储
        return self._wait_for_kvcache_write(expected_blocks, timeout=60)
    
    def _wait_for_kvcache_write(self, expected_blocks: int, timeout: int = 60) -> bool:
        """
        轮询等待KVCache写入完成
        
        Args:
            expected_blocks: 预期的Block数量
            timeout: 超时时间（秒）
        
        Returns:
            bool: KVCache是否成功写入
        """
        storage_dir = Path(self.storage_path)
        kv_dir = storage_dir / "kv"
        
        print(f"等待KVCache写入UCM存储 (预期 {expected_blocks} 个Block, 超时 {timeout}s)...")
        
        start_time = time.time()
        last_file_count = 0
        
        while time.time() - start_time < timeout:
            if not kv_dir.exists():
                time.sleep(1)
                continue
            
            # 统计当前文件数
            kv_files = list(kv_dir.rglob("*"))
            current_file_count = len([f for f in kv_files if f.is_file()])
            
            # 如果文件数有变化，打印进度
            if current_file_count != last_file_count:
                elapsed = time.time() - start_time
                print(f"  [{elapsed:.1f}s] 当前文件数: {current_file_count} / {expected_blocks}")
                last_file_count = current_file_count
            
            # 检查是否达到预期
            if current_file_count >= expected_blocks:
                elapsed = time.time() - start_time
                print(f"✓ KVCache写入完成! 耗时: {elapsed:.1f}s")
                return self._print_kvcache_stats(kv_dir)
            
            time.sleep(1)
        
        # 超时处理
        elapsed = time.time() - start_time
        if last_file_count > 0:
            print(f"⚠️ 等待超时 ({elapsed:.1f}s)，当前文件数: {last_file_count} / {expected_blocks}")
            return self._print_kvcache_stats(kv_dir)
        else:
            print(f"⚠️ 等待超时 ({elapsed:.1f}s)，未找到KVCache文件")
            print(f"  可能原因: block_size设置过大或prompt token数不足")
            return False
    
    def _print_kvcache_stats(self, kv_dir: Path) -> bool:
        """打印KVCache存储统计信息"""
        kv_files = list(kv_dir.rglob("*"))
        file_count = len([f for f in kv_files if f.is_file()])
        
        if file_count == 0:
            print(f"⚠️ 未找到KVCache文件")
            return False
        
        # 计算总大小
        total_size = sum(f.stat().st_size for f in kv_files if f.is_file())
        size_mb = total_size / (1024 * 1024)
        
        print(f"✓ KVCache已保存到UCM存储:")
        print(f"  存储路径: {kv_dir}")
        print(f"  文件数量: {file_count}")
        print(f"  总大小: {size_mb:.2f} MB")
        
        return True


# ==================== 主测试函数 ====================
def run_scenario_test(
    scenario: TestScenario,
    model_path: str,
    storage_path: str,
    tokenizer_path: str,
) -> Tuple[KVCacheStorageStats, bool]:
    """
    运行单个场景的测试
    
    Args:
        scenario: 测试场景配置
        model_path: 模型路径
        storage_path: KVCache存储路径
        tokenizer_path: tokenizer路径
    
    Returns:
        Tuple[KVCacheStorageStats, bool]: (存储统计信息, KVCache是否成功保存)
    """
    print("\n" + "=" * 70)
    print(f"准备测试场景: {scenario.name}")
    print("=" * 70)
    print(f"输入tokens: {scenario.input_tokens}")
    print(f"输出tokens: {scenario.output_tokens}")
    print(f"样本数: {scenario.num_samples}")
    print(f"前缀占比: {scenario.prefix_ratio * 100:.0f}%")
    
    # 清理存储目录
    storage_dir = Path(storage_path)
    if storage_dir.exists():
        shutil.rmtree(storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成测试数据
    print(f"\n生成测试数据...")
    prompt_generator = PromptGenerator(tokenizer_path)
    
    # 计算前缀长度（用于达到98%命中率）
    prefix_tokens = int(scenario.input_tokens * scenario.prefix_ratio)
    suffix_tokens = scenario.input_tokens - prefix_tokens
    
    prompts = prompt_generator.generate_prefix_suffix_prompts(
        prefix_tokens=prefix_tokens,
        suffix_tokens=suffix_tokens,
        num_variations=scenario.num_samples,
        base_seed=42,
    )
    
    # 打印每个prompt的实际token数量
    print(f"\n===== Prompt Token详情 =====")
    for i, (prompt, prefix_count, total_tokens) in enumerate(prompts):
        actual_tokens = len(prompt_generator.tokenizer.encode(prompt, add_special_tokens=False))
        print(f"  Prompt[{i+1}] 实际tokens: {actual_tokens}, 前缀tokens: {prefix_count}, 总tokens: {total_tokens}")
        if actual_tokens != scenario.input_tokens:
            print(f"    ⚠️ 警告: 实际tokens({actual_tokens}) != 预期tokens({scenario.input_tokens})")
    
    # 打印每个prompt的实际token数量
    print(f"\n实际prompt token统计:")
    for i, (prompt, prefix_count, total_count) in enumerate(prompts):
        actual_tokens = len(prompt_generator.tokenizer.encode(prompt, add_special_tokens=False))
        print(f"  Prompt[{i}]: 实际tokens={actual_tokens}, 前缀tokens={prefix_count}, 总tokens={total_count}")
    
    # 创建测试器并运行测试
    tester = OfflineInferenceTester(
        model_path=model_path,
        storage_path=storage_path,
        max_model_len=max(scenario.input_tokens + scenario.output_tokens + 1000, 32768),
    )
    tester.setup()
    kvcache_saved = False
    
    try:
        # 运行推理并保存KVCache
        kvcache_saved = tester.run_inference_and_save_kvcache(scenario, prompts)
    finally:
        tester.teardown()
    
    # 分析KVCache存储
    stats = analyze_kvcache_storage(storage_path)
    
    return stats, kvcache_saved


# ==================== 命令行入口 ====================
def main():
    parser = argparse.ArgumentParser(
        description="Qwen2.5-7B KVCache存储测试（离线推理模式）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 测试100场景
  python test_qwen7b_kvcache_storage.py --scenario 100 --model-path /path/to/Qwen2.5-7B-Instruct
  
  # 测试32K场景
  python test_qwen7b_kvcache_storage.py --scenario 32k --model-path /path/to/Qwen2.5-7B-Instruct
  
  # 测试所有场景
  python test_qwen7b_kvcache_storage.py --scenario all --model-path /path/to/Qwen2.5-7B-Instruct
        """,
    )
    
    parser.add_argument(
        "--scenario",
        type=str,
        choices=["100", "32k", "all"],
        default="all",
        help="测试场景: 100, 32k, 或 all",
    )
    parser.add_argument(
        "--model-path",
        type=str,
        required=True,
        help="模型路径",
    )
    parser.add_argument(
        "--storage-path",
        type=str,
        default="/home/w2938/test/ucm_kvcache_storage_offline",
        help="KVCache存储路径",
    )
    parser.add_argument(
        "--tokenizer-path",
        type=str,
        default=None,
        help="Tokenizer路径（默认与model-path相同）",
    )
    
    args = parser.parse_args()
    
    # 设置tokenizer路径
    tokenizer_path = args.tokenizer_path or args.model_path
    
    # 确定要测试的场景
    if args.scenario == "all":
        scenarios_to_test = ["100", "32k"]
    else:
        scenarios_to_test = [args.scenario]
    
    all_stats = {}
    
    for scenario_key in scenarios_to_test:
        scenario = SCENARIOS[scenario_key]
        
        # 为每个场景创建独立的存储路径
        scenario_storage_path = os.path.join(args.storage_path, scenario_key)
        
        stats, kvcache_saved = run_scenario_test(
            scenario=scenario,
            model_path=args.model_path,
            storage_path=scenario_storage_path,
            tokenizer_path=tokenizer_path,
        )
        
        # 打印统计摘要
        stats.print_summary()
        
        all_stats[scenario_key] = {
            "scenario_name": scenario.name,
            "input_tokens": scenario.input_tokens,
            "output_tokens": scenario.output_tokens,
            "num_samples": scenario.num_samples,
            "kvcache_saved": kvcache_saved,
            "storage_stats": {
                "total_size_mb": stats.total_size_mb,
                "total_files": stats.total_files,
                "total_dirs": stats.total_dirs,
                "avg_file_size": stats.avg_file_size,
                "min_file_size": stats.min_file_size,
                "max_file_size": stats.max_file_size,
                "file_size_distribution": dict(stats.file_size_distribution),
                "block_ids": stats.block_ids,
                "file_paths": stats.file_paths,
            }
        }
    
    # 打印汇总信息
    print("\n" + "=" * 70)
    print("所有场景KVCache存储汇总")
    print("=" * 70)
    for scenario_key, data in all_stats.items():
        print(f"\n场景: {data['scenario_name']}")
        print(f"  输入tokens: {data['input_tokens']}, 输出tokens: {data['output_tokens']}")
        print(f"  KVCache保存: {'成功' if data['kvcache_saved'] else '失败'}")
        stats_data = data['storage_stats']
        print(f"  总大小: {stats_data['total_size_mb']:.2f} MB")
        print(f"  目录数: {stats_data['total_dirs']}, 文件数: {stats_data['total_files']}")
        print(f"  文件大小: 平均 {stats_data['avg_file_size']:.2f} bytes, "
              f"最小 {stats_data['min_file_size']} bytes, "
              f"最大 {stats_data['max_file_size']} bytes")
        # 打印Block ID列表
        print(f"  Block IDs ({len(stats_data['block_ids'])} 个):")
        for i, block_id in enumerate(stats_data['block_ids'][:5]):  # 只显示前5个
            print(f"    [{i+1}] {block_id}")
        if len(stats_data['block_ids']) > 5:
            print(f"    ... 还有 {len(stats_data['block_ids']) - 5} 个Block")
    print("=" * 70)
    
    return all_stats


if __name__ == "__main__":
    main()
