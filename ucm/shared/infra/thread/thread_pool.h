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
#ifndef UNIFIEDCACHE_INFRA_THREAD_POOL_H
#define UNIFIEDCACHE_INFRA_THREAD_POOL_H

#include <atomic>
#include <condition_variable>
#include <functional>
#include <future>
#include <list>
#include <memory>
#include <mutex>
#include <sys/syscall.h>
#include <thread>
#include <unistd.h>
#include <vector>

namespace UC {

template <class Task, class WorkerArgs = void*>
class ThreadPool {
    using WorkerInitFn = std::function<bool(WorkerArgs&)>;              // 线程初始化
    using WorkerFn = std::function<void(Task&, const WorkerArgs&)>;     // 任务执行
    using WorkerTimeoutFn = std::function<void(Task&, const ssize_t)>;  // 超时处理
    using WorkerExitFn = std::function<void(WorkerArgs&)>;              // 线程退出

    // 停止信号
    class StopToken {
        std::shared_ptr<std::atomic<bool>> flag_ = std::make_shared<std::atomic<bool>>(false);

    public:
        // 请求停止
        void RequestStop() noexcept { this->flag_->store(true, std::memory_order_relaxed); }
        // 检查是否停止
        bool StopRequested() const noexcept { return this->flag_->load(std::memory_order_relaxed); }
    };

    // 工作线程结构
    struct Worker {
        ssize_t tid;             // 线程ID
        std::thread th;          // 线程对象
        StopToken stop;         // 停止信号
        std::weak_ptr<Task> current;        // 当前任务
        std::atomic<std::chrono::steady_clock::time_point> tp{};        // 任务开始时间
    };

public:
    ThreadPool() = default;
    ThreadPool(const ThreadPool&) = delete;
    ThreadPool& operator=(const ThreadPool&) = delete;
    ~ThreadPool()
    {
        {
            std::lock_guard<std::mutex> lock(this->taskMtx_);
            this->stop_ = true;
            this->cv_.notify_all();
        }
        if (this->monitor_.joinable()) { this->monitor_.join(); }
        for (auto& worker : this->workers_) {
            if (worker->th.joinable()) { worker->th.join(); }
        }
    }
    ThreadPool& SetWorkerFn(WorkerFn&& fn)
    {
        this->fn_ = std::move(fn);
        return *this;
    }
    ThreadPool& SetWorkerInitFn(WorkerInitFn&& fn)
    {
        this->initFn_ = std::move(fn);
        return *this;
    }
    ThreadPool& SetWorkerExitFn(WorkerExitFn&& fn)
    {
        this->exitFn_ = std::move(fn);
        return *this;
    }
    ThreadPool& SetWorkerTimeoutFn(WorkerTimeoutFn&& fn, const size_t timeoutMs,
                                   const size_t intervalMs = 1000)
    {
        this->timeoutFn_ = std::move(fn);
        this->timeoutMs_ = timeoutMs;
        this->intervalMs_ = intervalMs;
        return *this;
    }
    ThreadPool& SetNWorker(const size_t nWorker)
    {
        this->nWorker_ = nWorker;    // 保存线程数 = 4
        return *this;
    }
    bool Run()
    {
        if (this->nWorker_ == 0) { return false; }
        if (this->fn_ == nullptr) { return false; }
        this->workers_.reserve(this->nWorker_);
        // 循环4次，每次创建一个worker线程
        for (size_t i = 0; i < this->nWorker_; i++) {
            if (!this->AddOneWorker()) { return false; }
        }
        if (this->timeoutMs_ > 0) {
            this->monitor_ = std::thread([this] { this->MonitorLoop(); });
        }
        return true;
    }
    void Push(std::list<Task>& tasks) noexcept
    {
        std::unique_lock<std::mutex> lock(this->taskMtx_);
        this->taskQ_.splice(this->taskQ_.end(), tasks);
        this->cv_.notify_all();
    }
    // 提交任务
    void Push(Task&& task) noexcept
    {
        std::unique_lock<std::mutex> lock(this->taskMtx_);
        this->taskQ_.push_back(std::move(task));
        this->cv_.notify_one();
    }

private:
    bool AddOneWorker()
    {
        try {
            auto worker = std::make_shared<Worker>();
            std::promise<bool> prom;
            auto fut = prom.get_future();
            // 创建线程，执行worker loop
            worker->th = std::thread([this, worker, &prom] { this->WorkerLoop(prom, worker); });
            // 等待线程初始化完成
            auto success = fut.get();
            if (!success) { return false; }
            this->workers_.push_back(worker);
            return true;
        } catch (...) {
            return false;
        }
    }
    void WorkerLoop(std::promise<bool>& prom, std::shared_ptr<Worker> worker)
    {
        // 获取线程ID
        worker->tid = syscall(SYS_gettid);
        WorkerArgs args = nullptr;
        auto success = true;
        // 执行初始化回调
        if (this->initFn_) { success = this->initFn_(args); }
        // 通知主线程初始化完成
        prom.set_value(success);
        while (success) {
            std::shared_ptr<Task> task = nullptr;
            {
                std::unique_lock<std::mutex> lock(this->taskMtx_);
                // 等待任务
                this->cv_.wait(lock, [this, worker] {
                    return this->stop_ || worker->stop.StopRequested() || !this->taskQ_.empty();
                });
                if (this->stop_ || worker->stop.StopRequested()) { break; }
                if (this->taskQ_.empty()) { continue; }
                // 从队列获取任务
                task = std::make_shared<Task>(std::move(this->taskQ_.front()));
                this->taskQ_.pop_front();
            }
            worker->current = task;
            worker->tp.store(std::chrono::steady_clock::now(), std::memory_order_relaxed);
            // 执行任务
            this->fn_(*task, args);
            if (worker->stop.StopRequested()) { break; }
            worker->current.reset();
            worker->tp.store({}, std::memory_order_relaxed);
        }
        if (this->exitFn_) { this->exitFn_(args); }
    }
    
