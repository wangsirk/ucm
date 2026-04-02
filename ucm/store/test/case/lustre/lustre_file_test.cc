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
 * furnished to do so, subject to the following conditions.
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
#include "lustre_file.h"
#include <fstream>
#include <cstdio>
#include <unistd.h>

namespace UC::LustreStore {

class LustreFileTest : public ::testing::Test {
protected:
    std::string testDir_="/tmp/ucm_lustre_test_XXXXXX";
    std::vector<std::string> filesToRemove_;

    void SetUp() override {
        // 创建临时目录
        char tempDir[] = "/tmp/ucm_lustre_test_XXXXXX";
        char* result = mkdtemp(tempDir);
        ASSERT_NE(result, nullptr);
        testDir_ = tempDir;
    }

    void TearDown() override {
        // 清理测试文件
        for (const auto& file : filesToRemove_) {
            std::remove(file.c_str());
        }
        // 删除临时目录
        rmdir(testDir_.c_str());
    }

    std::string GetTestPath(const std::string& name) {
        return testDir_ + "/" + name;
    }
};

// ===== 文件存在性测试 =====

TEST_F(LustreFileTest, Exists_ExistingFile_ReturnsTrue) {
    std::string path = GetTestPath("existing_file.txt");
    std::ofstream(path).close();
    filesToRemove_.push_back(path);

    EXPECT_TRUE(LustreFile::Exists(path));
}

TEST_F(LustreFileTest, Exists_NonExistingFile_ReturnsFalse) {
    std::string path = GetTestPath("non_existing_file.txt");
    EXPECT_FALSE(LustreFile::Exists(path));
}

// ===== 目录创建测试 =====

TEST_F(LustreFileTest, MkDir_SingleDirectory_CreatesSuccessfully) {
    std::string path = GetTestPath("new_dir");
    filesToRemove_.push_back(path);

    auto result = LustreFile::MkDir(path);
    EXPECT_TRUE(result.Success());
    EXPECT_TRUE(LustreFile::Exists(path));
}

TEST_F(LustreFileTest, MkDir_NestedDirectories_CreatesSuccessfully) {
    std::string path = GetTestPath("parent/child/grandchild");
    filesToRemove_.push_back(GetTestPath("parent"));

    auto result = LustreFile::MkDir(path);
    EXPECT_TRUE(result.Success());
    EXPECT_TRUE(LustreFile::Exists(path));
}

TEST_F(LustreFileTest, MkDir_Idempotent_CallsMultipleTimes_ReturnsOK) {
    std::string path = GetTestPath("dir");
    filesToRemove_.push_back(path);

    auto result1 = LustreFile::MkDir(path);
    auto result2 = LustreFile::MkDir(path);

    EXPECT_TRUE(result1.Success());
    EXPECT_TRUE(result2.Success());  // 幂等性
}

// ===== 文件删除测试 =====

TEST_F(LustreFileTest, Remove_ExistingFile_RemovesSuccessfully) {
    std::string path = GetTestPath("to_remove.txt");
    std::ofstream(path).close();

    auto result = LustreFile::Remove(path);
    EXPECT_TRUE(result.Success());
    EXPECT_FALSE(LustreFile::Exists(path));
}

TEST_F(LustreFileTest, Remove_NonExistingFile_ReturnsOK) {
    std::string path = GetTestPath("non_existing.txt");

    auto result = LustreFile::Remove(path);
    EXPECT_TRUE(result.Success());  // 幂等性
}

// ===== 文件访问测试 =====

TEST_F(LustreFileTest, Access_ExistingReadableFile_ReturnsTrue) {
    std::string path = GetTestPath("readable.txt");
    std::ofstream(path).close();
    filesToRemove_.push_back(path);

    LustreFile file(path);
    EXPECT_TRUE(file.Access(R_OK));
}

TEST_F(LustreFileTest, Access_NonExistingFile_ReturnsFalse) {
    std::string path = GetTestPath("non_existing.txt");

    LustreFile file(path);
    EXPECT_FALSE(file.Access(F_OK));
}

// ===== Link 操作测试 =====

TEST_F(LustreFileTest, Link_NewFiles_CreatesHardLink) {
    std::string oldPath = GetTestPath("original.txt");
    std::string newPath = GetTestPath("link.txt");

    // 创建原始文件
    std::ofstream(oldPath) << "test content";
    filesToRemove_.push_back(oldPath);
    filesToRemove_.push_back(newPath);

    auto result = LustreFile::Link(oldPath, newPath);
    EXPECT_TRUE(result.Success());
    EXPECT_TRUE(LustreFile::Exists(newPath));
}

TEST_F(LustreFileTest, Link_ExistingFile_ReturnsDuplicateKey) {
    std::string oldPath = GetTestPath("original.txt");
    std::string newPath = GetTestPath("existing.txt");

    // 创建两个文件
    std::ofstream(oldPath) << "original";
    std::ofstream(newPath) << "existing";
    filesToRemove_.push_back(oldPath);
    filesToRemove_.push_back(newPath);

    auto result = LustreFile::Link(oldPath, newPath);
    EXPECT_TRUE(result.Failure());
    EXPECT_EQ(result.Underlying(), Status::DuplicateKey().Underlying());
}

// ===== LustreFile 类生命周期测试 =====

TEST_F(LustreFileTest, Destructor_AutoClosesFile) {
    std::string path = GetTestPath("auto_close.txt");
    filesToRemove_.push_back(path);

    {
        LustreFile file(path);
        file.CreateNormal(O_CREAT | O_WRONLY, 0644);
        EXPECT_TRUE(file.IsOpen());
    }  // 析构函数自动关闭

    // 文件应该已关闭，可以重新打开
    LustreFile file2(path);
    auto result = file2.Open(O_RDONLY);
    EXPECT_TRUE(result.Success());
}

}  // namespace UC::LustreStore
