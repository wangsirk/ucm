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
#include "lustre_store.h"
#include <fmt/ranges.h>
#include "logger/logger.h"
#include "space_manager.h"
#include "trans_manager.h"
#include "global_config.h"
#include "param_validator.h"

/*
 * LustreStore - Lustre并行文件系统的KV Cache存储实现
 *
 * 主要特性：
 * - 针对Lustre条带化特性优化的I/O
 * - 支持OST（对象存储目标）级别的并行访问
 * - 大规模分布式存储支持
 */

namespace UC::LustreStore {

/**
 * LustreStore实现类 - Pimpl模式
 */
class LustreStoreImpl {
public:
    SpaceManager spaceMgr;              // 空间管理器
    TransManager transMgr;              // 数据传输管理器
    bool transEnable{false};            // 是否启用传输功能
    Config config;                      // 配置存储


public:
    Status Setup(const Config& cfg)
    {
        auto s = CheckConfig(cfg);
        if (s.Failure()) [[unlikely]] {
            UC_ERROR("Failed to check config params: {}.", s);
            return s;
        }

        config = cfg;

        // 初始化空间管理器
        s = spaceMgr.Setup(config);
        if (s.Failure()) [[unlikely]] { return s; }

        transEnable = config.deviceId >= 0;

        // 初始化传输管理器（无论 deviceId 是什么都需要初始化）
        s = transMgr.Setup(config, spaceMgr.GetLayout());
        if (s.Failure()) [[unlikely]] { return s; }

        ShowConfig(config);
        return Status::OK();
    }

private:
    Status CheckConfig(const Config& cfg)
    {
        if (cfg.storageBackends.empty()) {
            return Status::InvalidParam("invalid storage backends");
        }
        if (cfg.deviceId < -1) {
            return Status::InvalidParam("invalid device({})", cfg.deviceId);
        }
        if (cfg.dataTransConcurrency == 0 || cfg.lookupConcurrency == 0) {
            return Status::InvalidParam("invalid concurrency({},{})", 
                                        cfg.dataTransConcurrency, cfg.lookupConcurrency);
        }
        if (cfg.dataDirShardBytes > 5) {
            return Status::InvalidParam("invalid shard bytes({})", cfg.dataDirShardBytes);
        }
        if (cfg.deviceId == -1) { return Status::OK(); }

        return Status::OK();
    }
    
