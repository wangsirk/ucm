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
#include "lustre_thread_pool.h"
#include "logger/logger.h"
#include <thread>
#include <mutex>
#include <condition_variable>
#include <queue>
#include <atomic>
#include <pthread.h>
#include <sched.h>

namespace UC::LustreStore {

// ============================================================================
// WorkerPool - 单一类型的工作线程池
// ============================================================================

class WorkerPool {
public:
    WorkerPool(const std::string& name, size_t numWorkers, int cpuAffinity, size_t queueDepth)
        : name_(name), numWorkers_(numWorkers), cpuAffinity_(cpuAffinity),
          queueDepth_(queueDepth), running_(false), activeWorkers_(0)
    {}

    ~WorkerPool() {
        Shutdown();
    }

    // 初始化并启动工作线程
    Status Start() {
        std::lock_guard<std::mutex> lock(mutex_);
        if (running_.load()) {
            return Status::Error("WorkerPool already started");
        }

        running_.store(true);

        for (size_t i = 0; i < numWorkers_; ++i) {
            // 计算 CPU 亲和性
            int workerCpu = -1;
            if (cpuAffinity_ >= 0) {
                workerCpu = (cpuAffinity_ + i) % std::thread::hardware_concurrency();
            } else if (cpuAffinity_ == -2) {
                // -2 表示自动分配：尽量均匀分布到所有 CPU
                workerCpu = i % std::thread::hardware_concurrency();
            }

            workers_.emplace_back([this, i, workerCpu]() {
                WorkerFunc(i, workerCpu);
            });
        }

        UC_INFO("{} started with {} workers", name_, numWorkers_);
        return Status::OK();
    }

    // 提交任务
    Status Submit(std::unique_ptr<Task> task) {
        std::unique_lock<std::mutex> lock(mutex_);

        // 检查队列是否已满
        if (taskQueue_.size() >= queueDepth_) {
            UC_WARN("{} task queue full (size >= {})", name_, queueDepth_);
            return Status::Error("Task queue full");
        }

        taskQueue_.push(std::move(task));
        lock.unlock();
        cv_.notify_one();

        return Status::OK();
    }

    // 等待所有任务完成
    Status WaitForAll(int timeoutMs = -1) {
        std::unique_lock<std::mutex> lock(mutex_);

        if (timeoutMs < 0) {
            // 无限等待
            cv_.wait(lock, [this] {
                return taskQueue_.empty() && activeWorkers_.load() == 0;
            });
        } else {
            // 超时等待
            bool success = cv_.wait_for(lock, std::chrono::milliseconds(timeoutMs), [this] {
                return taskQueue_.empty() && activeWorkers_.load() == 0;
            });

            if (!success) {
                return Status::Timeout();
            }
        }

        return Status::OK();
    }

    // 获取待处理任务数量
    size_t GetPendingCount() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return taskQueue_.size();
    }

    // 获取工作线程数量
    size_t GetWorkerCount() const {
        return workers_.size();
    }

    // 关闭线程池
    void Shutdown() {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (!running_.load()) {
                return;
            }
            running_.store(false);
        }

        cv_.notify_all();

        for (auto& worker : workers_) {
            if (worker.joinable()) {
                worker.join();
            }
        }
        workers_.clear();

        // 清空任务队列
        std::lock_guard<std::mutex> lock(mutex_);
        while (!taskQueue_.empty()) {
            taskQueue_.pop();
        }

        UC_INFO("{} shutdown complete", name_);
    }

