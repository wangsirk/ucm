# Lustre Store 设计文档 v1.2

## 文档版本信息

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| 1.0 | 2026-04-01 | Design Team | 初始版本 |
| 1.1 | 2026-04-01 | Design Team | 修复审查报告中的必须修复问题 |
| 1.2 | 2026-04-01 | Design Team | 修复二次审查报告中的阻塞问题 |

---

## 变更摘要

### 🔴 阻塞问题修复

| ID | 问题 | 状态 |
|----|------|------|
| **S-003** | 信号处理器中执行非异步信号安全操作 | ✅ 已修复 |

### 🟡 建议问题修复

| ID | 问题 | 状态 |
|----|------|------|
| **S-002** | 备选方案 TOCTOU 竞态窗口 | ✅ 已删除 |
| **S-004** | ExtractPidFromPath 异常处理缺失 | ✅ 已修复 |
| **A-001** | DuplicateKey 错误处理语义不统一 | ✅ 已文档化 |
| **B-004** | Setup() 可重入性未定义 | ✅ 已定义 |

---

## 目录

1. [临时文件清理策略 v1.2](#1-临时文件清理策略-v12)
2. [CommitFile 实现 v1.2](#2-commitfile-实现-v12)
3. [DuplicateKey 语义文档](#3-duplicatekey-语义文档)
4. [Setup() 可重入性定义](#4-setup-可重入性定义)
5. [异常处理规范](#5-异常处理规范)

---

## 1. 临时文件清理策略 v1.2

### 1.1 问题说明 (S-003)

v1.1 版本中在信号处理器中执行文件操作，但 `open()`, `stat()`, `unlink()` 等函数不是异步信号安全的，可能导致死锁或未定义行为。

### 1.2 修复方案

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         临时文件清理策略 (安全版本)                              │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  清理时机 (仅使用安全机制)                                              │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  ✅ 1. Setup() 时清理 (初始化)                                          │ │   │
│  │  │     - 扫描所有 .tmp.* 文件                                             │ │   │
│  │  │     - 只清理满足安全条件的文件                                         │ │   │
│  │  │                                                                       │ │   │
│  │  │  ✅ 2. 正常退出时清理 (atexit)                                          │ │   │
│  │  │     - 使用 atexit() 注册清理函数                                       │ │   │
│  │  │     - 进程正常终止时自动调用                                           │ │   │
│  │  │                                                                       │ │   │
│  │  │  ❌ 3. 异常退出时 (移除)                                                 │ │   │
│  │  │     - 不再使用信号处理器                                               │ │   │
│  │  │     - 异常终止后由下次 Setup() 清理                                    │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  清理条件 (全部满足才清理)                                               │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  1. 文件名匹配 .tmp.<pid> 后缀 (仅本进程)                              │ │   │
│  │  │  2. 文件年龄超过阈值 (默认: 1 小时)                                    │ │   │
│  │  │  3. 文件未被锁定 (使用 fcntl 检查)                                    │ │   │
│  │  │  4. 进程不存在 (检查 /proc/<pid>)                                      │ │   │
│  │  │     - 只有当确认进程不存在时才清理                                    │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 1.3 实现代码 (安全版本)

```cpp
namespace UC::LustreStore {

class SpaceLayout {
public:
    // ===== 初始化时清理 =====

    Status Setup(const Config& config) {
        // ... 其他初始化

        // 清理残留的临时文件 (安全)
        TempFileCleanupConfig cleanupConfig;
        cleanupConfig.maxAgeSeconds = 3600;  // 1 小时
        cleanupConfig.checkFileLock = true;
        cleanupConfig.checkProcessExists = true;  // 必须检查进程

        return CleanupTempFiles(cleanupConfig);
    }

private:
    // ===== 清理本进程的临时文件 =====

    /**
     * @brief 清理本进程的所有临时文件
     *
     * 在析构函数或 atexit() 注册的函数中调用
     * 注意: 此时进程即将退出，可以放宽清理条件
     */
    void CleanupOwnTempFiles() {
        std::string dataDir = mountPoint_ + "/data";
        auto shardDirs = ListShardDirs(dataDir);

        for (const auto& shardDir : shardDirs) {
            auto tempFiles = ListTempFiles(shardDir, pid_);

            for (const auto& filePath : tempFiles) {
                // 不检查年龄和锁，直接删除 (本进程即将退出)
                Remove(filePath);
                UC_DEBUG("Cleaned own temp file: {}", filePath);
            }
        }
    }

public:
    // ===== 临时文件清理 =====

    /**
     * @brief 清理残留的临时文件 (Setup 时调用)
     *
     * **安全性**: 仅在 Setup() 时调用，使用安全条件检查
     *
     * **清理条件** (全部满足才清理):
     * 1. 文件名匹配 .tmp.<pid> 后缀
     * 2. 文件年龄超过 maxAgeSeconds
     * 3. 文件未被锁定
     * 4. 进程不存在 (checkProcessExists=true 时)
     *
     * @param config 清理配置
     * @return Status 清理状态
     */
    Status CleanupTempFiles(const TempFileCleanupConfig& config) {
        if (!config.enableCleanup) {
            return Status::OK();
        }

        std::string dataDir = mountPoint_ + "/data";
        size_t cleanedCount = 0;

        // 遍历所有分片目录
        auto shardDirs = ListShardDirs(dataDir);
        for (const auto& shardDir : shardDirs) {
            // 扫描临时文件
            auto tempFiles = ListTempFiles(shardDir, pid_);

            for (const auto& filePath : tempFiles) {
                if (ShouldCleanupFile(filePath, config)) {
                    if (Remove(filePath)) {
                        cleanedCount++;
                        UC_INFO("Cleaned stale temp file: {}", filePath);
                    }
                }
            }
        }

        UC_INFO("Temp file cleanup completed: {} files removed", cleanedCount);
        return Status::OK();
    }

private:
    /**
     * @brief 判断文件是否应该被清理
     * @return true 应该清理, false 不清理
     */
    bool ShouldCleanupFile(
        const std::string& filePath,
        const TempFileCleanupConfig& config) const {

        // 条件 1: 检查文件年龄
        auto ageResult = GetFileAge(filePath);
        if (!ageResult.OK()) {
            return false;  // 无法获取年龄，跳过
        }
        if (ageResult.Value() < config.maxAgeSeconds) {
            return false;  // 文件太新，不清理
        }

        // 条件 2: 检查文件锁
        if (config.checkFileLock) {
            auto lockResult = IsFileLocked(filePath);
            if (!lockResult.OK()) {
                return false;
            }
            if (lockResult.Value()) {
                return false;  // 文件被锁定，不清理
            }
        }

        // 条件 3: 检查进程是否存在 (必须检查)
        if (config.checkProcessExists) {
            pid_t filePid;
            if (!ExtractPidFromPath(filePath, filePid)) {
                return false;  // 无法提取 PID，跳过
            }

            if (IsProcessRunning(filePid)) {
                return false;  // 进程仍在运行，不清理
            }
            // 进程不存在，可以安全清理
        }

        return true;  // 所有条件满足
    }

    /**
     * @brief 从文件路径提取 PID
     * @return true 成功提取, false 失败
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
        } catch (const std::exception& e) {
            UC_WARN("Failed to extract PID from path {}: {}", filePath, e.what());
            return false;
        }
    }

    /**
     * @brief 检查进程是否正在运行
     * @return true 进程运行中, false 进程不存在
     */
    bool IsProcessRunning(pid_t pid) const {
        // 检查 /proc/<pid> 是否存在
        std::string procPath = "/proc/" + std::to_string(pid);
        return (access(procPath.c_str(), F_OK) == 0);
    }
};

} // namespace UC::LustreStore
```

### 1.4 atexit() 注册

```cpp
namespace UC::LustreStore {

class LustreStoreImpl {
public:
    Status Setup(const Config& config) {
        // ... 其他初始化

        // 注册清理函数到 atexit
        std::atexit([this]() {
            this->CleanupOwnTempFiles();
        });

        // 清理残留临时文件
        TempFileCleanupConfig cleanupConfig;
        cleanupConfig.maxAgeSeconds = 3600;
        return layout_->CleanupTempFiles(cleanupConfig);
    }

    ~LustreStoreImpl() {
        // 析构函数也会清理
        CleanupOwnTempFiles();
    }

private:
    void CleanupOwnTempFiles();
};

} // namespace UC::LustreStore
```

---

## 2. CommitFile 实现 v1.2

### 2.1 问题说明 (S-002)

v1.1 版本中的备选方案 `CommitFileFallback` 存在 TOCTOU (Time-Of-Check-Time-Of-Use) 竞态窗口。

### 2.2 修复方案

**删除备选方案，仅使用 `link()` 方案**

```cpp
namespace UC::LustreStore {

class SpaceLayout {
public:
    // ===== 文件提交 (仅 link() 方案) =====

    /**
     * @brief 提交临时文件为正式文件 (原子性保证)
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
     * **实现说明**:
     * - 仅使用 link() 方案，不提供备选方案
     * - link() 在 POSIX 系统上是原子操作
     * - 如果文件系统不支持 link()，会返回错误
     *
     * @param blockId 块 ID
     * @param success 是否成功 (true=提交, false=删除临时文件)
     * @return Status 操作状态
     *   - Status::OK(): 提交成功
     *   - Status::DuplicateKey(): 文件已存在 (其他进程已提交)
     *   - Status::IOError(): I/O 错误
     */
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

        // 使用 link() 创建硬链接 (原子操作)
        if (link(tmpPath.c_str(), finalPath.c_str()) == 0) {
            // 成功: 删除临时文件
            Remove(tmpPath);
            UC_INFO("Commit succeeded: {} -> {}", tmpPath, finalPath);
            return Status::OK();
        }

        int error = errno;
        if (error == EEXIST) {
            // 文件已存在: 其他进程已经提交
            Remove(tmpPath);
            UC_INFO("Block already exists (concurrent commit), removed temp file");
            return Status::DuplicateKey("Block already exists");
        }

        // 其他错误 (如文件系统不支持 link())
        UC_ERROR("Commit failed: {} ({})", strerror(error), error);
        return Status::IOError(std::string("link() failed: ") + strerror(error));
    }

    // ===== 不提供备选方案 =====

    // 删除了 CommitFileFallback() 方法
    // 理由: 存在 TOCTOU 竞态窗口，不安全
};

} // namespace UC::LustreStore
```

### 2.3 文件系统兼容性

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         文件系统兼容性                                            │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  link() 支持情况:                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  文件系统      │ link() 支持 │ 备注                                    │   │
│  │  ├─────────────┼─────────────┼─────────────────────────────────────────────┤   │
│  │  │ Lustre       │ ✅ 支持      │ 主要目标平台                            │   │
│  │  │ ext4        │ ✅ 支持      │ 本地文件系统                             │   │
│  │  │ xfs         │ ✅ 支持      │ 本地文件系统                             │   │
│  │  │ NFS         │ ⚠️  取决于配置 │ 需要配置 no_root_squash               │   │
│  │  │ FAT32       │ ❌ 不支持    │ 不推荐                                  │   │
│  │  │ exFAT       │ ❌ 不支持    │ 不推荐                                  │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  Lustre 注意事项:                                                              │
│  - link() 在 Lustre 上创建硬链接 (指向同一 OST 数据)                             │
│  - 硬链接指向相同的 inode，不会额外占用 OST 空间                                   │
│  - 删除任一硬链接都会减少引用计数                                               │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. DuplicateKey 语义文档

### 3.1 问题说明 (A-001)

`CommitFile` 返回 `DuplicateKey` 表示文件已存在，但这是幂等性保证的一部分，应该被视为成功，而不是错误。

### 3.2 语义定义

```cpp
namespace UC::LustreStore {

/**
 * @brief DuplicateKey 错误的语义
 *
 * **定义**:
 * - `Status::DuplicateKey` 表示操作的目标已存在
 * - 对于幂等操作，DuplicateKey 应被视为成功
 * - 对于非幂等操作，DuplicateKey 是一个错误
 *
 * **在 LustreStore 中的语义**:
 *
 * | 操作 | DuplicateKey 含义 | 处理方式 |
 * |------|-------------------|----------|
 * | Dump() | Block 已存在 | ✅ 成功 (幂等性) |
 * | Load() | N/A | N/A |
 * | Lookup() | N/A | N/A |
 *
 * **示例代码**:
 * ```cpp
 * auto result = store.Dump(&blockId, 1, &addr);
 * store.Wait(result);
 *
 * if (result == Status::DuplicateKey()) {
 *     // 这不是错误，数据已经存在
 *     // 可以安全地继续
 * }
 * ```
 *
 * **与真正错误的区别**:
 *
 * | 错误类型 | 含义 | 是否可恢复 |
 * |----------|------|------------|
 * | DuplicateKey | 数据已存在，操作幂等 | ✅ 无需恢复 |
 * | IOError | I/O 失败，数据可能损坏 | ⚠️ 需要重试 |
 * | InvalidParam | 参数错误 | ❌ 调用者错误 |
 */
namespace Semantics {

/**
 * @brief 检查状态是否为成功 (包括 DuplicateKey)
 *
 * 对于幂等操作，DuplicateKey 被视为成功
 */
inline bool IsSuccessOrDuplicate(const Status& status) {
    return status.OK() || status.Code() == Status::DuplicateKey().Code();
}

} // namespace Semantics

} // namespace UC::LustreStore
```

### 3.3 使用示例

```cpp
// ===== 正确的 DuplicateKey 处理 =====

TaskHandle handle = store.Dump(&blockId, 1, &addr);
Status status = store.Wait(handle);

if (status.OK()) {
    // 写入成功
    UC_INFO("Block stored successfully");
} else if (status.Code() == Status::DuplicateKey().Code()) {
    // 文件已存在 (其他进程或之前已写入)
    // 这是成功的情况，不是错误
    UC_INFO("Block already exists (idempotent)");
} else {
    // 真正的错误
    UC_ERROR("Failed to store block: {}", status.ToString());
}
```

---

## 4. Setup() 可重入性定义

### 4.1 问题说明 (B-004)

多次调用 `Setup()` 的行为未定义。

### 4.2 可重入性规范

```cpp
namespace UC::LustreStore {

class LustreStore : public StoreV1 {
public:
    /**
     * @brief 使用配置初始化存储
     *
     * **可重入性**:
     * - ❌ 不支持多次调用 Setup()
     * - 多次调用将返回 Status::InvalidState("Already initialized")
     * - 如需重新初始化，请先析构当前实例再创建新实例
     *
     * **线程安全性**:
     * - Setup() 不是线程安全的
     * - 多线程同时调用 Setup() 会导致未定义行为
     * - 调用者需确保只有一个线程调用 Setup()
     *
     * **使用示例**:
     * ```cpp
     * LustreStore store;
     *
     * // 第一次调用
     * assert(store.Setup(config).OK());
     *
     * // 第二次调用 - 会失败
     * auto status = store.Setup(otherConfig);
     * assert(status.Code() == Status::InvalidState().Code());
     * ```
     *
     * @param config 配置参数
     * @return Status 初始化状态
     *   - Status::OK(): 成功初始化
     *   - Status::InvalidState(): 已经初始化
     *   - Status::InvalidParam(): 配置参数无效
     */
    Status Setup(const Config& config) override;

private:
    std::once_flag initOnce_;
    std::atomic<bool> initialized_{false};
};

} // namespace UC
```

### 4.3 实现

```cpp
Status LustreStore::Setup(const Config& config) {
    // 检查是否已初始化
    if (initialized_.load(std::memory_order_acquire)) {
        return Status::InvalidState("LustreStore already initialized");
    }

    // 使用 once_flag 确保只初始化一次
    std::call_once(initOnce_, [&]() {
        // 实际初始化逻辑
        impl_ = std::make_unique<LustreStoreImpl>();
        auto result = impl_->Setup(config);
        if (result.OK()) {
            initialized_.store(true, std::memory_order_release);
        }
    });

    return initialized_.load(std::memory_order_acquire)
        ? Status::OK()
        : Status::InvalidState("Initialization failed");
}
```

---

## 5. 异常处理规范

### 5.1 问题说明 (S-004)

`ExtractPidFromPath` 中 `std::stol` 可能抛异常但未捕获。

### 5.2 异常处理策略

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         异常处理策略                                          │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  异常分类                                                                   │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  1. 可恢复异常 - 记录日志，返回默认值或错误状态                         │ │   │
│  │  │     示例: std::stol() 转换失败                                         │ │   │
│  │  │                                                                       │ │   │
│  │  │  2. 不可恢复异常 - 记录错误后重新抛出 (使用 noexcept)                  │ │   │
│  │  │     示例: 内存分配失败                                                │ │   │
│  │  │                                                                       │ │   │
│  │  │  3. 析构函数异常 - 不抛出异常，使用 try-catch 记录日志                  │ │   │
│  │  │     示例: 文件关闭失败                                                  │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 5.3 实现规范

```cpp
namespace UC::LustreStore {

// ===== 可恢复异常处理示例 =====

bool ExtractPidFromPath(const std::string& filePath, pid_t& outPid) const {
    size_t lastDot = filePath.rfind('.');
    if (lastDot == std::string::npos) {
        return false;
    }

    std::string pidStr = filePath.substr(lastDot + 1);
    try {
        outPid = std::stol(pidStr);
        return true;
    } catch (const std::invalid_argument& e) {
        UC_WARN("Invalid PID format in path {}: {}", filePath, e.what());
        return false;
    } catch (const std::out_of_range& e) {
        UC_WARN("PID value out of range in path {}: {}", filePath, e.what());
        return false;
    } catch (...) {
        UC_WARN("Unknown exception when extracting PID from path {}", filePath);
        return false;
    }
}

// ===== 析构函数异常处理示例 =====

LustreFile::~LustreFile() {
    try {
        Close();
    } catch (const std::exception& e) {
        // 析构函数不应该抛出异常
        UC_ERROR("Exception in LustreFile destructor: {}", e.what());
        // 不重新抛出
    } catch (...) {
        UC_ERROR("Unknown exception in LustreFile destructor");
        // 不重新抛出
    }
}

// ===== noexcept 函数示例 =====

class Status {
public:
    // 移动构造不抛出异常
    Status(Status&& other) noexcept
        : code_(other.code_), msg_(std::move(other.msg_)) {
        other.code_ = 0;
    }

    // 移动赋值不抛出异常
    Status& operator=(Status&& other) noexcept {
        if (this != &other) {
            code_ = other.code_;
            msg_ = std::move(other.msg_);
            other.code_ = 0;
        }
        return *this;
    }
};

} // namespace UC::LustreStore
```

---

## 附录 A: 问题修复对比表

### v1.1 → v1.2 变更

| 章节 | v1.1 | v1.2 | 变更原因 |
|------|------|------|----------|
| 临时文件清理 | 使用信号处理器 | 使用 atexit() | S-003: 异步信号安全 |
| CommitFile | 提供备选方案 | 仅 link() 方案 | S-002: TOCTOU 竞态 |
| ExtractPidFromPath | 无异常处理 | 完整异常处理 | S-004: 异常安全 |
| DuplicateKey 语义 | 未文档化 | 完整文档化 | A-001: 语义清晰 |
| Setup() 可重入性 | 未定义 | 明确不支持 | B-004: 行为定义 |

---

## 附录 B: 测试建议

### B.1 临时文件清理测试

```cpp
// 正常退出清理测试
TEST(LustreStore, NormalExitCleanup) {
    {
        LustreStore store;
        store.Setup(config);

        // 创建临时文件
        std::string tmpFile = CreateTempFile();

    }  // 析构函数应清理临时文件

    // 验证: 临时文件被清理
    EXPECT_FALSE(FileExists(tmpFile));
}

// Setup 清理测试
TEST(LustreStore, SetupCleanup) {
    // 创建一个旧的临时文件 (进程不存在)
    std::string oldTmp = CreateOldTempFile(deadPid);

    LustreStore store;
    store.Setup(config);

    // 验证: 旧文件被清理
    EXPECT_FALSE(FileExists(oldTmp));
}
```

### B.2 并发写入测试

```cpp
TEST(LustreStore, ConcurrentDumpSameBlock) {
    LustreStore store1, store2;
    store1.Setup(config);
    store2.Setup(config);

    BlockId block;
    void* addr1 = AllocateBuffer();
    void* addr2 = AllocateBuffer();

    // 并发转储相同 Block
    auto handle1 = store1.Dump(&block, 1, &addr1);
    auto handle2 = store2.Dump(&block, 1, &addr2);

    auto status1 = store1.Wait(handle1);
    auto status2 = store2.Wait(handle2);

    // 验证: 至少一个成功，另一个也是 DuplicateKey(成功)
    bool atLeastOneOk = status1.OK() ||
                        (status1.Code() == Status::DuplicateKey().Code());
    EXPECT_TRUE(atLeastOneOk);

    // 验证: 文件存在且一致
    EXPECT_TRUE(FileExists(GetFinalPath(block)));
}
```

---

**文档结束**
