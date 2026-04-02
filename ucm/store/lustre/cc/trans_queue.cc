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
#include "lustre_file.h"
#include "fcntl.h"
#include <unistd.h>
#include <unordered_map>

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

// ============================================================================
// P1-1.1: 任务拆分实现
// ============================================================================

std::vector<std::unique_ptr<TransQueue::ExtendedIoUnit>>
TransQueue::SplitTask(const TransTask& task)
{
    UC_INFO("LustreTransQueue::SplitTask - Splitting task, id={}, type={}, shards={}",
            task.id, static_cast<int>(task.type), task.desc.size());

    std::vector<std::unique_ptr<ExtendedIoUnit>> units;
    units.reserve(task.desc.size());

    // P1-1.2: 首先按 BlockId 分组，计算每个 Block 的 Shard 数量
    std::unordered_map<Detail::BlockId, size_t, Detail::BlockIdHasher> blockShardCount;
    for (const auto& shard : task.desc) {
        blockShardCount[shard.owner]++;
    }

    // 为每个 Shard 创建一个 IoUnit
    for (size_t i = 0; i < task.desc.size(); ++i) {
        const auto& shard = task.desc[i];

        // P1-1.2: 获取该 Block 的总 Shard 数和当前 Shard 的序号
        size_t totalShards = blockShardCount[shard.owner];
        // 计算当前是第几个 shard (按出现顺序)
        size_t currentShard = 0;
        for (size_t j = 0; j < i; ++j) {
            if (task.desc[j].owner == shard.owner) {
                currentShard++;
            }
        }

        // 计算文件内偏移量
        // 使用 currentShard 而不是 shard.index，因为每个 block 有独立文件
        size_t fileOffset = currentShard * shardSize_;

        // 确定源地址和目标地址
        void* srcAddr = nullptr;
        void* dstAddr = nullptr;

        if (task.type == TransTask::Type::DUMP) {
            // Dump: Device -> Storage
            // shard.addrs 包含设备侧地址
            if (!shard.addrs.empty()) {
                srcAddr = shard.addrs[0];  // 使用第一个地址
            }
            // dstAddr 留空，由文件系统处理
        } else {
            // Load: Storage -> Device
            // srcAddr 留空，由文件系统处理
            if (!shard.addrs.empty()) {
                dstAddr = shard.addrs[0];  // 使用第一个地址
            }
        }

        // 创建 IoUnit
        auto ioUnit = std::make_unique<ExtendedIoUnit>(
            shard.owner,           // BlockId
            shard.index,          // ShardIndex
            srcAddr,              // 源地址
            dstAddr,              // 目标地址
            fileOffset,           // 文件偏移
            ioSize_,              // I/O 大小
            task.id,              // TaskHandle
            task.type,            // TaskType
            nullptr,              // Waiter (稍后设置)
            totalShards,          // P1-1.2: 总 Shard 数
            currentShard          // P1-1.2: 当前 Shard 序号
        );

        units.push_back(std::move(ioUnit));
    }

    // 标记第一个 I/O
    if (!units.empty()) {
        units[0]->firstIo = true;
    }

    UC_INFO("LustreTransQueue::SplitTask - Split into {} units", units.size());
    return units;
}

// ============================================================================
// Push 方法实现
// ============================================================================

void TransQueue::Push(TaskPtr task, WaiterPtr waiter)
{
    UC_INFO("LustreTransQueue::Push - Pushing task, id={}, type={}",
            task->id, static_cast<int>(task->type));

    // P1-1.1: 任务拆分
    auto units = SplitTask(*task);

    // 设置 Latch 计数 (需要等待的 IoUnit 数量)
    waiter->Set(units.size());

    // 执行每个 IoUnit
    for (auto& unit : units) {
        unit->waiter = waiter;
        // TODO: 实际推入线程池执行
        // pool_.Push(std::move(unit));
        // 暂时直接执行 (P1-1 阶段)
        if (task->type == TransTask::Type::DUMP) {
            H2S(*unit);
        } else {
            S2H(*unit);
        }
    }
}

// ============================================================================
// CommitFile 实现
// ============================================================================

Status TransQueue::CommitFile(const Detail::BlockId& blockId)
{
    UC_INFO("LustreTransQueue::CommitFile - Committing block: [{}]", blockId[0]);

    // 使用 SpaceLayout 的 CommitFile 方法
    return layout_->CommitFile(blockId, true);
}

// ============================================================================
// H2S (Dump) 实现
// ============================================================================

