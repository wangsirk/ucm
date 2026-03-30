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
 * */
#include "trans_queue.h"
#include "logger/logger.h"
#include "posix_file.h"

/*
TransQueue是PosixStore的核心I/O执行组件，负责将数据传输任务(load/dump)拆分为I/O单元并发执行
*/
namespace UC::PosixStore {

/*
初始化传输队列，配置参数并启动线程池
*/

/*
config 全局配置
failureSet 失败任务ID集合指针，Worker执行失败时将任务ID加入该集合
layout 空间布局指针，用于生成数据文件路径
*/
Status TransQueue::Setup(const Config& config, TaskIdSet* failureSet, const SpaceLayout* layout)
{
    failureSet_ = failureSet;                               // 保存失败集合指针
    layout_ = layout;                                       // 保存布局指针
    ioSize_ = config.tensorSize;                            // 单个tensor的I/O大小
    shardSize_ = config.shardSize;                          // 单个分片大小
    nShardPerBlock_ = config.blockSize / config.shardSize;  // 每个block的shard数量
    ioDirect_ = config.ioDirect;                            // 是否使用直接I/O
    // 启动线程池
    auto success = pool_.SetNWorker(config.dataTransConcurrency)
                       .SetWorkerFn([this](auto& ios, auto&) { Worker(ios); })
                       .Run();
    if (!success) [[unlikely]] {
        return Status::Error(fmt::format("workers({}) start failed", config.dataTransConcurrency));
    }
    return Status::OK();
}

/*
将传输任务拆分为多个IoUnit并推入线程池队列
*/
void TransQueue::Push(TaskPtr task, WaiterPtr waiter)
{
    waiter->Set(task->desc.size());     // 设置等待计数 = shard数量
    std::list<IoUnit> ios;
    /*
    遍历任务中的每个shard，创建IoUnit并添加到列表中

    task->id 任务ID
    task->type 任务类型（LOAD或DUMP）
    shard 具体的分片信息，包括所属block、分片索引和数据地址列表
    waiter 任务完成等待器，Worker执行完成后调用Done()通知
    */
    for (auto&& shard : task->desc) {
        ios.emplace_back<IoUnit>({task->id, task->type, std::move(shard), waiter});
    }
    /* 标记第一个 */
    ios.front().firstIo = true;
    /* 推入线程池 */
    pool_.Push(ios);
}

/* 线程池工作函数，处理单个IoUnit的I/O操作 */
void TransQueue::Worker(IoUnit& ios)
{   
    /* 记录等待时间，仅第一个IoUnit */
    if (ios.firstIo) {
        auto wait = NowTime::Now() - ios.waiter->startTp;
        UC_DEBUG("Posix task({}) start running, wait {:.3f}ms.", ios.owner, wait * 1e3);
    }

    /* 快速失败检查 */
    if (failureSet_->Contains(ios.owner)) {
        ios.waiter->Done();         // 任务已失败，直接完成
        return;
    }

    /* 执行I/O操作 */
    auto s = Status::OK();
    if (ios.type == TransTask::Type::DUMP) {
        s = H2S(ios);   // 写入
        if (ios.shard.index + 1 == nShardPerBlock_) {
            // 最后一个shard负责提交文件
            layout_->CommitFile(ios.shard.owner, s.Success());
        }
    } else {
        s = S2H(ios);  // 读取文件
    }
    /* 失败处理 */
    if (s.Failure()) [[unlikely]] { failureSet_->Insert(ios.owner); } // 标记任务失败

    /* 完成计数 */
    ios.waiter->Done();
}

/*
H2S：Host to Storage，将数据写入磁盘

ios：I/O单元
返回值: status 操作状态

这部分还需要再仔细看下
*/
Status TransQueue::H2S(IoUnit& ios)
{   
    // 获取临时文件路径
    const auto& path = layout_->DataFilePath(ios.shard.owner, true);
    PosixFile file{path};
    // 打开文件
    auto flags = PosixFile::OpenFlag::CREATE | PosixFile::OpenFlag::WRITE_ONLY;
    if (ioDirect_) { flags |= PosixFile::OpenFlag::DIRECT; }
    auto s = file.Open(flags);
    if (s.Failure()) [[unlikely]] {
        UC_ERROR("Failed({}) to open file({}) with flags({}).", s, path, flags);
        return s;
    }

    // 按offset写入
    auto offset = shardSize_ * ios.shard.index;
    for (const auto& addr : ios.shard.addrs) {
        s = file.Write(addr, ioSize_, offset);
        if (s.Failure()) [[unlikely]] {
            UC_ERROR("Failed({}) to write file({}:{}).", s, path, offset);
            return s;
        }
        offset += ioSize_;
    }
    return Status::OK();
}

/* 将数据从存储（磁盘）读取到主机内存 */
Status TransQueue::S2H(IoUnit& ios)
{   
    // 获取文件路径
    const auto& path = layout_->DataFilePath(ios.shard.owner, false);
    PosixFile file{path};

    // 打开文件
    auto flags = PosixFile::OpenFlag::READ_ONLY;
    if (ioDirect_) { flags |= PosixFile::OpenFlag::DIRECT; }
    auto s = file.Open(flags);
    if (s.Failure()) [[unlikely]] {
        UC_ERROR("Failed({}) to open file({}) with flags({}).", s, path, flags);
        return s;
    }

    // 按照offset进行读取
    auto offset = shardSize_ * ios.shard.index;
    for (const auto& addr : ios.shard.addrs) {
        s = file.Read(addr, ioSize_, offset);
        if (s.Failure()) [[unlikely]] {
            UC_ERROR("Failed({}) to read file({}:{}).", s, path, offset);
            return s;
        }
        offset += ioSize_;
    }
    return Status::OK();
}

}  // namespace UC::PosixStore
