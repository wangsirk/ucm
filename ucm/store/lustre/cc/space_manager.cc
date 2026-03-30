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
    // TODO: 实现并发查找逻辑
    std::vector<uint8_t> result(num, 0);
    for (size_t i = 0; i < num; i++) {
        result[i] = Lookup(&blocks[i]);
    }
    return result;
}

uint8_t SpaceManager::Lookup(const Detail::BlockId* block)
{
    UC_DEBUG("LustreSpaceManager::Lookup - Looking up single block");
    // TODO: 实现单个Block查找逻辑
    // 未来将支持OST感知的查找优化
    return 0;
}

}  // namespace UC::LustreStore