Status TransQueue::H2S(TransQueue::ExtendedIoUnit& ios)
{
    // 1. 生成临时文件路径
    std::string tmpPath = layout_->DataFilePath(ios.blockId, true);

    // 2. 打开或创建临时文件
    LustreFile file(tmpPath);

    // 检查文件是否已存在 (追加模式)
    if (LustreFile::Exists(tmpPath)) {
        UC_DEBUG("LustreTransQueue::H2S - Temp file exists, opening for append");
        Status status = file.Open(O_WRONLY | O_APPEND);
        if (status.Failure()) {
            UC_ERROR("LustreTransQueue::H2S - Failed to open temp file: {}", status.ToString());
            if (ios.waiter) { ios.waiter->Done(); }
            return status;
        }
    } else {
        // 创建父目录
        size_t lastSlash = tmpPath.find_last_of('/');
        if (lastSlash != std::string::npos) {
            std::string dir = tmpPath.substr(0, lastSlash);
            Status dirStatus = LustreFile::MkDir(dir, 0755);
            // 目录已存在不算错误，继续执行
            if (dirStatus.Failure()) {
                UC_WARN("LustreTransQueue::H2S - Failed to create directory: {}", dirStatus.ToString());
            }
        }

        // 创建新文件
        Status status = file.CreateNormal(O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (status.Failure()) {
            UC_ERROR("LustreTransQueue::H2S - Failed to create temp file: {}", status.ToString());
            if (ios.waiter) { ios.waiter->Done(); }
            return status;
        }
    }

    // 3. 写入数据 (使用 pwrite 支持并发写入不同偏移)
    if (ios.srcAddr != nullptr && ios.ioSize > 0) {
        Status status = file.Write(ios.srcAddr, ios.ioSize, ios.fileOffset);
        if (status.Failure()) {
            UC_ERROR("LustreTransQueue::H2S - Write failed: {}", status.ToString());
            file.Close();
            LustreFile::Remove(tmpPath);  // 清理失败的临时文件
            // 通知 waiter 任务失败
            if (ios.waiter) { ios.waiter->Done(); }
            return status;
        }
    } else {
        UC_WARN("LustreTransQueue::H2S - Skipping write: srcAddr={}, ioSize={}",
                fmt::ptr(ios.srcAddr), ios.ioSize);
    }

    // 4. P1-1.2: 如果是最后一个 Shard，提交文件
    if (ios.IsLastShard()) {
        Status commitStatus = CommitFile(ios.blockId);
        if (commitStatus.Failure()) {
            UC_ERROR("LustreTransQueue::H2S - Commit failed: {}", commitStatus.ToString());
            if (ios.waiter) { ios.waiter->Done(); }
            return commitStatus;
        }
    }

    UC_DEBUG("LustreTransQueue::H2S - Shard {}/{} write completed",
             ios.currentShard, ios.totalShards);

    // 标记完成
    ios.MarkCompleted(Status::OK());

    // 通知 waiter 完成
    if (ios.waiter) {
        UC_INFO("LustreTransQueue::H2S - Calling waiter->Done()");
        ios.waiter->Done();
        UC_INFO("LustreTransQueue::H2S - waiter->Done() returned");
    } else {
        UC_INFO("LustreTransQueue::H2S - waiter is null, skipping Done()");
    }

    UC_INFO("LustreTransQueue::H2S - EXIT, returning OK");
    return Status::OK();
}

Status TransQueue::S2H(TransQueue::ExtendedIoUnit& ios)
{
    UC_INFO("LustreTransQueue::S2H - Storage to Host (Load), owner={}, shard={}",
            ios.owner, ios.shardIndex);

    // P1-1.3: 实现数据读取逻辑

    // 1. 生成正式文件路径 (非临时文件)
    std::string finalPath = layout_->DataFilePath(ios.blockId, false);
    UC_DEBUG("LustreTransQueue::S2H - Final file path: {}", finalPath);

    // 2. 检查文件是否存在
    if (!LustreFile::Exists(finalPath)) {
        UC_ERROR("LustreTransQueue::S2H - File does not exist: {}", finalPath);
        if (ios.waiter) { ios.waiter->Done(); }
        failureSet_->Insert(ios.owner);  // 错误传播: 标记任务失败
        return Status::NotFound();
    }

    // 3. 打开文件读取
    LustreFile file(finalPath);
    Status status = file.Open(O_RDONLY);
    if (status.Failure()) {
        UC_ERROR("LustreTransQueue::S2H - Failed to open file: {}", status.ToString());
        if (ios.waiter) { ios.waiter->Done(); }
        failureSet_->Insert(ios.owner);  // 错误传播: 标记任务失败
        return status;
    }

    // 4. 读取数据 (使用 pread 支持并发读取不同偏移)
    if (ios.dstAddr != nullptr && ios.ioSize > 0) {
        status = file.Read(ios.dstAddr, ios.ioSize, ios.fileOffset);
        if (status.Failure()) {
            UC_ERROR("LustreTransQueue::S2H - Read failed: {}", status.ToString());
            file.Close();
            if (ios.waiter) { ios.waiter->Done(); }
            failureSet_->Insert(ios.owner);  // 错误传播: 标记任务失败
            return status;
        }
    }

    UC_DEBUG("LustreTransQueue::S2H - Shard {} read completed", ios.shardIndex);

    // 标记完成
    ios.MarkCompleted(Status::OK());

    // 通知 waiter 完成 (关键: 避免 Wait 永久阻塞)
    if (ios.waiter) {
        UC_INFO("LustreTransQueue::S2H - Calling waiter->Done()");
        ios.waiter->Done();
        UC_INFO("LustreTransQueue::S2H - waiter->Done() returned");
    } else {
        UC_INFO("LustreTransQueue::S2H - waiter is null, skipping Done()");
    }

    return Status::OK();
}

}  // namespace UC::LustreStore
