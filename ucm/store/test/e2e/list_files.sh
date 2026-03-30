#!/bin/bash
# ============================================================================
# POSIX存储目录查看脚本
# 用于查看哪些目录中存在文件
# ============================================================================

DATA_DIR="${1:-/mnt/lustre/data_verify}"

echo "======================================================================"
echo "POSIX 存储目录查看"
echo "======================================================================"
echo "存储路径: $DATA_DIR"
echo ""

# 检查目录是否存在
if [ ! -d "$DATA_DIR" ]; then
    echo "错误: 目录 $DATA_DIR 不存在"
    exit 1
fi

# 统计信息
echo "=== 统计信息 ==="
total_files=$(find "$DATA_DIR" -type f | wc -l)
total_dirs=$(find "$DATA_DIR" -type d | wc -l)
non_empty_dirs=$(find "$DATA_DIR" -mindepth 1 -maxdepth 1 -type d -exec sh -c 'ls -1 "$1" 2>/dev/null | head -1 | grep -q . && echo 1' _ {} \; | wc -l)

echo "文件总数: $total_files"
echo "目录总数: $total_dirs"
echo "非空目录数: $non_empty_dirs"
echo ""

# 显示有文件的目录
echo "=== 有文件的目录 ==="
for dir in "$DATA_DIR"/*/; do
    if [ -d "$dir" ]; then
        count=$(ls -1 "$dir" 2>/dev/null | wc -l)
        if [ "$count" -gt 0 ]; then
            dirname=$(basename "$dir")
            echo "目录 [$dirname]: $count 个文件"
            # 显示文件列表
            for f in "$dir"*; do
                if [ -f "$f" ]; then
                    fname=$(basename "$f")
                    fsize=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null)
                    echo "  - $fname (${fsize} bytes)"
                fi
            done
        fi
    fi
done

echo ""
echo "======================================================================"
echo "查看完成"
echo "======================================================================"
