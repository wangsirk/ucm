/**
 * MIT License
 *
 * Copyright (c) 2025 Huawei Technologies Co., Ltd. All rights reserved.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */
#ifndef UNIFIEDCACHE_LUSTRE_STORE_CC_TRANS_TASK_H
#define UNIFIEDCACHE_LUSTRE_STORE_CC_TRANS_TASK_H

#include <atomic>
#include "type/types.h"
#include "status/status.h"

namespace UC::LustreStore {

/**
 * TransTask - Lustre传输任务定义
 *
 * 定义LOAD（加载）和DUMP（转储）两种任务类型
 */
class TransTask {
public:
    enum class Type : uint8_t { LOAD, DUMP };  // 任务类型

    Detail::TaskHandle id{0};    // 任务唯一ID
    Type type{Type::DUMP};       // 任务类型
    Detail::TaskDesc desc;       // 任务描述

public:
    TransTask(Type type, Detail::TaskDesc desc)
        : id{NextId()}, type{type}, desc{std::move(desc)} {}

private:
    static size_t NextId() noexcept
    {
        static std::atomic<size_t> id{1};
        return id.fetch_add(1, std::memory_order_relaxed);
    }
};

/**
 * IoUnit - 最小I/O执行单元 (P1-1)
 *
 * 每个IoUnit对应一个Shard的I/O操作，包含:
 * - 标识信息 (BlockId, ShardIndex)
 * - 数据位置 (源地址、目标地址、文件偏移)
 * - 状态跟踪 (完成标志、执行结果)
 */
struct IoUnit {
    // ===== 标识信息 =====
    Detail::BlockId blockId;     // 所属Block标识 (16字节哈希)
    size_t shardIndex;           // Shard在Block中的索引

    // ===== 数据位置 =====
    void* srcAddr{nullptr};      // 源地址 (Dump时是Device, Load时是文件)
    void* dstAddr{nullptr};      // 目标地址 (Dump时是文件, Load时是Device)
    size_t fileOffset{0};        // 文件内的偏移量 (字节)
    size_t ioSize{0};            // 本次I/O的大小 (字节)

    // ===== 状态跟踪 =====
    std::atomic<bool> completed{false};  // 是否完成
    Status result{Status::OK()};        // 执行结果

    // ===== 构造函数 =====
    IoUnit() = default;

    IoUnit(const Detail::BlockId& bid, size_t sidx,
           void* src, void* dst, size_t offset, size_t size)
        : blockId(bid)
        , shardIndex(sidx)
        , srcAddr(src)
        , dstAddr(dst)
        , fileOffset(offset)
        , ioSize(size)
    {}

    // ===== 辅助方法 =====
    /**
     * 重置状态 (用于对象池复用)
     */
    void Reset() noexcept
    {
        shardIndex = 0;
        srcAddr = nullptr;
        dstAddr = nullptr;
        fileOffset = 0;
        ioSize = 0;
        completed.store(false, std::memory_order_relaxed);
        result = Status::OK();
        // blockId 保持不变，由外部设置
    }

    /**
     * 标记完成
     */
    void MarkCompleted(const Status& status) noexcept
    {
        result = status;
        completed.store(true, std::memory_order_release);
    }

    /**
     * 检查是否完成
     */
    bool IsCompleted() const noexcept
    {
        return completed.load(std::memory_order_acquire);
    }
};

}  // namespace UC::LustreStore

#endif
