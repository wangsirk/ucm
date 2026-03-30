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
#ifndef UNIFIEDCACHE_STORE_CC_LUSTRE_STORE_H
#define UNIFIEDCACHE_STORE_CC_LUSTRE_STORE_H

#include <memory>
#include "ucmstore_v1.h"

namespace UC::LustreStore {

/**
 * LustreStore - High-performance KV cache storage backend for Lustre parallel file system
 * 
 * This store is optimized for Lustre filesystem characteristics:
 * - Striping-aware I/O for parallel access
 * - OST (Object Storage Target) optimization
 * - Large-scale distributed storage support
 */
class LustreStoreImpl;
class LustreStore : public StoreV1 {
public:
    ~LustreStore() override;
    
    /**
     * Initialize the Lustre store with configuration
     * @param config Configuration dictionary containing:
     *   - storage_backends: List of Lustre mount paths
     *   - device_id: GPU/NPU device ID (-1 for CPU only)
     *   - tensor_size: Size of each tensor element
     *   - shard_size: Size of each shard
     *   - block_size: Size of each block
     *   - stripe_count: Lustre stripe count (optional)
     *   - stripe_size: Lustre stripe size (optional)
     */
    Status Setup(const Detail::Dictionary& config) override;
    
    std::string Readme() const override;
    
    /**
     * Check if blocks exist in Lustre storage
     * @param blocks Array of block IDs to check
     * @param num Number of blocks in the array
     * @return Vector of uint8_t indicating presence (1 = present, 0 = absent)
     */
    Expected<std::vector<uint8_t>> Lookup(const Detail::BlockId* blocks, size_t num) override;
    
    /**
     * Find first missing block in prefix sequence
     * @param blocks Array of block IDs (assumed to be in prefix order)
     * @param num Number of blocks in the array
     * @return Index of first missing block, or -1 if all present
     */
    Expected<ssize_t> LookupOnPrefix(const Detail::BlockId* blocks, size_t num) override;
    
    /**
     * Asynchronously prefetch blocks into page cache
     * @param blocks Array of block IDs to prefetch
     * @param num Number of blocks to prefetch
     */
    void Prefetch(const Detail::BlockId* blocks, size_t num) override;
    
    /**
     * Submit a load task (from Lustre to device memory)
     * @param task Task descriptor containing block IDs and destination buffers
     * @return Task handle for tracking completion
     */
    Expected<Detail::TaskHandle> Load(Detail::TaskDesc task) override;
    
    /**
     * Submit a dump task (from device memory to Lustre)
     * @param task Task descriptor containing block IDs and source buffers
     * @return Task handle for tracking completion
     */
    Expected<Detail::TaskHandle> Dump(Detail::TaskDesc task) override;
    
    /**
     * Non-blocking check if task is complete
     * @param taskId Task handle to check
     * @return true if task is complete, false otherwise
     */
    Expected<bool> Check(Detail::TaskHandle taskId) override;
    
    /**
     * Blocking wait for task completion
     * @param taskId Task handle to wait for
     * @return Status::OK() on success, error status on failure
     */
    Status Wait(Detail::TaskHandle taskId) override;

private:
    std::shared_ptr<LustreStoreImpl> impl_;
};

}  // namespace UC::LustreStore

#endif
