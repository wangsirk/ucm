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
#ifndef UNIFIEDCACHE_LUSTRE_STORE_CC_TRANS_QUEUE_H
#define UNIFIEDCACHE_LUSTRE_STORE_CC_TRANS_QUEUE_H

#include <memory>
#include "global_config.h"
#include "space_layout.h"
#include "template/hashset.h"
#include "thread/latch.h"
#include "thread/thread_pool.h"
#include "trans_task.h"

namespace UC::LustreStore {

/**
 * TransQueue - Lustre传输队列
 *
 * 负责执行实际的I/O操作
 * P1-1.1: 实现任务拆分功能
 */
class TransQueue {
    using TaskIdSet = HashSet<Detail::TaskHandle>;
    using TaskPtr = std::shared_ptr<TransTask>;
    using WaiterPtr = std::shared_ptr<Latch>;

private:
    // 内部使用的扩展 IoUnit (包含 TransQueue 特有字段)
    struct ExtendedIoUnit {
        // ===== IoUnit 核心字段 =====
        Detail::BlockId blockId;
        size_t shardIndex;
        void* srcAddr{nullptr};
        void* dstAddr{nullptr};
        size_t fileOffset{0};
        size_t ioSize{0};
        std::atomic<bool> completed{false};
        Status result{Status::OK()};

        // ===== TransQueue 特有字段 =====
        Detail::TaskHandle owner;        // 所属任务 ID
        TransTask::Type type;            // 任务类型
        std::shared_ptr<Latch> waiter;    // 完成通知
        bool firstIo{false};             // 是否为第一个 I/O

        // ===== P1-1.2: Shard 跟踪字段 =====
        size_t totalShards{1};           // Block 的总 Shard 数
        size_t currentShard{0};          // 当前 Shard 索引 (0-based)

        ExtendedIoUnit() = default;

        // 便捷构造函数
        ExtendedIoUnit(const Detail::BlockId& bid, size_t sidx,
                       void* src, void* dst, size_t offset, size_t size,
                       Detail::TaskHandle ownerId, TransTask::Type t,
                       std::shared_ptr<Latch> w, size_t totalShards = 1, size_t currentShard = 0)
            : blockId(bid), shardIndex(sidx), srcAddr(src), dstAddr(dst),
              fileOffset(offset), ioSize(size), owner(ownerId), type(t), waiter(w),
              totalShards(totalShards), currentShard(currentShard) {}

        // 状态管理方法
        bool IsCompleted() const noexcept {
            return completed.load(std::memory_order_acquire);
        }

        void MarkCompleted(const Status& status) noexcept {
            result = status;
            completed.store(true, std::memory_order_release);
        }

        // P1-1.2: 判断是否是最后一个 Shard
        bool IsLastShard() const noexcept {
            return currentShard == totalShards - 1;
        }
    };

    TaskIdSet* failureSet_;
    const SpaceLayout* layout_;
    size_t ioSize_;
    size_t shardSize_;
    size_t nShardPerBlock_;
    bool ioDirect_;

public:
    /**
     * 初始化传输队列
     */
    Status Setup(const Config& config, TaskIdSet* failureSet, const SpaceLayout* layout);

    /**
     * 将任务推入队列
     */
    void Push(TaskPtr task, WaiterPtr waiter);

private:
    /**
     * P1-1.1: 任务拆分 - 将 TransTask 拆分为多个 ExtendedIoUnit
     *
     * 每个 Shard 对应一个 IoUnit，包含:
     * - BlockId 标识
     * - Shard 索引
     * - 源/目标地址
     * - 文件偏移
     * - I/O 大小
     */
    std::vector<std::unique_ptr<ExtendedIoUnit>> SplitTask(const TransTask& task);

    /**
     * P1-1.2: 提交文件 - 当所有 Shard 写入完成后
     *
     * 将临时文件重命名为正式文件 (原子操作)
     */
    Status CommitFile(const Detail::BlockId& blockId);

    /**
     * Host to Storage - 将数据写入磁盘 (Dump)
     */
    Status H2S(ExtendedIoUnit& ios);

    /**
     * Storage to Host - 从磁盘读取数据 (Load)
     */
    Status S2H(ExtendedIoUnit& ios);
};

}  // namespace UC::LustreStore

#endif
