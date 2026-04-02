/**
 * MIT License
 *
 * Copyright (c) 2025 Huawei Technologies Co., Ltd. All rights reserved.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software (the "Software), to deal in the Software without restriction,
 * including without limitation the rights to use, copy, modify, merge, publish,
 * distribute, sublicense, and/or sell copies of the Software, and to permit
 * persons to whom the Software is furnished to do so, subject to the following
 * conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
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
#include <memory>
#include <fstream>
#include "trans_queue.h"
#include "trans_task.h"
#include "space_layout.h"
#include "global_config.h"
#include "template/hashset.h"
#include "thread/latch.h"
#include "store/detail/type/types.h"

namespace UC::LustreStore {

/**
 * P1-1.2: TransQueue H2S (Dump) 测试
 *
 * 测试范围:
 * - ExtendedIoUnit shard 跟踪字段
 * - 最后一个 Shard 检测
 * - 文件提交 (CommitFile)
 * - 多 Shard Dump 操作
 */

class TransQueueH2STest : public ::testing::Test {
protected:
    void SetUp() override {
        // 初始化配置
        config_.tensorSize = 256;
        config_.shardSize = 1024;
        config_.blockSize = 4096;  // 4 个 Shard
        config_.storageBackends = {testDir_};
        config_.deviceId = -1;
        config_.ioDirect = false;

        // 清理测试目录
        std::string cmd = "rm -rf " + testDir_ + " && mkdir -p " + testDir_;
        system(cmd.c_str());

        // 初始化布局
        layout_.Setup(config_);

        // 初始化失败集合
        failureSet_ = std::make_unique<HashSet<Detail::TaskHandle>>();

        // 初始化队列
        queue_.Setup(config_, failureSet_.get(), &layout_);
    }

    void TearDown() override {
        // 清理测试目录
        std::string cmd = "rm -rf " + testDir_;
        system(cmd.c_str());
    }

    // 辅助函数: 创建测试用 BlockId
    Detail::BlockId MakeTestBlockId(uint32_t seed = 0) {
        Detail::BlockId bid;
        for (size_t i = 0; i < bid.size(); ++i) {
            bid[i] = static_cast<std::byte>((seed + i) % 256);
        }
        return bid;
    }

    // 辅助函数: 创建测试数据
    std::vector<std::byte> CreateTestData(size_t size, std::byte pattern) {
        return std::vector<std::byte>(size, pattern);
    }

    // 辅助函数: 检查文件是否存在
    bool FileExists(const std::string& path) {
        std::ifstream f(path);
        return f.good();
    }

    // 辅助函数: 读取文件内容
    std::vector<std::byte> ReadFile(const std::string& path) {
        std::ifstream file(path, std::ios::binary);
        if (!file) return {};
        file.seekg(0, std::ios::end);
        size_t size = file.tellg();
        file.seekg(0, std::ios::beg);
        std::vector<std::byte> data(size);
        file.read(reinterpret_cast<char*>(data.data()), size);
        return data;
    }

    std::string testDir_ = "/tmp/lustre_h2s_test";
    Config config_;
    SpaceLayout layout_;
    std::unique_ptr<HashSet<Detail::TaskHandle>> failureSet_;
    TransQueue queue_;
};

// ===== P1-1.2-T1: ExtendedIoUnit shard 跟踪测试 =====

TEST_F(TransQueueH2STest, ExtendedIoUnit_ShardTrackingFields) {
    // 验证新字段存在且默认值正确
    TransQueue::ExtendedIoUnit unit;

    EXPECT_EQ(unit.totalShards, 1);   // 默认值
    EXPECT_EQ(unit.currentShard, 0);  // 默认值
    EXPECT_FALSE(unit.IsLastShard()); // 0 == 1-1 = 0, 应该是 true
}

TEST_F(TransQueueH2STest, ExtendedIoUnit_IsLastShard_SingleShard) {
    TransQueue::ExtendedIoUnit unit;
    unit.totalShards = 1;
    unit.currentShard = 0;

    EXPECT_TRUE(unit.IsLastShard()) << "Single shard should be last";
}

TEST_F(TransQueueH2STest, ExtendedIoUnit_IsLastShard_MultipleShards) {
    TransQueue::ExtendedIoUnit unit;
    unit.totalShards = 4;

    // 前三个不是最后一个
    for (size_t i = 0; i < 3; ++i) {
        unit.currentShard = i;
        EXPECT_FALSE(unit.IsLastShard()) << "Shard " << i << " should not be last";
    }

    // 最后一个是
    unit.currentShard = 3;
    EXPECT_TRUE(unit.IsLastShard()) << "Shard 3 should be last (total=4)";
}

// ===== P1-1.2-T2: SplitTask 填充 shard 信息测试 =====

