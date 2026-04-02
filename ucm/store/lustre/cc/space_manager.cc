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

namespace UC::LustreStore {

Status SpaceManager::Setup(const Config& config)
{
    UC_INFO("LustreSpaceManager::Setup - Initializing space manager");
    // TODO: 实现空间管理器初始化
    auto s = layout_.Setup(config);
    if (s.Failure()) {
        UC_ERROR("LustreSpaceManager::Setup - Failed to setup layout: {}", s);
        return s;
    }
    UC_INFO("LustreSpaceManager::Setup - Space manager initialized successfully");
    return Status::OK();
}

std::vector<uint8_t> SpaceManager::Lookup(const Detail::BlockId* blocks, size_t num)
{
    UC_INFO("LustreSpaceManager::Lookup - Looking up {} blocks", num);
    std::vector<uint8_t> result(num, 0);
    for (size_t i = 0; i < num; i++) {
        result[i] = LookupSingle(&blocks[i]);
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
