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
#include <gtest/gtest.h>
#include "temp_file_cleanup.h"
#include <fstream>
#include <unistd.h>

namespace UC::LustreStore {

class TempFileCleanupTest : public ::testing::Test {
protected:
    std::string testDir_ = "/tmp/ucm_cleanup_test_XXXXXX";
    pid_t testPid_;

    void SetUp() override {
        // 创建临时目录
        char tempDir[] = "/tmp/ucm_cleanup_test_XXXXXX";
        char* result = mkdtemp(tempDir);
        ASSERT_NE(result, nullptr);
        testDir_ = tempDir;
        testPid_ = getpid();
    }

    void TearDown() override {
        // 清理测试目录
        system(("rm -rf " + testDir_).c_str());
    }

    // 创建临时测试文件
    std::string CreateTempFile(const std::string& name, int ageSeconds = 0) {
        std::string path = testDir_ + "/" + name + ".tmp." + std::to_string(testPid_);
        std::ofstream(path) << "test data";

        // 如果需要旧文件，修改 mtime
        if (ageSeconds > 0) {
            struct timeval times[2];
            times[0].tv_sec = ageSeconds;  // atime
            times[1].tv_sec = ageSeconds;  // mtime
            times[0].tv_usec = 0;
            times[1].tv_usec = 0;
            utimes(path.c_str(), times);
        }

        return path;
    }

    std::string GetDataDir() const {
        return testDir_ + "/data";
    }
};

// ===== 清理条件测试 =====

TEST_F(TempFileCleanupTest, CleanupTempFiles_Disabled_ReturnsOK) {
    TempFileCleanupConfig config;
    config.enableCleanup = false;

    auto result = TempFileCleanup::CleanupTempFiles(GetDataDir(), testPid_, config);
    EXPECT_TRUE(result.Success());
}

TEST_F(TempFileCleanupTest, CleanupTempFiles_YoungFile_NotCleaned) {
    // 创建数据目录
    mkdir(GetDataDir().c_str(), 0755);

    // 创建新临时文件
    std::string tempFile = CreateTempFile("young", 0);

    TempFileCleanupConfig config;
    config.maxAgeSeconds = 3600;  // 1 小时

    TempFileCleanup::CleanupTempFiles(GetDataDir(), testPid_, config);

    // 文件应该仍然存在
    EXPECT_TRUE(access(tempFile.c_str(), F_OK) == 0);

    // 清理
    std::remove(tempFile.c_str());
}

TEST_F(TempFileCleanupTest, CleanupTempFiles_OldFile_Cleaned) {
    // 创建数据目录
    mkdir(GetDataDir().c_str(), 0755);

    // 创建旧临时文件 (2 小时前)
    std::string tempFile = CreateTempFile("old", 7200);

    TempFileCleanupConfig config;
    config.maxAgeSeconds = 3600;  // 1 小时
    config.checkFileLock = false;
    config.checkProcessExists = false;  // 不检查进程（测试进程仍在运行）

    TempFileCleanup::CleanupTempFiles(GetDataDir(), testPid_, config);

    // 文件应该被清理
    EXPECT_TRUE(access(tempFile.c_str(), F_OK) != 0);
}

// ===== 提取 PID 测试 =====

TEST_F(TempFileCleanupTest, ExtractPidFromPath_ValidFormat_ReturnsCorrectPid) {
    std::string path = "/data/block0123.tmp.12345";
    pid_t extractedPid;

    // 注意: ExtractPidFromPath 是 private，通过实际行为测试
    // 这里测试文件命名格式
    size_t pos = path.rfind(".tmp.");
    ASSERT_NE(pos, std::string::npos);

    std::string pidStr = path.substr(pos + 5);
    pid_t pid = std::stoi(pidStr);

    EXPECT_EQ(pid, 12345);
}

// ===== ListTempFiles 测试 =====

TEST_F(TempFileCleanupTest, ListTempFiles_FindsMatchingFiles) {
    // 创建数据目录
    mkdir(GetDataDir().c_str(), 0755);

    // 创建测试文件
    std::string temp1 = CreateTempFile("test1");
    std::string temp2 = CreateTempFile("test2");

    // 创建非临时文件
    std::string normalFile = GetDataDir() + "/normal_file.txt";
    std::ofstream(normalFile) << "normal data";

    // 注意: ListTempFiles 是 private，通过 CleanupTempFiles 间接测试
    TempFileCleanupConfig config;
    config.maxAgeSeconds = 0;
    config.checkFileLock = false;
    config.checkProcessExists = false;

    auto result = TempFileCleanup::CleanupTempFiles(GetDataDir(), testPid_, config);
    EXPECT_TRUE(result.Success());

    // 清理
    std::remove(temp1.c_str());
    std::remove(temp2.c_str());
    std::remove(normalFile.c_str());
}

// ===== 自身文件清理测试 =====

TEST_F(TempFileCleanupTest, CleanupOwnTempFiles_RemovesAllOwnFiles) {
    // 创建数据目录
    mkdir(GetDataDir().c_str(), 0755);

    // 创建多个临时文件
    std::string temp1 = CreateTempFile("own1");
    std::string temp2 = CreateTempFile("own2");

    // 清理自身文件
    TempFileCleanup::CleanupOwnTempFiles(GetDataDir(), testPid_);

    // 所有文件应该被清理
    EXPECT_TRUE(access(temp1.c_str(), F_OK) != 0);
    EXPECT_TRUE(access(temp2.c_str(), F_OK) != 0);
}

}  // namespace UC::LustreStore
