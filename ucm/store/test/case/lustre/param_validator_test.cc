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
#include "param_validator.h"

namespace UC::LustreStore {

class ParamValidatorTest : public ::testing::Test {
protected:
    // 测试辅助函数
    Status TestNullCheck(const void* ptr) {
        CHECK_NOT_NULL(ptr, "testPtr");
        return Status::OK();
    }

    Status TestRangeCheck(size_t value, size_t min, size_t max) {
        CHECK_RANGE(value, min, max, "testValue");
        return Status::OK();
    }

    Status TestParamCheck(bool condition) {
        CHECK_PARAM(condition, "test condition failed");
        return Status::OK();
    }
};

// ===== Null 指针校验测试 =====

TEST_F(ParamValidatorTest, NullCheck_WithNullPtr_ReturnsInvalidParam) {
    auto result = TestNullCheck(nullptr);
    EXPECT_TRUE(result.Failure());
    EXPECT_EQ(result.Underlying(), ParamErrors::E_PARAM_NULL);
}

TEST_F(ParamValidatorTest, NullCheck_WithValidPtr_ReturnsOK) {
    int value = 42;
    auto result = TestNullCheck(&value);
    EXPECT_TRUE(result.Success());
}

// ===== 范围校验测试 =====

TEST_F(ParamValidatorTest, RangeCheck_ValueInRange_ReturnsOK) {
    auto result = TestRangeCheck(50, 0, 100);
    EXPECT_TRUE(result.Success());
}

TEST_F(ParamValidatorTest, RangeCheck_ValueBelowMin_ReturnsInvalidParam) {
    auto result = TestRangeCheck(5, 10, 100);
    EXPECT_TRUE(result.Failure());
    EXPECT_EQ(result.Underlying(), ParamErrors::E_PARAM_RANGE);
}

TEST_F(ParamValidatorTest, RangeCheck_ValueAboveMax_ReturnsInvalidParam) {
    auto result = TestRangeCheck(150, 0, 100);
    EXPECT_TRUE(result.Failure());
    EXPECT_EQ(result.Underlying(), ParamErrors::E_PARAM_RANGE);
}

// ===== 条件校验测试 =====

TEST_F(ParamValidatorTest, ParamCheck_ConditionTrue_ReturnsOK) {
    auto result = TestParamCheck(true);
    EXPECT_TRUE(result.Success());
}

TEST_F(ParamValidatorTest, ParamCheck_ConditionFalse_ReturnsInvalidParam) {
    auto result = TestParamCheck(false);
    EXPECT_TRUE(result.Failure());
}

// ===== 错误码工厂函数测试 =====

TEST(ParamErrorsTest, NullParam_ContainsName) {
    auto status = ParamErrors::NullParam("testParam");
    EXPECT_TRUE(status.Failure());
    EXPECT_TRUE(status.ToString().find("testParam") != std::string::npos);
}

TEST(ParamErrorsTest, RangeError_ContainsDetails) {
    auto status = ParamErrors::RangeError("count", 150, 0, 100);
    EXPECT_TRUE(status.Failure());
    std::string msg = status.ToString();
    EXPECT_TRUE(msg.find("count") != std::string::npos);
    EXPECT_TRUE(msg.find("150") != std::string::npos);
}

TEST(ParamErrorsTest, ConsistencyError_ContainsMessage) {
    auto status = ParamErrors::ConsistencyError("values don't match");
    EXPECT_TRUE(status.Failure());
    EXPECT_TRUE(status.ToString().find("values don't match") != std::string::npos);
}

}  // namespace UC::LustreStore
