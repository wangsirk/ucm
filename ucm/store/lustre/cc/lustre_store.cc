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
        
        // TODO: 初始化空间管理器
        // s = spaceMgr.Setup(config);
        // if (s.Failure()) [[unlikely]] { return s; }
        
        transEnable = config.deviceId >= 0;
        
        // TODO: 初始化传输管理器
        // if (transEnable) {
        //     s = transMgr.Setup(config, spaceMgr.GetLayout());
        //     if (s.Failure()) [[unlikely]] { return s; }
        // }
        
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
        
        // TODO: 添加更多配置验证
        // if (cfg.tensorSize == 0 || cfg.shardSize < cfg.tensorSize ||
        //     cfg.blockSize < cfg.shardSize || cfg.shardSize % cfg.tensorSize != 0 ||
        //     cfg.blockSize % cfg.shardSize != 0) {
        //     return Status::InvalidParam("invalid size({},{},{})", 
        //                                 cfg.tensorSize, cfg.shardSize, cfg.blockSize);
        // }
        
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
    // TODO: 实现块查找逻辑
    // auto res = impl_->spaceMgr.Lookup(blocks, num);
    // if (!res) [[unlikely]] { UC_ERROR("Failed({}) to lookup blocks({}).", res.Error(), num); }
    // return res;
    
    (void)blocks;  // Mark as intentionally unused
    UC_WARN("LustreStore::Lookup not implemented yet, returning empty result for {} blocks.", num);
    return std::vector<uint8_t>(num, 0);
}

Expected<ssize_t> LustreStore::LookupOnPrefix(const Detail::BlockId* blocks, size_t num)
{
    // TODO: 实现前缀查找逻辑
    // auto res = impl_->spaceMgr.LookupOnPrefix(blocks, num);
    // if (!res) [[unlikely]] { UC_ERROR("Failed({}) to lookup blocks({}).", res.Error(), num); }
    // return res;
    
    (void)blocks; (void)num;  // Mark as intentionally unused
    UC_WARN("LustreStore::LookupOnPrefix not implemented yet.");
    return static_cast<ssize_t>(-1);
}

void LustreStore::Prefetch(const Detail::BlockId* blocks, size_t num)
{
    // TODO: 实现预取逻辑
    (void)blocks; (void)num;  // Mark as intentionally unused
    UC_WARN("LustreStore::Prefetch not implemented yet.");
}

Expected<Detail::TaskHandle> LustreStore::Load(Detail::TaskDesc task)
{
    // TODO: 实现加载任务提交
    // auto res = impl_->transMgr.SubmitLoadTask(task);
    // if (!res) [[unlikely]] { UC_ERROR("Failed({}) to submit load task.", res.Error()); }
    // return res;
    
    (void)task;  // Mark as intentionally unused
    UC_WARN("LustreStore::Load not implemented yet.");
    return Detail::TaskHandle{0};
}

Expected<Detail::TaskHandle> LustreStore::Dump(Detail::TaskDesc task)
{
    // TODO: 实现转储任务提交
    // auto res = impl_->transMgr.SubmitDumpTask(task);
    // if (!res) [[unlikely]] { UC_ERROR("Failed({}) to submit dump task.", res.Error()); }
    // return res;
    
    (void)task;  // Mark as intentionally unused
    UC_WARN("LustreStore::Dump not implemented yet.");
    return Detail::TaskHandle{0};
}

Expected<bool> LustreStore::Check(Detail::TaskHandle taskId)
{
    // TODO: 实现任务状态检查
    // return impl_->transMgr.Check(taskId);
    
    UC_WARN("LustreStore::Check not implemented yet for task {}.", taskId);
    return true;
}

Status LustreStore::Wait(Detail::TaskHandle taskId)
{
    // TODO: 实现任务等待逻辑
    // return impl_->transMgr.Wait(taskId);
    
    (void)taskId;  // Mark as intentionally unused
    UC_WARN("LustreStore::Wait not implemented yet for task {}.", taskId);
    return Status::OK();
}

}  // namespace UC::LustreStore

extern "C" UC::StoreV1* MakeLustreStore() { return new UC::LustreStore::LustreStore(); }
