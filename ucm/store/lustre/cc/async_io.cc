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
#include "async_io.h"
#include "logger/logger.h"
#include <thread>
#include <mutex>
#include <condition_variable>
#include <queue>
#include <vector>
#include <atomic>
#include <unistd.h>
#include <fcntl.h>

namespace UC::LustreStore {

// ============================================================================
// AsyncIOAdapter::Create
// ============================================================================

std::unique_ptr<AsyncIOAdapter> AsyncIOAdapter::Create(const std::string& backendType)
{
    if (backendType == "threadpool" || backendType.empty()) {
        return std::make_unique<ThreadPoolBackend>();
    }
    // 未来扩展：io_uring, libaio 等
    UC_WARN("Unknown backend type '{}', falling back to ThreadPoolBackend", backendType);
    return std::make_unique<ThreadPoolBackend>();
}

// ============================================================================
// ThreadPoolBackend 实现
// ============================================================================

struct ThreadPoolBackend::Impl {
    // 待处理的 I/O 请求队列
    std::queue<IoRequest> requestQueue;
    std::mutex queueMutex;
    std::condition_variable queueCV;

    // 工作线程
    std::vector<std::thread> workers;
    std::atomic<bool> running{false};
    std::atomic<size_t> activeWorkers{0};

    // 完成回调队列 (避免在工作线程中直接执行回调)
    struct Completion {
        std::function<void(IoRequest::Result, ssize_t)> callback;
        IoRequest::Result result;
        ssize_t bytesTransferred;
    };
    std::queue<Completion> completionQueue;
    std::mutex completionMutex;
    std::condition_variable completionCV;  // 用于通知完成事件

    // 完成处理线程 (持续处理完成队列)
    std::thread completionThread;

    // CPU 亲和性
    int cpuAffinity{-1};  // -1 表示不绑定

    // 完成处理循环
    void CompletionLoop(ThreadPoolBackend* adapter)
    {
        UC_DEBUG("ThreadPoolBackend completion thread started");

        while (running.load() || !completionQueue.empty()) {
            // 等待完成事件，超时 100ms 检查 running 状态
            adapter->ProcessCompletion(100);
        }

        // 最后处理一次剩余的完成事件
        while (!completionQueue.empty()) {
            adapter->ProcessCompletion(0);
        }

        UC_DEBUG("ThreadPoolBackend completion thread stopped");
    }

    // 同步 I/O 执行 (在工作线程中调用)
    static ssize_t ExecuteSyncIo(const IoRequest& req)
    {
        ssize_t result = -1;
        if (req.isWrite) {
            // pwrite: 线程安全的写操作
            result = pwrite(req.fd, req.buffer, req.size, req.offset);
        } else {
            // pread: 线程安全的读操作
            result = pread(req.fd, req.buffer, req.size, req.offset);
        }
        return result;
    }

    // 设置 CPU 亲和性
    static void SetCpuAffinity(int cpuId)
    {
        if (cpuId < 0) {
            return;  // 不绑定
        }

        cpu_set_t cpuset;
        CPU_ZERO(&cpuset);
        CPU_SET(cpuId, &cpuset);

        pthread_t currentThread = pthread_self();
        int rc = pthread_setaffinity_np(currentThread, sizeof(cpu_set_t), &cpuset);
        if (rc != 0) {
            UC_WARN("Failed to set CPU affinity to CPU {}: {}", cpuId, strerror(rc));
        } else {
            UC_DEBUG("Worker thread bound to CPU {}", cpuId);
        }
    }

    // 工作线程主函数
    void WorkerFunc(size_t workerId, int cpuId)
    {
        // 设置 CPU 亲和性
        if (cpuId >= 0) {
            SetCpuAffinity(cpuId);
        }

        UC_DEBUG("ThreadPoolBackend worker {} started", workerId);

        while (running.load()) {
            IoRequest req;

            // 获取请求
            {
                std::unique_lock<std::mutex> lock(queueMutex);
                queueCV.wait(lock, [this] {
                    return !requestQueue.empty() || !running.load();
                });

                if (!running.load() && requestQueue.empty()) {
                    break;  // 退出
                }

                if (requestQueue.empty()) {
                    continue;
                }

                req = std::move(requestQueue.front());
                requestQueue.pop();
            }

            // 标记开始执行 I/O
            activeWorkers.fetch_add(1, std::memory_order_release);

            // 执行 I/O
            ssize_t bytesTransferred = ExecuteSyncIo(req);
            IoRequest::Result result;

            if (bytesTransferred < 0) {
                result = IoRequest::Result::FAILURE;
                UC_ERROR("I/O failed: fd={}, isWrite={}, error={}",
                         req.fd, req.isWrite, strerror(errno));
            } else if (static_cast<size_t>(bytesTransferred) != req.size) {
                result = IoRequest::Result::PARTIAL;
                UC_WARN("Partial I/O: fd={}, expected={}, actual={}",
                        req.fd, req.size, bytesTransferred);
            } else {
                result = IoRequest::Result::SUCCESS;
            }

            // 将完成回调放入完成队列
            {
                std::lock_guard<std::mutex> lock(completionMutex);
                completionQueue.push({req.callback, result, bytesTransferred});
            }
            // 等待线程可能有完成事件
            completionCV.notify_one();

            // I/O 完成，递减活跃工作线程计数
            activeWorkers.fetch_sub(1, std::memory_order_release);
        }

        UC_DEBUG("ThreadPoolBackend worker {} stopped", workerId);
    }

