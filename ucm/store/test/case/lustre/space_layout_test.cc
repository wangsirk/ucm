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
#include "space_layout.h"
#include <fstream>
#include <cstring>

namespace UC::LustreStore {

class SpaceLayoutTest : public ::testing::Test {
protected:
    SpaceLayout layout_;
    std::string testDir_ = "/tmp/ucm_layout_test_XXXXXX";
    std::vector<std::string> dirsToRemove_;

    void SetUp() override {
        // 创建临时目录
        char tempDir[] = "/tmp/ucm_layout_test_XXXXXX";
        char* result = mkdtemp(tempDir);
        ASSERT_NE(result, nullptr);
        testDir_ = tempDir;
    }

    void TearDown() override {
        // 清理测试目录
        system(("rm -rf " + testDir_).c_str());
    }

    // 创建测试 BlockId (16 字节)
    Detail::BlockId CreateTestBlockId(const std::string& hex) {
        Detail::BlockId blockId;
        const auto* bytes = reinterpret_cast<uint8_t*>(blockId.data());
        for (size_t i = 0; i < 16 && i < hex.size() / 2; ++i) {
            std::string byteStr = hex.substr(i * 2, 2);
            bytes[i] = static_cast<uint8_t>(std::stoi(byteStr, nullptr, 16));
        }
        return blockId;
    }
};

// ===== Setup 测试 =====

TEST_F(SpaceLayoutTest, Setup_ValidConfig_InitializesSuccessfully) {
    Config config;
    config.storageBackends.push_back(testDir_);
    config.dataDirShardBytes = 2;

    auto result = layout_.Setup(config);
    EXPECT_TRUE(result.Success());
}

TEST_F(SpaceLayoutTest, Setup_EmptyStorageBackends_ReturnsInvalidParam) {
    Config config;
    config.storageBackends.clear();
    config.dataDirShardBytes = 2;

    auto result = layout_.Setup(config);
    EXPECT_TRUE(result.Failure());
}

// ===== 路径生成测试 =====

TEST_F(SpaceLayoutTest, DataFilePath_NoSharding_GeneratesCorrectPath) {
    Config config;
    config.storageBackends.push_back(testDir_);
    config.dataDirShardBytes = 0;
    layout_.Setup(config);

    auto blockId = CreateTestBlockId("0123456789abcdef0123456789abcdef");
    std::string path = layout_.DataFilePath(blockId, false);

    EXPECT_TRUE(path.find(testDir_) == 0);
    EXPECT_TRUE(path.find("/data/") != std::string::npos);
    EXPECT_TRUE(path.find("0123456789abcdef") != std::string::npos);
}

TEST_F(SpaceLayoutTest, DataFilePath_WithSharding_GeneratesShardedPath) {
    Config config;
    config.storageBackends.push_back(testDir_);
    config.dataDirShardBytes = 2;
    layout_.Setup(config);

    auto blockId = CreateTestBlockId("aabbccddeeff00112233445566778899");
    std::string path = layout_.DataFilePath(blockId, false);

    // 应该包含分片路径 /data/aa/bb/
    EXPECT_TRUE(path.find("/data/aa/bb/") != std::string::npos);
}

TEST_F(SpaceLayoutTest, DataFilePath_TempFile_HasPidSuffix) {
    Config config;
    config.storageBackends.push_back(testDir_);
    config.dataDirShardBytes = 0;
    layout_.Setup(config);

    auto blockId = CreateTestBlockId("0123456789abcdef0123456789abcdef");
    std::string path = layout_.DataFilePath(blockId, true);

    EXPECT_TRUE(path.find(".tmp.") != std::string::npos);
    EXPECT_TRUE(path.find(std::to_string(getpid())) != std::string::npos);
}

// ===== CommitFile 测试 =====

TEST_F(SpaceLayoutTest, CommitFile_Success_CommitsFile) {
    Config config;
    config.storageBackends.push_back(testDir_);
    config.dataDirShardBytes = 0;
    layout_.Setup(config);

    auto blockId = CreateTestBlockId("0123456789abcdef0123456789abcdef");

    // 创建临时文件
    std::string tmpPath = layout_.DataFilePath(blockId, true);
    std::ofstream(tmpPath) << "test data";
    ASSERT_TRUE(std::ifstream(tmpPath).good());

    // 提交文件
    auto result = layout_.CommitFile(blockId, true);
    EXPECT_TRUE(result.Success());

    // 验证最终文件存在
    std::string finalPath = layout_.DataFilePath(blockId, false);
    EXPECT_TRUE(std::ifstream(finalPath).good());

    // 清理
    std::remove(finalPath.c_str());
}

TEST_F(SpaceLayoutTest, CommitFile_AlreadyExists_ReturnsDuplicateKey) {
    Config config;
    config.storageBackends.push_back(testDir_);
    config.dataDirShardBytes = 0;
    layout_.Setup(config);

    auto blockId = CreateTestBlockId("0123456789abcdef0123456789abcdef");

    // 创建最终文件
    std::string finalPath = layout_.DataFilePath(blockId, false);
    std::ofstream(finalPath) << "existing data";

    // 尝试提交相同文件
    auto result = layout_.CommitFile(blockId, true);
    EXPECT_TRUE(result.Failure());
    EXPECT_EQ(result.Underlying(), Status::DuplicateKey().Underlying());

    // 清理
    std::remove(finalPath.c_str());
}

// ===== 后端选择测试 =====

TEST_F(SpaceLayoutTest, StorageBackend_SingleBackend_ReturnsThatBackend) {
    Config config;
    config.storageBackends.push_back("/mnt/lustre1");
    layout_.Setup(config);

    auto blockId = CreateTestBlockId("0123456789abcdef0123456789abcdef");
    std::string backend = layout_.StorageBackend(blockId);

    EXPECT_EQ(backend, "/mnt/lustre1");
}

TEST_F(SpaceLayoutTest, StorageBackend_MultipleBackends_SelectsBasedOnHash) {
    Config config;
    config.storageBackends.push_back("/mnt/lustre1");
    config.storageBackends.push_back("/mnt/lustre2");
    layout_.Setup(config);

    // 不同的 BlockId 应该映射到不同的后端
    auto blockId1 = CreateTestBlockId("00112233445566778899aabbccddeeff");
    auto blockId2 = CreateTestBlockId("ff112233445566778899aabbccddeeff");

    std::string backend1 = layout_.StorageBackend(blockId1);
    std::string backend2 = layout_.StorageBackend(blockId2);

    // 两个 BlockId 的第一个字节不同，应该映射到不同的后端
    EXPECT_NE(backend1, backend2);
}

}  // namespace UC::LustreStore
