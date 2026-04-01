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
 * IMPLIED, INCLUDING BUT NOT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */
#include "temp_file_cleanup.h"
#include "lustre_file.h"
#include "logger/logger.h"

#include <dirent.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <ctime>
#include <cstdlib>

namespace UC::LustreStore {

// ===== 清理残留临时文件 =====

Status TempFileCleanup::CleanupTempFiles(const std::string& dataDir, pid_t pid,
                                         const TempFileCleanupConfig& config)
{
    if (!config.enableCleanup) {
        UC_INFO("TempFileCleanup::CleanupTempFiles - Cleanup disabled");
        return Status::OK();
    }

    UC_INFO("TempFileCleanup::CleanupTempFiles - Starting cleanup for pid {}", pid);
    size_t cleanedCount = 0;
    Status status = Status::OK();

    // 遍历所有分片目录
    auto shardDirs = ListShardDirs(dataDir);
    for (const auto& shardDir : shardDirs) {
        // 扫描临时文件
        auto tempFiles = ListTempFiles(shardDir, pid);

        for (const auto& filePath : tempFiles) {
            auto [shouldCleanup, s] = ShouldCleanupFile(filePath, config);
            if (shouldCleanup) {
                // 清理文件
                if (LustreFile::Remove(filePath).Success()) {
                    cleanedCount++;
                    UC_INFO("TempFileCleanup::CleanupTempFiles - Cleaned stale temp file: {}", filePath);
                } else {
                    UC_WARN("TempFileCleanup::CleanupTempFiles - Failed to remove temp file: {}", filePath);
                }
            } else if (s.Failure()) {
                // 记录错误但继续
                status = s;
            }
        }
    }

    UC_INFO("TempFileCleanup::CleanupTempFiles - Cleanup completed: {} files removed", cleanedCount);
    return status;
}

// ===== 清理本进程的临时文件 =====

void TempFileCleanup::CleanupOwnTempFiles(const std::string& dataDir, pid_t pid)
{
    UC_INFO("TempFileCleanup::CleanupOwnTempFiles - Cleaning own temp files for pid {}", pid);

    // 遍历所有分片目录
    auto shardDirs = ListShardDirs(dataDir);
    for (const auto& shardDir : shardDirs) {
        // 扫描临时文件
        auto tempFiles = ListTempFiles(shardDir, pid);

        for (const auto& filePath : tempFiles) {
            // 不检查年龄和锁，直接删除 (本进程即将退出)
            if (LustreFile::Remove(filePath).Success()) {
                UC_DEBUG("TempFileCleanup::CleanupOwnTempFiles - Cleaned own temp file: {}", filePath);
            }
        }
    }
}

// ===== 判断文件是否应该被清理 =====

std::pair<bool, Status> TempFileCleanup::ShouldCleanupFile(
    const std::string& filePath,
    const TempFileCleanupConfig& config)
{
    // 条件 1: 检查文件年龄
    size_t age;
    auto s = GetFileAge(filePath, age);
    if (s.Failure()) {
        return {false, s};
    }
    if (age < config.maxAgeSeconds) {
        // 文件太新，不清理
        return {false, Status::OK()};
    }

    // 条件 2: 检查文件锁
    if (config.checkFileLock) {
        bool locked;
        s = IsFileLocked(filePath, locked);
        if (s.Failure()) {
            return {false, s};
        }
        if (locked) {
            // 文件被锁定，可能有进程正在使用
            UC_DEBUG("TempFileCleanup::ShouldCleanupFile - File locked, skipping: {}", filePath);
            return {false, Status::OK()};
        }
    }

    // 条件 3: 检查进程是否存在
    if (config.checkProcessExists) {
        // 从文件名提取 PID
        pid_t filePid;
        if (!ExtractPidFromPath(filePath, filePid)) {
            return {false, Status::OK()};  // 无法提取 PID，跳过
        }

        if (IsProcessRunning(filePid)) {
            // 进程仍在运行，不清理
            UC_DEBUG("TempFileCleanup::ShouldCleanupFile - Process {} still running, skipping: {}",
                     filePid, filePath);
            return {false, Status::OK()};
        }
        // 进程不存在，可以安全清理
    }

    // 所有条件满足，可以清理
    return {true, Status::OK()};
}

// ===== 获取文件年龄 =====

Status TempFileCleanup::GetFileAge(const std::string& filePath, size_t& outAge)
{
    struct stat st;
    if (stat(filePath.c_str(), &st) != 0) {
        int error = errno;
        return Status::OsApiError(std::string("stat() failed: ") + strerror(error));
    }

    time_t now = time(nullptr);
    if (now < st.st_mtime) {
        return Status::OsApiError("File mtime is in the future");
    }

    outAge = static_cast<size_t>(now - st.st_mtime);
    return Status::OK();
}

// ===== 检查文件是否被锁定 =====

Status TempFileCleanup::IsFileLocked(const std::string& filePath, bool& outLocked)
{
    int fd = open(filePath.c_str(), O_RDONLY);
    if (fd < 0) {
        int error = errno;
        return Status::OsApiError(std::string("open() failed: ") + strerror(error));
    }

    struct flock fl;
    fl.l_type = F_WRLCK;
    fl.l_whence = SEEK_SET;
    fl.l_start = 0;
    fl.l_len = 0;

    outLocked = (fcntl(fd, F_GETLK, &fl) == 0 && fl.l_type != F_UNLCK);

    close(fd);
    return Status::OK();
}

// ===== 检查进程是否正在运行 =====

bool TempFileCleanup::IsProcessRunning(pid_t pid)
{
    // 检查 /proc/<pid> 是否存在
    std::string procPath = "/proc/" + std::to_string(pid);
    return (access(procPath.c_str(), F_OK) == 0);
}

// ===== 从文件路径提取 PID =====

bool TempFileCleanup::ExtractPidFromPath(const std::string& filePath, pid_t& outPid)
{
    // 文件名格式: {hash}.tmp.{pid}
    size_t lastDot = filePath.rfind('.');
    if (lastDot == std::string::npos) {
        return false;
    }

    std::string pidStr = filePath.substr(lastDot + 1);
    try {
        outPid = static_cast<pid_t>(std::stol(pidStr));
        return true;
    } catch (const std::invalid_argument&) {
        UC_WARN("TempFileCleanup::ExtractPidFromPath - Invalid PID format in path: {}", filePath);
        return false;
    } catch (const std::out_of_range&) {
        UC_WARN("TempFileCleanup::ExtractPidFromPath - PID value out of range in path: {}", filePath);
        return false;
    }
}

// ===== 列出指定目录下的临时文件 =====

std::vector<std::string> TempFileCleanup::ListTempFiles(const std::string& dir, pid_t pid)
{
    std::vector<std::string> files;
    std::string pattern = ".tmp." + std::to_string(pid);

    DIR* d = opendir(dir.c_str());
    if (!d) {
        return files;
    }

    struct dirent* entry;
    while ((entry = readdir(d)) != nullptr) {
        std::string name = entry->d_name;
        // 检查文件名是否以 .tmp.{pid} 结尾
        if (name.size() > pattern.size() &&
            name.substr(name.size() - pattern.size()) == pattern) {
            files.push_back(dir + "/" + name);
        }
    }

    closedir(d);
    return files;
}

// ===== 列出所有分片目录 =====

std::vector<std::string> TempFileCleanup::ListShardDirs(const std::string& dataDir)
{
    std::vector<std::string> dirs;

    // 简单实现：返回 dataDir 本身
    // 完整实现需要扫描 dataDir 下的所有分片子目录
    dirs.push_back(dataDir);

    // 扫描分片子目录 (00/00/ ~ ff/ff/)
    DIR* d = opendir(dataDir.c_str());
    if (!d) {
        return dirs;
    }

    struct dirent* entry;
    while ((entry = readdir(d)) != nullptr) {
        if (entry->d_type != DT_DIR) {
            continue;
        }
        std::string name = entry->d_name;
        if (name == "." || name == "..") {
            continue;
        }

        // 检查是否是十六进制命名的目录 (分片目录)
        bool isHexDir = true;
        for (char c : name) {
            if (!isxdigit(c)) {
                isHexDir = false;
                break;
            }
        }

        if (isHexDir) {
            std::string subDir = dataDir + "/" + name;

            // 扫描二级分片目录
            DIR* d2 = opendir(subDir.c_str());
            if (d2) {
                struct dirent* entry2;
                while ((entry2 = readdir(d2)) != nullptr) {
                    if (entry2->d_type == DT_DIR) {
                        std::string name2 = entry2->d_name;
                        if (name2 != "." && name2 != "..") {
                            dirs.push_back(subDir + "/" + name2);
                        }
                    }
                }
                closedir(d2);
            }
        }
    }

    closedir(d);
    return dirs;
}

}  // namespace UC::LustreStore
