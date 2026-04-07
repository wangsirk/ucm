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
#ifndef UNIFIEDCACHE_STORE_LUSTRE_GLOBAL_CONFIG_H
#define UNIFIEDCACHE_STORE_LUSTRE_GLOBAL_CONFIG_H

#include <string>
#include <vector>
#include <cstdint>

/**
 * Lustre Store 全局配置
 * 
 * 编译时通过CMake传递的配置项
 */

// Git提交ID和构建类型（由CMake定义，使用条件保护避免重定义）
#ifndef UCM_COMMIT_ID
#define UCM_COMMIT_ID "unknown"
#endif

#ifndef UCM_BUILD_TYPE
#define UCM_BUILD_TYPE "Release"
#endif

// Lustre默认配置
#define LUSTRE_DEFAULT_STRIPE_COUNT 0       // 0表示使用文件系统默认值
#define LUSTRE_DEFAULT_STRIPE_SIZE 1048576  // 1MB默认条带大小
#define LUSTRE_MAX_PATH_LENGTH 4096         // 最大路径长度
#define LUSTRE_MAX_DATA_DIR_SHARD_BYTES 5   // 数据目录分片最大字节数 (最多支持 16^5 = 1048576 个分片目录)

// I/O配置
#define LUSTRE_DEFAULT_IO_DIRECT false      // 默认不使用直接I/O
#define LUSTRE_DEFAULT_TRANS_CONCURRENCY 16 // 默认传输并发数
#define LUSTRE_DEFAULT_LOOKUP_CONCURRENCY 8 // 默认查找并发数

// P2: 异步I/O配置
#define LUSTRE_DEFAULT_ASYNC_IO_BACKEND "threadpool"  // 默认异步I/O后端
#define LUSTRE_DEFAULT_QUEUE_DEPTH 256                // 默认队列深度

// P2: CPU亲和性配置
#define LUSTRE_DEFAULT_LOOKUP_CPU_CORES -1     // 默认不绑定CPU (-1=自动)
#define LUSTRE_DEFAULT_TRANS_CPU_CORES -1      // 默认不绑定CPU

namespace UC::LustreStore {

/**
 * Config - Lustre Store配置结构体
 */
struct Config {
    std::vector<std::string> storageBackends{};         // 存储后端路径列表
    int32_t deviceId{-1};                               // 设备ID，-1表示无设备
    size_t tensorSize{0};                               // 张量大小
    size_t shardSize{0};                                // 分片大小
    size_t blockSize{0};                                // 块大小
    bool ioDirect{false};                               // 是否使用直接IO
    size_t dataTransConcurrency{LUSTRE_DEFAULT_TRANS_CONCURRENCY};   // 数据传输并发度
    size_t lookupConcurrency{LUSTRE_DEFAULT_LOOKUP_CONCURRENCY};     // 查找并发度
    size_t timeoutMs{30000};                            // 操作超时时间，单位毫秒
    size_t dataDirShardBytes{0};                        // 数据目录分片字节数 (0=不分片，直接存data目录)

    // Lustre特有配置
    int stripeCount{LUSTRE_DEFAULT_STRIPE_COUNT};       // 条带数量
    size_t stripeSize{LUSTRE_DEFAULT_STRIPE_SIZE};      // 条带大小

    // P2: 异步I/O配置
    std::string asyncIoBackend{LUSTRE_DEFAULT_ASYNC_IO_BACKEND};  // 异步I/O后端类型
    size_t asyncIoQueueDepth{LUSTRE_DEFAULT_QUEUE_DEPTH};          // 异步I/O队列深度
    bool enableAsyncIo{true};                        // 是否启用异步I/O

    // P2: CPU亲和性配置
    int lookupCpuCores{LUSTRE_DEFAULT_LOOKUP_CPU_CORES};    // Lookup线程CPU亲和性 (-1=自动, -2=不绑定)
    int dataTransCpuCores{LUSTRE_DEFAULT_TRANS_CPU_CORES};  // DataTrans线程CPU亲和性
};

}  // namespace UC::LustreStore

#endif  // UNIFIEDCACHE_STORE_LUSTRE_GLOBAL_CONFIG_H
