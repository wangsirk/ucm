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
#include "space_layout.h"
#include <fmt/ranges.h>
#include "logger/logger.h"

namespace UC::LustreStore {

Status SpaceLayout::Setup(const Config& config)
{
    UC_INFO("LustreSpaceLayout::Setup - Initializing space layout");
    UC_INFO("LustreSpaceLayout::Setup - Storage backends: {}", config.storageBackends);
    UC_INFO("LustreSpaceLayout::Setup - Data dir shard bytes: {}", config.dataDirShardBytes);
    // TODO: 实现空间布局初始化
    return Status::OK();
}

std::string SpaceLayout::DataFilePath(const Detail::BlockId& blockId, bool activated) const
{
    UC_DEBUG("LustreSpaceLayout::DataFilePath - Generating path for block, activated={}", activated);
    // TODO: 实现路径生成逻辑
    return "/tmp/lustre_stub_path";
}

Status SpaceLayout::CommitFile(const Detail::BlockId& blockId, bool success) const
{
    UC_DEBUG("LustreSpaceLayout::CommitFile - Committing file, success={}", success);
    // TODO: 实现文件提交逻辑
    return Status::OK();
}

std::vector<std::string> SpaceLayout::RelativeRoots() const
{
    UC_DEBUG("LustreSpaceLayout::RelativeRoots - Getting relative roots");
    // TODO: 实现相对根目录获取
    return {};
}

Status SpaceLayout::AddStorageBackend(const std::string& path)
{
    UC_INFO("LustreSpaceLayout::AddStorageBackend - Adding backend: {}", path);
    // TODO: 实现存储后端添加逻辑
    return Status::OK();
}

std::string SpaceLayout::StorageBackend(const Detail::BlockId& blockId) const
{
    UC_DEBUG("LustreSpaceLayout::StorageBackend - Selecting backend for block");
    // TODO: 实现 OST 感知的后端选择
    return storageBackends_.empty() ? "" : storageBackends_[0];
}

}  // namespace UC::LustreStore
