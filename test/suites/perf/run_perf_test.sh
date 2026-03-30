#!/bin/bash
#
# Qwen2.5-7B KVCache性能测试执行脚本
#
# 使用方法:
#   ./run_perf_test.sh --scenario 4k --model-path /path/to/Qwen2.5-7B-Instruct
#   ./run_perf_test.sh --scenario 32k --model-path /path/to/Qwen2.5-7B-Instruct
#   ./run_perf_test.sh --scenario all --model-path /path/to/Qwen2.5-7B-Instruct
#

set -e

# 默认配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DEFAULT_MODEL_PATH="/home/w2938/model"
DEFAULT_STORAGE_PATH="/home/w2938/test/ucm_kvcache_perf"
DEFAULT_OUTPUT="perf_results_$(date +%Y%m%d_%H%M%S).json"

# 解析命令行参数
SCENARIO="all"
MODEL_PATH=""
STORAGE_PATH="${DEFAULT_STORAGE_PATH}"
OUTPUT_FILE="${DEFAULT_OUTPUT}"

usage() {
    echo "使用方法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  --scenario <4k|32k|all>  测试场景 (默认: all)"
    echo "  --model-path <path>      模型路径 (必需)"
    echo "  --storage-path <path>    KVCache存储路径 (默认: ${DEFAULT_STORAGE_PATH})"
    echo "  --output <file>          结果输出文件 (默认: ${DEFAULT_OUTPUT})"
    echo "  -h, --help               显示帮助信息"
    echo ""
    echo "测试场景说明:"
    echo "  4k:  4K输入 128输出 128并发 256样本"
    echo "  32k: 32K输入 128输出 16并发 32样本"
    echo "  all: 运行所有场景"
    echo ""
    echo "示例:"
    echo "  $0 --scenario 4k --model-path /home/models/Qwen2.5-7B-Instruct"
    echo "  $0 --scenario all --model-path /home/models/Qwen2.5-7B-Instruct --output results.json"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --scenario)
            SCENARIO="$2"
            shift 2
            ;;
        --model-path)
            MODEL_PATH="$2"
            shift 2
            ;;
        --storage-path)
            STORAGE_PATH="$2"
            shift 2
            ;;
        --output)
            OUTPUT_FILE="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "未知选项: $1"
            usage
            ;;
    esac
done

# 检查必需参数
if [ -z "${MODEL_PATH}" ]; then
    echo "错误: 必须指定模型路径 --model-path"
    usage
fi

# 检查模型路径是否存在
if [ ! -d "${MODEL_PATH}" ]; then
    echo "警告: 模型路径不存在: ${MODEL_PATH}"
fi

# 设置环境变量
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH}"
export UCM_CONFIG_FILE="${SCRIPT_DIR}/ucm_config_qwen7b_perf.yaml"

# 打印配置信息
echo "========================================"
echo "Qwen2.5-7B KVCache性能测试"
echo "========================================"
echo "测试场景: ${SCENARIO}"
echo "模型路径: ${MODEL_PATH}"
echo "存储路径: ${STORAGE_PATH}"
echo "输出文件: ${OUTPUT_FILE}"
echo "配置文件: ${UCM_CONFIG_FILE}"
echo "========================================"
echo ""

# 创建存储目录
mkdir -p "${STORAGE_PATH}"

# 运行测试
cd "${PROJECT_ROOT}"
python test/suites/perf/test_qwen7b_kvcache_perf.py \
    --scenario "${SCENARIO}" \
    --model-path "${MODEL_PATH}" \
    --storage-path "${STORAGE_PATH}" \
    --output "${OUTPUT_FILE}"

echo ""
echo "测试完成！结果已保存到: ${OUTPUT_FILE}"
