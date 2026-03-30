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
#ifndef UNIFIEDCACHE_LUSTRE_STORE_CC_TRANS_MANAGER_H
#define UNIFIEDCACHE_LUSTRE_STORE_CC_TRANS_MANAGER_H

#include "logger/logger.h"
#include "template/task_wrapper.h"
#include "trans_queue.h"

/**
 * TransManager - Lustre传输任务管理器
 * 
 * 继承自TaskWrapper模板类，管理传输任务的生命周期
 * 未来将支持Lustre特有的条带化任务调度
 */

namespace UC::LustreStore {

class TransManager : public Detail::TaskWrapper<TransTask, Detail::TaskHandle> {
    TransQueue queue_;
    size_t shardSize_;

public:
    /**
     * 初始化传输管理器
     */
    Status Setup(const Config& config, const SpaceLayout* layout)
    {
        UC_INFO("LustreTransManager::Setup - Initializing trans manager");
        timeoutMs_ = config.timeoutMs;
        shardSize_ = config.shardSize;
        UC_INFO("LustreTransManager::Setup - Timeout: {}ms, shard size: {}", timeoutMs_, shardSize_);
        return queue_.Setup(config, &failureSet_, layout);
    }

protected:
    /**
     * 将任务分发到队列
     */
    void Dispatch(TaskPtr t, WaiterPtr w) override
    {
        const auto id = t->id;
        const auto& brief = t->desc.brief;
        const auto num = t->desc.size();
        const auto size = shardSize_ * num;
        
        UC_INFO("LustreTransManager::Dispatch - Task dispatching, id={}, brief={}, num={}, size={}", 
                id, brief, num, size);
        
        // TODO: 设置回调并推入队列
        // w->SetEpilog([id, brief, num, size] { ... });
        // queue_.Push(t, w);
    }
};

}  // namespace UC::LustreStore

#endif
