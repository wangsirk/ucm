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
#include "cpu_affinity.h"
#include "logger/logger.h"
#include <pthread.h>
#include <sched.h>
#include <unistd.h>
#include <fstream>
#include <sstream>
#include <thread>
#include <set>

namespace UC::LustreStore {

// ============================================================================
// CpuAffinityManager 实现
// ============================================================================

Status CpuAffinityManager::SetThreadAffinity(const std::vector<int>& coreIds)
{
    if (coreIds.empty()) {
        return Status::InvalidParam("Core ID list is empty");
    }

    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);

    for (int coreId : coreIds) {
        if (coreId < 0 || coreId >= static_cast<int>(CPU_SETSIZE)) {
            return Status::InvalidParam("Invalid core ID: " + std::to_string(coreId));
        }
        CPU_SET(coreId, &cpuset);
    }

    pthread_t thread = pthread_self();
    int rc = pthread_setaffinity_np(thread, sizeof(cpu_set_t), &cpuset);

    if (rc != 0) {
        UC_ERROR("Failed to set CPU affinity: {}", strerror(rc));
        return Status::OsApiError("Failed to set CPU affinity: " + std::string(strerror(rc)));
    }

    std::stringstream ss;
    ss << "[";
    for (size_t i = 0; i < coreIds.size(); ++i) {
        if (i > 0) ss << ", ";
        ss << coreIds[i];
    }
    ss << "]";

    UC_DEBUG("Thread affinity set to cores {}", ss.str());
    return Status::OK();
}

Status CpuAffinityManager::SetThreadAffinity(int coreId)
{
    if (coreId < 0) {
        return Status::InvalidParam("Invalid core ID: " + std::to_string(coreId));
    }

    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(coreId, &cpuset);

    pthread_t thread = pthread_self();
    int rc = pthread_setaffinity_np(thread, sizeof(cpu_set_t), &cpuset);

    if (rc != 0) {
        UC_ERROR("Failed to set CPU affinity to core {}: {}", coreId, strerror(rc));
        return Status::OsApiError("Failed to set CPU affinity: " + std::string(strerror(rc)));
    }

    UC_DEBUG("Thread affinity set to core {}", coreId);
    return Status::OK();
}

std::vector<int> CpuAffinityManager::GetThreadAffinity()
{
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);

    pthread_t thread = pthread_self();
    int rc = pthread_getaffinity_np(thread, sizeof(cpu_set_t), &cpuset);

    if (rc != 0) {
        UC_ERROR("Failed to get CPU affinity: {}", strerror(rc));
        return {};
    }

    std::vector<int> cores;
    int numCpus = static_cast<int>(CpuAffinityConfig::GetAvailableCpuCount());

    for (int i = 0; i < numCpus; ++i) {
        if (CPU_ISSET(i, &cpuset)) {
            cores.push_back(i);
        }
    }

    return cores;
}

int CpuAffinityManager::GetCpuNumaNode(int coreId)
{
    // 读取 /sys/devices/system/cpu/cpu<N>/node 获取 NUMA 节点
    std::string path = "/sys/devices/system/cpu/cpu" + std::to_string(coreId) + "/node";

    std::ifstream file(path);
    if (!file.is_open()) {
        // 尝试另一种路径格式
        path = "/sys/devices/system/node/cpu" + std::to_string(coreId);
        file.open(path);

        if (!file.is_open()) {
            // 假设是 UMA 系统，返回 0
            return 0;
        }
    }

    // 文件内容是 "node<N>" 或只是数字
    std::string content;
    std::getline(file, content);

    // 提取数字
    size_t pos = content.find("node");
    if (pos != std::string::npos) {
        pos += 4;  // 跳过 "node"
    } else {
        pos = 0;
    }

    try {
        return std::stoi(content.substr(pos));
    } catch (...) {
        return 0;
    }
}

Status CpuAffinityManager::ClearThreadAffinity()
{
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);

    // 设置所有 CPU 核心
    int numCpus = static_cast<int>(CpuAffinityConfig::GetAvailableCpuCount());
    for (int i = 0; i < numCpus; ++i) {
        CPU_SET(i, &cpuset);
    }

    pthread_t thread = pthread_self();
    int rc = pthread_setaffinity_np(thread, sizeof(cpu_set_t), &cpuset);

    if (rc != 0) {
        UC_ERROR("Failed to clear CPU affinity: {}", strerror(rc));
        return Status::OsApiError("Failed to clear CPU affinity: " + std::string(strerror(rc)));
    }

    UC_DEBUG("Thread affinity cleared (all cores allowed)");
    return Status::OK();
}

Status CpuAffinityManager::SetThreadName(const std::string& name)
{
    if (name.empty()) {
        return Status::InvalidParam("Thread name cannot be empty");
    }

    // pthread 名称限制为 16 字符（包括 null 终止符）
    std::string truncated = name.substr(0, 15);

    int rc = pthread_setname_np(pthread_self(), truncated.c_str());

    if (rc != 0) {
        UC_WARN("Failed to set thread name to '{}': {}", truncated, strerror(rc));
        return Status::OsApiError("Failed to set thread name: " + std::string(strerror(rc)));
    }

    return Status::OK();
}

CpuAffinityManager::CpuInfo CpuAffinityManager::GetSystemCpuInfo()
{
    CpuInfo info;
    info.numCpus = std::thread::hardware_concurrency();

    // 读取 /proc/cpuinfo 获取 CPU 插槽信息
    std::ifstream file("/proc/cpuinfo");
    if (!file.is_open()) {
        UC_WARN("Failed to open /proc/cpuinfo");
        return info;
    }

    std::set<int> physicalIds;
    std::string line;

    while (std::getline(file, line)) {
        if (line.find("physical id") != std::string::npos) {
            size_t pos = line.find(':');
            if (pos != std::string::npos) {
                try {
                    int physId = std::stoi(line.substr(pos + 1));
                    physicalIds.insert(physId);
                } catch (...) {
                    // 忽略解析错误
                }
            }
        }
    }

    info.numSockets = physicalIds.size();

    // 假设均匀分布
    if (info.numSockets > 0) {
        size_t coresPerSocket = info.numCpus / info.numSockets;
        info.coresPerSocket.resize(info.numSockets, coresPerSocket);
    }

    return info;
}

// ============================================================================
// CpuAffinityScope 实现
// ============================================================================

CpuAffinityScope::CpuAffinityScope(const std::vector<int>& coreIds)
{
    // 保存原始亲和性
    originalAffinity_ = CpuAffinityManager::GetThreadAffinity();

    // 设置新的亲和性
    Status s = CpuAffinityManager::SetThreadAffinity(coreIds);
    valid_ = s.Success();

    if (!valid_) {
        UC_WARN("Failed to set CPU affinity scope: {}", s.ToString());
    }
}

CpuAffinityScope::CpuAffinityScope(int coreId)
{
    // 保存原始亲和性
    originalAffinity_ = CpuAffinityManager::GetThreadAffinity();

    // 设置新的亲和性
    Status s = CpuAffinityManager::SetThreadAffinity(coreId);
    valid_ = s.Success();

    if (!valid_) {
        UC_WARN("Failed to set CPU affinity scope: {}", s.ToString());
    }
}

CpuAffinityScope::~CpuAffinityScope()
{
    if (!originalAffinity_.empty()) {
        // 恢复原始亲和性
        Status s = CpuAffinityManager::SetThreadAffinity(originalAffinity_);
        if (s.Failure()) {
            UC_ERROR("Failed to restore CPU affinity: {}", s.ToString());
        }
    }
}

} // namespace UC::LustreStore
