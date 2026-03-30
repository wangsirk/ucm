#!/bin/bash
#
# Qwen2.5-7B Posix KVCache 测试运行脚本
#
# 使用方法:
#   ./run_qwen7b_posix_test.sh [选项]
#
# 选项:
#   --model-path PATH    模型路径 (默认: /home/w2938/model)
#   --storage-path PATH  存储路径 (默认: /tmp/ucm_kvcache_qwen7b)
#   --test-type TYPE     测试类型: basic, kvcache, batch, all (默认: all)
#   --use-lustre         使用Lustre客户端路径
#   --help               显示帮助信息

set -e

# 默认配置
MODEL_PATH="${MODEL_PATH:-/home/w2938/model}"
STORAGE_PATH="${STORAGE_PATH:-/home/w2938/test/ucm_kvcache_qwen7b}"
TEST_TYPE="${TEST_TYPE:-all}"
USE_LUSTRE=false

# Lustre配置 (备用)
LUSTRE_PATH="/mnt/lustre/ucm_kvcache"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --model-path)
            MODEL_PATH="$2"
            shift 2
            ;;
        --storage-path)
            STORAGE_PATH="$2"
            shift 2
            ;;
        --test-type)
            TEST_TYPE="$2"
            shift 2
            ;;
        --use-lustre)
            USE_LUSTRE=true
            shift
            ;;
        --help)
            echo "Qwen2.5-7B Posix KVCache 测试运行脚本"
            echo ""
            echo "使用方法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  --model-path PATH    模型路径 (默认: /home/w2938/model)"
            echo "  --storage-path PATH  存储路径 (默认: /tmp/ucm_kvcache_qwen7b)"
            echo "  --test-type TYPE     测试类型: basic, kvcache, batch, all (默认: all)"
            echo "  --use-lustre         使用Lustre客户端路径 ($LUSTRE_PATH)"
            echo "  --help               显示帮助信息"
            exit 0
            ;;
        *)
            echo -e "${RED}未知选项: $1${NC}"
            exit 1
            ;;
    esac
done

# 如果使用Lustre，更新存储路径
if [ "$USE_LUSTRE" = true ]; then
    STORAGE_PATH="$LUSTRE_PATH"
fi

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TEST_SCRIPT="$PROJECT_ROOT/test/suites/E2E/test_qwen7b_posix_kvcache.py"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Qwen2.5-7B Posix KVCache 测试${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "模型路径: ${YELLOW}$MODEL_PATH${NC}"
echo -e "存储路径: ${YELLOW}$STORAGE_PATH${NC}"
echo -e "测试类型: ${YELLOW}$TEST_TYPE${NC}"
echo ""

# 检查模型路径
if [ ! -d "$MODEL_PATH" ]; then
    echo -e "${RED}错误: 模型路径不存在: $MODEL_PATH${NC}"
    exit 1
fi

# 检查模型文件
if [ ! -f "$MODEL_PATH/config.json" ]; then
    echo -e "${RED}错误: 模型配置文件不存在: $MODEL_PATH/config.json${NC}"
    exit 1
fi

echo -e "${GREEN}模型检查通过${NC}"

# 创建存储目录
echo ""
echo "创建存储目录: $STORAGE_PATH"
mkdir -p "$STORAGE_PATH"

# 激活虚拟环境
VENV_PATH="$PROJECT_ROOT/py310"
if [ -d "$VENV_PATH" ]; then
    echo "激活虚拟环境: $VENV_PATH"
    source "$VENV_PATH/bin/activate"
else
    echo -e "${YELLOW}警告: 虚拟环境不存在: $VENV_PATH${NC}"
    echo "使用系统Python"
fi

# 设置环境变量
export MODEL_PATH
export UCM_STORAGE_PATH="$STORAGE_PATH"
export PYTHONPATH="$PROJECT_ROOT/test:$PROJECT_ROOT:$PYTHONPATH"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}开始运行测试...${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# 运行测试
cd "$PROJECT_ROOT/test"

echo "使用Python直接运行测试..."
python suites/E2E/test_qwen7b_posix_kvcache.py \
    --model-path "$MODEL_PATH" \
    --storage-path "$STORAGE_PATH" \
    --test-type "$TEST_TYPE"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}测试完成${NC}"
echo -e "${GREEN}========================================${NC}"

# 显示存储统计
if [ -d "$STORAGE_PATH" ]; then
    echo ""
    echo "存储统计:"
    echo "  路径: $STORAGE_PATH"
    FILE_COUNT=$(find "$STORAGE_PATH" -type f | wc -l)
    TOTAL_SIZE=$(du -sh "$STORAGE_PATH" | cut -f1)
    echo "  文件数: $FILE_COUNT"
    echo "  总大小: $TOTAL_SIZE"
fi
