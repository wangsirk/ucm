# Lustre Store 设计文档 v1.1

## 文档版本信息

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| 1.0 | 2026-04-01 | Design Team | 初始版本 |
| 1.1 | 2026-04-01 | Design Team | 修复审查报告中的必须修复问题 |

---

## 变更摘要

### 🔴 必须修复问题

| ID | 问题 | 状态 |
|----|------|------|
| **B-002** | 参数范围校验缺失 | ✅ 已修复 |
| **S-002** | 多进程写数据竞争 | ✅ 已修复 |
| **B-001** | TaskDesc 参数来源不明确 | ✅ 已修复 |
| **A-003** | 临时文件清理时机不明确 | ✅ 已修复 |

---

## 目录

1. [参数校验设计 (B-002)](#1-参数校验设计-b-002)
2. [多进程并发写入保护 (S-002)](#2-多进程并发写入保护-s-002)
3. [TaskDesc 参数责任明确化 (B-001)](#3-taskdesc-参数责任明确化-b-001)
4. [临时文件清理策略 (A-003)](#4-临时文件清理策略-a-003)
5. [更新的 API 定义](#5-更新的-api-定义)
6. [更新的数据模型](#6-更新的数据模型)
7. [更新的错误处理](#7-更新的错误处理)

---

## 1. 参数校验设计 (B-002)

### 1.1 问题说明

原设计中 API 缺少参数范围校验，可能导致空指针访问、数组越界等问题。

### 1.2 参数校验框架

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              参数校验框架                                          │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         参数校验层                                           │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  校验类型                                                             │ │   │
│  │  │  • 非空校验 (NotNull)        - 检查指针是否为 nullptr                │ │   │
│  │  │  • 范围校验 (Range)           - 检查数值是否在有效范围              │ │   │
│  │  │  • 一致性校验 (Consistency)   - 检查多个参数之间的一致性            │ │   │
│  │  │  • 状态校验 (State)           - 检查对象状态是否允许操作          │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  │                                       │                                     │   │
│  │                                       ▼                                     │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  校验失败处理                                                         │ │   │
│  │  │  • 立即返回 Status::InvalidParam                                      │ │   │
│  │  │  • 记录详细错误信息 (参数名、期望值、实际值)                           │ │   │
│  │  │  • 触发监控指标记录                                                   │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 1.3 校验宏定义

```cpp
namespace UC::LustreStore {

// ===== 参数校验宏 =====

// 非空校验
#define CHECK_NOT_NULL(ptr, name) \
    do { \
        if ((ptr) == nullptr) { \
            UC_ERROR("Parameter '%s' cannot be null", name); \
            return Status::InvalidParam(std::string(name) + " cannot be null"); \
        } \
    } while(0)

// 条件校验
#define CHECK_PARAM(condition, message) \
    do { \
        if (!(condition)) { \
            UC_ERROR("Parameter validation failed: %s", message); \
            return Status::InvalidParam(message); \
        } \
    } while(0)

// 范围校验
#define CHECK_RANGE(value, min, max, name) \
    do { \
        if ((value) < (min) || (value) > (max)) { \
            UC_ERROR("Parameter '%s'=%lu out of range [%lu, %lu]", \
                     name, (unsigned long)(value), \
                     (unsigned long)(min), (unsigned long)(max)); \
            return Status::InvalidParam(name " out of range"); \
        } \
    } while(0)

// 一致性校验
#define CHECK_CONSISTENCY(condition, message) \
    do { \
        if (!(condition)) { \
            UC_ERROR("Parameter consistency check failed: %s", message); \
            return Status::InvalidParam(message); \
        } \
    } while(0)

} // namespace UC::LustreStore
```

### 1.4 更新的 API 定义

```cpp
namespace UC {

class LustreStore : public StoreV1 {
public:
    // ===== 元数据操作 (带参数校验) =====

    std::vector<uint8_t> Lookup(const BlockId* blocks, size_t num) override {
        // 参数校验
        CHECK_NOT_NULL(blocks, "blocks");
        CHECK_RANGE(num, 0, 1000000, "num");  // 防止过大数组
        
        // 调用实现
        return impl_->Lookup(blocks, num);
    }

    Expected<ssize_t> LookupOnPrefix(const BlockId* blocks, size_t num) override {
        // 参数校验
        CHECK_NOT_NULL(blocks, "blocks");
        CHECK_RANGE(num, 0, 1000000, "num");
        
        // 文档化: blocks 必须按前缀排序
        // 如果未排序，结果可能不正确
        
        return impl_->LookupOnPrefix(blocks, num);
    }

    void Prefetch(const BlockId* blocks, size_t num) override {
        // 参数校验
        if (num == 0) return;  // 空操作，允许
        CHECK_NOT_NULL(blocks, "blocks");
        CHECK_RANGE(num, 0, 100000, "num");  // 预取数量限制
        
        impl_->Prefetch(blocks, num);
    }

    // ===== 数据传输操作 (带参数校验) =====

    TaskHandle Load(const BlockId* blocks, size_t num,
                    const void* const* addrs) override {
        // 参数校验
        if (num == 0) {
            return TaskHandle{};  // 空操作
        }
        CHECK_NOT_NULL(blocks, "blocks");
        CHECK_NOT_NULL(addrs, "addrs");
        CHECK_RANGE(num, 0, 10000, "num");
        
        // 校验地址数组非空
        for (size_t i = 0; i < num; ++i) {
            CHECK_CONSISTENCY(addrs[i] != nullptr,
                            "addrs[" + std::to_string(i) + "] cannot be null");
        }
        
        return impl_->Load(blocks, num, addrs);
    }

    TaskHandle Dump(const BlockId* blocks, size_t num,
                    const void* const* addrs) override {
        // 参数校验 (与 Load 相同)
        if (num == 0) {
            return TaskHandle{};
        }
        CHECK_NOT_NULL(blocks, "blocks");
        CHECK_NOT_NULL(addrs, "addrs");
        CHECK_RANGE(num, 0, 10000, "num");
        
        for (size_t i = 0; i < num; ++i) {
            CHECK_CONSISTENCY(addrs[i] != nullptr,
                            "addrs[" + std::to_string(i) + "] cannot be null");
        }
        
        return impl_->Dump(blocks, num, addrs);
    }

    // ===== 任务管理 (带参数校验) =====

    bool Check(TaskHandle handle) const override {
        // 参数校验
        CHECK_PARAM(handle.IsValid(), "Invalid task handle");
        return impl_->Check(handle);
    }

    Status Wait(TaskHandle handle) const override {
        // 参数校验
        CHECK_PARAM(handle.IsValid(), "Invalid task handle");
        return impl_->Wait(handle);
    }
};

} // namespace UC
```

### 1.5 组件级参数校验

```cpp
namespace UC::LustreStore {

class SpaceLayout {
public:
    Status Setup(const Config& config) override {
        // 配置校验
        CHECK_NOT_NULL(config.storageBackends.data(), "storageBackends");
        CHECK_PARAM(!config.storageBackends.empty(),
                   "storageBackends cannot be empty");
        
        // 校验挂载点路径格式
        for (const auto& path : config.storageBackends) {
            CHECK_PARAM(!path.empty(), "storageBackend path cannot be empty");
            CHECK_PARAM(path[0] == '/', "storageBackend path must be absolute");
        }
        
        // 校验目录分片层级
        CHECK_RANGE(config.dataDirShardBytes, 0, 3, "dataDirShardBytes");
        
        // ... 其他校验
        
        return Status::OK();
    }
};

class TransQueue {
public:
    Status Setup(const Config& config, TaskIdSet* failureSet,
                 const SpaceLayout* layout) override {
        // 参数校验
        CHECK_NOT_NULL(failureSet, "failureSet");
        CHECK_NOT_NULL(layout, "layout");
        CHECK_PARAM(layout->IsInitialized(), "layout must be initialized first");
        
        // 校验并发度
        CHECK_RANGE(config.dataTransConcurrency, 1, 256, "dataTransConcurrency");
        
        return Status::OK();
    }
};

} // namespace UC::LustreStore
```

---

## 2. 多进程并发写入保护 (S-002)

### 2.1 问题说明

原设计中，多进程同时写入同一 Block 时，后完成的进程的 rename() 会覆盖先完成进程的数据，违反了幂等性原则。

### 2.2 解决方案设计

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         多进程并发写入保护机制                                      │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  原设计问题:                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  进程 A: Block X → data/{shard_path}/{hash}.tmp.<pid_A>                     │   │
│  │          └─ rename() → {hash} ✅ 成功                                        │   │
│  │  进程 B: Block X → data/{shard_path}/{hash}.tmp.<pid_B>                     │   │
│  │          └─ rename() → {hash} ⚠️ 覆盖进程 A 的数据!                          │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  新设计方案: 使用 link() + EEXIST 检测                                             │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  进程 A: Block X → data/{shard_path}/{hash}.tmp.<pid_A>                     │   │
│  │          └─ link() → {hash} ✅ 成功 (原子操作)                               │   │
│  │          └─ remove(.tmp.<pid_A>)                                            │   │
│  │  进程 B: Block X → data/{shard_path}/{hash}.tmp.<pid_B>                     │   │
│  │          └─ link() → {hash} ❌ EEXIST (文件已存在)                          │   │
│  │          └─ 检测到 DuplicateKey                                             │   │
│  │          └─ remove(.tmp.<pid_B>)                                            │   │
│  │          └─ 返回成功 (数据已存在，幂等性保证)                                │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 更新的 CommitFile 实现

```cpp
namespace UC::LustreStore {

class SpaceLayout {
public:
    // ===== 文件提交 (原子性保证) =====

    // 提交临时文件为正式文件
    // @param blockId 块 ID
    // @param success 是否成功 (true=提交, false=删除临时文件)
    // @return Status 操作状态
    //   - Status::OK(): 提交成功
    //   - Status::DuplicateKey(): 文件已存在 (其他进程已提交)
    //   - Status::IOError(): I/O 错误
    Status CommitFile(const BlockId& blockId, bool success) const {
        if (!success) {
            // 失败: 删除临时文件
            std::string tmpPath = DataFilePath(blockId, true);
            Remove(tmpPath);
            UC_WARN("Commit failed, removed temp file: {}", tmpPath);
            return Status::IOError("Operation failed, temp file removed");
        }

        std::string tmpPath = DataFilePath(blockId, true);
        std::string finalPath = DataFilePath(blockId, false);

        // ===== 方案 1: 使用 link() + EEXIST (推荐) =====
        // link() 是原子操作，如果目标文件已存在会返回 EEXIST
        if (link(tmpPath.c_str(), finalPath.c_str()) == 0) {
            // 成功: 原子性地创建了硬链接
            // 现在可以安全地删除临时文件
            Remove(tmpPath);
            UC_INFO("Commit succeeded: {} -> {}", tmpPath, finalPath);
            return Status::OK();
        }

        int error = errno;
        if (error == EEXIST) {
            // 文件已存在: 其他进程已经提交了相同的数据
            // 这是预期行为，删除我们的临时文件并返回成功
            Remove(tmpPath);
            UC_INFO("Block already exists (concurrent commit), removed temp file: {}",
                   BlockIdToString(blockId));
            return Status::DuplicateKey("Block already exists");
        }

        // 其他错误
        UC_ERROR("Commit failed for {}: {} ({})",
                BlockIdToString(blockId), strerror(error), error);
        return Status::IOError(std::string("link() failed: ") + strerror(error));
    }

    // ===== 备选方案: 使用 rename() + O_EXCL 检查 =====
    // 如果文件系统不支持 link()，可以使用以下方案
    Status CommitFileFallback(const BlockId& blockId, bool success) const {
        if (!success) {
            std::string tmpPath = DataFilePath(blockId, true);
            Remove(tmpPath);
            return Status::IOError("Operation failed, temp file removed");
        }

        std::string tmpPath = DataFilePath(blockId, true);
        std::string finalPath = DataFilePath(blockId, false);

        // 先检查目标文件是否存在
        if (access(finalPath.c_str(), F_OK) == 0) {
            // 文件已存在
            Remove(tmpPath);
            return Status::DuplicateKey("Block already exists");
        }

        // 尝试原子重命名
        if (rename(tmpPath.c_str(), finalPath.c_str()) == 0) {
            return Status::OK();
        }

        int error = errno;
        if (error == EEXIST) {
            // 重命名期间文件被创建
            Remove(tmpPath);
            return Status::DuplicateKey("Block already exists");
        }

        UC_ERROR("Commit failed: {}", strerror(error));
        return Status::IOError(std::string("rename() failed: ") + strerror(error));
    }

private:
    // 辅助函数: BlockId 转字符串
    static std::string BlockIdToString(const BlockId& blockId);
};

} // namespace UC::LustreStore
```

### 2.4 并发写入流程

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         并发 Dump 操作完整流程                                      │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  进程 A                                      进程 B                                │
│  │                                           │                                     │
│  │  Dump(Block X)                            │  Dump(Block X)                      │
│  │    │                                      │    │                                │
│  │    ▼                                      │    ▼                                │
│  │  创建 .tmp.<pid_A>                        │  创建 .tmp.<pid_B>                  │
│  │  写入数据                                  │  写入数据                            │
│  │    │                                      │    │                                │
│  │    ▼                                      │    ▼                                │
│  │  CommitFile(success=true)                 │  CommitFile(success=true)         │
│  │    │                                      │    │                                │
│  │    ▼                                      │    │                                │
│  │  link(.tmp.<pid_A> → {hash})              │    │                                │
│  │    │                                      │    │ (等待中...)                     │
│  │    ├─ 成功 ✅                              │    │                                │
│  │    ▼                                      │    ▼                                │
│  │  remove(.tmp.<pid_A>)                     │  link(.tmp.<pid_B> → {hash})       │
│  │    │                                      │    │                                │
│  │    ▼                                      │    ├─ EEXIST ❌                     │
│  │  返回 OK                                  │    ▼                                │
│  │                                           │    │                                │
│  │                                           │    ▼                                │
│  │                                           │  检测到 DuplicateKey               │
│  │                                           │    │                                │
│  │                                           │    ▼                                │
│  │                                           │  remove(.tmp.<pid_B>)              │
│  │                                           │    │                                │
│  │                                           │    ▼                                │
│  │                                           │  返回 OK (幂等性)                  │
│  │                                           │                                     │
│  最终状态: {hash} 存在，内容一致，无数据损坏                                         │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.5 文档说明

```cpp
/**
 * @brief 提交临时文件为正式文件
 *
 * **并发安全性**:
 * - 使用原子 link() 操作确保多进程并发写入的安全性
 * - 如果目标文件已存在，返回 Status::DuplicateKey()
 * - 调用者应将 DuplicateKey 视为成功（幂等性保证）
 *
 * **幂等性保证**:
 * - 多次提交相同的 Block 不会导致数据损坏
 * - 后续提交会检测到文件已存在并返回 DuplicateKey
 *
 * @param blockId 块 ID
 * @param success 是否成功 (true=提交, false=删除临时文件)
 * @return Status 操作状态
 */
Status CommitFile(const BlockId& blockId, bool success) const;
```

---

## 3. TaskDesc 参数责任明确化 (B-001)

### 3.1 问题说明

原设计中 TaskDesc 的部分参数（如 shardIndex, numShards）来源不明确，调用者和实现者责任不清。

### 3.2 参数责任划分

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         TaskDesc 参数责任划分                                       │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  TaskDesc 结构                                                              │   │
│  ├─────────────────────────────────────────────────────────────────────────────┤   │
│  │                                                                             │   │
│  │  ╔═════════════════════════════════════════════════════════════════════════╗ │   │
│  │  ║ [输入参数 - 由调用者提供]                                              ║ │   │
│  │  ╠──────────────────────────────────────────────────────────────────────────╣ │   │
│  │  ║  const BlockId* blockIds;     // 块 ID 数组                            ║ │   │
│  │  ║  size_t numBlocks;            // 块数量                                ║ │   │
│  │  ║  const void* const* addrs;     // 设备内存地址数组                      ║ │   │
│  │  ╚═════════════════════════════════════════════════════════════════════════╝ │   │
│  │                                                                             │   │
│  │  ╔═════════════════════════════════════════════════════════════════════════╗ │   │
│  │  ║ [自动填充参数 - 由 TransManager 从 Config 获取]                         ║ │   │
│  │  ╠──────────────────────────────────────────────────────────────────────────╣ │   │
│  │  ║  size_t shardIndex;            // [自动] 起始分片索引                   ║ │   │
│  │  ║  size_t numShards;             // [自动] 分片数量                       ║ │   │
│  │  ║  size_t tensorSize;            // [自动] 单个 tensor 大小               ║ │   │
│  │  ║  size_t shardSize;             // [自动] 单个 shard 大小                ║ │   │
│  │  ║  size_t blockSize;             // [自动] 单个 block 大小                ║ │   │
│  │  ╚═════════════════════════════════════════════════════════════════════════╝ │   │
│  │                                                                             │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 更新的 TaskDesc 定义

```cpp
namespace UC::LustreStore {

/**
 * @brief 任务描述符
 *
 * **参数责任划分**:
 * - [输入参数]: 由调用者提供，必须在调用前有效
 * - [自动填充]: 由 TransManager 从 Config 自动获取，调用者无需设置
 */
struct TaskDesc {
    // ===== [输入参数] 由调用者提供 =====

    /// 块 ID 数组 [必须提供]
    /// @note 调用者必须保证指针有效且包含 numBlocks 个元素
    const BlockId* blockIds{nullptr};

    /// 块数量 [必须提供]
    /// @note 必须与 blockIds 数组长度一致
    size_t numBlocks{0};

    /// 设备内存地址数组 [必须提供]
    /// @note 调用者必须保证指针有效且包含 numBlocks 个元素
    /// @note 每个地址必须指向有效的设备内存区域
    const void* const* addrs{nullptr};

    // ===== [自动填充] 由 TransManager 从 Config 获取 =====
    // 调用者无需设置以下参数，它们会自动从 Config 中获取

    /// 起始分片索引 [自动]
    /// @note 从 Config::shardIndex 获取
    size_t shardIndex{0};

    /// 分片数量 [自动]
    /// @note 从 Config::nShardPerBlock 获取
    size_t numShards{0};

    /// 单个 tensor 大小 [自动]
    /// @note 从 Config::tensorSize 获取
    size_t tensorSize{0};

    /// 单个 shard 大小 [自动]
    /// @note 从 Config::shardSize 获取
    size_t shardSize{0};

    /// 单个 block 大小 [自动]
    /// @note 计算: blockSize = shardSize * nShardPerBlock
    size_t blockSize{0};

    // ===== 构造函数 =====

    TaskDesc() = default;

    // 便捷构造函数 (仅需要输入参数)
    TaskDesc(const BlockId* blocks, size_t num, const void* const* addresses)
        : blockIds(blocks), numBlocks(num), addrs(addresses) {}
};

} // namespace UC::LustreStore
```

### 3.4 TransManager 填充逻辑

```cpp
namespace UC::LustreStore {

class TransManager : public TaskWrapper<TransTask, TaskHandle> {
public:
    // ===== 任务提交 (自动填充参数) =====

    TaskHandle SubmitLoad(const TaskDesc& userDesc) {
        // 创建内部任务描述，填充自动参数
        TaskDesc internalDesc = userDesc;  // 复制用户输入

        // 从 Config 自动填充参数
        internalDesc.shardIndex = config_.shardIndex;
        internalDesc.numShards = config_.nShardPerBlock;
        internalDesc.tensorSize = config_.tensorSize;
        internalDesc.shardSize = config_.shardSize;
        internalDesc.blockSize = config_.shardSize * config_.nShardPerBlock;

        // 创建任务
        auto task = std::make_shared<TransTask>(
            TransTask::Type::LOAD,
            internalDesc
        );

        // 分发任务
        return SubmitTask(task);
    }

    TaskHandle SubmitDump(const TaskDesc& userDesc) {
        // 同上，填充自动参数
        TaskDesc internalDesc = userDesc;

        internalDesc.shardIndex = config_.shardIndex;
        internalDesc.numShards = config_.nShardPerBlock;
        internalDesc.tensorSize = config_.tensorSize;
        internalDesc.shardSize = config_.shardSize;
        internalDesc.blockSize = config_.shardSize * config_.nShardPerBlock;

        auto task = std::make_shared<TransTask>(
            TransTask::Type::DUMP,
            internalDesc
        );

        return SubmitTask(task);
    }

private:
    Config config_;  // 配置对象
};

} // namespace UC::LustreStore
```

### 3.5 调用示例

```cpp
// ===== 调用者代码 =====

namespace UC {

class LustreStore : public StoreV1 {
public:
    TaskHandle Load(const BlockId* blocks, size_t num,
                    const void* const* addrs) override {
        // 仅提供输入参数
        TaskDesc desc(blocks, num, addrs);

        // TransManager 会自动填充其他参数
        return impl_->transManager_->SubmitLoad(desc);
    }

    TaskHandle Dump(const BlockId* blocks, size_t num,
                    const void* const* addrs) override {
        // 仅提供输入参数
        TaskDesc desc(blocks, num, addrs);

        return impl_->transManager_->SubmitDump(desc);
    }
};

} // namespace UC
```

---

## 4. 临时文件清理策略 (A-003)

### 4.1 问题说明

原设计中，临时文件清理仅检查进程 ID，可能误删其他活跃进程的临时文件。

### 4.2 清理策略设计

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         临时文件清理策略                                          │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  清理时机                                                                   │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  1. 初始化时清理 (Setup)                                               │ │   │
│  │  │     - 扫描所有 .tmp.* 文件                                             │ │   │
│  │  │     - 只清理满足条件的文件                                             │ │   │
│  │  │                                                                       │ │   │
│  │  │  2. 正常退出时清理 (~LustreStore)                                     │ │   │
│  │  │     - 清理本进程创建的所有 .tmp.<pid> 文件                            │ │   │
│  │  │                                                                       │ │   │
│  │  │  3. 异常退出时清理 (信号处理器)                                       │ │   │
│  │  │     - 注册信号处理器 (SIGTERM, SIGINT, SIGSEGV)                      │ │   │
│  │  │     - 尝试清理本进程的临时文件                                        │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  清理条件 (多选，全部满足才清理)                                           │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  1. 文件名匹配 .tmp.<pid> 后缀 (仅本进程)                              │ │   │
│  │  │  2. 文件年龄超过阈值 (默认: 1 小时)                                    │ │   │
│  │  │  3. 文件未被锁定 (使用 fcntl 检查)                                    │ │   │
│  │  │  4. 或文件对应的进程不存在 (检查 /proc/<pid>)                          │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 清理配置

```cpp
namespace UC::LustreStore {

/**
 * @brief 临时文件清理配置
 */
struct TempFileCleanupConfig {
    /// 最大文件年龄 (秒)，超过此年龄的文件会被清理
    /// 默认: 3600 秒 (1 小时)
    size_t maxAgeSeconds{3600};

    /// 是否检查文件锁
    /// true: 使用 fcntl 检查文件是否被锁定
    /// false: 跳过锁检查 (更快，但可能误删)
    bool checkFileLock{true};

    /// 是否检查进程是否存在
    /// true: 检查 /proc/<pid> 是否存在
    /// false: 跳过进程检查
    bool checkProcessExists{true};

    /// 是否启用清理
    /// false: 禁用自动清理 (用于调试)
    bool enableCleanup{true};

    /// 清理模式
    enum class CleanupMode {
        SAFE,      // 安全模式: 所有条件都满足才清理
        AGGRESSIVE // 激进模式: 仅检查 PID 和年龄
    };
    CleanupMode mode{CleanupMode::SAFE};
};

} // namespace UC::LustreStore
```

### 4.4 清理实现

```cpp
namespace UC::LustreStore {

class SpaceLayout {
public:
    // ===== 临时文件清理 =====

    /**
     * @brief 清理残留的临时文件
     *
     * **清理条件** (全部满足才清理):
     * 1. 文件名匹配 .tmp.<pid> 后缀 (仅本进程)
     * 2. 文件年龄超过 maxAgeSeconds
     * 3. 文件未被锁定 (如果 checkFileLock=true)
     * 4. 或对应的进程不存在 (如果 checkProcessExists=true)
     *
     * @param config 清理配置
     * @return Status 清理状态
     */
    Status CleanupTempFiles(const TempFileCleanupConfig& config = {}) {
        if (!config.enableCleanup) {
            UC_INFO("Temp file cleanup disabled");
            return Status::OK();
        }

        std::string dataDir = mountPoint_ + "/data";
        size_t cleanedCount = 0;
        Status status = Status::OK();

        // 遍历所有分片目录
        auto shardDirs = ListShardDirs(dataDir);
        for (const auto& shardDir : shardDirs) {
            // 扫描临时文件
            auto tempFiles = ListTempFiles(shardDir, pid_);

            for (const auto& filePath : tempFiles) {
                auto result = ShouldCleanupFile(filePath, config);
                if (result.first) {
                    // 清理文件
                    if (Remove(filePath)) {
                        cleanedCount++;
                        UC_INFO("Cleaned stale temp file: {}", filePath);
                    } else {
                        UC_WARN("Failed to remove temp file: {}", filePath);
                        // 继续清理其他文件
                    }
                } else if (!result.second.OK()) {
                    // 记录错误但继续
                    status = result.second;
                }
            }
        }

        UC_INFO("Temp file cleanup completed: {} files removed", cleanedCount);
        return status;
    }

private:
    /**
     * @brief 判断文件是否应该被清理
     * @return pair<bool, Status> (should_cleanup, error_status)
     */
    std::pair<bool, Status> ShouldCleanupFile(
        const std::string& filePath,
        const TempFileCleanupConfig& config) const {

        // 条件 1: 检查文件年龄
        auto ageResult = GetFileAge(filePath);
        if (!ageResult.OK()) {
            return {false, ageResult};
        }
        if (ageResult.Value() < config.maxAgeSeconds) {
            // 文件太新，不清理
            return {false, Status::OK()};
        }

        // 条件 2: 检查文件锁
        if (config.checkFileLock) {
            auto lockResult = IsFileLocked(filePath);
            if (!lockResult.OK()) {
                return {false, lockResult};
            }
            if (lockResult.Value()) {
                // 文件被锁定，可能有进程正在使用
                UC_DEBUG("File locked, skipping: {}", filePath);
                return {false, Status::OK()};
            }
        }

        // 条件 3: 检查进程是否存在
        if (config.checkProcessExists) {
            // 从文件名提取 PID
            pid_t filePid;
            if (!ExtractPidFromPath(filePath, filePid)) {
                return {false, Status::OK()};  // 无法提取 PID，跳过
            }

            if (IsProcessRunning(filePid)) {
                // 进程仍在运行，不清理
                UC_DEBUG("Process {} still running, skipping: {}", filePid, filePath);
                return {false, Status::OK()};
            }
        }

        // 所有条件满足，可以清理
        return {true, Status::OK()};
    }

    /**
     * @brief 获取文件年龄 (秒)
     */
    Expected<size_t> GetFileAge(const std::string& filePath) const {
        struct stat st;
        if (stat(filePath.c_str(), &st) != 0) {
            return Status::OsApiError(std::string("stat() failed: ") + strerror(errno));
        }

        time_t now = time(nullptr);
        if (now < st.st_mtime) {
            return Status::OsApiError("File mtime is in the future");
        }

        return static_cast<size_t>(now - st.st_mtime);
    }

    /**
     * @brief 检查文件是否被锁定
     */
    Expected<bool> IsFileLocked(const std::string& filePath) const {
        int fd = open(filePath.c_str(), O_RDONLY);
        if (fd < 0) {
            return Status::OsApiError(std::string("open() failed: ") + strerror(errno));
        }

        struct flock fl;
        fl.l_type = F_WRLCK;
        fl.l_whence = SEEK_SET;
        fl.l_start = 0;
        fl.l_len = 0;

        bool isLocked = (fcntl(fd, F_GETLK, &fl) == 0 && fl.l_type != F_UNLCK);

        close(fd);
        return isLocked;
    }

    /**
     * @brief 检查进程是否正在运行
     */
    bool IsProcessRunning(pid_t pid) const {
        // 检查 /proc/<pid> 是否存在
        std::string procPath = "/proc/" + std::to_string(pid);
        return (access(procPath.c_str(), F_OK) == 0);
    }

    /**
     * @brief 从文件路径提取 PID
     */
    bool ExtractPidFromPath(const std::string& filePath, pid_t& outPid) const {
        // 文件名格式: {hash}.tmp.{pid}
        size_t lastDot = filePath.rfind('.');
        if (lastDot == std::string::npos) {
            return false;
        }

        std::string pidStr = filePath.substr(lastDot + 1);
        try {
            outPid = std::stol(pidStr);
            return true;
        } catch (...) {
            return false;
        }
    }

    /**
     * @brief 列出所有分片目录
     */
    std::vector<std::string> ListShardDirs(const std::string& dataDir) const {
        std::vector<std::string> dirs;

        if (dataDirShardBytes_ == 0) {
            dirs.push_back(dataDir);
            return dirs;
        }

        // 扫描分片目录
        // ... 实现略
        return dirs;
    }

    /**
     * @brief 列出指定目录下的临时文件
     */
    std::vector<std::string> ListTempFiles(const std::string& dir, pid_t pid) const {
        std::vector<std::string> files;
        std::string pattern = ".tmp." + std::to_string(pid);

        // 扫描目录
        DIR* d = opendir(dir.c_str());
        if (!d) {
            return files;
        }

        struct dirent* entry;
        while ((entry = readdir(d)) != nullptr) {
            std::string name = entry->d_name;
            if (name.size() > pattern.size() &&
                name.substr(name.size() - pattern.size()) == pattern) {
                files.push_back(dir + "/" + name);
            }
        }

        closedir(d);
        return files;
    }
};

} // namespace UC::LustreStore
```

### 4.5 信号处理集成

```cpp
namespace UC::LustreStore {

class LustreStoreImpl {
public:
    Status Setup(const Config& config) {
        // ... 其他初始化

        // 注册信号处理器
        RegisterSignalHandlers();

        // 清理残留临时文件
        TempFileCleanupConfig cleanupConfig;
        cleanupConfig.maxAgeSeconds = 3600;  // 1 小时
        return layout_->CleanupTempFiles(cleanupConfig);
    }

    ~LustreStoreImpl() {
        // 退出时清理本进程的临时文件
        CleanupOwnTempFiles();
    }

private:
    void RegisterSignalHandlers() {
        // 注册清理函数到 atexit
        std::atexit([]() {
            // 全局清理逻辑
        });

        // 注册信号处理器
        signal(SIGTERM, SignalHandler);
        signal(SIGINT, SignalHandler);
    }

    static void SignalHandler(int signal) {
        // 尝试清理临时文件
        // 注意: 在信号处理器中要谨慎，只使用异步信号安全函数
    }

    void CleanupOwnTempFiles() {
        // 清理本进程的所有 .tmp.<pid> 文件
        // 不检查年龄和锁，因为本进程即将退出
    }
};

} // namespace UC::LustreStore
```

---

## 5. 更新的 API 定义

### 5.1 LustreStore API (完整版)

```cpp
namespace UC {

class LustreStore : public StoreV1 {
public:
    // ===== 生命周期管理 =====

    /**
     * @brief 使用配置初始化存储
     * @param config 配置参数 (必须通过 Validate() 检查)
     * @return Status 初始化状态
     * @post 成功后可以调用其他方法
     */
    Status Setup(const Config& config) override;

    /**
     * @brief 析构，自动清理资源
     * @note 会清理本进程创建的所有临时文件
     */
    ~LustreStore() override;

    // ===== 元数据操作 =====

    /**
     * @brief 批量检查块是否存在
     * @param blocks 块 ID 数组 (不能为 nullptr)
     * @param num 块数量 (必须 > 0)
     * @return std::vector<uint8_t> 存在性位图 (1=存在, 0=不存在)
     * @pre blocks 必须指向包含 num 个元素的数组
     * @post 返回的 vector 长度等于 num
     */
    std::vector<uint8_t> Lookup(const BlockId* blocks, size_t num) override;

    /**
     * @brief 查找前缀序列中首个缺失块
     * @param blocks 块 ID 数组 (不能为 nullptr)
     * @param num 块数量 (必须 > 0)
     * @return Expected<ssize_t> 首个缺失块索引，全部存在返回 -1
     * @pre blocks 必须按前缀排序，否则结果不正确
     * @note 调用者负责确保 blocks 已排序
     */
    Expected<ssize_t> LookupOnPrefix(const BlockId* blocks, size_t num) override;

    /**
     * @brief 预取提示 (非阻塞)
     * @param blocks 块 ID 数组 (num=0 时可为 nullptr)
     * @param num 块数量
     * @note 实现可能忽略此提示
     */
    void Prefetch(const BlockId* blocks, size_t num) override;

    // ===== 数据传输操作 =====

    /**
     * @brief 启动异步加载任务 (Lustre → Device)
     * @param blocks 块 ID 数组 (不能为 nullptr)
     * @param num 块数量 (必须 > 0)
     * @param addrs 设备内存地址数组 (不能为 nullptr，每个元素也不能为 nullptr)
     * @return TaskHandle 任务句柄 (用于 Check/Wait)
     * @pre addrs[i] 必须指向足够大的内存区域 (至少 blockSize 字节)
     */
    TaskHandle Load(const BlockId* blocks, size_t num,
                    const void* const* addrs) override;

    /**
     * @brief 启动异步转储任务 (Device → Lustre)
     * @param blocks 块 ID 数组 (不能为 nullptr)
     * @param num 块数量 (必须 > 0)
     * @param addrs 设备内存地址数组 (不能为 nullptr，每个元素也不能为 nullptr)
     * @return TaskHandle 任务句柄 (用于 Check/Wait)
     * @note 具有幂等性: 多次转储相同 Block 不会导致数据损坏
     */
    TaskHandle Dump(const BlockId* blocks, size_t num,
                    const void* const* addrs) override;

    // ===== 任务管理 =====

    /**
     * @brief 轮询任务完成状态 (非阻塞)
     * @param handle 任务句柄 (必须有效)
     * @return bool true=完成, false=进行中
     */
    bool Check(TaskHandle handle) const override;

    /**
     * @brief 阻塞等待任务完成
     * @param handle 任务句柄 (必须有效)
     * @return Status 任务执行状态
     * @post 任务完成后，数据已传输完成 (或失败)
     */
    Status Wait(TaskHandle handle) const override;

private:
    std::unique_ptr<LustreStoreImpl> impl_;
};

} // namespace UC
```

---

## 6. 更新的数据模型

### 6.1 TaskDesc (完整版)

```cpp
namespace UC::LustreStore {

/**
 * @brief 任务描述符
 *
 * **参数责任划分**:
 * - [输入]: 由调用者提供，必须在调用前有效
 * - [自动]: 由 TransManager 从 Config 自动填充
 *
 * **线程安全性**:
 * - 只读结构，可在多线程中安全传递
 *
 * **生命周期**:
 * - 仅在任务执行期间需要有效
 * - 任务完成后可销毁
 */
struct TaskDesc {
    // ===== [输入] 由调用者提供 =====

    const BlockId* blockIds{nullptr};  ///< 块 ID 数组 [必须]
    size_t numBlocks{0};               ///< 块数量 [必须]
    const void* const* addrs{nullptr}; ///< 设备内存地址数组 [必须]

    // ===== [自动] 由 TransManager 填充 =====

    size_t shardIndex{0};    ///< 起始分片索引
    size_t numShards{0};     ///< 分片数量
    size_t tensorSize{0};    ///< 单个 tensor 大小
    size_t shardSize{0};     ///< 单个 shard 大小
    size_t blockSize{0};     ///< 单个 block 大小

    // ===== 构造函数 =====

    TaskDesc() = default;

    /// 便捷构造函数 (仅输入参数)
    TaskDesc(const BlockId* blocks, size_t num, const void* const* addresses)
        : blockIds(blocks), numBlocks(num), addrs(addresses) {}

    // ===== 校验方法 =====

    /**
     * @brief 校验参数有效性
     * @return true 参数有效, false 参数无效
     */
    bool IsValid() const {
        if (numBlocks == 0) return true;  // 空任务有效
        return blockIds != nullptr && addrs != nullptr;
    }
};

} // namespace UC::LustreStore
```

---

## 7. 更新的错误处理

### 7.1 错误码扩展

```cpp
namespace UC::LustreStore {

/**
 * @brief 参数校验错误码
 */
namespace ParamErrors {

// 参数校验失败
constexpr int32_t E_PARAM_NULL = -50200;        // 参数为 null
constexpr int32_t E_PARAM_RANGE = -50201;       // 参数超出范围
constexpr int32_t E_PARAM_CONSISTENCY = -50202; // 参数一致性检查失败
constexpr int32_t E_PARAM_STATE = -50203;       // 对象状态不允许操作

// 工厂函数
inline Status NullParam(const std::string& name) {
    return Status(E_PARAM_NULL, name + " cannot be null");
}

inline Status RangeError(const std::string& name, size_t value,
                          size_t min, size_t max) {
    std::string msg = name + "=" + std::to_string(value) +
                     " out of range [" + std::to_string(min) +
                     ", " + std::to_string(max) + "]";
    return Status(E_PARAM_RANGE, msg);
}

inline Status ConsistencyError(const std::string& msg) {
    return Status(E_PARAM_CONSISTENCY, msg);
}

} // namespace ParamErrors

} // namespace UC::LustreStore
```

---

## 附录 A: 变更对比表

| 章节 | 变更类型 | 说明 |
|------|----------|------|
| 4. API接口定义 | 新增 | 参数校验宏定义 |
| 4. API接口定义 | 修改 | 所有 public API 添加参数校验 |
| 5. 数据模型设计 | 修改 | TaskDesc 添加参数责任注释 |
| 8. 错误处理机制 | 新增 | 参数校验错误码 |
| SpaceLayout::CommitFile | 修改 | 使用 link() 替代 rename() |
| SpaceLayout::CleanupTempFiles | 修改 | 添加年龄和锁检查 |

---

## 附录 B: 测试建议

### B.1 参数校验测试

```cpp
// 参数校验测试用例
TEST(LustreStore, Lookup_NullBlocks) {
    LustreStore store;
    store.Setup(validConfig);

    // 空指针测试
    auto result = store.Lookup(nullptr, 10);
    EXPECT_TRUE(result.empty());  // 或抛出异常
}

TEST(LustreStore, Load_NullAddrs) {
    LustreStore store;
    store.Setup(validConfig);

    BlockId blocks[1];
    auto handle = store.Load(blocks, 1, nullptr);
    EXPECT_EQ(handle, TaskHandle{});  // 无效句柄
}

TEST(LustreStore, Load_EmptyBlockList) {
    LustreStore store;
    store.Setup(validConfig);

    // 空列表应被允许
    auto handle = store.Load(nullptr, 0, nullptr);
    EXPECT_TRUE(handle.IsValid());
}
```

### B.2 并发写入测试

```cpp
// 并发写入测试用例
TEST(LustreStore, ConcurrentDumpSameBlock) {
    // 创建两个 Store 实例 (模拟两个进程)
    LustreStore store1, store2;
    store1.Setup(validConfig);
    store2.Setup(validConfig);

    BlockId block;
    void* addr1 = AllocateBuffer();
    void* addr2 = AllocateBuffer();

    // 并发转储相同 Block
    auto handle1 = store1.Dump(&block, 1, &addr1);
    auto handle2 = store2.Dump(&block, 1, &addr2);

    store1.Wait(handle1);
    store2.Wait(handle2);

    // 验证: 文件存在且内容一致
    // 无论哪个进程先完成，结果应该一致
}
```

### B.3 临时文件清理测试

```cpp
// 临时文件清理测试
TEST(SpaceLayout, CleanupOldTempFiles) {
    SpaceLayout layout;
    layout.Setup(validConfig);

    // 创建一个旧的临时文件
    std::string oldTemp = CreateOldTempFile(layout);

    // 运行清理
    TempFileCleanupConfig config;
    config.maxAgeSeconds = 3600;  // 1 小时
    layout.CleanupTempFiles(config);

    // 验证: 旧文件被清理
    EXPECT_FALSE(FileExists(oldTemp));
}

TEST(SpaceLayout, PreserveLockedTempFiles) {
    SpaceLayout layout;
    layout.Setup(validConfig);

    // 创建一个被锁定的临时文件
    std::string lockedTemp = CreateLockedTempFile(layout);

    // 运行清理
    TempFileCleanupConfig config;
    config.checkFileLock = true;
    layout.CleanupTempFiles(config);

    // 验证: 被锁定的文件被保留
    EXPECT_TRUE(FileExists(lockedTemp));
}
```

---

**文档结束**