    // 监控线程
    void MonitorLoop()
    {
        const auto interval = std::chrono::milliseconds(this->intervalMs_);
        while (!this->stop_) {
            std::this_thread::sleep_for(interval);
            // 检查超时任务
            size_t nWorker = this->Monitor();
            // 补充工作线程
            for (size_t i = nWorker; i < this->nWorker_; i++) { (void)this->AddOneWorker(); }
        }
    }

    // 超时检测
    size_t Monitor()
    {
        using namespace std::chrono;
        const auto timeout = milliseconds(this->timeoutMs_);
        for (auto it = this->workers_.begin(); it != this->workers_.end();) {
            auto tp = (*it)->tp.load(std::memory_order_relaxed);
            auto task = (*it)->current.lock();
            auto now = steady_clock::now();
            // 检查任务是否超时
            if (task && tp != steady_clock::time_point{} && now - tp > timeout) {
                if (this->timeoutFn_) { this->timeoutFn_(*task, (*it)->tid); }
                (*it)->stop.RequestStop();                          // 请求停止
                if ((*it)->th.joinable()) { (*it)->th.detach(); }   // 分离线程
                it = this->workers_.erase(it);                      // 移除
            } else {
                it++;
            }
        }
        return this->workers_.size();
    }

private:
WorkerInitFn initFn_{nullptr};                          // 线程初始化函数
    WorkerFn fn_{nullptr};                              // 任务执行函数
    WorkerTimeoutFn timeoutFn_{nullptr};                // 任务超时函数
    WorkerExitFn exitFn_{nullptr};                      // 线程退出函数
    size_t timeoutMs_{0};                               // 任务超时时间
    size_t intervalMs_{0};                              // 监控间隔时间  
    size_t nWorker_{0};                                 // 线程数量
    bool stop_{false};                              
    std::vector<std::shared_ptr<Worker>> workers_;      // 工作线程列表
    std::thread monitor_;                               // 监控线程 
    std::mutex taskMtx_;                                // 任务队列互斥锁
    std::list<Task> taskQ_;                             // 任务队列
    std::condition_variable cv_;                        // 条件变量
};

}  // namespace UC
  
#endif
