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
#include <thread>
#include <vector>
#include <atomic>
#include "trans_task.h"
#include "store/detail/type/types.h"

namespace UC::LustreStore {

/**
 * P1-1: IoUnit 结构测试
 *
 * 测试范围:
 * - P1-1.0-T1: 构造函数
 * - P1-1.0-T2: 状态跟踪
 * - P1-1.0-T3: 线程安全
 * - P1-1.0-T4: 内存布局
 */

class IoUnitTest : public ::testing::Test {
protected:
    // 辅助函数: 创建测试用 BlockId
    Detail::BlockId MakeTestBlockId(uint32_t seed = 0) {
        Detail::BlockId bid;
        for (size_t i = 0; i < bid.size(); ++i) {
            bid[i] = static_cast<std::byte>((seed + i) % 256);
        }
        return bid;
    }
};

// ===== P1-1.0-T1: 构造函数测试 =====

TEST_F(IoUnitTest, DefaultConstruction_InitializesFieldsToZero) {
    IoUnit unit;

    EXPECT_EQ(unit.shardIndex, 0);
    EXPECT_EQ(unit.srcAddr, nullptr);
    EXPECT_EQ(unit.dstAddr, nullptr);
    EXPECT_EQ(unit.fileOffset, 0);
    EXPECT_EQ(unit.ioSize, 0);
    EXPECT_FALSE(unit.IsCompleted());
}

TEST_F(IoUnitTest, ParameterizedConstruction_SetsAllFields) {
    auto blockId = MakeTestBlockId(42);
    const size_t shardIndex = 5;
    void* srcAddr = reinterpret_cast<void*>(0x1000);
    void* dstAddr = reinterpret_cast<void*>(0x2000);
    const size_t fileOffset = 4096;
    const size_t ioSize = 1024;

    IoUnit unit(blockId, shardIndex, srcAddr, dstAddr, fileOffset, ioSize);

    EXPECT_EQ(unit.blockId, blockId);
    EXPECT_EQ(unit.shardIndex, shardIndex);
    EXPECT_EQ(unit.srcAddr, srcAddr);
    EXPECT_EQ(unit.dstAddr, dstAddr);
    EXPECT_EQ(unit.fileOffset, fileOffset);
    EXPECT_EQ(unit.ioSize, ioSize);
    EXPECT_FALSE(unit.IsCompleted());
}

TEST_F(IoUnitTest, CopyConstruction_CreatesIndependentCopy) {
    auto blockId = MakeTestBlockId(1);
    IoUnit original(blockId, 3, reinterpret_cast<void*>(0x1000),
                     reinterpret_cast<void*>(0x2000), 512, 256);

    IoUnit copy(original);

    // 验证值相等
    EXPECT_EQ(copy.blockId, original.blockId);
    EXPECT_EQ(copy.shardIndex, original.shardIndex);

    // 修改拷贝不应影响原对象
    copy.shardIndex = 99;
    EXPECT_EQ(original.shardIndex, 3);
}

// ===== P1-1.0-T2: 状态跟踪测试 =====

TEST_F(IoUnitTest, InitialState_IsNotCompleted) {
    IoUnit unit;
    EXPECT_FALSE(unit.IsCompleted());
}

TEST_F(IoUnitTest, MarkCompleted_SetsCompletedFlag) {
    IoUnit unit;
    unit.MarkCompleted(Status::OK());

    EXPECT_TRUE(unit.IsCompleted());
}

TEST_F(IoUnitTest, MarkCompleted_StoresResultStatus) {
    IoUnit unit;
    Status testStatus = Status::OK();
    unit.MarkCompleted(testStatus);

    // result 字段应该被设置
    EXPECT_TRUE(unit.IsCompleted());
}

TEST_F(IoUnitTest, Reset_ClearsAllFieldsExceptBlockId) {
    auto blockId = MakeTestBlockId(123);
    IoUnit unit(blockId, 5, reinterpret_cast<void*>(0x1000),
                     reinterpret_cast<void*>(0x2000), 1024, 512);

    unit.MarkCompleted(Status::OK());
    EXPECT_TRUE(unit.IsCompleted());

    unit.Reset();

    EXPECT_EQ(unit.shardIndex, 0);
    EXPECT_EQ(unit.srcAddr, nullptr);
    EXPECT_EQ(unit.dstAddr, nullptr);
    EXPECT_EQ(unit.fileOffset, 0);
    EXPECT_EQ(unit.ioSize, 0);
    EXPECT_FALSE(unit.IsCompleted());
    // blockId 保持不变
}

// ===== P1-1.0-T3: 线程安全测试 =====

TEST_F(IoUnitTest, ConcurrentMarkCompleted_DoesNotCrash) {
    IoUnit unit;

    auto markTask = [&unit]() {
        for (int i = 0; i < 100; ++i) {
            unit.MarkCompleted(Status::OK());
        }
    };

    std::vector<std::thread> threads;
    for (int i = 0; i < 10; ++i) {
        threads.emplace_back(markTask);
    }

    for (auto& t : threads) {
        t.join();
    }

    EXPECT_TRUE(unit.IsCompleted());
}

TEST_F(IoUnitTest, ConcurrentIsCompleted_DoesNotCrash) {
    auto blockId = MakeTestBlockId(1);
    IoUnit unit(blockId, 0, nullptr, nullptr, 0, 1024);

    std::atomic<int> checkCount{0};
    std::vector<std::thread> threads;

    auto checkTask = [&unit, &checkCount]() {
        for (int i = 0; i < 1000; ++i) {
            if (unit.IsCompleted()) {
                break;
            }
            checkCount++;
        }
    };

    for (int i = 0; i < 5; ++i) {
        threads.emplace_back(checkTask);
    }

    for (auto& t : threads) {
        t.join();
    }

    EXPECT_GT(checkCount.load(), 0);
}

// ===== P1-1.0-T4: 内存布局测试 =====

TEST_F(IoUnitTest, BlockId_SizeIs16Bytes) {
    Detail::BlockId bid = MakeTestBlockId();
    EXPECT_EQ(bid.size(), 16);
}

TEST_F(IoUnitTest, MultiShardIoUnit_Sequence_HasCorrectOffsets) {
    auto blockId = MakeTestBlockId(999);
    const size_t shardSize = 1024;
    const size_t numShards = 4;

    std::vector<IoUnit> units;
    for (size_t i = 0; i < numShards; ++i) {
        units.emplace_back(blockId, i,
            reinterpret_cast<void*>(i * shardSize),
            reinterpret_cast<void*>(i * shardSize),
            i * shardSize, shardSize);
    }

    for (size_t i = 0; i < numShards; ++i) {
        EXPECT_EQ(units[i].shardIndex, i);
        EXPECT_EQ(units[i].fileOffset, i * shardSize);
        EXPECT_EQ(units[i].ioSize, shardSize);
    }
}

// ===== 集成测试 =====

TEST_F(IoUnitTest, DumpScenario_CreatesCorrectIoUnit) {
    // 模拟 Dump 操作创建的 IoUnit
    auto blockId = MakeTestBlockId(123);
    const size_t shardSize = 4096;

    IoUnit unit(
        blockId,                    // BlockId
        0,                          // shardIndex
        reinterpret_cast<void*>(0x10000),  // srcAddr (设备内存)
        nullptr,                    // dstAddr (文件路径由其他层处理)
        0,                          // fileOffset
        shardSize                   // ioSize
    );

    EXPECT_EQ(unit.blockId, blockId);
    EXPECT_EQ(unit.shardIndex, 0);
    EXPECT_EQ(unit.ioSize, shardSize);
}

TEST_F(IoUnitTest, LoadScenario_CreatesCorrectIoUnit) {
    // 模拟 Load 操作创建的 IoUnit
    auto blockId = MakeTestBlockId(456);
    const size_t shardSize = 1024;

    IoUnit unit(
        blockId,                    // BlockId
        1,                          // shardIndex
        nullptr,                    // srcAddr (文件路径由其他层处理)
        reinterpret_cast<void*>(0x20000),  // dstAddr (设备内存)
        shardSize,                  // fileOffset
        shardSize                   // ioSize
    );

    EXPECT_EQ(unit.blockId, blockId);
    EXPECT_EQ(unit.shardIndex, 1);
    EXPECT_EQ(unit.fileOffset, shardSize);
    EXPECT_EQ(unit.ioSize, shardSize);
}

}  // namespace UC::LustreStore