private:
    // 设置 CPU 亲和性
    static void SetCpuAffinity(int cpuId) {
        if (cpuId < 0) {
            return;
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
    void WorkerFunc(size_t workerId, int cpuId) {
        // 设置线程名称 (Linux)
        pthread_setname_np(pthread_self(), name_.substr(0, 15).c_str());

        // 设置 CPU 亲和性
        SetCpuAffinity(cpuId);

        UC_DEBUG("{} worker {} started (CPU affinity: {})", name_, workerId, cpuId);

        while (running_.load()) {
            std::unique_ptr<Task> task;

            {
                std::unique_lock<std::mutex> lock(mutex_);
                cv_.wait(lock, [this] {
                    return !taskQueue_.empty() || !running_.load();
                });

                if (!running_.load()) {
                    break;
                }

                if (taskQueue_.empty()) {
                    continue;
                }

                task = std::move(taskQueue_.front());
                taskQueue_.pop();
                activeWorkers_.fetch_add(1, std::memory_order_release);
            }

            // 执行任务
            try {
                if (task) {
                    task->Execute();
                }
            } catch (const std::exception& e) {
                UC_ERROR("{} worker {} exception: {}", name_, workerId, e.what());
            } catch (...) {
                UC_ERROR("{} worker {} unknown exception", name_, workerId);
            }

            activeWorkers_.fetch_sub(1, std::memory_order_release);

            // 通知可能在等待的主线程
            cv_.notify_one();
        }

        UC_DEBUG("{} worker {} stopped", name_, workerId);
    }

    std::string name_;
    size_t numWorkers_;
    int cpuAffinity_;
    size_t queueDepth_;

    std::atomic<bool> running_;
    std::atomic<size_t> activeWorkers_;

    std::vector<std::thread> workers_;
    std::queue<std::unique_ptr<Task>> taskQueue_;
    mutable std::mutex mutex_;
    std::condition_variable cv_;
};

// ============================================================================
// LustreThreadPool::Impl
// ============================================================================

struct LustreThreadPool::Impl {
    std::unique_ptr<WorkerPool> lookupPool;
    std::unique_ptr<WorkerPool> dataTransPool;
    ThreadPoolConfig config;
    bool initialized{false};

    Status Setup(const ThreadPoolConfig& cfg) {
        if (initialized) {
            return Status::Error("ThreadPool already initialized");
        }

        config = cfg;

        // 创建 Lookup 线程池
        lookupPool = std::make_unique<WorkerPool>(
            "LookupPool",
            config.lookupConcurrency,
            config.lookupCpuCores,
            config.queueDepth
        );

        Status s = lookupPool->Start();
        if (s.Failure()) {
            UC_ERROR("Failed to start Lookup thread pool: {}", s.ToString());
            return s;
        }

        // 创建 DataTrans 线程池
        dataTransPool = std::make_unique<WorkerPool>(
            "DataTransPool",
            config.dataTransConcurrency,
            config.dataTransCpuCores,
            config.queueDepth
        );

        s = dataTransPool->Start();
        if (s.Failure()) {
            UC_ERROR("Failed to start DataTrans thread pool: {}", s.ToString());
            lookupPool->Shutdown();
            return s;
        }

        initialized = true;
        UC_INFO("LustreThreadPool initialized: Lookup={} workers, DataTrans={} workers",
                config.lookupConcurrency, config.dataTransConcurrency);

        return Status::OK();
    }

    WorkerPool* GetPool(WorkerType type) {
        switch (type) {
        case WorkerType::LOOKUP:
            return lookupPool.get();
        case WorkerType::DATATRANS:
            return dataTransPool.get();
        default:
            return nullptr;
        }
    }

    void Shutdown() {
        if (lookupPool) {
            lookupPool->Shutdown();
        }
        if (dataTransPool) {
            dataTransPool->Shutdown();
        }
        initialized = false;
    }
};

// ============================================================================
// LustreThreadPool
// ============================================================================

LustreThreadPool::LustreThreadPool()
    : impl_(std::make_unique<Impl>())
{}

LustreThreadPool::~LustreThreadPool() {
    if (impl_) {
        impl_->Shutdown();
    }
}

Status LustreThreadPool::Setup(const ThreadPoolConfig& config) {
    // 验证配置
    Status s = config.Validate();
    if (s.Failure()) {
        return s;
    }

    return impl_->Setup(config);
}

Status LustreThreadPool::Submit(std::unique_ptr<Task> task, WorkerType type) {
    if (!impl_->initialized) {
        return Status::Error("ThreadPool not initialized");
    }

    WorkerPool* pool = impl_->GetPool(type);
    if (!pool) {
        return Status::InvalidParam("Invalid worker type");
    }

    return pool->Submit(std::move(task));
}

Status LustreThreadPool::WaitForAll(int timeoutMs) {
    if (!impl_->initialized) {
        return Status::Error("ThreadPool not initialized");
    }

    // 同时等待两个线程池
    Status s1 = impl_->lookupPool->WaitForAll(timeoutMs);
    Status s2 = impl_->dataTransPool->WaitForAll(timeoutMs);

    // 如果有一个失败，返回错误
    if (s1.Failure()) {
        return s1;
    }
    return s2;
}

size_t LustreThreadPool::GetPendingCount(WorkerType type) const {
    if (!impl_->initialized) {
        return 0;
    }

    WorkerPool* pool = impl_->GetPool(type);
    if (!pool) {
        return 0;
    }

    return pool->GetPendingCount();
}

size_t LustreThreadPool::GetWorkerCount(WorkerType type) const {
    if (!impl_->initialized) {
        return 0;
    }

    WorkerPool* pool = impl_->GetPool(type);
    if (!pool) {
        return 0;
    }

    return pool->GetWorkerCount();
}

void LustreThreadPool::Shutdown() {
    impl_->Shutdown();
}

} // namespace UC::LustreStore