TEST_F(TransQueueH2STest, SplitTask_PopulatesShardInfo_SingleShard) {
    auto blockId = MakeTestBlockId(1);
    TaskDesc desc;
    desc.push_back(Detail::Shard{blockId, 0, {}});

    TransTask task(TransTask::Type::DUMP, desc);
    auto units = queue_.SplitTask(task);

    ASSERT_EQ(units.size(), 1);
    EXPECT_EQ(units[0]->totalShards, 1);
    EXPECT_EQ(units[0]->currentShard, 0);
    EXPECT_TRUE(units[0]->IsLastShard());
}

TEST_F(TransQueueH2STest, SplitTask_PopulatesShardInfo_MultipleShards) {
    auto blockId = MakeTestBlockId(2);
    const size_t numShards = 4;

    TaskDesc desc;
    for (size_t i = 0; i < numShards; ++i) {
        desc.push_back(Detail::Shard{blockId, static_cast<size_t>(i), {}});
    }

    TransTask task(TransTask::Type::DUMP, desc);
    auto units = queue_.SplitTask(task);

    ASSERT_EQ(units.size(), numShards);

    // 验证每个 unit 的 shard 信息
    for (size_t i = 0; i < numShards; ++i) {
        EXPECT_EQ(units[i]->totalShards, numShards)
            << "Unit " << i << " should have totalShards=" << numShards;
        EXPECT_EQ(units[i]->currentShard, i)
            << "Unit " << i << " should have currentShard=" << i;

        // 只有最后一个应该是 IsLastShard
        if (i == numShards - 1) {
            EXPECT_TRUE(units[i]->IsLastShard()) << "Unit " << i << " should be last";
        } else {
            EXPECT_FALSE(units[i]->IsLastShard()) << "Unit " << i << " should not be last";
        }
    }
}

TEST_F(TransQueueH2STest, SplitTask_PopulatesShardInfo_MultipleBlocks) {
    const size_t numBlocks = 2;
    const size_t shardsPerBlock = 3;

    TaskDesc desc;
    for (size_t b = 0; b < numBlocks; ++b) {
        auto blockId = MakeTestBlockId(b + 10);
        for (size_t s = 0; s < shardsPerBlock; ++s) {
            desc.push_back(Detail::Shard{blockId, s, {}});
        }
    }

    TransTask task(TransTask::Type::DUMP, desc);
    auto units = queue_.SplitTask(task);

    ASSERT_EQ(units.size(), numBlocks * shardsPerBlock);

    // 每个块的最后 shard 应该被标记为 IsLastShard
    size_t lastShardCount = 0;
    for (const auto& unit : units) {
        if (unit->IsLastShard()) {
            lastShardCount++;
            EXPECT_EQ(unit->totalShards, shardsPerBlock);
            EXPECT_EQ(unit->currentShard, shardsPerBlock - 1);
        }
    }
    EXPECT_EQ(lastShardCount, numBlocks) << "Should have " << numBlocks << " last shards";
}

// ===== P1-1.2-T3: 文件提交测试 =====

TEST_F(TransQueueH2STest, CommitFile_CreatesFinalFile) {
    auto blockId = MakeTestBlockId(100);

    // 手动创建临时文件
    std::string tmpPath = layout_.DataFilePath(blockId, true);
    std::string finalPath = layout_.DataFilePath(blockId, false);

    // 创建临时文件并写入数据
    std::string parentDir = tmpPath.substr(0, tmpPath.find_last_of('/'));
    system(("mkdir -p " + parentDir).c_str());

    {
        std::ofstream f(tmpPath, std::ios::binary);
        f << "test data";
    }

    ASSERT_TRUE(FileExists(tmpPath));
    ASSERT_FALSE(FileExists(finalPath));

    // 提交文件
    Status status = queue_.CommitFile(blockId);

    EXPECT_TRUE(status.OK()) << "Commit should succeed: " << status.ToString();
    EXPECT_FALSE(FileExists(tmpPath)) << "Temp file should be removed";
    EXPECT_TRUE(FileExists(finalPath)) << "Final file should exist";

    // 验证内容
    auto content = ReadFile(finalPath);
    EXPECT_EQ(content.size(), 9);
    EXPECT_EQ(std::string(reinterpret_cast<char*>(content.data()), content.size()), "test data");
}

TEST_F(TransQueueH2STest, CommitFile_FailureRemovesTempFile) {
    auto blockId = MakeTestBlockId(101);

    // 创建临时文件
    std::string tmpPath = layout_.DataFilePath(blockId, true);
    std::string finalPath = layout_.DataFilePath(blockId, false);

    std::string parentDir = tmpPath.substr(0, tmpPath.find_last_of('/'));
    system(("mkdir -p " + parentDir).c_str());

    {
        std::ofstream f(tmpPath, std::ios::binary);
        f << "test data";
    }

    ASSERT_TRUE(FileExists(tmpPath));

    // 失败提交
    Status status = layout_.CommitFile(blockId, false);

    EXPECT_FALSE(status.OK()) << "Commit with success=false should fail";
    EXPECT_FALSE(FileExists(tmpPath)) << "Temp file should be removed on failure";
    EXPECT_FALSE(FileExists(finalPath)) << "Final file should not exist on failure";
}

