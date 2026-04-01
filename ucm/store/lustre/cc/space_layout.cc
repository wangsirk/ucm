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
#include "lustre_file.h"
#include "param_validator.h"

#include <sstream>
#include <iomanip>
#include <unistd.h>
#include <errno.h>
#include <cstring>

namespace UC::LustreStore {

// ===== 辅助函数 =====

namespace {

/**
 * 将 BlockId 转换为十六进制字符串
 *
 * BlockId 是 16 字节的 SHA-256 前缀
 * 输出为 32 个十六进制字符
 */
std::string BlockIdToHex(const Detail::BlockId& blockId)
{
    std::ostringstream oss;
    const auto* data = reinterpret_cast<const uint8_t*>(blockId.data());

    for (size_t i = 0; i < blockId.size(); ++i) {
        oss << std::hex << std::setw(2) << std::setfill('0')
            << static_cast<int>(data[i]);
    }

    return oss.str();
}

/**
 * 生成分片路径
 *
 * 根据配置的 dataDirShardBytes 生成目录分片
 * 例如: "00/00/00/" 当 dataDirShardBytes=3
 */
std::string GetShardPath(const std::string& hexHash, size_t shardBytes)
{
    if (shardBytes == 0) {
        return "";
    }

    std::string path;
    for (size_t i = 0; i < shardBytes; ++i) {
        if (i > 0) path += "/";
        path += hexHash.substr(i * 2, 2);
    }
    path += "/";

    return path;
}

/**
 * 获取当前进程 ID
 */
pid_t GetPid()
{
    return static_cast<pid_t>(syscall(SYS_getpid));
}

} // anonymous namespace

// ===== SpaceLayout 实现 =====

Status SpaceLayout::Setup(const Config& config)
{
    UC_INFO("LustreSpaceLayout::Setup - Initializing space layout");
    UC_INFO("LustreSpaceLayout::Setup - Storage backends: {}", config.storageBackends);
    UC_INFO("LustreSpaceLayout::Setup - Data dir shard bytes: {}", config.dataDirShardBytes);

    // 存储配置
    storageBackends_ = config.storageBackends;
    dataDirShard_ = config.dataDirShardBytes > 0;
    dataDirShardBytes_ = config.dataDirShardBytes;

    // 验证存储后端
    if (storageBackends_.empty()) {
        UC_ERROR("LustreSpaceLayout::Setup - No storage backends configured");
        return Status::InvalidParam("storageBackends cannot be empty");
    }

    // 创建基础目录结构
    for (const auto& backend : storageBackends_) {
        std::string dataDir = backend + "/data";

        // 创建数据目录
        if (auto s = LustreFile::MkDir(dataDir, 0755); s.Failure()) {
            UC_ERROR("LustreSpaceLayout::Setup - Failed to create data directory {}: {}",
                     dataDir, s.ToString());
            return s;
        }

        // 创建分片目录（如果启用）
        if (dataDirShard_) {
            // 创建 2 级分片目录 (00/00/ ~ ff/ff/)
            for (int i = 0; i < 256; ++i) {
                for (int j = 0; j < 256; ++j) {
                    std::string shardDir = dataDir + "/" +
                                         std::string(fmt::format("{:02x}", i)) + "/" +
                                         std::string(fmt::format("{:02x}", j)) + "/";

                    // 尝试创建，忽略已存在错误
                    LustreFile::MkDir(shardDir, 0755);
                }
            }
        }
    }

    UC_INFO("LustreSpaceLayout::Setup - Space layout initialized successfully");
    return Status::OK();
}

std::string SpaceLayout::DataFilePath(const Detail::BlockId& blockId, bool activated) const
{
    // 1. 选择存储后端
    std::string backend = StorageBackend(blockId);
    if (backend.empty()) {
        return "";
    }

    // 2. 转换 BlockId 为十六进制
    std::string hexHash = BlockIdToHex(blockId);

    // 3. 生成分片路径
    std::string shardPath = GetShardPath(hexHash, dataDirShardBytes_);

    // 4. 构建完整路径
    std::string path = backend + "/data/" + shardPath + hexHash;

    // 5. 如果是临时文件，添加 .tmp.{pid} 后缀
    if (activated) {
        path += ".tmp." + std::to_string(GetPid());
    }

    UC_DEBUG("LustreSpaceLayout::DataFilePath - Generated path: {}", path);
    return path;
}

Status SpaceLayout::CommitFile(const Detail::BlockId& blockId, bool success) const
{
    if (!success) {
        // 失败: 删除临时文件
        std::string tmpPath = DataFilePath(blockId, true);
        UC_WARN("LustreSpaceLayout::CommitFile - Operation failed, removing temp file: {}", tmpPath);

        if (auto s = LustreFile::Remove(tmpPath); s.Failure()) {
            UC_ERROR("LustreSpaceLayout::CommitFile - Failed to remove temp file: {}", s.ToString());
        }
        return Status::OsApiError("Operation failed, temp file removed");
    }

    // 成功: 使用 link() 原子提交 (v1.1 设计)
    std::string tmpPath = DataFilePath(blockId, true);
    std::string finalPath = DataFilePath(blockId, false);

    UC_DEBUG("LustreSpaceLayout::CommitFile - Linking {} -> {}", tmpPath, finalPath);

    // 使用 link() 创建硬链接 (原子操作)
    auto linkResult = LustreFile::Link(tmpPath, finalPath);

    if (linkResult.Success()) {
        // 成功: 删除临时文件
        if (auto s = LustreFile::Remove(tmpPath); s.Failure()) {
            UC_WARN("LustreSpaceLayout::CommitFile - Failed to remove temp file after commit: {}", s.ToString());
        }
        UC_INFO("LustreSpaceLayout::CommitFile - Commit succeeded: {} -> {}", tmpPath, finalPath);
        return Status::OK();
    }

    if (linkResult.Underlying() == Status::DuplicateKey().Underlying()) {
        // 文件已存在: 其他进程已经提交 (幂等性保证)
        if (auto s = LustreFile::Remove(tmpPath); s.Failure()) {
            UC_WARN("LustreSpaceLayout::CommitFile - Failed to remove temp file: {}", s.ToString());
        }
        UC_INFO("LustreSpaceLayout::CommitFile - Block already exists (concurrent commit), removed temp file");
        return Status::DuplicateKey();
    }

    // 其他错误
    UC_ERROR("LustreSpaceLayout::CommitFile - link() failed: {}", linkResult.ToString());
    return linkResult;
}

std::vector<std::string> SpaceLayout::RelativeRoots() const
{
    std::vector<std::string> roots;
    for (const auto& backend : storageBackends_) {
        roots.push_back(backend + "/data");
    }
    return roots;
}

Status SpaceLayout::AddStorageBackend(const std::string& path)
{
    UC_INFO("LustreSpaceLayout::AddStorageBackend - Adding backend: {}", path);

    // 检查路径是否存在
    if (!LustreFile::Exists(path)) {
        UC_ERROR("LustreSpaceLayout::AddStorageBackend - Backend path does not exist: {}", path);
        return Status::InvalidParam("Backend path does not exist: " + path);
    }

    // 检查是否已存在
    for (const auto& backend : storageBackends_) {
        if (backend == path) {
            UC_WARN("LustreSpaceLayout::AddStorageBackend - Backend already exists: {}", path);
            return Status::OK();  // 幂等性
        }
    }

    storageBackends_.push_back(path);
    return Status::OK();
}

std::string SpaceLayout::StorageBackend(const Detail::BlockId& blockId) const
{
    // TODO: 实现 OST 感知的后端选择
    // 当前: 简单轮询选择
    if (storageBackends_.empty()) {
        return "";
    }

    // 使用 BlockId 的第一个字节作为哈希选择后端
    const auto* data = reinterpret_cast<const uint8_t*>(blockId.data());
    size_t index = data[0] % storageBackends_.size();

    return storageBackends_[index];
}

}  // namespace UC::LustreStore
