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
#ifndef UNIFIEDCACHE_STORE_LUSTRE_CC_LUSTRE_THREAD_POOL_H
#define UNIFIEDCACHE_STORE_LUSTRE_CC_LUSTRE_THREAD_POOL_H

#include <functional>
#include <memory>
#include <vector>
#include <cstdint>
#include "status/status.h"

namespace UC::LustreStore {

/**
 * 分层线程池配置 (P2)
 *
 * LustreStore 使用两种类型的线程池：
 * 1. LookupThreadPool: 用于文件查找操作 (CPU 密集型)
 * 2. DataTransThreadPool: 用于数据传输操作 (I/O 密集型)
 */
struct ThreadPoolConfig {
    // Lookup 线程池配置
    size_t lookupConcurrency{8};     // Lookup 线程数量
    int lookupCpuCores{-1};          // Lookup CPU 亲和性 (-1 = 自动)

    // DataTrans 线程池配置
    size_t dataTransConcurrency{16}; // DataTrans 线程数量
    int dataTransCpuCores{-1};       // DataTrans CPU 亲和性 (-1 = 自动)

    // 通用配置
    size_t queueDepth{256};          // 任务队列深度
    int timeoutMs{30000};            // 任务超时时间

    // 获取默认配置
    static ThreadPoolConfig Default() {
        return ThreadPoolConfig{};
    }

    // 验证配置
    Status Validate() const {
        if (lookupConcurrency == 0 || dataTransConcurrency == 0) {
            return Status::InvalidParam("Thread pool concurrency cannot be zero");
        }
        if (lookupConcurrency > 128 || dataTransConcurrency > 128) {
            return Status::InvalidParam("Thread pool concurrency too large (max 128)");
        }
        if (queueDepth == 0 || queueDepth > 10000) {
            return Status::InvalidParam("Invalid queue depth");
        }
        return Status::OK();
    }
};

/**
 * 通用任务接口
 */
class Task {
public:
    virtual ~Task() = default;
    virtual void Execute() = 0;
};

/**
 * 任务包装器 - 支持任意可调用对象
 */
template<typename F>
class FunctionTask : public Task {
public:
    explicit FunctionTask(F&& func) : func_(std::move(func)) {}
    void Execute() override { func_(); }

private:
    F func_;
};

/**
 * 分层线程池 (P2)
 *
 * 提供两种独立的线程池：
 * 1. Lookup 线程池：处理文件存在性检查、前缀查找等操作
 * 2. DataTrans 线程池：处理数据读写操作
 *
 * 特点：
 * - 独立的线程池，避免相互干扰
 * - 支持 CPU 亲和性绑定
 * - 任务队列管理
 * - 优雅关闭
 */
class LustreThreadPool {
public:
    /**
     * 工作线程类型
     */
    enum class WorkerType {
        LOOKUP,     // 查找工作线程
        DATATRANS   // 数据传输工作线程
    };

    LustreThreadPool();
    ~LustreThreadPool();

    // 禁止拷贝和移动
    LustreThreadPool(const LustreThreadPool&) = delete;
    LustreThreadPool& operator=(const LustreThreadPool&) = delete;
    LustreThreadPool(LustreThreadPool&&) = delete;
    LustreThreadPool& operator=(LustreThreadPool&&) = delete;

    /**
     * 初始化线程池
     * @param config 线程池配置
     */
    Status Setup(const ThreadPoolConfig& config);

    /**
     * 提交任务到指定线程池
     * @param task 任务对象
     * @param type 工作线程类型
     */
    Status Submit(std::unique_ptr<Task> task, WorkerType type);

    /**
     * 提交函数任务 (便捷方法)
     * @param func 可调用对象
     * @param type 工作线程类型
     */
    template<typename F>
    Status SubmitFunc(F&& func, WorkerType type) {
        auto task = std::make_unique<FunctionTask<F>>(std::forward<F>(func));
        return Submit(std::move(task), type);
    }

    /**
     * 等待所有任务完成
     * @param timeoutMs 超时时间 (毫秒)，-1 表示无限等待
     */
    Status WaitForAll(int timeoutMs = -1);

    /**
     * 获取待处理任务数量
     */
    size_t GetPendingCount(WorkerType type) const;

    /**
     * 获取工作线程数量
     */
    size_t GetWorkerCount(WorkerType type) const;

    /**
     * 关闭线程池
     */
    void Shutdown();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace UC::LustreStore

#endif // UNIFIEDCACHE_STORE_LUSTRE_CC_LUSTRE_THREAD_POOL_H
