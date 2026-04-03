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
#include <cstring>

namespace UC::LustreStore {

Status TransQueue::Setup(const Config& config, TaskIdSet* failureSet, const SpaceLayout* layout)
{
    UC_INFO("LustreTransQueue::Setup - Initializing trans queue");
    UC_INFO("LustreTransQueue::Setup - IO size: {}, shard size: {}", config.tensorSize, config.shardSize);
    UC_INFO("LustreTransQueue::Setup - IO direct: {}, concurrency: {}", config.ioDirect, config.dataTransConcurrency);
    UC_INFO("LustreTransQueue::Setup - Async I/O: {}, backend: {}", config.enableAsyncIo, config.asyncIoBackend);
    UC_INFO("LustreTransQueue::Setup - Stripe count: {}, stripe size: {}", config.stripeCount, config.stripeSize);

    failureSet_ = failureSet;
    layout_ = layout;
    ioSize_ = config.tensorSize;
    shardSize_ = config.shardSize;
    nShardPerBlock_ = config.blockSize / config.shardSize;
    ioDirect_ = config.ioDirect;

    // P3: 条带化配置
    stripeCount_ = config.stripeCount;
    stripeSize_ = config.stripeSize;

    // P2: 初始化异步 I/O 后端
    enableAsyncIo_ = config.enableAsyncIo;
    if (enableAsyncIo_) {
        asyncIo_ = AsyncIOAdapter::Create(config.asyncIoBackend);
        Status s = asyncIo_->Setup(config.asyncIoQueueDepth, config.dataTransCpuCores);
        if (s.Failure()) {
            UC_WARN("Failed to initialize async I/O ({}), falling back to sync I/O", s.ToString());
            enableAsyncIo_ = false;
            asyncIo_.reset();
        } else {
            UC_INFO("LustreTransQueue::Setup - Async I/O initialized (queue depth: {})",
                    config.asyncIoQueueDepth);
        }
    }

    UC_INFO("LustreTransQueue::Setup - Trans queue initialized successfully");
    return Status::OK();
}

// ============================================================================
// P1-1.1: 任务拆分实现
// ============================================================================

std::vector<std::shared_ptr<TransQueue::ExtendedIoUnit>>
TransQueue::SplitTask(const TransTask& task)
{
    UC_INFO("LustreTransQueue::SplitTask - Splitting task, id={}, type={}, shards={}",
            task.id, static_cast<int>(task.type), task.desc.size());

    std::vector<std::shared_ptr<ExtendedIoUnit>> units;
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

        // 创建 IoUnit (使用 shared_ptr 以支持异步回调的生命周期管理)
        auto ioUnit = std::make_shared<ExtendedIoUnit>(
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

        units.push_back(ioUnit);
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
            H2S(unit);
        } else {
            S2H(unit);
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
// H2S (Dump) 实现 - P2 支持异步 I/O
// ============================================================================

Status TransQueue::H2S(const std::shared_ptr<ExtendedIoUnit>& ios)
{
    // 1. 生成临时文件路径
    std::string tmpPath = layout_->DataFilePath(ios->blockId, true);

    // 2. 打开或创建临时文件 - 使用 shared_ptr 管理生命周期
    auto file = std::make_shared<LustreFile>(tmpPath);

    // 检查文件是否已存在 (追加模式)
    if (LustreFile::Exists(tmpPath)) {
        UC_DEBUG("LustreTransQueue::H2S - Temp file exists, opening for append");
        Status status = file->Open(O_WRONLY | O_APPEND);
        if (status.Failure()) {
            UC_ERROR("LustreTransQueue::H2S - Failed to open temp file: {}", status.ToString());
            if (ios->waiter) { ios->waiter->Done(); }
            return status;
        }
    } else {
        // 创建父目录
        size_t lastSlash = tmpPath.find_last_of('/');
        if (lastSlash != std::string::npos) {
            std::string dir = tmpPath.substr(0, lastSlash);
            Status dirStatus = LustreFile::MkDir(dir, 0755);
            if (dirStatus.Failure()) {
                UC_WARN("LustreTransQueue::H2S - Failed to create directory: {}", dirStatus.ToString());
            }
        }

        // P3: 根据条带配置选择文件创建方式
        Status status = Status::OK();
        if (stripeCount_ > 0) {
            // 使用条带化文件创建
            UC_DEBUG("LustreTransQueue::H2S - Creating striped file (count={}, size={})",
                     stripeCount_, stripeSize_);
            status = file->CreateStriped(static_cast<int>(stripeCount_), stripeSize_, 0644);
        } else {
            // 使用普通文件创建
            status = file->CreateNormal(O_WRONLY | O_CREAT | O_TRUNC, 0644);
        }

        if (status.Failure()) {
            UC_ERROR("LustreTransQueue::H2S - Failed to create temp file: {}", status.ToString());
            if (ios->waiter) { ios->waiter->Done(); }
            return status;
        }
    }

    // 3. 写入数据 (同步或异步)
    if (ios->srcAddr != nullptr && ios->ioSize > 0) {
        if (enableAsyncIo_ && asyncIo_) {
            // P2: 异步 I/O 路径 - 传递 shared_ptr 保持文件打开状态
            return H2SAsync(ios, tmpPath, file);
        } else {
            // 同步 I/O 路径
            return H2SSync(ios, tmpPath, *file);
        }
    } else {
        UC_WARN("LustreTransQueue::H2S - Skipping write: srcAddr={}, ioSize={}",
                fmt::ptr(ios->srcAddr), ios->ioSize);
        // 标记完成并通知 waiter
        ios->MarkCompleted(Status::OK());
        if (ios->waiter) { ios->waiter->Done(); }
        return Status::OK();
    }
}

// P2: 同步 H2S 实现 (保持原有逻辑)
Status TransQueue::H2SSync(const std::shared_ptr<ExtendedIoUnit>& ios, const std::string& tmpPath, LustreFile& file)
{
    // 写入数据 (使用 pwrite 支持并发写入不同偏移)
    Status status = file.Write(ios->srcAddr, ios->ioSize, ios->fileOffset);
    if (status.Failure()) {
        UC_ERROR("LustreTransQueue::H2SSync - Write failed: {}", status.ToString());
        file.Close();
        LustreFile::Remove(tmpPath);
        if (ios->waiter) { ios->waiter->Done(); }
        return status;
    }

    // 如果是最后一个 Shard，提交文件
    if (ios->IsLastShard()) {
        // 确保数据写入磁盘后再提交
        Status syncStatus = file.Sync();
        if (syncStatus.Failure()) {
            UC_ERROR("LustreTransQueue::H2SSync - Sync failed: {}", syncStatus.ToString());
            if (ios->waiter) { ios->waiter->Done(); }
            return syncStatus;
        }

        Status commitStatus = CommitFile(ios->blockId);
        if (commitStatus.Failure()) {
            UC_ERROR("LustreTransQueue::H2SSync - Commit failed: {}", commitStatus.ToString());
            if (ios->waiter) { ios->waiter->Done(); }
            return commitStatus;
        }
    }

    UC_DEBUG("LustreTransQueue::H2SSync - Shard {}/{} write completed",
             ios->currentShard, ios->totalShards);

    ios->MarkCompleted(Status::OK());
    if (ios->waiter) { ios->waiter->Done(); }

    return Status::OK();
}

// P2: 异步 H2S 实现
Status TransQueue::H2SAsync(const std::shared_ptr<ExtendedIoUnit>& ios,
                             const std::string& tmpPath,
                             const std::shared_ptr<LustreFile>& file)
{
    // 提交异步写请求
    // 修复 C1/C3: 捕获必要的值和 shared_ptr 确保生命周期安全
    int fd = file->GetFd();
    std::weak_ptr<ExtendedIoUnit> weakIos = ios->WeakPtr();

    // 捕获必要的数据值，避免访问可能被销毁的对象成员
    Detail::BlockId blockId = ios->blockId;
    size_t currentShard = ios->currentShard;
    size_t totalShards = ios->totalShards;

    IoRequest req(
        fd,
        ios->srcAddr,
        ios->ioSize,
        static_cast<off64_t>(ios->fileOffset),
        true,  // isWrite
        [this, weakIos, tmpPath, blockId, currentShard, totalShards, file](IoRequest::Result result, ssize_t bytesTransferred) {
            // 尝试获取 shared_ptr，如果对象已被销毁则跳过
            auto ios = weakIos.lock();
            if (!ios) {
                UC_WARN("LustreTransQueue::H2SAsync - IoUnit already destroyed, skipping callback");
                return;
            }

            if (result == IoRequest::Result::FAILURE) {
                UC_ERROR("LustreTransQueue::H2SAsync - Async write failed");
                LustreFile::Remove(tmpPath);
                ios->MarkCompleted(Status::OsApiError("Async write failed"));
                if (ios->waiter) { ios->waiter->Done(); }
                return;
            }

            // 写入成功，如果是最后一个 Shard，提交文件
            if (currentShard == totalShards - 1) {
                Status commitStatus = CommitFile(blockId);
                // 幂等操作：DuplicateKey 表示其他 shard 已提交，应视为成功
                if (!commitStatus.IsSuccessOrDuplicate()) {
                    UC_ERROR("LustreTransQueue::H2SAsync - Commit failed: {}", commitStatus.ToString());
                    ios->MarkCompleted(commitStatus);
                    if (ios->waiter) { ios->waiter->Done(); }
                    return;
                }
                if (commitStatus.IsDuplicate()) {
                    UC_INFO("LustreTransQueue::H2SAsync - Commit: file already exists (concurrent commit)");
                }
            }

            UC_DEBUG("LustreTransQueue::H2SAsync - Shard {}/{} async write completed",
                     currentShard, totalShards);

            ios->MarkCompleted(Status::OK());
            if (ios->waiter) { ios->waiter->Done(); }
        }
    );

    Status s = asyncIo_->SubmitWrite(req);
    if (s.Failure()) {
        // 回退到同步 I/O（确保文件正确关闭）
        UC_WARN("Async submit failed, falling back to sync I/O: {}", s.ToString());
        LustreFile fallbackFile(tmpPath);
        Status openStatus = fallbackFile.Open(O_WRONLY | O_APPEND);
        if (openStatus.Failure()) {
            UC_ERROR("Failed to open file in fallback mode: {}", openStatus.ToString());
            if (ios->waiter) { ios->waiter->Done(); }
            return openStatus;
        }
        // H2SSync 内部会关闭文件
        return H2SSync(ios, tmpPath, fallbackFile);
    }

    // 修复 P0: 使用事件驱动等待 + 主动检查结合，避免死锁和 CPU 浪费
    const int maxWaitMs = 5000;  // 最大等待 5 秒
    const int checkIntervalMs = 10;  // 每 10ms 检查一次完成队列
    int waitedMs = 0;

    // 先处理已有的完成事件
    asyncIo_->ProcessCompletion(0);

    // 使用条件变量等待，但定期检查完成队列
    while (!ios->IsCompleted() && waitedMs < maxWaitMs) {
        // 等待一小段时间或直到被通知
        if (!ios->WaitForCompletion(checkIntervalMs)) {
            // 超时了，主动处理一次完成队列
            asyncIo_->ProcessCompletion(0);
        }
        waitedMs += checkIntervalMs;
    }

    if (!ios->IsCompleted()) {
        UC_ERROR("LustreTransQueue::H2SAsync - Async write timeout after {}ms", waitedMs);
        if (ios->waiter) { ios->waiter->Done(); }
        return Status::OsApiError("Async write timeout");
    }

    // 检查异步操作的结果
    if (ios->result.Failure()) {
        UC_ERROR("LustreTransQueue::H2SAsync - Async write failed: {}", ios->result.ToString());
        return ios->result;
    }

    UC_DEBUG("LustreTransQueue::H2SAsync - Async write completed and verified");
    return Status::OK();
}

Status TransQueue::S2H(const std::shared_ptr<ExtendedIoUnit>& ios)
{
    UC_INFO("LustreTransQueue::S2H - Storage to Host (Load), owner={}, shard={}",
            ios->owner, ios->shardIndex);

    // 1. 生成正式文件路径 (非临时文件)
    std::string finalPath = layout_->DataFilePath(ios->blockId, false);
    UC_DEBUG("LustreTransQueue::S2H - Final file path: {}", finalPath);

    // 2. 检查文件是否存在
    if (!LustreFile::Exists(finalPath)) {
        UC_ERROR("LustreTransQueue::S2H - File does not exist: {}", finalPath);
        if (ios->waiter) { ios->waiter->Done(); }
        failureSet_->Insert(ios->owner);
        return Status::NotFound();
    }

    // 3. 打开文件读取 - 使用 shared_ptr 管理生命周期
    auto file = std::make_shared<LustreFile>(finalPath);
    Status status = file->Open(O_RDONLY);
    if (status.Failure()) {
        UC_ERROR("LustreTransQueue::S2H - Failed to open file: {}", status.ToString());
        if (ios->waiter) { ios->waiter->Done(); }
        failureSet_->Insert(ios->owner);
        return status;
    }

    // 4. 读取数据 (同步或异步)
    if (ios->dstAddr != nullptr && ios->ioSize > 0) {
        if (enableAsyncIo_ && asyncIo_) {
            // P2: 异步 I/O 路径 - 传递 shared_ptr 保持文件打开状态
            return S2HAsync(ios, finalPath, file);
        } else {
            // 同步 I/O 路径
            return S2HSync(ios, finalPath, *file);
        }
    } else {
        UC_WARN("LustreTransQueue::S2H - Skipping read: dstAddr={}, ioSize={}",
                fmt::ptr(ios->dstAddr), ios->ioSize);
        ios->MarkCompleted(Status::OK());
        if (ios->waiter) { ios->waiter->Done(); }
        return Status::OK();
    }
}

// P2: 同步 S2H 实现 (保持原有逻辑)
Status TransQueue::S2HSync(const std::shared_ptr<ExtendedIoUnit>& ios, const std::string& finalPath, LustreFile& file)
{
    // 读取数据 (使用 pread 支持并发读取不同偏移)
    Status status = file.Read(ios->dstAddr, ios->ioSize, ios->fileOffset);
    if (status.Failure()) {
        UC_ERROR("LustreTransQueue::S2HSync - Read failed: {}", status.ToString());
        file.Close();
        if (ios->waiter) { ios->waiter->Done(); }
        failureSet_->Insert(ios->owner);
        return status;
    }

    UC_DEBUG("LustreTransQueue::S2HSync - Shard {} read completed", ios->shardIndex);

    ios->MarkCompleted(Status::OK());
    if (ios->waiter) { ios->waiter->Done(); }

    return Status::OK();
}

// P2: 异步 S2H 实现
Status TransQueue::S2HAsync(const std::shared_ptr<ExtendedIoUnit>& ios,
                             const std::string& finalPath,
                             const std::shared_ptr<LustreFile>& file)
{
    // 提交异步读请求
    // 修复 C1/C3: 捕获必要的值和 shared_ptr 确保生命周期安全
    int fd = file->GetFd();
    std::weak_ptr<ExtendedIoUnit> weakIos = ios->WeakPtr();

    // 捕获必要的数据值，避免访问可能被销毁的对象成员
    Detail::TaskHandle owner = ios->owner;  // TaskHandle (任务 ID)
    size_t shardIndex = ios->shardIndex;

    IoRequest req(
        fd,
        ios->dstAddr,
        ios->ioSize,
        static_cast<off64_t>(ios->fileOffset),
        false,  // isWrite = false (读)
        [this, weakIos, owner, shardIndex, file](IoRequest::Result result, ssize_t bytesTransferred) {
            // 尝试获取 shared_ptr，如果对象已被销毁则跳过
            auto ios = weakIos.lock();
            if (!ios) {
                UC_WARN("LustreTransQueue::S2HAsync - IoUnit already destroyed, skipping callback");
                return;
            }

            // 回调函数
            if (result == IoRequest::Result::FAILURE) {
                UC_ERROR("LustreTransQueue::S2HAsync - Async read failed");
                ios->MarkCompleted(Status::OsApiError("Async read failed"));
                failureSet_->Insert(owner);
                if (ios->waiter) { ios->waiter->Done(); }
                return;
            }

            UC_DEBUG("LustreTransQueue::S2HAsync - Shard {} async read completed", shardIndex);

            ios->MarkCompleted(Status::OK());
            if (ios->waiter) { ios->waiter->Done(); }
        }
    );

    Status s = asyncIo_->SubmitRead(req);
    if (s.Failure()) {
        // 回退到同步 I/O
        UC_WARN("Async submit failed, falling back to sync I/O: {}", s.ToString());
        return S2HSync(ios, finalPath, *file);
    }

    // 修复 P0: 等待异步操作完成（之前直接返回导致数据未加载）
    const int maxWaitMs = 5000;  // 最大等待 5 秒
    const int checkIntervalMs = 10;  // 每 10ms 检查一次完成队列
    int waitedMs = 0;

    // 先处理已有的完成事件
    asyncIo_->ProcessCompletion(0);

    // 使用条件变量等待，但定期检查完成队列
    while (!ios->IsCompleted() && waitedMs < maxWaitMs) {
        if (!ios->WaitForCompletion(checkIntervalMs)) {
            asyncIo_->ProcessCompletion(0);
        }
        waitedMs += checkIntervalMs;
    }

    if (!ios->IsCompleted()) {
        UC_ERROR("LustreTransQueue::S2HAsync - Async read timeout after {}ms", waitedMs);
        if (ios->waiter) { ios->waiter->Done(); }
        return Status::OsApiError("Async read timeout");
    }

    // 检查异步操作的结果
    if (ios->result.Failure()) {
        UC_ERROR("LustreTransQueue::S2HAsync - Async read failed: {}", ios->result.ToString());
        return ios->result;
    }

    UC_DEBUG("LustreTransQueue::S2HAsync - Async read completed and verified");
    return Status::OK();
}

}  // namespace UC::LustreStore