// ===== P1-1.2-T4: H2S 完整流程测试 =====

TEST_F(TransQueueH2STest, H2S_SingleShard_CreatesAndCommitsFile) {
    auto blockId = MakeTestBlockId(200);
    auto testData = CreateTestData(256, std::byte{0xAB});

    // 创建 ExtendedIoUnit
    TransQueue::ExtendedIoUnit unit(
        blockId,       // BlockId
        0,             // shardIndex
        testData.data(),  // srcAddr
        nullptr,       // dstAddr
        0,             // fileOffset
        testData.size(),  // ioSize
        1,             // TaskHandle
        TransTask::Type::DUMP,
        nullptr,       // waiter
        1,             // totalShards
        0              // currentShard
    );

    // 执行 H2S
    Status status = queue_.H2S(unit);

    EXPECT_TRUE(status.OK()) << "H2S should succeed: " << status.ToString();

    // 验证文件存在
    std::string finalPath = layout_.DataFilePath(blockId, false);
    EXPECT_TRUE(FileExists(finalPath)) << "Final file should exist after H2S";

    // 验证内容
    auto content = ReadFile(finalPath);
    EXPECT_EQ(content.size(), testData.size());
    EXPECT_EQ(content, testData);
}

TEST_F(TransQueueH2STest, H2S_MultipleShards_CreatesFileAfterLastShard) {
    auto blockId = MakeTestBlockId(201);
    const size_t numShards = 4;
    const size_t shardSize = 256;

    std::string finalPath = layout_.DataFilePath(blockId, false);

    // 模拟多个 shard 的写入
    for (size_t i = 0; i < numShards; ++i) {
        auto testData = CreateTestData(shardSize, std::byte(static_cast<uint8_t>(0x10 + i)));

        TransQueue::ExtendedIoUnit unit(
            blockId,
            i,
            testData.data(),
            nullptr,
            i * shardSize,
            testData.size(),
            1,
            TransTask::Type::DUMP,
            nullptr,
            numShards,   // 总 shard 数
            i           // 当前 shard 序号
        );

        Status status = queue_.H2S(unit);
        EXPECT_TRUE(status.OK()) << "H2S shard " << i << " should succeed";

        // 只有最后一个 shard 完成后，最终文件才存在
        if (i == numShards - 1) {
            EXPECT_TRUE(FileExists(finalPath)) << "Final file should exist after last shard";
        } else {
            // 中间状态，可能存在临时文件
            std::string tmpPath = layout_.DataFilePath(blockId, true);
            // 注意: 临时文件可能在最后一个 shard 写入后被删除
        }
    }

    // 验证最终文件内容
    auto content = ReadFile(finalPath);
    EXPECT_EQ(content.size(), numShards * shardSize);

    // 验证每个 shard 的数据
    for (size_t i = 0; i < numShards; ++i) {
        size_t offset = i * shardSize;
        std::byte expected = static_cast<std::byte>(0x10 + i);
        for (size_t j = 0; j < shardSize; ++j) {
            EXPECT_EQ(content[offset + j], expected)
                << "Data mismatch at shard " << i << " byte " << j;
        }
    }
}

// ===== P1-1.2-T5: 错误处理测试 =====

TEST_F(TransQueueH2STest, H2S_InvalidPath_ReturnsError) {
    // 修改配置为无效路径
    Config badConfig;
    badConfig.tensorSize = 256;
    badConfig.shardSize = 1024;
    badConfig.blockSize = 4096;
    badConfig.storageBackends = {"/nonexistent/path/12345678"};
    badConfig.deviceId = -1;

    SpaceLayout badLayout;
    badLayout.Setup(badConfig);

    HashSet<Detail::TaskHandle> badFailureSet;
    TransQueue badQueue;
    badQueue.Setup(badConfig, &badFailureSet, &badLayout);

    auto blockId = MakeTestBlockId(300);
    auto testData = CreateTestData(256, std::byte{0xCD});

    TransQueue::ExtendedIoUnit unit(
        blockId,
        0,
        testData.data(),
        nullptr,
        0,
        testData.size(),
        1,
        TransTask::Type::DUMP,
        nullptr,
        1,
        0
    );

    Status status = badQueue.H2S(unit);
    // 应该失败，因为路径无效
    EXPECT_FALSE(status.OK()) << "H2S to invalid path should fail";
}

}  // namespace UC::LustreStore
