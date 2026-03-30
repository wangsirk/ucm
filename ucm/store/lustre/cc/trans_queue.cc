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
#include "trans_queue.h"
#include "logger/logger.h"

namespace UC::LustreStore {

Status TransQueue::Setup(const Config& config, TaskIdSet* failureSet, const SpaceLayout* layout)
{
    UC_INFO("LustreTransQueue::Setup - Initializing trans queue");
    UC_INFO("LustreTransQueue::Setup - IO size: {}, shard size: {}", config.tensorSize, config.shardSize);
    UC_INFO("LustreTransQueue::Setup - IO direct: {}, concurrency: {}", config.ioDirect, config.dataTransConcurrency);
    
    failureSet_ = failureSet;
    layout_ = layout;
    ioSize_ = config.tensorSize;
    shardSize_ = config.shardSize;
    nShardPerBlock_ = config.blockSize / config.shardSize;
    ioDirect_ = config.ioDirect;
    
    // TODO: 启动线程池
    // auto success = pool_.SetNWorker(config.dataTransConcurrency)
    //                    .SetWorkerFn([this](auto& ios, auto&) { Worker(ios); })
    //                    .Run();
    
    UC_INFO("LustreTransQueue::Setup - Trans queue initialized successfully");
    return Status::OK();
}

void TransQueue::Push(TaskPtr task, WaiterPtr waiter)
{
    UC_INFO("LustreTransQueue::Push - Pushing task, id={}, type={}", 
            task->id, static_cast<int>(task->type));
    
    // TODO: 实现任务拆分和推入队列
    // waiter->Set(task->desc.size());
    // std::list<IoUnit> ios;
    // for (auto&& shard : task->desc) {
    //     ios.emplace_back<IoUnit>({task->id, task->type, std::move(shard), waiter});
    // }
    // ios.front().firstIo = true;
    // pool_.Push(ios);
}

Status TransQueue::H2S(IoUnit& ios)
{
    UC_INFO("LustreTransQueue::H2S - Host to Storage (Dump), owner={}", ios.owner);
    
    // TODO: 实现数据写入逻辑
    // const auto& path = layout_->DataFilePath(ios.shard.owner, true);
    // LustreFile file{path};
    // auto flags = LustreFile::OpenFlag::CREATE | LustreFile::OpenFlag::WRITE_ONLY;
    // if (ioDirect_) { flags |= LustreFile::OpenFlag::DIRECT; }
    // auto s = file.Open(flags);
    // auto offset = shardSize_ * ios.shard.index;
    // for (const auto& addr : ios.shard.addrs) {
    //     file.Write(addr, ioSize_, offset);
    //     offset += ioSize_;
    // }
    
    return Status::OK();
}

Status TransQueue::S2H(IoUnit& ios)
{
    UC_INFO("LustreTransQueue::S2H - Storage to Host (Load), owner={}", ios.owner);
    
    // TODO: 实现数据读取逻辑
    // const auto& path = layout_->DataFilePath(ios.shard.owner, false);
    // LustreFile file{path};
    // auto flags = LustreFile::OpenFlag::READ_ONLY;
    // if (ioDirect_) { flags |= LustreFile::OpenFlag::DIRECT; }
    // auto s = file.Open(flags);
    // auto offset = shardSize_ * ios.shard.index;
    // for (const auto& addr : ios.shard.addrs) {
    //     file.Read(addr, ioSize_, offset);
    //     offset += ioSize_;
    // }
    
    return Status::OK();
}

}  // namespace UC::LustreStore
