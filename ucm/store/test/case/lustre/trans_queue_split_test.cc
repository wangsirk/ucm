/**
 * MIT License
 *
 * Copyright (c) 2025 Huawei Technologies Co., Ltd. All rights reserved.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * THE above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES, MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */
#include <gtest/gtest.h>
#include <memory>
#include "trans_queue.h"
#include "trans_task.h"
#include "space_layout.h"
#include "global_config.h"
#include "template/hashset.h"
#include "thread/latch.h"
#include "store/detail/type/types.h"

namespace UC::LustreStore {

/**
 * P1-1.1: TransQueue 任务拆分测试
 *
 * 测试范围:
 * - SplitTask 基础功能
 * - 单 Shard 任务拆分
 * - 多 Shard 任务拆分
 * - 地址和偏移计算
 */

class TransQueueSplitTaskTest : public ::testing::Test {
protected:
    void SetUp() override {
        // 初始化配置
        config_.tensorSize = 256;
        config_.shardSize = 1024;
        config_.blockSize = 4096;  // 4 个 Shard
        config_.storageBackends = {"/tmp/lustre_test"};
        config_.deviceId = -1;

        // 初始化布局
        layout_.Setup(config_);

        // 初始化失败集合
        failureSet_ = std::make_unique<HashSet<Detail::TaskHandle>>();

        // 初始化队列
        queue_.Setup(config_, failureSet_.get(), &layout_);
    }

    // 辅助函数: 创建测试用 BlockId
    Detail::BlockId MakeTestBlockId(uint32_t seed = 0) {
        Detail::BlockId bid;
        for (size_t i = 0; i < bid.size(); ++i) {
            bid[i] = static_cast<std::byte>((seed + i) % 256);
        }
        return bid;
    }

    // 辅助函数: 创建测试 Shard
    Detail::Shard MakeTestShard(const Detail::BlockId& blockId, size_t index) {
        Detail::Shard shard;
        shard.owner = blockId;
        shard.index = index;
        // 模拟设备地址
        shard.addrs.push_back(reinterpret_cast<void*>(0x1000 + index * 0x1000));
        return shard;
    }

