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
#ifndef UNIFIEDCACHE_LUSTRE_STORE_CC_PARAM_VALIDATOR_H
#define UNIFIEDCACHE_LUSTRE_STORE_CC_PARAM_VALIDATOR_H

#include <cstdint>
#include <string>
#include "status/status.h"

/**
 * 参数校验框架 - v1.1 设计
 *
 * 提供统一的参数校验宏和错误码，用于所有 public API 的参数验证。
 *
 * 使用示例:
 *   Status MyFunction(const void* ptr, size_t num) {
 *       CHECK_NOT_NULL(ptr, "ptr");
 *       CHECK_RANGE(num, 1, 10000, "num");
 *       return Status::OK();
 *   }
 */

namespace UC::LustreStore {

// ===== 参数校验错误码范围: -50200 ~ -50203 =====

namespace ParamErrors {

/**
 * 参数校验错误码定义
 *
 * 错误码范围: -50200 ~ -50203 (LustreStore 专用)
 */
constexpr int32_t E_PARAM_NULL        = -50200;  // 参数为 null
constexpr int32_t E_PARAM_RANGE       = -50201;  // 参数超出范围
constexpr int32_t E_PARAM_CONSISTENCY = -50202;  // 参数一致性检查失败
constexpr int32_t E_PARAM_STATE       = -50203;  // 对象状态不允许操作

/**
 * 创建空指针错误
 * @param name 参数名称
 * @return Status 错误状态
 */
inline Status NullParam(const std::string& name)
{
    return Status(E_PARAM_NULL, name + " cannot be null");
}

/**
 * 创建参数范围错误
 * @param name 参数名称
 * @param value 实际值
 * @param min 最小值
 * @param max 最大值
 * @return Status 错误状态
 */
inline Status RangeError(const std::string& name, size_t value,
                         size_t min, size_t max)
{
    return Status(E_PARAM_RANGE,
                  name + "=" + std::to_string(value) +
                  " out of range [" + std::to_string(min) +
                  ", " + std::to_string(max) + "]");
}

/**
 * 创建一致性错误
 * @param message 错误消息
 * @return Status 错误状态
 */
inline Status ConsistencyError(const std::string& message)
{
    return Status(E_PARAM_CONSISTENCY, message);
}

/**
 * 创建状态错误
 * @param message 错误消息
 * @return Status 错误状态
 */
inline Status StateError(const std::string& message)
{
    return Status(E_PARAM_STATE, message);
}

} // namespace ParamErrors

// ===== 参数校验宏 =====

/**
 * 非空校验宏
 *
 * 检查指针是否为 nullptr，如果是则返回错误
 *
 * @param ptr 要检查的指针
 * @param name 参数名称（用于错误消息）
 */
#define CHECK_NOT_NULL(ptr, name) \
    do { \
        if ((ptr) == nullptr) { \
            UC_ERROR("Parameter '%s' cannot be null", name); \
            return UC::LustreStore::ParamErrors::NullParam(name); \
        } \
    } while(0)

/**
 * 条件校验宏
 *
 * 检查条件是否满足，不满足则返回错误
 *
 * @param condition 校验条件
 * @param message 错误消息
 */
#define CHECK_PARAM(condition, message) \
    do { \
        if (!(condition)) { \
            UC_ERROR("Parameter validation failed: %s", message); \
            return Status::InvalidParam(message); \
        } \
    } while(0)

/**
 * 范围校验宏
 *
 * 检查数值是否在指定范围内，超出则返回错误
 *
 * @param value 要检查的值
 * @param min 最小值（包含）
 * @param max 最大值（包含）
 * @param name 参数名称（用于错误消息）
 */
#define CHECK_RANGE(value, min, max, name) \
    do { \
        if ((value) < (min) || (value) > (max)) { \
            UC_ERROR("Parameter '%s'=%lu out of range [%lu, %lu]", \
                     name, (unsigned long)(value), \
                     (unsigned long)(min), (unsigned long)(max)); \
            return UC::LustreStore::ParamErrors::RangeError(name, value, min, max); \
        } \
    } while(0)

/**
 * 一致性校验宏
 *
 * 检查多个参数之间的一致性关系
 *
 * @param condition 一致性条件
 * @param message 错误消息
 */
#define CHECK_CONSISTENCY(condition, message) \
    do { \
        if (!(condition)) { \
            UC_ERROR("Parameter consistency check failed: %s", message); \
            return UC::LustreStore::ParamErrors::ConsistencyError(message); \
        } \
    } while(0)

/**
 * 状态校验宏
 *
 * 检查对象状态是否允许执行操作
 *
 * @param condition 状态条件
 * @param message 错误消息
 */
#define CHECK_STATE(condition, message) \
    do { \
        if (!(condition)) { \
            UC_ERROR("Object state check failed: %s", message); \
            return UC::LustreStore::ParamErrors::StateError(message); \
        } \
    } while(0)

/**
 * 绝对断言宏
 *
 * 用于检查不应该发生的条件（调试模式）
 *
 * @param condition 断言条件
 * @param message 错误消息
 */
#ifdef NDEBUG
#define CHECK_ASSERT(condition, message) ((void)0)
#else
#define CHECK_ASSERT(condition, message) \
    do { \
        if (!(condition)) { \
            UC_ERROR("Assertion failed: %s", message); \
            std::abort(); \
        } \
    } while(0)
#endif

} // namespace UC::LustreStore

#endif  // UNIFIEDCACHE_LUSTRE_STORE_CC_PARAM_VALIDATOR_H
