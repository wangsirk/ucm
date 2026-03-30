"""
Qwen2 模型离线推理测试脚本 (CPU版本)
使用 UCMConnector 进行 KV 缓存管理

使用方法:
    cd /home/w2938/unified-cache-management
    LD_PRELOAD=/usr/lib64/libtcmalloc.so python test/offline_inference_qwen_cpu.py
    
注意: vLLM CPU 版本需要预加载 libtcmalloc 库
"""

import os

# 设置 LD_PRELOAD (如果尚未设置)
if "LD_PRELOAD" not in os.environ:
    tcmalloc_path = "/usr/lib64/libtcmalloc.so"
    if os.path.exists(tcmalloc_path):
        os.environ["LD_PRELOAD"] = tcmalloc_path
        print(f"[INFO] 自动设置 LD_PRELOAD={tcmalloc_path}")
    else:
        print(f"[WARNING] {tcmalloc_path} 不存在，请手动设置 LD_PRELOAD")

# 修复 _sqlite3 模块缺失问题
try:
    import pysqlite3 as sqlite3
    import sys
    sys.modules["sqlite3"] = sqlite3
except ImportError:
    pass

import contextlib
import os
import time
from dataclasses import asdict

from transformers import AutoTokenizer

# Third Party
from vllm import LLM, SamplingParams
from vllm.config import KVTransferConfig
from vllm.engine.arg_utils import EngineArgs

from ucm.logger import init_logger

logger = init_logger(__name__)


@contextlib.contextmanager
def build_llm_with_uc(module_path: str, name: str, model: str):
    """构建带有 UCMConnector 的 LLM 引擎 (CPU版本)"""
    ktc = KVTransferConfig(
        kv_connector=name,
        kv_connector_module_path=module_path,
        kv_role="kv_both",
        kv_connector_extra_config={
            "UCM_CONFIG_FILE": "/home/w2938/unified-cache-management/test/test_ucm_config.yaml"
        },
    )

    llm_args = EngineArgs(
        model=model,
        kv_transfer_config=ktc,
        max_model_len=512,  # CPU版本使用较小的上下文长度
        max_num_batched_tokens=1024,
        block_size=16,  # CPU版本使用较小的block size
        enforce_eager=True,
        trust_remote_code=True,
        enable_prefix_caching=False,
        # CPU版本不需要gpu_memory_utilization和device参数
    )

    llm = LLM(**asdict(llm_args))
    try:
        yield llm
    finally:
        logger.info("LLM engine is exiting.")


def print_output(
    llm: LLM,
    prompt: list[str],
    sampling_params: SamplingParams,
    req_str: str,
):
    """打印输出结果"""
    start = time.time()
    outputs = llm.generate(prompt, sampling_params)
    print("-" * 50)
    for output in outputs:
        generated_text = output.outputs[0].text
        print(f"Generated text: {generated_text!r}")
    print(f"Generation took {time.time() - start:.2f} seconds, {req_str} request Done.")
    print("-" * 50)


def main():
    # UCM Connector 配置
    module_path = "ucm.integration.vllm.ucm_connector"
    name = "UCMConnector"
    
    # 模型路径 - 使用 /home/w2938/model 下的 Qwen2 模型
    model = os.getenv("MODEL_PATH", "/home/w2938/model")

    logger.info(f"Loading model from: {model}")
    logger.info(f"Using UCM config: /home/w2938/unified-cache-management/test/test_ucm_config.yaml")
    logger.info("Running in CPU mode")

    tokenizer = AutoTokenizer.from_pretrained(model, use_chat_template=True)

    with build_llm_with_uc(module_path, name, model) as llm:
        # 测试消息 - 简单测试
        messages = [
            {
                "role": "system",
                "content": "You are a helpful assistant.",
            },
            {
                "role": "user",
                "content": "Hello, please say 'Hello World' in response.",
            },
        ]

        prompts = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        sampling_params = SamplingParams(temperature=0, top_p=0.95, max_tokens=50)

        # 第一次推理（会缓存 KV）
        print("\n=== 第一次推理（构建缓存）===")
        print_output(llm, prompts, sampling_params, "first")
        
        # 第二次推理（应该从缓存加载）
        print("\n=== 第二次推理（使用缓存）===")
        print_output(llm, prompts, sampling_params, "second")


if __name__ == "__main__":
    main()
