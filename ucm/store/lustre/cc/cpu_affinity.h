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
#ifndef UNIFIEDCACHE_STORE_LUSTRE_CC_CPU_AFFINITY_H
#define UNIFIEDCACHE_STORE_LUSTRE_CC_CPU_AFFINITY_H

#include <string>
#include <vector>
#include <cstdint>
#include <thread>
#include "status/status.h"

namespace UC::LustreStore {

/**
 * CPU 亲和性配置 (P2)
 *
 * 支持将工作线程绑定到特定 CPU 核心，优化缓存局部性和减少上下文切换。
 */
struct CpuAffinityConfig {
    /**
     * CPU 分配策略
     */
    enum class Strategy {
        AUTO,       // 自动分配（均匀分布到所有核心）
        MANUAL,     // 手动指定 CPU 核心
        NUMA_LOCAL  // NUMA 本地分配（未来扩展）
    };

    Strategy strategy{Strategy::AUTO};
    std::vector<int> lookupCores;     // Lookup 线程绑定的 CPU 核心
    std::vector<int> dataTransCores;  // DataTrans 线程绑定的 CPU 核心

    // 获取默认配置
    static CpuAffinityConfig Default() {
        return CpuAffinityConfig{};
    }

    // 验证配置
    Status Validate() const {
        int numCpus = static_cast<int>(GetAvailableCpuCount());

        // 验证 CPU 核心编号有效性
        auto validateCores = [numCpus](const std::vector<int>& cores) -> Status {
            for (int core : cores) {
                if (core < 0 || core >= numCpus) {
                    return Status::InvalidParam("Invalid CPU core: " + std::to_string(core));
                }
            }
            return Status::OK();
        };

        Status s = validateCores(lookupCores);
        if (s.Failure()) {
            return s;
        }

        return validateCores(dataTransCores);
    }

    /**
     * 获取可用 CPU 核心数量
     */
    static size_t GetAvailableCpuCount() {
        return std::thread::hardware_concurrency();
    }

    /**
     * 自动分配 CPU 核心
     *
     * @param numThreads 线程数量
     * @param offset 起始 CPU 偏移量
     * @return 分配的 CPU 核心列表
     */
    static std::vector<int> AutoAssignCores(size_t numThreads, size_t offset = 0) {
        std::vector<int> cores;
        size_t numCpus = GetAvailableCpuCount();

        for (size_t i = 0; i < numThreads; ++i) {
            cores.push_back(static_cast<int>((offset + i) % numCpus));
        }

        return cores;
    }
};

/**
 * CPU 亲和性管理器 (P2)
 *
 * 提供线程与 CPU 核心绑定的功能。
 */
class CpuAffinityManager {
public:
    /**
     * 设置当前线程的 CPU 亲和性
     *
     * @param coreIds 要绑定的 CPU 核心列表
     * @return Status 操作状态
     */
    static Status SetThreadAffinity(const std::vector<int>& coreIds);

    /**
     * 设置当前线程的 CPU 亲和性（单个核心）
     *
     * @param coreId 要绑定的 CPU 核心
     * @return Status 操作状态
     */
    static Status SetThreadAffinity(int coreId);

    /**
     * 获取当前线程的 CPU 亲和性
     *
     * @return CPU 核心列表，失败时返回空向量
     */
    static std::vector<int> GetThreadAffinity();

    /**
     * 获取 CPU 核心的 NUMA 节点
     *
     * @param coreId CPU 核心编号
     * @return NUMA 节点编号，失败时返回 -1
     */
    static int GetCpuNumaNode(int coreId);

    /**
     * 清除当前线程的 CPU 亲和性（允许在所有核心上运行）
     *
     * @return Status 操作状态
     */
    static Status ClearThreadAffinity();

    /**
     * 设置线程名称（用于调试）
     *
     * @param name 线程名称（最多 16 字符）
     * @return Status 操作状态
     */
    static Status SetThreadName(const std::string& name);

    /**
     * 获取系统 CPU 信息
     */
    struct CpuInfo {
        size_t numCpus{0};         // 总 CPU 核心数
        size_t numSockets{0};      // CPU 插槽数
        std::vector<size_t> coresPerSocket;  // 每个插槽的核心数
    };

    static CpuInfo GetSystemCpuInfo();
};

/**
 * RAII 风格的 CPU 亲和性作用域守卫
 *
 * 在构造时设置亲和性，析构时恢复原始亲和性。
 */
class CpuAffinityScope {
public:
    explicit CpuAffinityScope(const std::vector<int>& coreIds);
    explicit CpuAffinityScope(int coreId);
    ~CpuAffinityScope();

    // 禁止拷贝和移动
    CpuAffinityScope(const CpuAffinityScope&) = delete;
    CpuAffinityScope& operator=(const CpuAffinityScope&) = delete;
    CpuAffinityScope(CpuAffinityScope&&) = delete;
    CpuAffinityScope& operator=(CpuAffinityScope&&) = delete;

    /**
     * 检查是否成功设置亲和性
     */
    bool IsValid() const { return valid_; }

private:
    std::vector<int> originalAffinity_;
    bool valid_{false};
};

} // namespace UC::LustreStore

#endif // UNIFIEDCACHE_STORE_LUSTRE_CC_CPU_AFFINITY_H
