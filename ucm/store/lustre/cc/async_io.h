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
#ifndef UNIFIEDCACHE_STORE_LUSTRE_CC_ASYNC_IO_H
#define UNIFIEDCACHE_STORE_LUSTRE_CC_ASYNC_IO_H

#include <memory>
#include <functional>
#include <cstdint>
#include <atomic>
#include "status/status.h"

namespace UC::LustreStore {

/**
 * I/O 请求描述符
 */
struct IoRequest {
    int fd{-1};              // 文件描述符
    void* buffer{nullptr};   // 缓冲区地址
    size_t size{0};          // I/O 大小
    off64_t offset{0};       // 文件偏移量
    bool isWrite{false};     // true=写, false=读

    // 完成回调 (使用 Result 避免异步信号安全问题)
    enum class Result {
        SUCCESS,
        FAILURE,
        PARTIAL
    };
    std::function<void(Result, ssize_t)> callback;

    IoRequest() = default;
    IoRequest(int f, void* buf, size_t sz, off64_t off, bool write,
              std::function<void(Result, ssize_t)> cb)
        : fd(f), buffer(buf), size(sz), offset(off), isWrite(write), callback(cb) {}
};

/**
 * 异步 I/O 适配器接口 (P2)
 *
 * 提供统一的异步 I/O 接口，支持多种后端实现：
 * - ThreadPoolBackend: 线程池后端 (兜底方案，所有平台可用)
 * - 未来可扩展: IoUringBackend (Linux 5.1+), LibaioBackend
 */
class AsyncIOAdapter {
public:
    virtual ~AsyncIOAdapter() = default;

    /**
     * 初始化异步 I/O 后端
     * @param queueDepth 队列深度 (同时进行的 I/O 数量)
     * @param sqThreadCpu Submission Queue 线程绑定的 CPU (-1 = 不绑定)
     */
    virtual Status Setup(size_t queueDepth = 256, int sqThreadCpu = -1) = 0;

    /**
     * 提交读请求
     */
    virtual Status SubmitRead(const IoRequest& req) = 0;

    /**
     * 提交写请求
     */
    virtual Status SubmitWrite(const IoRequest& req) = 0;

    /**
     * 处理完成的 I/O 请求
     * @param timeoutMs 超时时间 (毫秒)，0 = 非阻塞，-1 = 无限等待
     * @return 处理的完成数量
     */
    virtual size_t ProcessCompletion(int timeoutMs = 0) = 0;

    /**
     * 获取队列深度
     */
    virtual size_t GetQueueDepth() const = 0;

    /**
     * 获取待处理请求数量
     */
    virtual size_t GetPendingCount() const = 0;

    /**
     * 创建异步 I/O 适配器实例
     *
     * 优先选择策略：
     * 1. 如果配置指定后端类型，使用指定后端
     * 2. 否则使用 ThreadPoolBackend (最兼容)
     *
     * @param backendType 后端类型 ("threadpool", "ioruring", "libaio")
     * @return 适配器实例
     */
    static std::unique_ptr<AsyncIOAdapter> Create(const std::string& backendType = "threadpool");
};

/**
 * 线程池后端实现
 *
 * 使用线程池模拟异步 I/O，特点：
 * - 所有平台兼容
 * - 适合中等规模的 I/O 并发
 * - 作为其他后端不可用时的回退方案
 */
class ThreadPoolBackend : public AsyncIOAdapter {
public:
    ThreadPoolBackend();
    ~ThreadPoolBackend() override;

    // 禁止拷贝
    ThreadPoolBackend(const ThreadPoolBackend&) = delete;
    ThreadPoolBackend& operator=(const ThreadPoolBackend&) = delete;

    Status Setup(size_t queueDepth = 256, int sqThreadCpu = -1) override;
    Status SubmitRead(const IoRequest& req) override;
    Status SubmitWrite(const IoRequest& req) override;
    size_t ProcessCompletion(int timeoutMs = 0) override;
    size_t GetQueueDepth() const override { return queueDepth_; }
    size_t GetPendingCount() const override { return pendingCount_.load(); }

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;

    size_t queueDepth_{256};
    std::atomic<size_t> pendingCount_{0};

    Status SubmitIo(const IoRequest& req);
};

} // namespace UC::LustreStore

#endif // UNIFIEDCACHE_STORE_LUSTRE_CC_ASYNC_IO_H
