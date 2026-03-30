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
 * */
#ifndef UNIFIEDCACHE_POSIX_STORE_CC_GLOBAL_CONFIG_H
#define UNIFIEDCACHE_POSIX_STORE_CC_GLOBAL_CONFIG_H

#include <string>
#include <vector>

/*
该文件的主要作用是：
定义全局结构配置体
*/

namespace UC::PosixStore {

struct Config {
    std::vector<std::string> storageBackends{};         // 存储后端路径列表
    int32_t deviceId{-1};                               // 设备ID，-1表示无设备
    size_t tensorSize{0};                               // 张量大小
    size_t shardSize{0};                                // 分片大小
    size_t blockSize{0};                                // 块大小   
    bool ioDirect{false};                               // 是否使用直接IO  
    size_t dataTransConcurrency{8};                     // 数据传输并发度
    size_t lookupConcurrency{8};                        // 查找并发度
    size_t timeoutMs{30000};                            // 操作超时时间，单位毫秒
    size_t dataDirShardBytes{3};                        // 数据目录分片字节数，默认3表示每256个文件一个目录
};

}  // namespace UC::PosixStore

#endif
