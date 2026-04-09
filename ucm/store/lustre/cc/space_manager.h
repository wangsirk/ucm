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
#ifndef UNIFIEDCACHE_LUSTRE_STORE_CC_SPACE_MANAGER_H
#define UNIFIEDCACHE_LUSTRE_STORE_CC_SPACE_MANAGER_H

#include "global_config.h"
#include "space_layout.h"
#include "lustre_thread_pool.h"
#include "thread/latch.h"
#include <memory>

namespace UC::LustreStore {

/**
 * SpaceManager - Lustre空间管理器
 * 
 * 提供并发的Block查找能力
 * 未来将支持Lustre特有的OST感知查找优化
 * 
 * P2 优化：统一使用 LustreThreadPool 进行并发查询
 */
class SpaceManager {
    SpaceLayout layout_;
    std::unique_ptr<LustreThreadPool> threadPool_;
    size_t lookupConcurrency_{8};

public:
    /**
     * 初始化空间管理器
     * @param config 配置参数
     * @return 状态码
     */
    Status Setup(const Config& config);

    /**
     * 批量查找Block是否存在
     * @param blocks Block ID数组
     * @param num Block数量
     * @return 存在性位图
     */
    std::vector<uint8_t> Lookup(const Detail::BlockId* blocks, size_t num);

    /**
     * 前缀查找，返回第一个缺失的Block索引
     * @param blocks Block ID数组（按前缀顺序）
     * @param num Block数量
     * @return 第一个缺失Block的索引，-1表示全部存在
     */
    ssize_t LookupOnPrefix(const Detail::BlockId* blocks, size_t num);

    /**
     * 获取空间布局
     * @return 空间布局指针
     */
    const SpaceLayout* GetLayout() const { return &layout_; }

private:
    /**
     * 单个Block查找
     * @param block Block ID
     * @return 1=存在, 0=不存在
     */
    uint8_t LookupSingle(const Detail::BlockId* block);
};

}  // namespace UC::LustreStore

#endif
