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
Qwen2.5-7B KVCache保存测试 - Posix存储后端

测试功能：
1. 使用Qwen2.5-7B模型进行推理
2. KVCache通过Posix存储后端保存到磁盘
3. 验证存储文件已创建

使用方法：
    pytest test/suites/E2E/test_qwen7b_kvcache_save.py -v -s
    或
    python test/suites/E2E/test_qwen7b_kvcache_save.py
"""

import os
import sys
import time
from pathlib import Path
from typing import Dict

# 将 test 目录添加到 Python 路径，以支持直接运行脚本
TEST_ROOT = Path(__file__).resolve().parent.parent.parent
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

import argparse

from common.offline_inference_utils import (
    build_llm_with_uc,
    ensure_storage_dir,
)
from common.path_utils import get_path_relative_to_test_root, get_path_to_model
from vllm import SamplingParams

from ucm.logger import init_logger

logger = init_logger(__name__)


# 默认配置
DEFAULT_MODEL_NAME = "Qwen2.5-7B-Instruct"
DEFAULT_STORAGE_PATH = "/home/w2938/test/ucm_kvcache_qwen7b"


def get_ucm_config_inline(storage_path: str) -> Dict:
    """
    生成内联UCM配置（通过kv_connector_extra_config传递）
    
    Args:
        storage_path: 存储路径
    
    Returns:
        UCM配置字典（用于kv_connector_extra_config）
    """
    return {
        "ucm_connectors": [
            {
                "ucm_connector_name": "UcmPipelineStore",
                "ucm_connector_config": {
                    "store_pipeline": "Posix",
                    "storage_backends": storage_path,  # 字符串格式，多个路径用冒号分隔
                    "io_direct": False,
                    "posix_data_trans_concurrency": 16,
                    "posix_lookup_concurrency": 16,
                }
            }
        ]
    }


def run_kvcache_save_test(model_path: str, storage_path: str, prompt: str = None):
    """
    运行KVCache保存测试
    
    Args:
        model_path: 模型路径
        storage_path: 存储路径
        prompt: 可选的自定义prompt
    """
    print("=" * 70)
    print("Qwen2.5-7B KVCache保存测试")
    print("=" * 70)
    print(f"模型路径: {model_path}")
    print(f"存储路径: {storage_path}")
    print("=" * 70)
    
    # 检查模型路径
    if not os.path.exists(model_path):
        print(f"错误: 模型路径不存在: {model_path}")
        return False
    
    # 清理并创建存储目录
    ensure_storage_dir(storage_path, clear_existing=True)
    
    # 默认prompt
    if prompt is None:
        prompt = "hello, how are you? the week is oing well. save the kvcache please. sa1ve the kvcache please. save the kvcache please do interesting things lustre is skill agent be doing asdasadasadsasdasdaawwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwqqweqweqweqw."
    
    print(f"\n输入Prompt: {prompt}")
    print("\n开始推理并保存KVCache...")
    
    # 配置
    sampling_params = SamplingParams(
        temperature=0.0,  # 使用确定性采样
        max_tokens=256,
    )
    ucm_config = get_ucm_config_inline(storage_path)
    
    # 记录开始时间
    start_time = time.time()
    
    # 运行推理
    # 注意：block_size需要根据prompt的token数量设置
    # 如果prompt tokens < block_size，则不会生成完整的block，KVCache不会被保存
    # 对于短prompt（如"hello"只有1-2个tokens），需要设置较小的block_size（如16）
    with build_llm_with_uc(
        model_path=model_path,
        ucm_config=ucm_config,
        enable_prefix_caching=False,
        max_num_batched_tokens=2048,
        gpu_memory_utilization=0.8,
        max_model_len=4096,
        enforce_eager=True,
        block_size=16,  # 减小block_size以适应短prompt
    ) as llm:
        outputs = llm.generate([prompt], sampling_params)
        generated_text = outputs[0].outputs[0].text
        elapsed_time = time.time() - start_time
        
        print(f"\n推理完成，耗时: {elapsed_time:.2f}s")
        print(f"\n生成文本:\n{generated_text}")
    
    # 等待数据写入
    print("\n等待KVCache数据写入存储...")
    time.sleep(2)
    
    # 检查存储目录
    print("\n检查存储目录...")
    kv_path = Path(storage_path) / "kv"
    
    if kv_path.exists():
        # 统计子目录数量
        subdirs = [d for d in kv_path.iterdir() if d.is_dir()]
        print(f"KV目录子目录数: {len(subdirs)}")
        
        # 统计文件数量
        files = list(kv_path.rglob("*"))
        file_count = len([f for f in files if f.is_file()])
        print(f"KV目录文件数: {file_count}")
        
        # 计算目录大小
        total_size = sum(f.stat().st_size for f in kv_path.rglob("*") if f.is_file())
        print(f"KV目录总大小: {total_size / 1024:.2f} KB")
        
        # 显示部分文件示例
        if file_count > 0:
            print("\n文件示例（前10个）:")
            sample_files = [f for f in kv_path.rglob("*") if f.is_file()][:10]
            for f in sample_files:
                rel_path = f.relative_to(kv_path)
                print(f"  {rel_path} ({f.stat().st_size} bytes)")
    else:
        print(f"KV目录不存在: {kv_path}")
    
    print("\n" + "=" * 70)
    print("测试完成")
    print("=" * 70)
    
    return True


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Qwen2.5-7B KVCache保存测试")
    parser.add_argument(
        "--model-path",
        type=str,
        default="/home/w2938/model",
        help="模型路径",
    )
    parser.add_argument(
        "--storage-path",
        type=str,
        default="/home/w2938/test/ucm_kvcache_qwen7b",
        help="KVCache存储路径",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="自定义prompt（可选）",
    )
    args = parser.parse_args()
    
    run_kvcache_save_test(
        model_path=args.model_path,
        storage_path=args.storage_path,
        prompt=args.prompt,
    )


if __name__ == "__main__":
    main()