    void ShowConfig(const Config& cfg)
    {
        constexpr const char* ns = "LustreStore";
        std::string buildType = UCM_BUILD_TYPE;
        if (buildType.empty()) { buildType = "Release"; }
        
        UC_INFO("{}-{}({}).", ns, UCM_COMMIT_ID, buildType);
        UC_INFO("Set {}::StorageBackends to {}.", ns, cfg.storageBackends);
        UC_INFO("Set {}::DeviceId to {}.", ns, cfg.deviceId);
        UC_INFO("Set {}::TensorSize to {}.", ns, cfg.tensorSize);
        UC_INFO("Set {}::ShardSize to {}.", ns, cfg.shardSize);
        UC_INFO("Set {}::BlockSize to {}.", ns, cfg.blockSize);
        UC_INFO("Set {}::IoDirect to {}.", ns, cfg.ioDirect);
        UC_INFO("Set {}::DataTransConcurrency to {}.", ns, cfg.dataTransConcurrency);
        UC_INFO("Set {}::LookupConcurrency to {}.", ns, cfg.lookupConcurrency);
        UC_INFO("Set {}::TimeoutMs to {}.", ns, cfg.timeoutMs);
        UC_INFO("Set {}::DataDirShardBytes to {}.", ns, cfg.dataDirShardBytes);
        UC_INFO("Set {}::StripeCount to {}.", ns, cfg.stripeCount);
        UC_INFO("Set {}::StripeSize to {}.", ns, cfg.stripeSize);
    }
};

LustreStore::~LustreStore() = default;

Status LustreStore::Setup(const Detail::Dictionary& config)
{
    Config param;
    config.Get("storage_backends", param.storageBackends);
    config.GetNumber("device_id", param.deviceId);
    config.GetNumber("tensor_size", param.tensorSize);
    config.GetNumber("shard_size", param.shardSize);
    config.GetNumber("block_size", param.blockSize);
    config.Get("io_direct", param.ioDirect);
    config.GetNumber("lustre_data_trans_concurrency", param.dataTransConcurrency);
    config.GetNumber("lustre_lookup_concurrency", param.lookupConcurrency);
    config.GetNumber("timeout_ms", param.timeoutMs);
    config.GetNumber("data_dir_shard_bytes", param.dataDirShardBytes);

    // Lustre特定配置
    config.GetNumber("stripe_count", param.stripeCount);
    config.GetNumber("stripe_size", param.stripeSize);

    // P2: 异步 I/O 配置
    config.Get("enable_async_io", param.enableAsyncIo);
    config.Get("async_io_backend", param.asyncIoBackend);
    config.GetNumber("async_io_queue_depth", param.asyncIoQueueDepth);

    // P2: CPU 亲和性配置
    config.GetNumber("lustre_lookup_cpu_cores", param.lookupCpuCores);
    config.GetNumber("lustre_data_trans_cpu_cores", param.dataTransCpuCores);

    try {
        impl_ = std::make_shared<LustreStoreImpl>();
    } catch (const std::exception& e) {
        UC_ERROR("Failed({}) to make lustre store object.", e.what());
        return Status::Error(e.what());
    }
    return impl_->Setup(param);
}

std::string LustreStore::Readme() const 
{ 
    return "LustreStore - High-performance KV cache storage for Lustre parallel filesystem"; 
}

Expected<std::vector<uint8_t>> LustreStore::Lookup(const Detail::BlockId* blocks, size_t num)
{
    // 参数校验 (v1.1)
    if (num > 0) {
        CHECK_NOT_NULL(blocks, "blocks");
    }
    CHECK_RANGE(num, 0, 1000000, "num");  // 防止过大数组

    // 委托给 SpaceManager
    auto result = impl_->spaceMgr.Lookup(blocks, num);
    UC_DEBUG("LustreStore::Lookup - {} blocks, {} found",
             num, std::count(result.begin(), result.end(), 1));
    return result;
}

Expected<ssize_t> LustreStore::LookupOnPrefix(const Detail::BlockId* blocks, size_t num)
{
    // 参数校验 (v1.1)
    if (num > 0) {
        CHECK_NOT_NULL(blocks, "blocks");
    }
    CHECK_RANGE(num, 0, 1000000, "num");

    // 委托给 SpaceManager
    return impl_->spaceMgr.LookupOnPrefix(blocks, num);
}

void LustreStore::Prefetch(const Detail::BlockId* blocks, size_t num)
{
    // Prefetch 是可选的提示接口，与其他 Store 保持一致（空实现）
    if (num == 0 || blocks == nullptr) { return; }
    (void)blocks; (void)num;
}

Expected<Detail::TaskHandle> LustreStore::Load(Detail::TaskDesc task)
{
    // 参数校验 (v1.1)
    CHECK_RANGE(task.size(), 0, 10000, "task.size");

    // 校验每个 Shard 的地址数组非空
    for (size_t i = 0; i < task.size(); ++i) {
        if (task[i].addrs.empty()) {
            return Status::InvalidParam("task[" + std::to_string(i) + "].addrs cannot be empty");
        }
    }

    // P1: 创建 LOAD 任务
    TransTask transTask(TransTask::Type::LOAD, task);

    // 提交到传输管理器
    auto result = impl_->transMgr.Submit(std::move(transTask));
    if (!result) [[unlikely]] {
        UC_ERROR("LustreStore::Load - Failed to submit task: {}", result.Error());
        return result.Error();
    }

    UC_INFO("LustreStore::Load - Task submitted successfully, handle={}", result.Value());
    return result;
}

Expected<Detail::TaskHandle> LustreStore::Dump(Detail::TaskDesc task)
{
    // 参数校验 (v1.1) - 与 Load 相同
    CHECK_RANGE(task.size(), 0, 10000, "task.size");

    // 校验每个 Shard 的地址数组非空
    for (size_t i = 0; i < task.size(); ++i) {
        if (task[i].addrs.empty()) {
            return Status::InvalidParam("task[" + std::to_string(i) + "].addrs cannot be empty");
        }
    }

    // P1: 创建 DUMP 任务
    TransTask transTask(TransTask::Type::DUMP, task);

    // 提交到传输管理器
    auto result = impl_->transMgr.Submit(std::move(transTask));
    if (!result) [[unlikely]] {
        UC_ERROR("LustreStore::Dump - Failed to submit task: {}", result.Error());
        return result.Error();
    }

    UC_INFO("LustreStore::Dump - Task submitted successfully, handle={}", result.Value());
    return result;
}

Expected<bool> LustreStore::Check(Detail::TaskHandle taskId)
{
    // 参数校验 (v1.1)
    CHECK_PARAM(taskId != 0, "Invalid task handle");

    return impl_->transMgr.Check(taskId);
}

Status LustreStore::Wait(Detail::TaskHandle taskId)
{
    // 参数校验 (v1.1)
    CHECK_PARAM(taskId != 0, "Invalid task handle");

    return impl_->transMgr.Wait(taskId);
}

}  // namespace UC::LustreStore

extern "C" UC::StoreV1* MakeLustreStore() { return new UC::LustreStore::LustreStore(); }