    // 启动工作线程
    Status StartWorkers(size_t numWorkers, int cpuAffinity, ThreadPoolBackend* adapter)
    {
        running.store(true);

        for (size_t i = 0; i < numWorkers; ++i) {
            // 如果指定了 CPU 亲和性，尝试均匀分布
            int workerCpu = -1;
            if (cpuAffinity >= 0) {
                size_t hwConcurrency = std::thread::hardware_concurrency();
                if (hwConcurrency == 0) {
                    hwConcurrency = 4;  // 防止除以零
                }
                workerCpu = (cpuAffinity + i) % hwConcurrency;
            }

            workers.emplace_back([this, i, workerCpu]() {
                WorkerFunc(i, workerCpu);
            });
        }

        // 启动完成处理线程
        completionThread = std::thread([this, adapter]() {
            CompletionLoop(adapter);
        });

        UC_INFO("ThreadPoolBackend started {} workers", numWorkers);
        return Status::OK();
    }

    // 停止工作线程
    void StopWorkers()
    {
        running.store(false);
        queueCV.notify_all();
        completionCV.notify_all();  // 通知完成处理线程

        for (auto& worker : workers) {
            if (worker.joinable()) {
                worker.join();
            }
        }
        workers.clear();

        // 等待完成处理线程退出
        if (completionThread.joinable()) {
            completionThread.join();
        }
    }
};

ThreadPoolBackend::ThreadPoolBackend()
    : impl_(std::make_unique<Impl>())
{}

ThreadPoolBackend::~ThreadPoolBackend()
{
    if (impl_) {
        impl_->StopWorkers();
    }
}

Status ThreadPoolBackend::Setup(size_t queueDepth, int sqThreadCpu)
{
    queueDepth_ = queueDepth;
    impl_->cpuAffinity = sqThreadCpu;

    // 工作线程数量：基于 CPU 核心数的合理限制
    size_t hardwareConcurrency = std::thread::hardware_concurrency();
    // 如果 hardwareConcurrency 返回 0，使用默认值 4
    if (hardwareConcurrency == 0) {
        hardwareConcurrency = 4;
        UC_WARN("std::thread::hardware_concurrency() returned 0, using default value 4");
    }
    size_t maxWorkers = std::max(size_t{4}, hardwareConcurrency * 2);  // 合理上限

    size_t numWorkers = std::min({queueDepth, maxWorkers, hardwareConcurrency});

    // 确保至少有 1 个工作线程
    numWorkers = std::max(size_t{1}, numWorkers);

    return impl_->StartWorkers(numWorkers, sqThreadCpu, this);
}

Status ThreadPoolBackend::SubmitRead(const IoRequest& req)
{
    return SubmitIo(req);
}

Status ThreadPoolBackend::SubmitWrite(const IoRequest& req)
{
    return SubmitIo(req);
}

Status ThreadPoolBackend::SubmitIo(const IoRequest& req)
{
    {
        std::lock_guard<std::mutex> lock(impl_->queueMutex);

        // 检查队列是否已满
        if (impl_->requestQueue.size() >= queueDepth_) {
            UC_WARN("ThreadPoolBackend queue full (size >= {})", queueDepth_);
            // 同步执行作为回退
            ssize_t result = Impl::ExecuteSyncIo(req);
            if (result < 0) {
                return Status::OsApiError("I/O failed in fallback mode");
            }
            return Status::OK();
        }

        impl_->requestQueue.push(req);
        pendingCount_++;
    }

    // 通知一个工作线程
    impl_->queueCV.notify_one();

    return Status::OK();
}

size_t ThreadPoolBackend::ProcessCompletion(int timeoutMs)
{
    std::unique_lock<std::mutex> lock(impl_->completionMutex);

    // 如果 timeoutMs > 0，等待指定时间或直到有完成事件
    if (timeoutMs > 0 && impl_->completionQueue.empty()) {
        if (timeoutMs == -1) {
            // 无限等待
            impl_->completionCV.wait(lock, [this] {
                return !impl_->completionQueue.empty();
            });
        } else {
            // 超时等待
            impl_->completionCV.wait_for(lock, std::chrono::milliseconds(timeoutMs), [this] {
                return !impl_->completionQueue.empty();
            });
        }
    }

    size_t processed = 0;
    while (!impl_->completionQueue.empty()) {
        auto& completion = impl_->completionQueue.front();

        // 执行回调
        if (completion.callback) {
            completion.callback(completion.result, completion.bytesTransferred);
        }

        impl_->completionQueue.pop();
        processed++;
        pendingCount_--;
    }

    return processed;
}

} // namespace UC::LustreStore
