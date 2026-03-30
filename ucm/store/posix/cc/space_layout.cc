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
#include "space_layout.h"
#include <algorithm>
#include <fmt/ranges.h>
#include "logger/logger.h"
#include "posix_file.h"

/*
主要负责管理数据文件的目录结构和路径生成

通过dataDirShardBytes配置，将数据文件分散到以文件名前缀命名的子目录中，避免
单目录文件过多。

*/

namespace UC::PosixStore {

// 数据根目录名
static const std::string DATA_ROOT = "data";
// 临时文件扩展名
static const std::string ACTIVATED_FILE_EXTENSION = ".tmp";


// 将blockid（字节序列）转换为十六进制字符串文件名
inline std::string DataFileName(const Detail::BlockId& blockId)
{
    return fmt::format("{:02x}", fmt::join(blockId, ""));
}

// 生成n位十六进制的所有可能组合
/*
n等于1:16个
n等于2:256个
*/
std::vector<std::string> GenerateHexStrings(const size_t n)
{
    if (n == 0) [[unlikely]] { return {}; }
    size_t nCombinations = 1ULL << (n * 4);
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

/*
初始化存储后端，创建必要的目录结构

流程：
1. 读取分片配置
2. 遍历所有存储后端路径
3. 调用AddStorageBackend添加
*/
Status SpaceLayout::Setup(const Config& config)
{
    dataDirShardBytes_ = config.dataDirShardBytes;      // 分片字节数
    dataDirShard_ = dataDirShardBytes_ > 0;             // 是否启用分片
    auto status = Status::OK();
    for (auto& path : config.storageBackends) {
        if ((status = AddStorageBackend(path)).Failure()) { return status; }
    }
    return status;
}

/* 根据blockid生成数据文件路径 */
std::string SpaceLayout::DataFilePath(const Detail::BlockId& blockId, bool activated) const
{
    const auto& backend = StorageBackend(blockId);      // 选择存储后端
    const auto& file = DataFileName(blockId);           // 生成文件名
    const auto& shard = dataDirShard_ ? FileShardName(file) : DATA_ROOT;    // 分片目录
    if (!activated) { return fmt::format("{}{}/{}", backend, shard, file); }
    return fmt::format("{}{}/{}{}", backend, shard, file, ACTIVATED_FILE_EXTENSION);
}

/* 提交文件（将.tmp临时文件重名为正式文件） */
Status SpaceLayout::CommitFile(const Detail::BlockId& blockId, bool success) const
{
    const auto& activated = DataFilePath(blockId, true);        // 临时文件路径
    auto s = Status::OK();
    if (success) {
        const auto& archived = DataFilePath(blockId, false);    // 正式文件路径
        s = PosixFile{activated}.Rename(archived);              // 重命名为正式文件
    }
    if (!success || s.Failure()) { PosixFile{activated}.Remove(); }
    return s;
}

std::vector<std::string> SpaceLayout::RelativeRoots() const
{
    if (dataDirShard_) { return GenerateHexStrings(dataDirShardBytes_); }
    return {DATA_ROOT};
}

/* 添加存储后端 */
Status SpaceLayout::AddStorageBackend(const std::string& path)
{
    auto normalizedPath = path;
    if (normalizedPath.back() != '/') { normalizedPath += '/'; }        // 确保以/结尾
    auto status = Status::OK();
    if (storageBackends_.empty()) {
        status = AddFirstStorageBackend(normalizedPath);                // 第一个后端：创建目录
    } else {
        status = AddSecondaryStorageBackend(normalizedPath);            // 其他后端：检查权限
    }
    if (status.Failure()) {
        UC_ERROR("Failed({}) to add storage backend({}).", status, normalizedPath);
    }
    return status;
}

Status SpaceLayout::AddFirstStorageBackend(const std::string& path)
{
    for (const auto& root : RelativeRoots()) {
        PosixFile dir{path + root};
        auto status = dir.MkDir();
        if (status == Status::DuplicateKey()) { status = Status::OK(); }
        if (status.Failure()) { return status; }
    }
    storageBackends_.emplace_back(path);
    return Status::OK();
}

Status SpaceLayout::AddSecondaryStorageBackend(const std::string& path)
{
    auto iter = std::find(storageBackends_.begin(), storageBackends_.end(), path);
    if (iter != storageBackends_.end()) { return Status::OK(); }
    constexpr auto accessMode = PosixFile::AccessMode::READ | PosixFile::AccessMode::WRITE;
    for (const auto& root : RelativeRoots()) {
        PosixFile dir{path + root};
        auto status = dir.Access(accessMode);
        if (status.Failure()) { return status; }
    }
    storageBackends_.emplace_back(path);
    return Status::OK();
}

/* 根据blockid哈希选择存储后端 */
std::string SpaceLayout::StorageBackend(const Detail::BlockId& blockId) const
{
    const auto number = storageBackends_.size();
    if (number == 1) { return storageBackends_.front(); }       // 单后端直接返回
    static Detail::BlockIdHasher hasher;
    return storageBackends_[hasher(blockId) % number];          // 哈希取模选择
}

}  // namespace UC::PosixStore
