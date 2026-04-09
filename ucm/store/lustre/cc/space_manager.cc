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
#include "space_manager.h"
#include "logger/logger.h"
#include <algorithm>

namespace UC::LustreStore {

Status SpaceManager::Setup(const Config& config)
{
    UC_INFO("LustreSpaceManager::Setup - Initializing space manager");
    
    // 初始化空间布局
    auto s = layout_.Setup(config);
    if (s.Failure()) {
        UC_ERROR("LustreSpaceManager::Setup - Failed to setup layout: {}", s);
        return s;
    }
    
    // P2 优化：初始化 Lookup 线程池
    lookupConcurrency_ = config.lookupConcurrency;
    
    ThreadPoolConfig poolConfig;
    poolConfig.lookupConcurrency = config.lookupConcurrency;
    poolConfig.dataTransConcurrency = 1;  // SpaceManager 只需要 Lookup 线程池
    poolConfig.lookupCpuCores = config.lookupCpuCores;
    poolConfig.dataTransCpuCores = -2;  // 不绑定 DataTrans 线程池
    poolConfig.queueDepth = 1024;  // 足够大的队列深度
    poolConfig.timeoutMs = config.timeoutMs;
    
    // 验证配置
    s = poolConfig.Validate();
    if (s.Failure()) {
        UC_ERROR("LustreSpaceManager::Setup - Invalid thread pool config: {}", s);
        return s;
    }
    
    // 创建并初始化线程池
    try {
        threadPool_ = std::make_unique<LustreThreadPool>();
        s = threadPool_->Setup(poolConfig);
        if (s.Failure()) {
            UC_ERROR("LustreSpaceManager::Setup - Failed to setup thread pool: {}", s);
            return s;
        }
    } catch (const std::exception& e) {
        UC_ERROR("LustreSpaceManager::Setup - Exception creating thread pool: {}", e.what());
        return Status::Error(std::string("Failed to create thread pool: ") + e.what());
    }
    
    UC_INFO("LustreSpaceManager::Setup - Space manager initialized successfully "
            "(lookup_concurrency={})", lookupConcurrency_);
    return Status::OK();
}

std::vector<uint8_t> SpaceManager::Lookup(const Detail::BlockId* blocks, size_t num)
{
    UC_INFO("LustreSpaceManager::Lookup - Looking up {} blocks", num);
    std::vector<uint8_t> result(num, 0);

    // P1 修复: 使用多线程并行查询，避免 N+1 syscall 问题
    // 小数量直接顺序查询，避免线程开销
    if (num <= 4 || !threadPool_) {
        for (size_t i = 0; i < num; i++) {
            result[i] = LookupSingle(&blocks[i]);
        }
    } else {
        // P2 优化：使用 LustreThreadPool 统一管理线程
        // 使用 Latch 等待所有任务完成
        auto latch = std::make_shared<Latch>();
        latch->Set(num);
        
        // 为每个 block 提交一个查询任务
        for (size_t i = 0; i < num; ++i) {
            // 注意：捕获 i 而不是 &i，避免引用失效
            auto task = [this, &blocks, &result, i, latch]() {
                result[i] = LookupSingle(&blocks[i]);
                latch->Done();
            };
            
            Status s = threadPool_->SubmitFunc(std::move(task), 
                                                LustreThreadPool::WorkerType::LOOKUP);
            if (s.Failure()) {
                // 提交失败，回退到同步查询
                UC_WARN("LustreSpaceManager::Lookup - Failed to submit task: {}, "
                        "falling back to sync", s.ToString());
                result[i] = LookupSingle(&blocks[i]);
                latch->Done();
            }
        }
        
        // 等待所有任务完成
        latch->Wait();
    }

    size_t foundCount = std::count(result.begin(), result.end(), 1);
    UC_INFO("LustreSpaceManager::Lookup - {} blocks, {} found", num, foundCount);
    return result;
}

uint8_t SpaceManager::LookupSingle(const Detail::BlockId* block)
{
    if (!block) {
        return 0;
    }

    // 使用 SpaceLayout 检查文件存在
    bool exists = layout_.Exists(*block);

    UC_DEBUG("LustreSpaceManager::LookupSingle - block={}, exists={}",
             (*block)[0], exists);

    return exists ? 1 : 0;
}

ssize_t SpaceManager::LookupOnPrefix(const Detail::BlockId* blocks, size_t num)
{
    if (!blocks || num == 0) {
        return -1;
    }

    // 遍历 blocks，找到第一个不存在的
    for (size_t i = 0; i < num; i++) {
        if (LookupSingle(&blocks[i]) == 0) {
            UC_DEBUG("LustreSpaceManager::LookupOnPrefix - first missing at index={}", i);
            return static_cast<ssize_t>(i);
        }
    }

    UC_DEBUG("LustreSpaceManager::LookupOnPrefix - all {} blocks exist", num);
    return -1;  // 全部存在
}

}  // namespace UC::LustreStore
