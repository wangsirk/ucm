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
#include <unistd.h>
#include <sys/syscall.h>
#include <iomanip>
#include <unistd.h>
#include <errno.h>
#include <cstring>

namespace UC::LustreStore {

// ===== 辅助函数 =====

namespace {

/**
 * 生成 n 位十六进制的所有可能组合
 *
 * 注意：这里的 n 是十六进制字符数（每个字符=4位）
 * n=0: 返回空（表示扁平化结构）
 * n=1: 16个目录 (0-f)
 * n=2: 256个目录 (00-ff)
 * n=3: 4096个目录 (000-fff)
 *
 * 与 PosixStore::GenerateHexStrings 保持一致
 */
std::vector<std::string> GenerateHexStrings(size_t n)
{
    if (n == 0) [[unlikely]] { return {}; }
    size_t nCombinations = 1ULL << (n * 4);  // 16^n 种组合
    std::vector<std::string> result;
    result.reserve(nCombinations);
    constexpr char hexChars[] = "0123456789abcdef";
    for (size_t i = 0; i < nCombinations; ++i) {
        std::string s(n, '0');
        auto temp = i;
        for (int j = n - 1; j >= 0; --j) {
            s[j] = hexChars[temp & 0xF];
            temp >>= 4;
        }
        result.push_back(s);
    }
    return result;
}

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
    UC_INFO("LustreSpaceLayout::Setup - Stripe count: {}, Stripe size: {}",
            config.stripeCount, config.stripeSize);

    // 存储配置
    storageBackends_ = config.storageBackends;
    dataDirShard_ = config.dataDirShardBytes > 0;
    dataDirShardBytes_ = config.dataDirShardBytes;
    stripeCount_ = config.stripeCount;
    stripeSize_ = config.stripeSize;

    // 验证存储后端
    if (storageBackends_.empty()) {
        UC_ERROR("LustreSpaceLayout::Setup - No storage backends configured");
        return Status::InvalidParam("storageBackends cannot be empty");
    }

    // 创建基础目录结构（与 PosixStore 保持一致）
    // - dataDirShardBytes = 0: 创建 backend/data/
    // - dataDirShardBytes > 0: 创建 backend/00/, backend/01/, ..., backend/ff/ (直接在 backend 下)
    //
    // 条带化策略：
    // - 当 stripeCount_ > 0 时，直接在 backend 目录上设置条带属性
    // - 之后在该目录下创建的所有文件都会自动继承条带属性
    // - 分片子目录不需要单独设置条带（会自动继承父目录）

    for (const auto& backend : storageBackends_) {
        // 第一步：当启用条带化时，在 backend 目录上设置条带属性
        if (stripeCount_ > 0) {
            auto s = LustreFile::SetStripedDirectory(backend, stripeCount_, stripeSize_, 0755);
            if (s.Failure()) {
                UC_WARN("LustreSpaceLayout::Setup - Failed to set stripe on backend {}, "
                        "continuing with normal directory: {}", backend, s.ToString());
                // 即使设置条带失败，也继续创建目录
            } else {
                UC_INFO("LustreSpaceLayout::Setup - Set stripe on backend directory {} "
                        "(stripe_count={}, stripe_size={})",
                        backend, stripeCount_, stripeSize_);
            }
        }

        // 第二步：创建分片目录（会自动继承父目录的条带属性）
        auto relativeRoots = RelativeRoots();

        for (const auto& relativeRoot : relativeRoots) {
            std::string fullPath = backend + "/" + relativeRoot;

            // 使用普通目录创建（如果父目录已设置条带，子目录会自动继承）
            auto s = LustreFile::MkDir(fullPath, 0755);
            if (s == Status::DuplicateKey()) {
                s = Status::OK();  // 目录已存在，忽略错误
            }
            if (s.Failure()) {
                UC_ERROR("LustreSpaceLayout::Setup - Failed to create directory {}: {}",
                         fullPath, s.ToString());
                return s;
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

    // 3. 确定分片目录路径（与 PosixStore 保持一致）
    std::string shardPath;
    if (dataDirShard_) {
        // 分片模式：直接使用分片目录（如 "00", "7f", "ff"）
        shardPath = FileShardName(hexHash) + "/";
    } else {
        // 扁平化模式：使用 data 子目录
        shardPath = "data/";
    }

    // 4. 构建完整路径
    std::string path = backend + "/" + shardPath + hexHash;

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
    // 与 PosixStore 保持一致：
    // - 当 dataDirShardBytes_ == 0 时，返回 {"data"}（使用 data 子目录）
    // - 当 dataDirShardBytes_ > 0 时，返回所有分片目录（直接在 backend 下创建，如 "00", "01", ..., "ff"）
    if (!dataDirShard_) {
        return {"data"};
    }

    // 生成所有分片目录名（不包含 data/ 前缀）
    return GenerateHexStrings(dataDirShardBytes_);
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

bool SpaceLayout::Exists(const Detail::BlockId& blockId) const
{
    std::string path = DataFilePath(blockId, false);
    return LustreFile::Exists(path);
}

}  // namespace UC::LustreStore
