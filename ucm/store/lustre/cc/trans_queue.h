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
 * 未来将支持Lustre条带化并行I/O优化
 */
class TransQueue {
    using TaskIdSet = HashSet<Detail::TaskHandle>;
    using TaskPtr = std::shared_ptr<TransTask>;
    using WaiterPtr = std::shared_ptr<Latch>;

private:
    struct IoUnit {
        Detail::TaskHandle owner;
        TransTask::Type type;
        Detail::Shard shard;
        std::shared_ptr<Latch> waiter;
        bool firstIo{false};
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
     * Host to Storage - 将数据写入磁盘 (Dump)
     */
    Status H2S(IoUnit& ios);

    /**
     * Storage to Host - 从磁盘读取数据 (Load)
     */
    Status S2H(IoUnit& ios);
};

}  // namespace UC::LustreStore

#endif
