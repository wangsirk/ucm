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
#ifndef UNIFIEDCACHE_LUSTRE_STORE_CC_TEMP_FILE_CLEANUP_H
#define UNIFIEDCACHE_LUSTRE_STORE_CC_TEMP_FILE_CLEANUP_H

#include <cstdint>
#include <string>
#include <vector>
#include "status/status.h"

/**
 * 临时文件清理配置 (v1.2 设计)
 *
 * 使用 atexit() 而非信号处理器，确保异步信号安全
 */
namespace UC::LustreStore {

struct TempFileCleanupConfig {
    /// 最大文件年龄 (秒)，超过此年龄的文件会被清理
    /// 默认: 3600 秒 (1 小时)
    size_t maxAgeSeconds{3600};

    /// 是否检查文件锁
    /// true: 使用 fcntl 检查文件是否被锁定
    /// false: 跳过锁检查 (更快，但可能误删)
    bool checkFileLock{true};

    /// 是否检查进程是否存在
    /// true: 检查 /proc/<pid> 是否存在
    /// false: 跳过进程检查
    bool checkProcessExists{true};

    /// 是否启用清理
    /// false: 禁用自动清理 (用于调试)
    bool enableCleanup{true};

    /// 清理模式
    enum class CleanupMode {
        SAFE,      // 安全模式: 所有条件都满足才清理
        AGGRESSIVE // 激进模式: 仅检查 PID 和年龄
    };
    CleanupMode mode{CleanupMode::SAFE};
};

/**
 * 临时文件清理器
 *
 * 负责清理残留的临时文件，使用安全的 atexit() 机制
 */
class TempFileCleanup {
public:
    /**
     * 清理残留的临时文件
     *
     * **清理条件** (全部满足才清理):
     * 1. 文件名匹配 .tmp.<pid> 后缀
     * 2. 文件年龄超过 maxAgeSeconds
     * 3. 文件未被锁定 (如果 checkFileLock=true)
     * 4. 进程不存在 (如果 checkProcessExists=true)
     *
     * @param dataDir 数据目录路径
     * @param pid 当前进程 ID (只清理本进程的临时文件)
     * @param config 清理配置
     * @return Status 清理状态
     */
    static Status CleanupTempFiles(const std::string& dataDir, pid_t pid,
                                    const TempFileCleanupConfig& config = {});

    /**
     * 清理本进程的所有临时文件
     *
     * 在析构函数或 atexit() 注册的函数中调用
     * 注意: 此时进程即将退出，可以放宽清理条件
     *
     * @param dataDir 数据目录路径
     * @param pid 当前进程 ID
     */
    static void CleanupOwnTempFiles(const std::string& dataDir, pid_t pid);

private:
    /**
     * 判断文件是否应该被清理
     * @return pair<bool, Status> (should_cleanup, error_status)
     */
    static std::pair<bool, Status> ShouldCleanupFile(
        const std::string& filePath,
        const TempFileCleanupConfig& config);

    /**
     * 获取文件年龄 (秒)
     * @return Expected<size_t> 文件年龄
     */
    static Status GetFileAge(const std::string& filePath, size_t& outAge);

    /**
     * 检查文件是否被锁定
     * @return Expected<bool> true=被锁定, false=未锁定
     */
    static Status IsFileLocked(const std::string& filePath, bool& outLocked);

    /**
     * 检查进程是否正在运行
     * @return bool true=运行中, false=不存在
     */
    static bool IsProcessRunning(pid_t pid);

    /**
     * 从文件路径提取 PID
     * @return bool true=成功提取, false=失败
     */
    static bool ExtractPidFromPath(const std::string& filePath, pid_t& outPid);

    /**
     * 列出指定目录下的临时文件
     */
    static std::vector<std::string> ListTempFiles(const std::string& dir, pid_t pid);

    /**
     * 列出所有分片目录
     */
    static std::vector<std::string> ListShardDirs(const std::string& dataDir);
};

}  // namespace UC::LustreStore

#endif  // UNIFIEDCACHE_LUSTRE_STORE_CC_TEMP_FILE_CLEANUP_H
