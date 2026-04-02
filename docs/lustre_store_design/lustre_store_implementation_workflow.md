# Lustre Store 实现工作流

## 文档版本信息

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| 1.0 | 2026-04-01 | Implementation Team | 初始版本，基于 v1.2 设计文档 |

---

## 目录

1. [项目概述](#1-项目概述)
2. [设计审查结论](#2-设计审查结论)
3. [实现阶段划分](#3-实现阶段划分)
4. [P0: 核心基础设施](#4-p0-核心基础设施)
5. [P1: 数据传输核心](#5-p1-数据传输核心)
6. [P2: 性能与优化](#6-p2-性能与优化)
7. [P3: 增强与验证](#7-p3-增强与验证)
8. [测试策略](#8-测试策略)
9. [质量门禁](#9-质量门禁)

---

## 1. 项目概述

### 1.1 目标

实现 LustreStore - UCM 的存储后端，专门针对 Lustre 并行文件系统优化。

### 1.2 设计基础

- **详细设计文档**: [lustre_store_detailed_design.md](lustre_store_detailed_design.md)
- **v1.1 设计**: [lustre_store_design_v1.1.md](lustre_store_design_v1.1.md) - 参数校验、并发写入保护
- **v1.2 设计**: [lustre_store_design_v1.2.md](lustre_store_design_v1.2.md) - 信号处理器安全修复
- **v2 审查报告**: [lustre_store_review_report_v2.md](lustre_store_review_report_v2.md) - 评分 8.5/10

### 1.3 当前实现状态

| 组件 | 文件 | 状态 | 说明 |
|------|------|------|------|
| LustreStore | lustre_store.h/cc | 🟡 框架完成 | 接口 TODO 实现 |
| SpaceLayout | space_layout.h/cc | 🟡 部分完成 | 基础结构已有 |
| SpaceManager | space_manager.h/cc | 🟡 部分完成 | 基础结构已有 |
| TransManager | trans_manager.h/cc | 🟡 部分完成 | 基础结构已有 |
| TransQueue | trans_queue.h/cc | 🟡 部分完成 | 基础结构已有 |
| TransTask | trans_task.h | ✅ 完成 | 基本定义 |
| GlobalConfig | global_config.h | ✅ 完成 | 配置结构 |

---

## 2. 设计审查结论

### 2.1 审查评分

| 维度 | v1.0 | v1.1 | v1.2 | 变化 |
|------|------|------|------|------|
| 架构合理性 | 8/10 | 9/10 | 9/10 | +1 |
| API 设计 | 7/10 | 8.5/10 | 8.5/10 | +1.5 |
| 性能策略 | 8/10 | 9/10 | 9/10 | +1 |
| 错误处理 | 7/10 | 8/10 | 8/10 | +1 |
| **综合评分** | **7.5/10** | **8.5/10** | **8.5/10** | **+1** |

### 2.2 实现准入判定

**结论**: ✅ **可以进入实现阶段**

**前提条件** (已在 v1.2 中完成):
- ✅ S-003: 信号处理器安全问题已修复
- ✅ S-002: 备选方案 TOCTOU 竞态已删除
- ✅ B-002: 参数校验框架已定义
- ✅ A-001: DuplicateKey 语义已文档化
- ✅ B-004: Setup() 可重入性已定义

---

## 3. 实现阶段划分

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                            实现阶段划分 (8 周)                                     │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  Week 1-2: P0 核心基础设施                                                         │
│  ├── 参数校验框架 (v1.1 设计)                                                      │
│  ├── SpaceLayout 完整实现 (路径生成 + CommitFile link())                          │
│  ├── LustreFile 文件操作封装                                                       │
│  └── 配置管理完整验证                                                              │
│                                                                                     │
│  Week 3-4: P1 数据传输核心                                                         │
│  ├── TransQueue I/O 队列 + 任务拆分                                                │
│  ├── TransManager 任务生命周期管理                                                 │
│  ├── Load/Dump 流程实现                                                            │
│  └── 错误处理与恢复                                                                │
│                                                                                     │
│  Week 5-6: P2 性能与优化                                                           │
│  ├── 异步 I/O (io_uring/libaio 后端)                                               │
│  ├── 分层线程池实现                                                                │
│  ├── CPU 亲和性配置                                                                │
│  └── 目录分片优化                                                                  │
│                                                                                     │
│  Week 7-8: P3 增强与验证                                                           │
│  ├── 监控指标收集                                                                  │
│  ├── 单元测试                                                                      │
│  ├── 集成测试                                                                      │
│  ├── 并发测试                                                                      │
│  └── 文档完善                                                                      │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. P0: 核心基础设施

### 4.1 参数校验框架 (v1.1)

**文件**: `ucm/store/lustre/cc/param_validator.h` (新建)

**实现内容**:

```cpp
// 参数校验宏定义
#define CHECK_NOT_NULL(ptr, name) ...
#define CHECK_PARAM(condition, message) ...
#define CHECK_RANGE(value, min, max, name) ...
#define CHECK_CONSISTENCY(condition, message) ...

// 参数校验错误码
namespace ParamErrors {
    constexpr int32_t E_PARAM_NULL = -50200;
    constexpr int32_t E_PARAM_RANGE = -50201;
    constexpr int32_t E_PARAM_CONSISTENCY = -50202;
    constexpr int32_t E_PARAM_STATE = -50203;
}
```

**验收标准**:
- [ ] 所有 public API 包含参数校验
- [ ] 校验失败返回 Status::InvalidParam
- [ ] 错误信息包含参数名和值

---

### 4.2 SpaceLayout 完整实现

**文件**: `ucm/store/lustre/cc/space_layout.cc` (扩展现有)

**实现内容**:

#### 4.2.1 路径生成

```cpp
std::string SpaceLayout::DataFilePath(const Detail::BlockId& blockId, bool activated) const {
    // 1. 选择存储后端
    // 2. 生成分片路径
    // 3. 生成文件名 (BlockId -> Hex)
    // 4. 如果 activated=true, 添加 .tmp.{pid} 后缀
}
```

#### 4.2.2 CommitFile (v1.1 link() 方案)

```cpp
Status SpaceLayout::CommitFile(const Detail::BlockId& blockId, bool success) const {
    // 失败: 删除临时文件
    if (!success) { ... }

    // 使用 link() + EEXIST 检测 (原子操作)
    if (link(tmpPath.c_str(), finalPath.c_str()) == 0) {
        // 成功
        Remove(tmpPath);
        return Status::OK();
    }

    if (errno == EEXIST) {
        // 其他进程已提交 (幂等性)
        Remove(tmpPath);
        return Status::DuplicateKey("Block already exists");
    }

    // 其他错误
    return Status::IOError(...);
}
```

**验收标准**:
- [ ] 路径生成正确处理目录分片
- [ ] CommitFile 使用 link() 原子操作
- [ ] DuplicateKey 正确返回
- [ ] 临时文件清理完成

---

### 4.3 LustreFile 文件操作

**文件**: `ucm/store/lustre/cc/lustre_file.h` (新建)

**实现内容**:

```cpp
class LustreFile {
public:
    explicit LustreFile(const std::string& path);
    ~LustreFile();

    // 文件创建
    Status CreateStriped(mode_t mode = 0644);  // Lustre 条带化
    Status CreateNormal(uint32_t flags, mode_t mode = 0644);

    // 文件操作
    Status Open(uint32_t flags);
    Status Read(void* buffer, size_t size, off64_t offset);
    Status Write(const void* buffer, size_t size, off64_t offset);
    void Close();

    // 目录操作
    static Status MkDir(const std::string& path, mode_t mode = 0755);
    bool Access(int32_t mode) const;

    // 文件管理
    Status Rename(const std::string& newName);
    static Status Remove(const std::string& path);
    size_t GetSize() const;

    // 状态查询
    bool IsOpen() const;
    int GetFd() const;
};
```

**验收标准**:
- [ ] 支持 Lustre 条带化文件创建
- [ ] 正确处理文件描述符生命周期
- [ ] 异常安全 (析构函数不抛异常)

---

### 4.4 临时文件清理 (v1.2)

**文件**: `ucm/store/lustre/cc/temp_file_cleanup.h` (新建)

**实现内容**:

```cpp
struct TempFileCleanupConfig {
    size_t maxAgeSeconds{3600};
    bool checkFileLock{true};
    bool checkProcessExists{true};
    bool enableCleanup{true};
};

class SpaceLayout {
public:
    Status CleanupTempFiles(const TempFileCleanupConfig& config);

private:
    void CleanupOwnTempFiles();  // atexit() 调用
    bool ShouldCleanupFile(...) const;
    bool IsProcessRunning(pid_t pid) const;
};
```

**验收标准**:
- [ ] 使用 atexit() 而非信号处理器
- [ ] 清理前检查进程存在性
- [ ] 检查文件锁状态

---

## 5. P1: 数据传输核心

### 5.1 TransQueue I/O 队列

**文件**: `ucm/store/lustre/cc/trans_queue.cc` (扩展现有)

**实现内容**:

#### 5.1.1 任务拆分

```cpp
std::vector<IoUnit> TransQueue::SplitTask(const TransTask& task) {
    // 将 TaskDesc 拆分为多个 IoUnit
    // 每个 IoUnit 包含:
    //   - BlockId
    //   - ShardIndex
    //   - Address
    //   - Offset
    //   - Size
}
```

#### 5.1.2 H2S/S2H 实现

```cpp
Status TransQueue::H2S(IoUnit& ios) {
    // 1. 创建临时文件
    // 2. 写入数据
    // 3. CommitFile (link())
}

Status TransQueue::S2H(IoUnit& ios) {
    // 1. 打开文件
    // 2. 读取数据到目标地址
}
```

**验收标准**:
- [ ] 任务正确拆分为 IoUnit
- [ ] H2S 使用临时文件 + link() 提交
- [ ] S2H 正确处理文件不存在

---

### 5.2 TransManager 任务管理

**文件**: `ucm/store/lustre/cc/trans_manager.cc` (扩展现有)

**实现内容**:

#### 5.2.1 TaskDesc 参数填充 (v1.1)

```cpp
TaskHandle TransManager::SubmitLoad(const TaskDesc& userDesc) {
    // 自动填充参数
    TaskDesc internalDesc = userDesc;
    internalDesc.shardIndex = config_.shardIndex;
    internalDesc.numShards = config_.nShardPerBlock;
    internalDesc.tensorSize = config_.tensorSize;
    internalDesc.shardSize = config_.shardSize;
    internalDesc.blockSize = config_.shardSize * config_.nShardPerBlock;

    // 创建并分发任务
    return SubmitTask(...);
}
```

**验收标准**:
- [ ] 自动填充 Config 参数
- [ ] 调用者只需提供 3 个参数
- [ ] 任务生命周期正确管理

---

### 5.3 Load/Dump 流程

**文件**: `ucm/store/lustre/cc/lustre_store.cc` (扩展现有)

**实现内容**:

```cpp
Expected<Detail::TaskHandle> LustreStore::Load(Detail::TaskDesc task) {
    // 1. 参数校验
    // 2. 转换为内部 TaskDesc
    // 3. 提交到 TransManager
}

Expected<Detail::TaskHandle> LustreStore::Dump(Detail::TaskDesc task) {
    // 同 Load
}

Status LustreStore::Wait(Detail::TaskHandle taskId) {
    // 1. 检查任务状态
    // 2. 阻塞等待完成
    // 3. 返回最终状态
}

Expected<bool> LustreStore::Check(Detail::TaskHandle taskId) {
    // 非阻塞检查任务状态
}
```

**验收标准**:
- [ ] 参数校验完整
- [ ] 异步接口正确实现
- [ ] Wait/Check 语义正确

---

## 6. P2: 性能与优化

### 6.1 异步 I/O 后端

**文件**: `ucm/store/lustre/cc/async_io.h` (新建)

**实现内容**:

```cpp
class AsyncIOAdapter {
public:
    static std::unique_ptr<AsyncIOAdapter> Create(size_t queueDepth = 256);

    virtual Status Setup(size_t queueDepth, int sqThreadCpu = -1) = 0;
    virtual Status SubmitRead(const IoRequest& req) = 0;
    virtual Status SubmitWrite(const IoRequest& req) = 0;
    virtual size_t ProcessCompletion(int timeoutMs = 0) = 0;
};

// 后端实现
class IoUringBackend : public AsyncIOAdapter { ... };
class LibaioBackend : public AsyncIOAdapter { ... };
class ThreadPoolBackend : public AsyncIOAdapter { ... };
```

**验收标准**:
- [ ] io_uring 后端 (Linux 5.1+)
- [ ] libaio 后端 (兼容旧内核)
- [ ] 线程池回退 (兜底方案)

---

### 6.2 分层线程池

**文件**: `ucm/store/lustre/cc/thread_pool_config.h` (新建)

**实现内容**:

```cpp
struct ThreadPoolConfig {
    size_t dataTransConcurrency{16};
    size_t lookupConcurrency{8};

    // CPU 亲和性
    int lookupCpuCores{-1};      // -1 = 自动
    int transCpuCores{-1};
};
```

**验收标准**:
- [ ] Lookup 线程池独立
- [ ] DataTrans 线程池独立
- [ ] CPU 亲和性可配置

---

### 6.3 目录分片优化

**实现内容**:

```cpp
// 在 SpaceLayout 中优化
std::string SpaceLayout::ShardPath(const Detail::BlockId& blockId) const {
    // 生成分片路径: data/{00/00/00/} (根据 dataDirShardBytes)
    // 减少单个目录文件数量
}
```

**验收标准**:
- [ ] 支持 0-3 级目录分片
- [ ] 路径生成性能满足要求

---

## 7. P3: 增强与验证

### 7.1 监控指标

**文件**: `ucm/store/lustre/cc/metrics.h` (新建)

**实现内容**:

```cpp
struct Metrics {
    // I/O 计数
    std::atomic<size_t> loadCount{0};
    std::atomic<size_t> dumpCount{0};

    // I/O 大小
    std::atomic<size_t> loadBytes{0};
    std::atomic<size_t> dumpBytes{0};

    // 延迟
    std::atomic<uint64_t> avgLatencyUs{0};

    // 错误
    std::atomic<size_t> errorCount{0};

    // 获取快照
    MetricsSnapshot Snapshot() const;
};
```

**验收标准**:
- [ ] 所有关键路径有指标
- [ ] 线程安全
- [ ] 性能影响 < 1%

---

### 7.2 单元测试

**目录**: `ucm/store/lustre/tests/`

**测试列表**:

| 测试文件 | 测试内容 | 优先级 |
|----------|----------|--------|
| param_validator_test.cc | 参数校验 | P0 |
| space_layout_test.cc | 路径生成、CommitFile | P0 |
| lustre_file_test.cc | 文件操作 | P0 |
| trans_queue_test.cc | I/O 队列 | P1 |
| trans_manager_test.cc | 任务管理 | P1 |
| lustre_store_test.cc | 集成测试 | P1 |
| concurrent_test.cc | 并发测试 | P2 |

---

### 7.3 集成测试

**文件**: `test/test_lustre_store_flow.py` (已存在，需扩展)

**测试场景**:

```python
# 1. 基本读写
def test_basic_load_dump():
    store = create_lustre_store()
    block_id = generate_block_id()
    data = create_test_data()

    # Dump
    task = store.dump([block_id], [0], [[data]])
    store.wait(task)

    # Load
    task = store.load([block_id], [0], [[buffer]])
    store.wait(task)

    assert buffer == data

# 2. 并发写入 (link() 测试)
def test_concurrent_dump_same_block():
    store1 = create_lustre_store()
    store2 = create_lustre_store()

    block_id = generate_block_id()
    data1 = create_test_data()
    data2 = create_test_data()  # 相同数据

    task1 = store1.dump([block_id], [0], [[data1]])
    task2 = store2.dump([block_id], [0], [[data2]])

    store1.wait(task1)
    store2.wait(task2)

    # 至少一个成功，另一个是 DuplicateKey

# 3. 前缀查找
def test_lookup_on_prefix():
    ...
```

---

### 7.4 并发测试

**文件**: `ucm/store/lustre/tests/concurrent_test.cc`

**测试场景**:

```cpp
// 多线程并发 Dump
TEST(ConcurrentTest, MultiThreadDump) {
    const int N = 100;
    std::vector<std::thread> threads;

    for (int i = 0; i < N; ++i) {
        threads.emplace_back([i]() {
            LustreStore store;
            store.Setup(config);
            // 执行 Dump
        });
    }

    for (auto& t : threads) t.join();
}

// 多进程并发 Dump (需要文件锁协调)
TEST(ConcurrentTest, MultiProcessDump) {
    // 使用 fork() 创建多个进程
    // 验证 link() + EEXIST 机制
}
```

---

## 8. 测试策略

### 8.1 测试金字塔

```
                    E2E 测试
                   /         \
                  /           \
                 / 5% 并发测试  \
                /_______________\
               /                 \
              /    集成测试        \
             /      15%           \
            /______________________\
           /                        \
          /     单元测试              \
         /        80%                \
        /______________________________\
```

### 8.2 测试覆盖率目标

| 组件 | 语句覆盖率 | 分支覆盖率 |
|------|-----------|-----------|
| 参数校验 | 100% | 100% |
| SpaceLayout | 95% | 90% |
| TransQueue | 90% | 85% |
| TransManager | 90% | 85% |
| LustreStore | 85% | 80% |

---

## 9. 质量门禁

### 9.1 代码质量

- [ ] 无编译警告
- [ ] 通过 clang-tidy 检查
- [ ] 通过 cppcheck 静态分析
- [ ] 代码覆盖率 ≥ 80%

### 9.2 性能目标

| 指标 | 目标 | 测试方法 |
|------|------|----------|
| Lookup 吞吐量 | > 100K ops/s | 基准测试 |
| Load 吞吐量 | > 1GB/s | 基准测试 |
| Dump 吞吐量 | > 1GB/s | 基准测试 |
| P99 延迟 | < 10ms | 延迟测试 |

### 9.3 功能验收

- [ ] 所有单元测试通过
- [ ] 所有集成测试通过
- [ ] 并发测试通过 (多线程)
- [ ] 多进程测试通过 (link() 验证)
- [ ] 临时文件清理验证

---

## 附录 A: 依赖关系图

```
                    ┌──────────────┐
                    │ LustreStore  │
                    └──────┬───────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
    ┌─────────────────┐        ┌─────────────────┐
    │  SpaceManager   │        │  TransManager   │
    └────────┬────────┘        └────────┬────────┘
             │                          │
             ▼                          ▼
    ┌─────────────────┐        ┌─────────────────┐
    │   SpaceLayout   │        │    TransQueue   │
    └─────────────────┘        └────────┬────────┘
                                         │
                                         ▼
                                ┌─────────────────┐
                                │    LustreFile   │
                                └────────┬────────┘
                                         │
                                         ▼
                                ┌─────────────────┐
                                │ AsyncIOAdapter  │
                                └─────────────────┘
```

---

## 附录 B: 文件清单

### 新建文件

| 文件 | 说明 | 阶段 |
|------|------|------|
| param_validator.h | 参数校验框架 | P0 |
| lustre_file.h/cc | 文件操作封装 | P0 |
| temp_file_cleanup.h | 临时文件清理 | P0 |
| async_io.h | 异步 I/O 抽象 | P2 |
| metrics.h | 监控指标 | P3 |

### 扩展文件

| 文件 | 扩展内容 | 阶段 |
|------|----------|------|
| space_layout.cc | 路径生成、CommitFile | P0 |
| space_manager.cc | Lookup 实现 | P0 |
| trans_queue.cc | I/O 处理 | P1 |
| trans_manager.cc | 任务管理 | P1 |
| lustre_store.cc | Load/Dump/Wait/Check | P1 |

### 测试文件

| 文件 | 说明 | 阶段 |
|------|------|------|
| param_validator_test.cc | 参数校验测试 | P0 |
| space_layout_test.cc | 路径生成测试 | P0 |
| lustre_file_test.cc | 文件操作测试 | P0 |
| trans_queue_test.cc | I/O 队列测试 | P1 |
| trans_manager_test.cc | 任务管理测试 | P1 |
| concurrent_test.cc | 并发测试 | P2 |

---

**文档结束**