    Config config_;
    SpaceLayout layout_;
    std::unique_ptr<HashSet<Detail::TaskHandle>> failureSet_;
    TransQueue queue_;
};

// ===== P1-1.1-T1: 基础拆分测试 =====

TEST_F(TransQueueSplitTaskTest, SplitTask_EmptyTask_ReturnsEmptyVector) {
    TaskDesc desc;  // 空 TaskDesc
    TransTask task(TransTask::Type::LOAD, desc);

    auto units = queue_.SplitTask(task);

    EXPECT_TRUE(units.empty());
}

TEST_F(TransQueueSplitTaskTest, SplitTask_SingleShard_CreatesOneIoUnit) {
    auto blockId = MakeTestBlockId(42);
    TaskDesc desc;
    desc.push_back(MakeTestShard(blockId, 0));

    TransTask task(TransTask::Type::LOAD, desc);

    auto units = queue_.SplitTask(task);

    EXPECT_EQ(units.size(), 1);
    EXPECT_EQ(units[0]->blockId, blockId);
    EXPECT_EQ(units[0]->shardIndex, 0);
    EXPECT_EQ(units[0]->fileOffset, 0);
    EXPECT_EQ(units[0]->ioSize, config_.tensorSize);
    EXPECT_TRUE(units[0]->firstIo);
}

TEST_F(TransQueueSplitTaskTest, SplitTask_MultiShards_CreatesMultipleIoUnits) {
    auto blockId = MakeTestBlockId(123);
    const size_t numShards = 4;

    TaskDesc desc;
    for (size_t i = 0; i < numShards; ++i) {
        desc.push_back(MakeTestShard(blockId, i));
    }

    TransTask task(TransTask::Type::LOAD, desc);

    auto units = queue_.SplitTask(task);

    EXPECT_EQ(units.size(), numShards);

    // 验证每个 IoUnit
    for (size_t i = 0; i < numShards; ++i) {
        EXPECT_EQ(units[i]->blockId, blockId);
        EXPECT_EQ(units[i]->shardIndex, i);
        EXPECT_EQ(units[i]->fileOffset, i * config_.shardSize);
        EXPECT_EQ(units[i]->ioSize, config_.tensorSize);

        // 只有第一个被标记为 firstIo
        if (i == 0) {
            EXPECT_TRUE(units[i]->firstIo);
        } else {
            EXPECT_FALSE(units[i]->firstIo);
        }
    }
}

// ===== P1-1.1-T2: Dump 类型拆分测试 =====

TEST_F(TransQueueSplitTaskTest, SplitTask_DumpType_SetsCorrectAddresses) {
    auto blockId = MakeTestBlockId(99);
    TaskDesc desc;
    desc.push_back(MakeTestShard(blockId, 0));

    TransTask task(TransTask::Type::DUMP, desc);

    auto units = queue_.SplitTask(task);

    ASSERT_EQ(units.size(), 1);
    auto& unit = units[0];

    // Dump: srcAddr 应该指向设备内存
    EXPECT_NE(unit->srcAddr, nullptr);
    EXPECT_EQ(unit->dstAddr, nullptr);  // 文件路径由其他层处理
    EXPECT_EQ(unit->type, TransTask::Type::DUMP);
    EXPECT_EQ(unit->owner, task.id);
}

// ===== P1-1.1-T3: Load 类型拆分测试 =====

TEST_F(TransQueueSplitTaskTest, SplitTask_LoadType_SetsCorrectAddresses) {
    auto blockId = MakeTestBlockId(88);
    TaskDesc desc;
    desc.push_back(MakeTestShard(blockId, 0));

    TransTask task(TransTask::Type::LOAD, desc);

    auto units = queue_.SplitTask(task);

    ASSERT_EQ(units.size(), 1);
    auto& unit = units[0];

    // Load: dstAddr 应该指向设备内存
    EXPECT_EQ(unit->srcAddr, nullptr);  // 文件路径由其他层处理
    EXPECT_NE(unit->dstAddr, nullptr);
    EXPECT_EQ(unit->type, TransTask::Type::LOAD);
    EXPECT_EQ(unit->owner, task.id);
}

// ===== P1-1.1-T4: 文件偏移计算测试 =====

TEST_F(TransQueueSplitTaskTest, SplitTask_CalculatesCorrectFileOffsets) {
    auto blockId = MakeTestBlockId(55);
    const size_t shardSize = 2048;  // 与配置一致
    config_.shardSize = shardSize;

    // 重新配置
    SpaceLayout newLayout;
    newLayout.Setup(config_);

    HashSet<Detail::TaskHandle> newFailureSet;
    TransQueue newQueue;
    newQueue.Setup(config_, &newFailureSet, &newLayout);

    TaskDesc desc;
    const size_t numShards = 4;
    for (size_t i = 0; i < numShards; ++i) {
        desc.push_back(MakeTestShard(blockId, i));
    }

    TransTask task(TransTask::Type::LOAD, desc);

    auto units = newQueue.SplitTask(task);

    ASSERT_EQ(units.size(), numShards);

    // 验证文件偏移
    for (size_t i = 0; i < numShards; ++i) {
        EXPECT_EQ(units[i]->fileOffset, i * shardSize)
            << "Shard " << i << " should have file offset " << (i * shardSize);
    }
}

// ===== P1-1.1-T5: 多 Block 任务拆分测试 =====

TEST_F(TransQueueSplitTaskTest, SplitTask_MultipleBlocks_CreatesCorrectIoUnits) {
    const size_t numBlocks = 3;
    const size_t shardsPerBlock = 2;

    TaskDesc desc;
    for (size_t b = 0; b < numBlocks; ++b) {
        auto blockId = MakeTestBlockId(b + 100);
        for (size_t s = 0; s < shardsPerBlock; ++s) {
            desc.push_back(MakeTestShard(blockId, s));
        }
    }

    TransTask task(TransTask::Type::LOAD, desc);

    auto units = queue_.SplitTask(task);

    EXPECT_EQ(units.size(), numBlocks * shardsPerBlock);

    // 验证每个 Block 的 Shard 索引
    for (size_t i = 0; i < units.size(); ++i) {
        size_t expectedBlockIndex = i / shardsPerBlock;
        size_t expectedShardIndex = i % shardsPerBlock;
        EXPECT_EQ(units[i]->shardIndex, expectedShardIndex);
    }
}

// ===== 边界条件测试 =====

TEST_F(TransQueueSplitTaskTest, SplitTask_ShardWithEmptyAddrs_HandlesGracefully) {
    auto blockId = MakeTestBlockId(77);
    Detail::Shard shard;
    shard.owner = blockId;
    shard.index = 0;
    // shard.addrs 为空

    TaskDesc desc;
    desc.push_back(shard);

    TransTask task(TransTask::Type::LOAD, desc);

    // 不应崩溃
    auto units = queue_.SplitTask(task);

    EXPECT_EQ(units.size(), 1);
    EXPECT_EQ(units[0]->srcAddr, nullptr);
    EXPECT_EQ(units[0]->dstAddr, nullptr);
}

}  // namespace UC::LustreStore
