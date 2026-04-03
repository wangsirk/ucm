/**
 * MIT License
 *
 * Copyright (c) 2025 Huawei Technologies Technologies Co., Ltd. All rights reserved.
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
#include "lustre_file.h"
#include "logger/logger.h"
#include "param_validator.h"

#include <fcntl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <cerrno>
#include <cstring>

// Lustre 特定头文件 (如果可用)
#ifdef HAVE_LUSTRE_API
#include <lustre/lustreapi.h>
#endif

namespace UC::LustreStore {

// ===== 构造/析构 =====

LustreFile::LustreFile(const std::string& path)
    : path_(path), fd_(-1)
{}

LustreFile::~LustreFile()
{
    try {
        Close();
    } catch (const std::exception& e) {
        // 析构函数不应该抛出异常
        UC_ERROR("Exception in LustreFile destructor for {}: {}", path_, e.what());
    } catch (...) {
        UC_ERROR("Unknown exception in LustreFile destructor for {}", path_);
    }
}

// ===== 文件创建 =====

Status LustreFile::CreateStriped(int stripeCount, size_t stripeSize, mode_t mode)
{
    // 检查文件是否已打开
    if (IsOpen()) {
        return Status::Error("File already open");
    }

#ifdef HAVE_LUSTRE_API
    // 使用 Lustre API 创建条带化文件
    struct llapi_layout* layout = llapi_layout_alloc();
    if (!layout) {
        UC_ERROR("Failed to allocate Lustre layout for {}", path_);
        return Status::OsApiError("Failed to allocate Lustre layout");
    }

    // 设置条带参数
    if (stripeCount > 0) {
        llapi_layout_stripe_count_set(layout, stripeCount);
    }
    if (stripeSize > 0) {
        llapi_layout_stripe_size_set(layout, stripeSize);
    }

    // 创建文件 (layout 参数在最后)
    int rc = llapi_layout_file_create(path_.c_str(), O_CREAT | O_WRONLY | O_EXCL, mode, layout);
    llapi_layout_free(layout);

    if (rc != 0) {
        UC_ERROR("Failed to create striped file {}: {}", path_, strerror(errno));
        return Status::OsApiError(std::string("llapi_layout_create failed: ") + strerror(errno));
    }

    UC_INFO("Created striped file {} (stripe_count={}, stripe_size={})",
            path_, stripeCount, stripeSize);
    return Status::OK();
#else
    // 回退到普通文件创建
    UC_WARN("Lustre API not available, creating normal file for {}", path_);
    return CreateNormal(O_CREAT | O_WRONLY | O_EXCL, mode);
#endif
}

Status LustreFile::CreateNormal(uint32_t flags, mode_t mode)
{
    if (IsOpen()) {
        return Status::Error("File already open");
    }

    fd_ = open(path_.c_str(), flags, mode);
    if (fd_ < 0) {
        int error = errno;
        UC_ERROR("Failed to create file {}: {}", path_, strerror(error));
        return Status::OsApiError(std::string("open failed: ") + strerror(error));
    }

    UC_INFO("Created normal file {}", path_);
    return Status::OK();
}

// ===== 文件操作 =====

Status LustreFile::Open(uint32_t flags)
{
    if (IsOpen()) {
        return Status::Error("File already open");
    }

    fd_ = ::open(path_.c_str(), flags);
    if (fd_ < 0) {
        int error = errno;
        UC_ERROR("Failed to open file {}: {}", path_, strerror(error));
        return Status::OsApiError(std::string("open failed: ") + strerror(error));
    }

    return Status::OK();
}

Status LustreFile::Read(void* buffer, size_t size, off64_t offset)
{
    if (auto s = CheckOpen(); s.Failure()) [[unlikely]] {
        return s;
    }

    CHECK_NOT_NULL(buffer, "buffer");

    // 使用 pread 进行线程安全的读取
    ssize_t bytesRead = pread64(fd_, buffer, size, offset);
    if (bytesRead < 0) {
        int error = errno;
        UC_ERROR("Failed to read file {} at offset {}: {}", path_, offset, strerror(error));
        return Status::OsApiError(std::string("pread failed: ") + strerror(error));
    }

    if (static_cast<size_t>(bytesRead) != size) {
        UC_WARN("Short read on file {}: expected {}, got {}", path_, size, bytesRead);
        return Status::OsApiError("Short read");
    }

    return Status::OK();
}

Status LustreFile::Write(const void* buffer, size_t size, off64_t offset)
{
    if (auto s = CheckOpen(); s.Failure()) [[unlikely]] {
        return s;
    }

    CHECK_NOT_NULL(buffer, "buffer");

    // 使用 pwrite 进行线程安全的写入
    ssize_t bytesWritten = pwrite64(fd_, buffer, size, offset);
    if (bytesWritten < 0) {
        int error = errno;
        UC_ERROR("Failed to write file {} at offset {}: {}", path_, offset, strerror(error));
        return Status::OsApiError(std::string("pwrite failed: ") + strerror(error));
    }

    if (static_cast<size_t>(bytesWritten) != size) {
        UC_WARN("Short write on file {}: expected {}, got {}", path_, size, bytesWritten);
        return Status::OsApiError("Short write");
    }

    return Status::OK();
}

void LustreFile::Close()
{
    if (IsOpen()) {
        close(fd_);
        fd_ = -1;
    }
}

Status LustreFile::Sync()
{
    if (auto s = CheckOpen(); s.Failure()) [[unlikely]] {
        return s;
    }

#ifdef __APPLE__
    if (fsync(fd_) != 0) {
#else
    if (fdatasync(fd_) != 0) {
#endif
        int error = errno;
        UC_ERROR("Failed to sync file {}: {}", path_, strerror(error));
        return Status::OsApiError(std::string("fdatasync failed: ") + strerror(error));
    }

    return Status::OK();
}

// ===== 目录操作 =====

Status LustreFile::MkDir(const std::string& path, mode_t mode)
{
    // 尝试创建目录
    if (mkdir(path.c_str(), mode) == 0) {
        return Status::OK();
    }

    int error = errno;

    // 如果目录已存在，返回成功
    if (error == EEXIST) {
        struct stat st;
        if (stat(path.c_str(), &st) == 0 && S_ISDIR(st.st_mode)) {
            return Status::OK();
        }
    }

    // 如果需要父目录，递归创建
    if (error == ENOENT) {
        size_t pos = path.rfind('/');
        if (pos > 0 && pos != std::string::npos) {
            std::string parent = path.substr(0, pos);
            if (auto s = MkDir(parent, mode); s.Failure()) {
                return s;
            }
            // 重试创建当前目录
            if (mkdir(path.c_str(), mode) == 0) {
                return Status::OK();
            }
        }
    }

    UC_ERROR("Failed to create directory {}: {}", path, strerror(error));
    return Status::OsApiError(std::string("mkdir failed: ") + strerror(error));
}

Status LustreFile::SetStripedDirectory(const std::string& path,
                                       int stripeCount,
                                       size_t stripeSize,
                                       mode_t mode)
{
#ifdef HAVE_LUSTRE_API
    // stripeCount 为 0 时不启用条带化
    if (stripeCount <= 0) {
        UC_DEBUG("Stripe count is {}, skipping striping setup for {}", stripeCount, path);
        return Status::OK();
    }

    // 简化方案：在父目录（backend）设置条带属性
    // data 子目录会自动继承父目录的条带属性
    // 例如：/mnt/lustre47/demo 设置条带化，/mnt/lustre47/demo/data 自动继承

    // 从路径中提取父目录（去掉 /data 后缀）
    std::string parentPath = path;
    const std::string dataSuffix = "/data";
    if (parentPath.length() > dataSuffix.length() &&
        parentPath.substr(parentPath.length() - dataSuffix.length()) == dataSuffix) {
        parentPath = parentPath.substr(0, parentPath.length() - dataSuffix.length());
    }

    // 步骤 1: 创建父目录
    auto s = MkDir(parentPath, mode);
    if (s.Failure()) {
        UC_ERROR("Failed to create parent directory {}: {}", parentPath, s.ToString());
        return s;
    }

    // 步骤 2: 使用 lfs setstripe 设置条带属性
    // 构造命令: lfs setstripe <parentPath> -c <stripeCount> -S <stripeSize>
    std::string cmd = "lfs setstripe " + parentPath + " -c " + std::to_string(stripeCount) +
                      " -S " + std::to_string(stripeSize) + " 2>&1";

    FILE* pipe = popen(cmd.c_str(), "r");
    if (pipe) {
        char buffer[256];
        std::string output;
        while (fgets(buffer, sizeof(buffer), pipe) != nullptr) {
            output += buffer;
        }
        int status = pclose(pipe);

        if (status != 0) {
            // 检查是否是因为条带属性已存在
            if (output.find("stripe already set") != std::string::npos ||
                output.find("existing stripe") != std::string::npos) {
                UC_INFO("Parent directory {} already has stripe attributes", parentPath);
            } else {
                UC_WARN("lfs setstripe command failed for {}: {}", parentPath, output);
            }
        } else {
            UC_INFO("Set stripe attributes on parent directory {} (stripe_count={}, stripe_size={})",
                    parentPath, stripeCount, stripeSize);
        }
    }

    // 步骤 3: 创建 data 子目录（自动继承条带属性）
    s = MkDir(path, mode);
    if (s.Failure()) {
        UC_WARN("Failed to create data directory {}: {}", path, s.ToString());
        // 不返回错误，因为父目录已设置条带属性
    }

    return Status::OK();
#else
    // 非 Lustre 环境，返回 OK（no-op）
    UC_DEBUG("Lustre API not available, skipping striping setup for {}", path);
    return Status::OK();
#endif
}

bool LustreFile::Access(int32_t mode) const
{
    return (access(path_.c_str(), mode) == 0);
}

// ===== 文件管理 =====

Status LustreFile::Rename(const std::string& newName)
{
    if (rename(path_.c_str(), newName.c_str()) != 0) {
        int error = errno;
        UC_ERROR("Failed to rename {} to {}: {}", path_, newName, strerror(error));
        return Status::OsApiError(std::string("rename failed: ") + strerror(error));
    }

    path_ = newName;
    return Status::OK();
}

Status LustreFile::Link(const std::string& oldPath, const std::string& newPath)
{
    if (link(oldPath.c_str(), newPath.c_str()) == 0) {
        return Status::OK();
    }

    int error = errno;
    if (error == EEXIST) {
        // 文件已存在 (用于幂等性检查)
        return Status::DuplicateKey();
    }

    UC_ERROR("Failed to link {} to {}: {}", oldPath, newPath, strerror(error));
    return Status::OsApiError(std::string("link() failed: ") + strerror(error));
}

Status LustreFile::Remove(const std::string& path)
{
    if (unlink(path.c_str()) != 0) {
        int error = errno;
        if (error == ENOENT) {
            return Status::OK();  // 文件不存在视为成功
        }
        UC_ERROR("Failed to remove file {}: {}", path, strerror(error));
        return Status::OsApiError(std::string("unlink failed: ") + strerror(error));
    }
    return Status::OK();
}

bool LustreFile::Exists(const std::string& path)
{
    return (access(path.c_str(), F_OK) == 0);
}

size_t LustreFile::GetSize() const
{
    if (!IsOpen()) {
        return 0;
    }

    struct stat st;
    if (fstat(fd_, &st) != 0) {
        return 0;
    }

    return static_cast<size_t>(st.st_size);
}

// ===== 辅助函数 =====

Status LustreFile::CheckOpen() const
{
    if (!IsOpen()) {
        return Status::Error("File not open: " + path_);
    }
    return Status::OK();
}

}  // namespace UC::LustreStore
