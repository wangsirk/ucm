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
#ifndef UNIFIEDCACHE_LUSTRE_STORE_CC_SPACE_LAYOUT_H
#define UNIFIEDCACHE_LUSTRE_STORE_CC_SPACE_LAYOUT_H

#include "global_config.h"
#include "status/status.h"
#include "type/types.h"

namespace UC::LustreStore {

/**
 * SpaceLayout - Lustre存储空间布局管理
 * 
 * 负责管理数据文件的目录结构和路径生成
 * 未来将支持Lustre特有的OST亲和性布局
 */
class SpaceLayout {
    std::vector<std::string> storageBackends_;
    bool dataDirShard_;
    size_t dataDirShardBytes_;
    int stripeCount_;      // 条带数量 (0 = 不启用)
    size_t stripeSize_;    // 条带大小 (字节)

public:
    /**
     * 初始化空间布局
     * @param config 配置参数
     * @return 状态码
     */
    Status Setup(const Config& config);

    /**
     * 根据BlockId生成数据文件路径
     * @param blockId 块ID
     * @param activated 是否为临时文件
     * @return 文件路径
     */
    std::string DataFilePath(const Detail::BlockId& blockId, bool activated) const;

    /**
     * 提交文件（将临时文件重命名为正式文件）
     * @param blockId 块ID
     * @param success 操作是否成功
     * @return 状态码
     */
    Status CommitFile(const Detail::BlockId& blockId, bool success) const;

    /**
     * 检查 Block 文件是否存在
     * @param blockId 块ID
     * @return true 文件存在，false 文件不存在
     */
    bool Exists(const Detail::BlockId& blockId) const;

private:
    std::vector<std::string> RelativeRoots() const;
    Status AddStorageBackend(const std::string& path);
    std::string StorageBackend(const Detail::BlockId& blockId) const;
    std::string FileShardName(const std::string& fileName) const
    {
        return fileName.substr(0, dataDirShardBytes_);
    }
};

}  // namespace UC::LustreStore

#endif
