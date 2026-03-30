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
#include "space_manager.h"
#include "logger/logger.h"
#include "posix_file.h"

/*
空间管理器，提供并发查找服务
SpaceManager类组合和SpaceLayout和线程池，提供并发的Block查找能力
*/

namespace UC::PosixStore {

/*  
初始化布局和查找线程池
*/
Status SpaceManager::Setup(const Config& config)
{   
    /* 初始化空间布局 */
    auto s = layout_.Setup(config);
    if (s.Failure()) [[unlikely]] { return s; }

    /* 启动查找线程池 */
    auto success =
        lookupSrv_.SetWorkerFn([this](LookupContext& ctx, auto&) { OnLookup(ctx); })
            .SetWorkerTimeoutFn([this](LookupContext& ctx, auto) { OnLookupTimeout(ctx); },
                                config.timeoutMs)
            .SetNWorker(config.lookupConcurrency)
            .Run();
    if (!success) [[unlikely]] { return Status::Error("failed to run lookup service thread pool"); }
    return Status::OK();
}

/* 
并发查找多个Block，返回每个block是否存在的位图
*/
Expected<std::vector<uint8_t>> SpaceManager::Lookup(const Detail::BlockId* blocks, size_t num)
{
    /* 分配结果容器 */
    std::shared_ptr<std::vector<uint8_t>> founds;
    std::shared_ptr<std::atomic<int32_t>> status;    // 状态码
    std::shared_ptr<Latch> waiter;                   // 等待
    const auto ok = Status::OK().Underlying();
    try {
        founds = std::make_shared<std::vector<uint8_t>>(num, 0);
        status = std::make_shared<std::atomic<int32_t>>(ok);
        waiter = std::make_shared<Latch>();
    } catch (const std::exception& e) {
        UC_ERROR("Failed({}) to allocate memory for lookup context.", e.what());
        return Status::OutOfMemory();
    }
    waiter->Set(num);       // 设置等待计数
    // 推送任务
    for (size_t i = 0; i < num; i++) { lookupSrv_.Push({blocks[i], i, founds, status, waiter}); }
    // 阻塞等待完成
    waiter->Wait();
    auto s = status->load();
    if (s != ok) [[unlikely]] { return Status{s, "failed to lookup some blocks"}; }
    return std::move(*founds);
}

/*
按前缀顺序查找，返回最后一个存在的Block索引
*/
Expected<ssize_t> SpaceManager::LookupOnPrefix(const Detail::BlockId* blocks, size_t num)
{
    ssize_t index = -1;
    for (size_t i = 0; i < num && Lookup(blocks + i); i++) { index = static_cast<ssize_t>(i); }
    return index;
}

/* 单个block查找，检查单个block对应的文件是否存在且可读写 */
uint8_t SpaceManager::Lookup(const Detail::BlockId* block)
{
    const auto& path = layout_.DataFilePath(*block, false);
    PosixFile file{path};
    constexpr auto mode =
        PosixFile::AccessMode::EXIST | PosixFile::AccessMode::READ | PosixFile::AccessMode::WRITE;
    auto s = file.Access(mode);
    if (s.Failure()) {
        if (s != Status::NotFound()) { UC_ERROR("Failed({}) to access file({}).", s, path); }
        return false;
    }
    return true;
}

/* 线程池工作函数 */
void SpaceManager::OnLookup(LookupContext& ctx)
{
    const auto ok = Status::OK().Underlying();
    // 仅在状态正常时执行
    if (ctx.status->load() == ok) { (*ctx.founds)[ctx.index] = Lookup(&ctx.block); }
    // 完成计数减1
    ctx.waiter->Done();
}

/* 超时处理函数 */
void SpaceManager::OnLookupTimeout(LookupContext& ctx)
{
    auto ok = Status::OK().Underlying();
    auto timeout = Status::Timeout().Underlying();
    // CAS设置超时状态
    ctx.status->compare_exchange_weak(ok, timeout, std::memory_order_acq_rel);
    ctx.waiter->Done();
}

}  // namespace UC::PosixStore
