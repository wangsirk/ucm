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
#include <mutex>
#include <condition_variable>
#include "global_config.h"
#include "space_layout.h"
#include "template/hashset.h"
#include "thread/latch.h"
#include "thread/thread_pool.h"
#include "trans_task.h"
#include "async_io.h"  // P2: 异步 I/O 支持
#include "lustre_file.h"  // 需要 LustreFile 定义

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
    struct ExtendedIoUnit : public std::enable_shared_from_this<ExtendedIoUnit> {
        // ===== IoUnit 核心字段 =====
        Detail::BlockId blockId;
        size_t shardIndex;
        std::vector<void*> srcAddrs;   // 修复: 保存所有地址 (与 PosixStore 保持一致)
        std::vector<void*> dstAddrs;   // 修复: 保存所有地址 (与 PosixStore 保持一致)
        void* srcAddr{nullptr};        // 兼容旧代码 (第一个地址)
        void* dstAddr{nullptr};        // 兼容旧代码 (第一个地址)
        size_t fileOffset{0};
        size_t ioSize{0};
        std::atomic<bool> completed{false};
        Status result{Status::OK()};

        // ===== TransQueue 特有字段 =====
        Detail::TaskHandle owner;        // 所属任务 ID
        TransTask::Type type;            // 任务类型
        std::shared_ptr<Latch> waiter;    // 完成通知

        // ===== P1-1.2: Shard 跟踪字段 =====
        size_t totalShards{1};           // Block 的总 Shard 数
        size_t currentShard{0};          // 当前 Shard 索引 (0-based)

        // ===== 事件驱动同步机制 (修复 P0 轮询 CPU 浪费问题) =====
        mutable std::mutex cvMutex;      // 保护条件变量的互斥锁
        mutable std::condition_variable cv;  // 完成事件通知

        ExtendedIoUnit() = default;

        // 便捷构造函数
        ExtendedIoUnit(const Detail::BlockId& bid, size_t sidx,
                       const std::vector<void*>& srcs, const std::vector<void*>& dsts,
                       size_t offset, size_t size,
                       Detail::TaskHandle ownerId, TransTask::Type t,
                       std::shared_ptr<Latch> w, size_t totalShards = 1, size_t currentShard = 0)
            : blockId(bid), shardIndex(sidx), srcAddrs(srcs), dstAddrs(dsts),
              srcAddr(srcs.empty() ? nullptr : srcs[0]),
              dstAddr(dsts.empty() ? nullptr : dsts[0]),
              fileOffset(offset), ioSize(size), owner(ownerId), type(t), waiter(w),
              totalShards(totalShards), currentShard(currentShard) {}

        // 状态管理方法
        bool IsCompleted() const noexcept {
            return completed.load(std::memory_order_acquire);
        }

        void MarkCompleted(const Status& status) noexcept {
            result = status;
            completed.store(true, std::memory_order_release);
            // 通知等待线程
            cv.notify_all();
        }

        // 事件驱动的等待方法 (替代轮询)
        bool WaitForCompletion(int timeoutMs = -1) const {
            std::unique_lock<std::mutex> lock(cvMutex);
            if (timeoutMs < 0) {
                // 无限等待
                cv.wait(lock, [this] { return IsCompleted(); });
                return true;
            } else {
                // 超时等待
                return cv.wait_for(lock, std::chrono::milliseconds(timeoutMs),
                    [this] { return IsCompleted(); });
            }
        }

        // P1-1.2: 判断是否是最后一个 Shard (基于 shardIndex，与 PosixStore 保持一致)
        bool IsLastShardByIndex(size_t nShardPerBlock) const noexcept {
            return (shardIndex + 1) == nShardPerBlock;
        }

        // 创建 weak_ptr 用于回调捕获 (修复循环引用问题)
        std::weak_ptr<ExtendedIoUnit> WeakPtr() {
            return shared_from_this();
        }
    };

    TaskIdSet* failureSet_;
    const SpaceLayout* layout_;
    size_t ioSize_;
    size_t shardSize_;
    size_t nShardPerBlock_;
    bool ioDirect_;

    // P3: 条带化配置
    size_t stripeCount_{0};
    size_t stripeSize_{0};

    // P2: 异步 I/O 支持
    std::unique_ptr<AsyncIOAdapter> asyncIo_;
    bool enableAsyncIo_{false};

    // 数据传输线程池
    ThreadPool<std::shared_ptr<ExtendedIoUnit>> pool_;

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
    std::vector<std::shared_ptr<ExtendedIoUnit>> SplitTask(const TransTask& task);

    /**
     * 线程池工作函数 - 处理单个 IoUnit 的 I/O 操作
     */
    void Worker(const std::shared_ptr<ExtendedIoUnit>& ios);

    /**
     * P1-1.2: 提交文件 - 当所有 Shard 写入完成后
     *
     * 将临时文件重命名为正式文件 (原子操作)
     */
    Status CommitFile(const Detail::BlockId& blockId);

    /**
     * Host to Storage - 将数据写入磁盘 (Dump)
     */
    Status H2S(const std::shared_ptr<ExtendedIoUnit>& ios);

    /**
     * P2: 同步 H2S 实现
     */
    Status H2SSync(const std::shared_ptr<ExtendedIoUnit>& ios, const std::string& tmpPath, LustreFile& file);

    /**
     * P2: 异步 H2S 实现
     */
    Status H2SAsync(const std::shared_ptr<ExtendedIoUnit>& ios,
                    const std::string& tmpPath,
                    const std::shared_ptr<LustreFile>& file);

    /**
     * Storage to Host - 从磁盘读取数据 (Load)
     */
    Status S2H(const std::shared_ptr<ExtendedIoUnit>& ios);

    /**
     * P2: 同步 S2H 实现
     */
    Status S2HSync(const std::shared_ptr<ExtendedIoUnit>& ios, const std::string& finalPath, LustreFile& file);

    /**
     * P2: 异步 S2H 实现
     */
    Status S2HAsync(const std::shared_ptr<ExtendedIoUnit>& ios,
                    const std::string& finalPath,
                    const std::shared_ptr<LustreFile>& file);
};

}  // namespace UC::LustreStore

#endif
