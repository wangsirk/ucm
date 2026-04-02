# Lustre Store 设计文档

## 目录

1. [概述](#1-概述)
   - 1.1 [实现状态](#11-实现状态)
   - 1.2 [设计原则](#12-设计原则)
2. [架构设计](#2-架构设计)
   - 2.1 [整体架构](#21-整体架构)
   - 2.2 [组件架构图](#22-组件架构图)
   - 2.3 [分层线程池架构](#23-分层线程池架构)
3. [文件布局与数据流](#3-文件布局与数据流)
4. [核心组件设计](#4-核心组件设计)
   - 4.1 [LustreStore (主入口)](#41-lustrestore-主入口)
   - 4.2 [LustreStoreImpl (内部实现)](#42-lustrestoreimpl-内部实现)
   - 4.3 [SpaceLayout (空间布局)](#43-spacelayout-空间布局)
   - 4.4 [SpaceManager (空间管理)](#44-spacemanager-空间管理)
   - 4.5 [LustreFile (文件操作)](#45-lustrefile-文件操作)
   - 4.6 [TransQueue (传输队列)](#46-transqueue-传输队列)
   - 4.7 [TransManager (传输管理)](#47-transmanager-传输管理)
   - 4.8 [TransTask (任务定义)](#48-transtask-任务定义)
   - 4.9 [数据模型设计](#49-数据模型设计)
      - 4.9.1 [Block 与 Shard 的关系](#491-block-与-shard-的关系)
      - 4.9.2 [Block 文件格式](#492-block-文件格式)
      - 4.9.3 [BlockId 映射](#493-blockid-映射)
5. [配置说明](#5-配置说明)
   - 5.1 [配置参数命名规范](#51-配置参数命名规范)
   - 5.2 [基础配置结构](#52-基础配置结构)
   - 5.3 [YAML 配置示例](#53-yaml-配置示例)
6. [性能优化设计](#6-性能优化设计)
   - 6.1 [异步 I/O 设计](#61-异步-io-设计)
   - 6.2 [CPU 亲和性（绑核）设计](#62-cpu-亲和性绑核设计)
7. [Lustre 特性](#7-lustre-特性)
   - 7.1 [条带化文件创建](#71-条带化文件创建)
   - 7.2 [与 PosixStore 对比](#72-与-posixstore-对比)
8. [错误处理与故障排查](#8-错误处理与故障排查)
   - 8.1 [错误码设计](#81-错误码设计)
   - 8.2 [错误处理策略](#82-错误处理策略)
   - 8.3 [错误恢复策略](#83-错误恢复策略)
   - 8.4 [并发控制设计](#84-并发控制设计)
   - 8.5 [常见问题排查](#85-常见问题排查)
   - 8.6 [资源管理](#86-资源管理)
   - 8.7 [监控与可观测性](#87-监控与可观测性)
9. [实施路线图](#9-实施路线图)
   - 9.1 [基础功能实现](#91-基础功能实现)
   - 9.2 [数据传输实现](#92-数据传输实现)
   - 9.3 [性能优化实现](#93-性能优化实现)
   - 9.4 [构建配置](#94-构建配置)
10. [测试策略](#10-测试策略)
11. [参考文档](#11-参考文档)
12. [附录 A: 接口兼容性](#附录-a-接口兼容性)
13. [附录 B: 扩展预留](#附录-b-扩展预留)

---

## 1. 概述

Lustre Store 是 UCM (Unified Cache Management) 的存储后端实现，利用 Lustre 并行文件系统存储 KV Cache 数据。它完全兼容 UCM StoreV1 接口，可通过 PipelineStore 与 Cache Store 等其他存储串联使用。

### 1.1 实现状态

| 模块 | 状态 | 说明 |
|------|------|------|
| **基础框架** | ✅ 已完成 | 头文件、类结构、配置解析 |
| **空间管理** | 🚧 框架完成 | `SpaceLayout`/`SpaceManager` 接口定义完成，实现待补充 |
| **数据传输** | 🚧 框架完成 | `TransManager`/`TransQueue` 接口定义完成，实现待补充 |
| **Lustre 文件操作** | ⏳ 未开始 | `LustreFile` 类设计完成，待实现 |
| **异步 I/O** | ⏳ 未开始 | `io_uring` 适配器设计完成，待实现 |

**当前阶段**：框架验证期，接口设计已通过评审，进入逐步实现阶段。

### 1.2 设计原则


| 原则         | 说明                   | LustreStore 实现                   |
| ------------ | ---------------------- | ---------------------------------- |
| **简单性**   | 避免不必要的复杂功能   | 复用 PosixStore 设计模式           |
| **解耦**     | 独立部署，无需上报状态 | 标准接口，无外部依赖               |
| **性能优先** | 利用 Lustre 特性优化   | 条带化文件创建，异步 I/O |
| **兼容性**   | 与 UCM 生态保持一致    | 数据格式、错误处理、并发控制       |

---

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           UCM 多存储后端架构                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  UCM 层: 可配置多个 Store 串联                                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ store_pipeline: "Cache|Lustre"  或  "Lustre"                         │   │
│  │                                                                      │   │
│  │  ┌─────────┐    ┌─────────────────────────────────────────────────┐  │   │
│  │  │ Cache   │───▶│  LustreStore                                    │  │   │
│  │  │ Store   │    │  - 处理 Host ↔ Lustre 文件系统 I/O            │  │   │
│  │  └─────────┘    │  - 支持条带化文件创建 (系统默认/可配置)       │  │   │
│  │                 └─────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 组件架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            LustreStore                                 │
│                         (implements StoreV1)                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  公开接口:                                                                │
│  ├─ Setup()              → 使用配置初始化存储                              │
│  ├─ Lookup()             → 检查块是否存在                                 │
│  ├─ LookupOnPrefix()    → 查找前缀序列中首个缺失块                        │
│  ├─ Prefetch()           → 预取提示                                       │
│  ├─ Load()               → 启动异步加载任务                                 │
│  ├─ Dump()               → 启动异步转储任务                                 │
│  ├─ Check()              → 轮询任务完成状态                                 │
│  └─ Wait()               → 阻塞等待任务完成                                 │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
            ┌───────────▼──────────┐   ┌─────────▼──────────┐
            │   LustreStoreImpl    │   │  Configuration     │
            │                      │   │  (Config 结构体)   │
            ├───────────┬──────────┤   └────────────────────┘
            │           │          │
      ┌─────▼─────┐ ┌─▼─────────┐ │
      │SpaceManager│ │TransManager│ │
      └─────┬─────┘ └─┬─────────┘ │
            │           │          │
      ┌─────▼─────┐ ┌─▼─────┐   │
      │SpaceLayout│ │TransQueue│
      └─────┬─────┘ └─┬─────┘   │
            │           │        │
            └─────┬─────┘        │
                  └──┬────────────┘
                     ▼
              ┌───────────────┐
              │  LustreFile    │
              └───────────────┘
```

### 2.3 分层线程池架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        LustreStore 线程池架构                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Lookup 线程池 (轻量级)                          │  │
│  │  - 用途: 文件存在性检查                                            │  │
│  │  - 并发度: lookup_concurrency (默认: 8)                            │  │
│  │  - 任务特点: 短暂、I/O 密集型 (MDT 元数据查询)                     │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                          ↓                               │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │              Data Transfer 线程池 (重量级)                          │  │
│  │  - 用途: Load/Dump 数据传输                                        │  │
│  │  - 并发度: data_trans_concurrency (默认: 16)                       │  │
│  │  - 任务特点: 长时间、I/O 密集型                                     │  │
│  │  - 绑核: 支持指定 CPU 亲和性                                       │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘
```

**说明**:
- Lookup 线程池使用较少线程，避免 MDT 元数据服务压力
- Lookup 操作为 I/O 密集型（`access()` 系统调用 + MDT 查询）
- Data Transfer 线程池可以配置更多线程，充分利用 I/O 带宽
- 支持 CPU 亲和性配置（见 6.2 节）


---

## 3. 文件布局与数据流

### 3.1 目录结构

```
{lustre_mount_point}/          # 单一 Lustre 挂载点
└── data/                       # 唯一数据目录 (初始化时创建)
    └── {shard_path}/           # 目录分片 (根据 dataDirShardBytes 配置)
        ├── {block_hash_hex}        # 正式文件 (条带化)
        └── {block_hash_hex}.tmp.*  # 临时文件 (非条带化, 进程隔离)
```

**目录分片说明**：

| `dataDirShardBytes` | 目录层级 | 子目录数量 | shard_path 示例 |
|-------------------|---------|-----------|----------------|
| 0 | 无分片 | 1 (单目录) | `data/` |
| 1 | 1 级 | 16 | `data/0/` ~ `data/f/` |
| 2 | 2 级 | 256 | `data/00/` ~ `data/ff/` |
| 3 | 3 级 | 4096 (推荐) | `data/000/` ~ `data/fff/` |

**shard_path 生成规则**：取 BlockId 前缀的前 N 个十六进制字符，其中 N = `dataDirShardBytes`

**文件名映射**: Block ID (16 字节) → 十六进制字符串 (32 个十六进制字符)

### 3.2 临时文件机制

UCM 采用**分片并发写入**模型，每个 Block 由多个 Shard 组成：

#### 3.2.1 单进程内并发写入

```
Block (hash: a1b2c3...)
├── Shard 0 → [并发写入 pwrite(data/{shard_path}/{hash}.tmp.<pid>, offset=0)]
├── Shard 1 → [并发写入 pwrite(data/{shard_path}/{hash}.tmp.<pid>, offset=S)]
├── Shard 2 → [并发写入 pwrite(data/{shard_path}/{hash}.tmp.<pid>, offset=2S)]
└── Shard N-1 → [并发写入 pwrite(data/{shard_path}/{hash}.tmp.<pid>, offset=(N-1)S)]
                                            │
                                            ▼
                                     CommitFile()
                        rename(data/{shard_path}/{hash}.tmp.<pid>
                           → data/{shard_path}/{hash})  [原子操作]
```

**进程级临时文件隔离**：
- 每个进程使用**唯一的临时文件后缀**（如 `.tmp.<pid>` 或 `.tmp.<uuid>`）
- 同一进程内的多个 Shard 使用 `pwrite()` 并发写入**同一个**临时文件
- `pwrite()` 是线程安全的，可以并发写入不同 offset
- 最后完成的 Shard 触发 `CommitFile()`

#### 3.2.2 多进程并发场景

```
进程 A: Block X → data/{shard_path}/{hash}.tmp.<pid_A> (写入中)
进程 B: Block X → data/{shard_path}/{hash}.tmp.<pid_B> (写入中)

最终结果:
├─ 进程 A 成功 → rename(data/{shard_path}/{hash}.tmp.<pid_A>
                      → data/{shard_path}/{hash}) ✅
└─ 进程 B 稍后 → rename(data/{shard_path}/{hash}.tmp.<pid_B>
                      → data/{shard_path}/{hash})
                   → 文件已存在 (Status::DuplicateKey)
                   → 删除 .tmp.<pid_B>，返回成功
```

**并发安全性保证**：

| 场景 | 处理机制 |
|------|----------|
| 单进程多 Shard 写入 | ✅ `pwrite()` 线程安全，写入不同 offset |
| 多进程写同一 Block | ✅ 进程级 `.tmp` 文件隔离 |
| 多进程写不同 Block | ✅ 不同文件，无冲突 |
| `rename()` 原子性 | ✅ 保证不会出现部分写入数据 |
| 文件已存在处理 | ✅ 后续进程删除自己的 `.tmp`，不覆盖 |

#### 3.2.3 临时文件的优势

| 优势            | 说明                                                         |
| --------------- | ------------------------------------------------------------ |
| **原子性**      | 数据对其他进程不可见，直到提交完成                           |
| **进程隔离**    | 每个进程独立的临时文件，避免写入冲突                        |
| **无需加锁**    | 利用文件系统原子性，无需应用层锁机制                         |
| **失败回滚**    | 写入失败直接删除`.tmp.<pid>` 文件                           |
| **Lustre 优化** | 临时文件不条带化 (节省 OST 资源)，正式文件使用系统默认条带化 |

#### 3.2.4 初始化清理

系统启动时清理残留的临时文件：

```cpp
// 扫描并删除所有 data/ 下的 .tmp.* 文件（递归所有分片子目录）
for (auto& shard_dir : ListDirs("data/")) {
    for (auto& file : ListFiles(shard_dir, "*.tmp.*")) {
        // 只删除本进程的临时文件，避免误删其他进程正在使用的文件
        if (IsOwnTempFile(file, getpid())) {
            Remove(file);
            UC_INFO("Cleaned stale temp file: {}", file);
        }
    }
}
```

**安全注意事项**：
- 仅删除当前进程 ID 的临时文件，避免误删其他进程的活跃文件
- 可选：检查文件修改时间，只删除超过阈值的旧文件
- 记录清理日志，便于故障排查

### 3.3 Load 流程 (Lustre → Device)

```
LustreStore::Load(block_ids, shard_addrs)
    │
    ▼
TransManager::Submit(TaskDesc)
    │
    ▼
TransQueue::Push(TaskPtr)
    │
    ▼
ThreadPool (并发 Workers)
    │
    ├─► IoUnit 0 ──► LustreFile::Open("data/{shard_path}/{hash}") (读模式)
    │                └─► LustreFile::Read(offset, size)
    │                     └─► 拷贝到 device_addr[0]
    │
    ├─► IoUnit 1 ──► LustreFile::Open("data/{shard_path}/{hash}") (读模式)
    │                └─► LustreFile::Read(offset, size)
    │                     └─► 拷贝到 device_addr[1]
    │
    └─► IoUnit N ──► ... (并行执行)

所有 Worker 完成 → 任务标记为完成
```

**说明**：`{shard_path}` 为 BlockId 前缀的前 N 个字符（N = dataDirShardBytes）

### 3.4 Dump 流程 (Device → Lustre)

```
LustreStore::Dump(block_ids, shard_addrs)
    │
    ▼
TransManager::Submit(TaskDesc)
    │
    ▼
TransQueue::Push(TaskPtr)
    │
    ▼
ThreadPool (并发 Workers)
    │
    ├─► IoUnit 0 ──► LustreFile::CreateNormal() → "data/{shard_path}/{hash}.tmp.<pid>"
    │                └─► LustreFile::Write(offset, size)
    │                     └─► 从 device_addr[0] 拷贝
    │
    ├─► IoUnit 1 ──► LustreFile::Open("data/{shard_path}/{hash}.tmp.<pid>", 追加模式)
    │                └─► LustreFile::Write(offset, size)
    │                     └─► 从 device_addr[1] 拷贝
    │
    ├─► IoUnit N-1 ──► ... (并行写入 .tmp.<pid>)
    │
    └─► IoUnit N ──► LustreFile::Write() (最后一个 shard)
                     └─► CommitFile()
                          └─► LustreFile::CreateStriped() (系统默认条带)
                          └─► LustreFile::Open() (正式文件: "data/{shard_path}/{hash}")
                          └─► 从 .tmp.<pid> 拷贝数据
                          └─► LustreFile::Remove(.tmp.<pid>)

所有 Worker 完成 → 任务标记为完成
```

**说明**：
- `{shard_path}` 为 BlockId 前缀的前 N 个字符（N = dataDirShardBytes）
- 临时文件名格式：`{hash}.tmp.<pid>`，其中 pid 为进程 ID，保证进程级隔离

---

## 4. 核心组件设计

### 4.1 LustreStore (主入口)

**文件**: `lustre_store.cc`, `lustre_store.h`

实现 `StoreV1` 接口的主入口，委托给 `LustreStoreImpl` 进行实际处理。

### 4.2 LustreStoreImpl (内部实现)

**文件**: `lustre_store.cc`

包含核心实现，持有以下组件：

- `SpaceManager` - 并发块查找
- `TransManager` - 数据传输任务管理
- `transEnable` - 是否启用数据传输的标志

### 4.3 SpaceLayout (空间布局)

**文件**: `space_layout.h`, `space_layout.cc`

**核心职责**：
- 管理文件存储路径生成（支持目录分片）
- 生成正式文件和临时文件路径
- 原子性提交临时文件为正式文件

```cpp
class SpaceLayout {
public:
    // 初始化存储后端
    Status Setup(const Config& config);

    // 生成文件路径
    // activated=true:  返回 "data/{shard_path}/{hash}.tmp.<pid>"
    // activated=false: 返回 "data/{shard_path}/{hash}"
    // 其中 shard_path 取 hash 的前 dataDirShardBytes 个字符
    std::string DataFilePath(const BlockId& blockId, bool activated) const;

    // 生成目录分片路径
    // 返回 "data/{shard_path}/"，其中 shard_path 根据配置决定
    std::string ShardPath(const BlockId& blockId) const;

    // 提交临时文件为正式文件 (原子重命名)
    // success=true:  rename({hash}.tmp.<pid> → {hash})
    // success=false: remove({hash}.tmp.<pid>)
    Status CommitFile(const BlockId& blockId, bool success) const;

private:
    std::string mountPoint_;          // Lustre 挂载点
    size_t dataDirShardBytes_;        // 目录分片层级 (0-3)
    pid_t pid_;                       // 进程 ID，用于临时文件隔离
};
```

**路径生成示例**：
```cpp
// 假设: mountPoint="/mnt/lustre", dataDirShardBytes=3, pid=12345
// BlockId hash: "0123456789abcdef0123456789abcdef"

DataFilePath(blockId, false);  // → "/mnt/lustre/data/012/0123456789abcdef0123456789abcdef"
DataFilePath(blockId, true);   // → "/mnt/lustre/data/012/0123456789abcdef0123456789abcdef.tmp.12345"
ShardPath(blockId);            // → "/mnt/lustre/data/012/"
```

### 4.4 SpaceManager (空间管理)

**文件**: `space_manager.h`, `space_manager.cc`

**核心特性**:

- 支持并发文件存在性检查
- 可配置的查找并发度
- 支持超时的查找操作

```cpp
class SpaceManager {
    // 初始化空间管理器
    Status Setup(const Config& config);

    // 批量块查找 (返回存在性位图)
    std::vector<uint8_t> Lookup(const BlockId* blocks, size_t num);

    // 查找前缀序列中首个缺失块
    Expected<ssize_t> LookupOnPrefix(const BlockId* blocks, size_t num);
};
```

### 4.5 LustreFile (文件操作)

**文件**: `lustre_file.h`, `lustre_file.cc`

```cpp
class LustreFile {
    // 创建条带化文件 (Lustre API, 用于正式文件)
    // 使用系统默认条带配置
    Status CreateStriped(mode_t mode);

    // 创建普通文件 (POSIX, 用于临时文件)
    Status CreateNormal(uint32_t flags, mode_t mode);

    // 标准 POSIX I/O
    Status Open(uint32_t flags);
    Status Read(void* buffer, size_t size, off64_t offset);
    Status Write(const void* buffer, size_t size, off64_t offset);

    // 文件管理
    Status MkDir();
    Status Access(int32_t mode);
    Status Rename(const std::string& newName);
    void Remove();
};
```

**Lustre API 使用**:

```cpp
#ifdef HAS_LUSTRE_API
    // 使用 llapi_file_create 创建条带化文件
    // stripe_count = -1, stripe_size = 0 表示使用系统默认
    int rc = llapi_file_create(path, 0, -1, -1, LOV_PATTERN_RAID0, NULL);
#else
    // 回退到普通文件创建
#endif
```

### 4.6 TransQueue (传输队列)

**文件**: `trans_queue.h`, `trans_queue.cc`

**核心特性**:

- 支持并发 I/O 操作
- 将任务拆分为 IoUnit 并行处理
- 处理 H2S (Host to Storage/Dump) 和 S2H (Storage to Host/Load)

```cpp
class TransQueue {
    // 初始化传输队列
    Status Setup(const Config& config, TaskIdSet* failureSet,
                 const SpaceLayout* layout);

    // 推送任务到队列
    void Push(TaskPtr task, WaiterPtr waiter);

private:
    // 写入存储 (Dump 操作)
    Status H2S(IoUnit& ios);

    // 读取存储 (Load 操作)
    Status S2H(IoUnit& ios);
};
```

### 4.7 TransManager (传输管理)

**文件**: `trans_manager.h`, `trans_manager.cc`

**核心特性**:

- 继承自 `TaskWrapper` 模板类
- 管理任务生命周期和完成跟踪
- 处理任务分发到 TransQueue

```cpp
class TransManager : public TaskWrapper<TransTask, TaskHandle> {
    // 使用配置和布局初始化
    Status Setup(const Config& config, const SpaceLayout* layout);

protected:
    // 分发任务到队列
    void Dispatch(TaskPtr t, WaiterPtr w) override;
};
```

### 4.8 TransTask (任务定义)

**文件**: `trans_task.h`

```cpp
class TransTask {
public:
    enum class Type : uint8_t { LOAD, DUMP };

    TaskHandle id{0};
    Type type{Type::DUMP};
    TaskDesc desc;

    TransTask(Type type, TaskDesc desc);
};
```

### 4.9 数据模型设计

LustreStore 遵循 UCM 项目统一的数据模型，与 PosixStore 保持完全一致：

#### 4.9.1 Block 与 Shard 的关系

**术语说明**：

| 术语 | 定义 | 关系 |
|------|------|------|
| **Block** | 一个完整的 KV Cache 块 | 包含多个 Shard |
| **Shard** | Block 的分片，对应一个 Transformer Layer | nShardPerBlock 个 Shard 组成一个 Block |
| **Tensor** | 每层的数据张量 | 一个 Shard 包含多个 Tensor |

**关系公式**：
```
blockSize = shardSize × nShardPerBlock
shardSize = tensorSize × nTensorPerShard
```

#### 4.9.2 Block 文件格式

```
┌─────────────────────────────────────────────────────────┐
│ Block 文件布局 (无 Header，纯数据，与 UCM 一致)        │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Offset 0        ┌─────────────────────────────────┐   │
│                  │  Shard 0 数据                   │   │
│                  │  (大小: shardSize)              │   │
│  Offset S        ├─────────────────────────────────┤   │
│                  │  Shard 1 数据                   │   │
│  Offset 2S       ├─────────────────────────────────┤   │
│                  │  ...                            │   │
│  Offset (n-1)×S  ├─────────────────────────────────┤   │
│                  │  Shard n-1 数据                 │   │
│  Offset n×S      └─────────────────────────────────┘   │
│                                                         │
│  S = shardSize, n = nShardPerBlock                      │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**设计决策** (与 UCM 一致):

- ❌ 无文件 Header (无版本、校验和)
- ✅ 纯数据布局，与内存布局一一对应
- ✅ 支持直接 mmap (如需要)
- ✅ 跨 Store 兼容 (PosixStore/NfsStore/LustreStore 数据格式一致)

**兼容性保证**:

- 数据可在不同 Store 间迁移
- BlockId (SHA-256 哈希) 隐式版本控制
- 与 UCM 现有生态完全兼容

#### 4.9.3 BlockId 映射

```
BlockId (16 字节，取 SHA-256 哈希值的前 16 字节)
        │
        ▼
  十六进制编码 (32 个十六进制字符)
        │
        ▼
  shard_path (取前 N 个字符，N = dataDirShardBytes)
        │
        ▼
  完整路径: {mount}/data/{shard_path}/{hash}
```

**说明**：BlockId 为 16 字节，取自完整 SHA-256 哈希值的前 16 字节（前缀），既保证唯一性又节省存储空间。

**示例** (dataDirShardBytes = 3):

```
BlockId (raw): 0x01 0x23 0x45 ... 0xef (16 bytes)
           ↓
Hash String: 0123456789abcdef0123456789abcdef
           ↓
shard_path (前3字符): 012
           ↓
正式文件: /mnt/lustre/data/012/0123456789abcdef0123456789abcdef
临时文件: /mnt/lustre/data/012/0123456789abcdef0123456789abcdef.tmp.<pid>
```

**不同 dataDirShardBytes 配置示例**:

| 配置值 | Hash | shard_path | 完整路径 |
|-------|------|-----------|---------|
| 0 | `0123456...` | (空) | `/mnt/lustre/data/0123456789abcdef...` |
| 1 | `0123456...` | `0` | `/mnt/lustre/data/0/0123456789abcdef...` |
| 2 | `0123456...` | `01` | `/mnt/lustre/data/01/0123456789abcdef...` |
| 3 | `0123456...` | `012` | `/mnt/lustre/data/012/0123456789abcdef...` |

---

## 5. 配置说明

### 5.1 配置参数命名规范

LustreStore 使用**三层命名映射**机制，确保不同语言层的命名风格一致：

| 层级 | 命名风格 | 示例 | 说明 |
|------|----------|------|------|
| **C++ 内部** | camelCase | `dataTransConcurrency` | Config 结构体内部使用 |
| **Python/YAML** | snake_case + `lustre_` 前缀 | `lustre_data_trans_concurrency` | 外部配置使用 |
| **映射规则** | 去除前缀 + 驼峰转换 | `lustre_data_trans_concurrency` → `dataTransConcurrency` | 自动转换 |

**命名映射规则**：
```python
# YAML/Python 配置名称
lustre_data_trans_concurrency
    ↓ 去除 lustre_ 前缀
data_trans_concurrency
    ↓ 下划线转驼峰
dataTransConcurrency
```

**注意事项**：
- 无 `lustre_` 前缀的参数直接映射（如 `device_id` → `deviceId`）
- 部分参数直接使用原名称（如 `block_size` → `blockSize`）

### 5.2 基础配置结构

```cpp
struct Config {
    // ===== 必需参数 =====
    std::vector<std::string> storageBackends{};  // Lustre 挂载路径
    int32_t deviceId{-1};                        // -1=仅CPU, >=0=GPU/NPU ID

    // ===== 可选参数 =====
    size_t tensorSize{0};         // 单个 tensor 大小
    size_t shardSize{0};          // 分片大小
    size_t blockSize{0};          // 块大小

    // ===== Lustre 特性 =====
    // 初始版本使用系统默认条带配置，后续版本可支持自定义
    // stripe_count = -1 (由 Lustre FS 自动管理，推荐)
    // stripe_count = 0 (使用系统默认值)
    // stripe_size = 0 (使用系统默认值)

    // ===== I/O 优化 =====
    bool ioDirect{false};         // Direct I/O (默认: 关闭)
    size_t dataTransConcurrency{16};   // 数据传输并发数
    size_t lookupConcurrency{8};      // 查找并发数
    size_t timeoutMs{30000};          // 操作超时 (毫秒)

    // ===== 目录布局 =====
    size_t dataDirShardBytes{3};   // 目录分片层级：
                                  // 0 = 单目录 "data/" (无分片)
                                  // 1 = 16 个子目录 "data/0/" ~ "data/f/"
                                  // 2 = 256 个子目录 "data/00/" ~ "data/ff/"
                                  // 3 = 4096 个子目录 "data/000/" ~ "data/fff/" [推荐]
};
```

### 5.3 YAML 配置示例

```yaml
ucm_connectors:
  - ucm_connector_name: "UcmPipelineStore"
    ucm_connector_config:
      store_pipeline: "Lustre"

      # 必需参数
      storage_backends: ["/mnt/lustre"]
      device_id: -1
      block_size: 4096

      # 可选参数
      tensor_size: 1024
      shard_size: 4096
      data_dir_shard_bytes: 3   # 目录分片层级: 0=无分片, 1=16子目录, 2=256子目录, 3=4096子目录(推荐)

      # I/O 优化
      io_direct: false      # 设置为 true 启用 Direct I/O
      lustre_data_trans_concurrency: 16
      lustre_lookup_concurrency: 8
      timeout_ms: 30000
```

---

## 6. 性能优化设计

### 6.1 异步 I/O 设计

#### 6.1.1 异步 I/O 后端选择

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          异步 I/O 分层设计                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                        AsyncIOAdapter                             │  │
│  │  - 抽象异步 I/O 接口                                               │  │
│  │  - 自动选择最佳实现                                                 │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              │                                           │
│           ┌──────────────────┼──────────────────┐                       │
│           ▼                  ▼                  ▼                       │
│  ┌────────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │   IoUringIO    │  │  LibAIOIO    │  │ ThreadPoolIO │               │
│  │  (Linux 5.1+)  │  │  (Legacy)    │  │  (Fallback)  │               │
│  │  - 零拷贝      │  │  - 内核AIO   │  │  - 模拟异步   │               │
│  │  - 批量提交    │  │  - 高性能    │  │  - 最大兼容   │               │
│  └────────────────┘  └──────────────┘  └──────────────┘               │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘
```


| 方案           | 优势                 | 劣势            | 推荐场景     |
| -------------- | -------------------- | --------------- | ------------ |
| **io_uring**   | 最先进，高效，零拷贝 | 需要 Linux 5.1+ | 现代系统首选 |
| **Linux AIO**  | 内核级支持，高性能   | 仅支持 O_DIRECT | 高性能场景   |
| **线程池模拟** | 兼容性最好，简单     | 线程开销        | 备选方案     |

**优先级**: io_uring > libaio > 线程池模拟

#### 6.1.2 io_uring 实现设计

```cpp
class IoUringAdapter {
public:
    struct IoRequest {
        void* buffer;           // 缓冲区地址
        size_t size;            // I/O 大小
        off64_t offset;         // 文件偏移
        int fd;                 // 文件描述符
        enum Op { READ, WRITE } op;
        std::function<void(const Status&, size_t)> callback;
    };

    Status Setup(size_t queueDepth, int sqThreadCpu = -1);
    Status SubmitRead(const IoRequest& req);
    Status SubmitWrite(const IoRequest& req);
    size_t ProcessCompletion(int timeoutMs = 0);
};
```

### 6.2 CPU 亲和性（绑核）设计

#### 6.2.1 绑核架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        CPU 亲和性设计                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  NUMA Node 0                    NUMA Node 1                              │
│  ┌───────────────────────┐    ┌───────────────────────┐                  │
│  │ CPU 0-7               │    │ CPU 8-15              │                  │
│  │                       │    │                       │                  │
│  │ ┌───────────────────┐ │    │ ┌───────────────────┐ │                  │
│  │ │ Lookup 线程       │ │    │ │ Lookup 线程       │ │                  │
│  │ └───────────────────┘ │    │ └───────────────────┘ │                  │
│  │                       │    │                       │                  │
│  │ ┌───────────────────┐ │    │ ┌───────────────────┐ │                  │
│  │ │ I/O 线程池        │ │    │ │ I/O 线程池        │ │                  │
│  │ └───────────────────┘ │    │ └───────────────────┘ │                  │
│  └───────────────────────┘    └───────────────────────┘                  │
│           │                             │                                 │
│           └───────────┬─────────────────┘                                 │
│                       ▼                                                   │
│              Lustre 文件系统 (由文件系统层做负载均衡)                        │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 6.2.2 CPU 亲和性管理器

```cpp
class CpuAffinityManager {
public:
    enum class Policy {
        COMPACT,    // 紧凑分配: 线程集中到少数 CPU
        SPREAD,     // 分散分配: 线程均匀分布
        NUMA,       // NUMA 感知: 按 NUMA 节点分配
        CUSTOM,     // 自定义: 使用指定 CPU 列表
    };

    static Status SetAffinity(pid_t tid, const std::vector<int>& cpuList);
    static std::vector<int> GetAffinity(pid_t tid);
    static std::vector<int> AllocateCpus(Policy policy, size_t numThreads, int numaNode = -1);
};
```

**设计说明**:

- **COMPACT**: 适用于低延迟场景，减少跨 NUMA 访问
- **SPREAD**: 适用于高吞吐场景，分散 CPU 负载
- **NUMA**: 适用于 NUMA 架构服务器，优化内存访问延迟
- **CUSTOM**: 允许用户根据实际环境定制 CPU 分配

#### 6.2.3 Lustre 环境下的收益评估

**注意**：Lustre 是分布式并行文件系统，性能瓶颈主要在于：

| 瓶颈层级 | 说明 | CPU 绑核收益 |
|----------|------|--------------|
| **网络层** | 客户端 ↔ OSS/OST 网络延迟 | ❌ 收益极低 |
| **OSS/OST** | 对象存储服务器磁盘 I/O | ❌ 无收益 |
| **MDT/MDS** | 元数据服务器处理 | ⚠️ 收益有限 |
| **客户端** | 本地 CPU/内存 | ✅ 有一定收益 |

**结论**：
- 对于 **Lustre 网络存储**，CPU 亲和性的收益远低于**本地 NVMe SSD** 场景
- 本设计将 CPU 亲和性作为**可选项**，非必需特性
- 建议通过性能测试验证实际收益后再启用


## 7. Lustre 特性

### 7.1 条带化文件创建

对于正式文件，LustreStore 使用 `llapi_file_create()` 创建带条带化的文件：

```cpp
// 使用系统默认条带配置
// stripe_size = 0, stripe_count = -1, stripe_offset = -1
int llapi_file_create(const char *name,
                       unsigned long long stripe_size,  // 0 = 默认
                       int stripe_offset,               // -1 = 默认
                       int stripe_count,                // -1 = 由 FS 管理 (推荐)
                       int stripe_pattern);             // LOV_PATTERN_RAID0
```

**设计决策**:


| 阶段           | 条带化策略     | 理由                                   |
| -------------- | -------------- | -------------------------------------- |
| **V1 (当前)**  | 使用系统默认   | 由 Lustre 管理员统一调优，应用层零配置 |
| **V2+ (未来)** | 支持自定义配置 | 针对不同业务场景优化                   |

**V1 设计理由**:

- 应用层无需干预，保持简单性
- 由 Lustre 管理员根据环境调优
- 避免应用层需要特殊权限
- 临时文件不条带化，节省 OST 资源

**优势**:

- 跨多个 OST 的并行 I/O
- 更好的带宽利用率
- 为大顺序读/写优化
- 与文件系统层优化协同工作

---

## 7.2 与 PosixStore 对比

LustreStore 在设计上与 PosixStore 保持高度一致，同时利用 Lustre 特性进行优化：

| 特性 | PosixStore | LustreStore | 说明 |
|------|------------|-------------|------|
| **数据格式** | 纯数据，无 Header | 纯数据，无 Header | ✅ 完全兼容 |
| **临时文件机制** | `.tmp` 后缀 | `.tmp.<pid>` 后缀 | ✅ 改进：进程隔离 |
| **并发写入模型** | `pwrite()` 线程安全 | `pwrite()` 线程安全 | ✅ 相同 |
| **文件操作 API** | POSIX (`open`/`read`/`write`) | POSIX + Lustre API | ✅ 兼容扩展 |
| **条带化支持** | ❌ 无 | ✅ `llapi_file_create()` | 🆕 新增 |
| **并发控制** | `rename()` 原子性 | `rename()` 原子性 | ✅ 相同 |
| **错误处理** | UCM Status | UCM Status + Lustre 扩展 | ✅ 兼容扩展 |

### 7.2.1 代码复用策略

LustreStore 大量复用 PosixStore 的成熟设计：

| 组件 | 复用方式 | 说明 |
|------|----------|------|
| `SpaceLayout` | 参考实现 | 目录结构、路径生成逻辑相同 |
| `SpaceManager` | 参考实现 | 并发查找机制相同 |
| `TransQueue` | 参考实现 | I/O 调度、任务分发相同 |
| `TransManager` | 参考实现 | 任务生命周期管理相同 |
| `LustreFile` | 新增实现 | 封装 Lustre 特定 API |

### 7.2.2 设计差异

**临时文件命名**：
```cpp
// PosixStore (与 LustreStore 改进前)
DataFilePath(blockId, true)  // → "data/{hash}.tmp"

// LustreStore (改进后，支持目录分片)
DataFilePath(blockId, true)  // → "data/{shard_path}/{hash}.tmp.<pid>"
// 例如: data/012/0123456789abcdef0123456789abcdef.tmp.12345
```

**文件创建**：
```cpp
// PosixStore
open(path, O_CREAT | O_WRONLY, mode);

// LustreStore
#ifdef HAS_LUSTRE_API
    llapi_file_create(path, 0, -1, -1, LOV_PATTERN_RAID0);
#else
    open(path, O_CREAT | O_WRONLY, mode);  // 回退
#endif
```

---

## 8. 错误处理与故障排查

### 8.1 错误码设计

LustreStore 扩展 UCM 基础错误码，增加 Lustre 特定错误：

```cpp
namespace UC::LustreStore {

// 扩展 Status 错误码 (基于 UCM Status 基础)
// 基础码范围: -50000 ~ -50010 (UCM 定义)
// Lustre 扩展码范围: -50100 ~ -50199
class LustreStatus {
public:
    // === 配置错误 (-50100 ~ -50109) ===
    static constexpr int32_t ELUSTRE_CONFIG = -50100;       // 通用配置错误
    static constexpr int32_t ELUSTRE_NO_BACKEND = -50101;   // 无可用存储后端
    static constexpr int32_t ELUSTRE_INVALID_MOUNT = -50102;// 挂载点无效
    static constexpr int32_t ELUSTRE_INVALID_STRIPE = -50103;// 条带化参数无效

    // === Lustre API 错误 (-50110 ~ -50119) ===
    static constexpr int32_t ELUSTRE_API_FAILED = -50110;   // Lustre API 调用失败
    static constexpr int32_t ELUSTRE_NO_API = -50111;       // Lustre API 不可用
    static constexpr int32_t ELUSTRE_STRIPE_FAILED = -50112;// 条带化创建失败

    // === 空间错误 (-50120 ~ -50129) ===
    static constexpr int32_t ELUSTRE_NO_SPACE = -50120;     // OST 空间不足
    static constexpr int32_t ELUSTRE_QUOTA_EXCEEDED = -50121;// 配额超限
    static constexpr int32_t ELUSTRE_OST_FULL = -50122;     // 特定 OST 已满

    // === I/O 错误 (-50130 ~ -50139) ===
    static constexpr int32_t ELUSTRE_IO_ERROR = -50130;     // 通用 I/O 错误
    static constexpr int32_t ELUSTRE_READ_FAILED = -50131;  // 读操作失败
    static constexpr int32_t ELUSTRE_WRITE_FAILED = -50132; // 写操作失败
    static constexpr int32_t ELUSTRE_IO_TIMEOUT = -50133;   // I/O 超时

    // === 元数据错误 (-50140 ~ -50149) ===
    static constexpr int32_t ELUSTRE_MDT_ERROR = -50140;    // MDT 操作失败
    static constexpr int32_t ELUSTRE_LOOKUP_FAILED = -50141;// 查找操作失败
    static constexpr int32_t ELUSTRE_MDC_TIMEOUT = -50142;  // MDC 连接超时

    // === 连接错误 (-50150 ~ -50159) ===
    static constexpr int32_t ELUSTRE_NOT_CONNECTED = -50150;// 未连接到 Lustre
    static constexpr int32_t ELUSTRE_CONNECTION_LOST = -50151;// 连接丢失
    static constexpr int32_t ELUSTRE_RECOVERING = -50152;   // 正在恢复连接

    // 工厂函数
    static Status ConfigError(const std::string& msg) {
        return Status(ELUSTRE_CONFIG, msg);
    }
    static Status ApiFailed(const std::string& msg) {
        return Status(ELUSTRE_API_FAILED, msg);
    }
    static Status IoError(const std::string& msg) {
        return Status(ELUSTRE_IO_ERROR, msg);
    }
    // ... 其他工厂函数
};

}  // namespace UC::LustreStore
```

### 8.2 错误处理策略


| 场景                  | 错误码                  | 处理策略                       | 是否重试 |
| --------------------- | ----------------------- | ------------------------------ | -------- |
| **文件已存在 (Dump)** | `Status::DuplicateKey`  | 覆盖 (先删除后创建)            | 否       |
| **条带化 API 失败**   | `ELUSTRE_STRIPE_FAILED` | 降级到普通文件创建             | 否       |
| **残留 .tmp.* 文件**  | N/A                     | 初始化时清理通配符匹配         | N/A      |
| **I/O 超时**          | `ELUSTRE_IO_TIMEOUT`    | 标记任务失败，继续处理其他任务 | 是(1次)  |
| **磁盘空间不足**      | `ELUSTRE_NO_SPACE`      | 报错并标记任务失败             | 否       |
| **权限拒绝**          | `Status::OsApiError`    | 立即返回错误                   | 否       |
| **Lustre API 不可用** | `ELUSTRE_NO_API`        | 回退到普通 POSIX 文件操作      | 否       |

### 8.3 错误恢复策略


| 错误类型        | 重试策略 | 降级处理       | 日志级别 | 用户通知 |
| --------------- | -------- | -------------- | -------- | -------- |
| 网络瞬断        | 3次      | 否             | WARN     | 否       |
| OST 空间不足    | 否       | 尝试其他 OST   | ERROR    | 是       |
| 条带化 API 失败 | 否       | 普通文件创建   | INFO     | 否       |
| I/O 超时        | 1次      | 否             | WARN     | 否       |
| 权限拒绝        | 否       | 否             | ERROR    | 是       |
| MDT 响应缓慢    | 否       | 降低并发度重试 | WARN     | 否       |

### 8.4 并发控制设计

LustreStore 遵循 UCM 项目的并发控制策略，与 PosixStore 保持一致：

#### 8.4.1 并发场景分析


| 场景                   | 冲突可能性 | 处理策略 (与 UCM 一致)           |
| ---------------------- | ---------- | -------------------------------- |
| 并发 Load 同一 Block   | ✅ 安全    | 只读操作，无冲突                 |
| 并发 Dump 同一 Block   | ⚠️ 冲突  | 临时文件机制隔离 + rename 原子性 |
| Load + Dump 同一 Block | ⚠️ 冲突  | 临时文件隔离，读旧文件           |
| 并发 Dump 不同 Block   | ✅ 安全    | 独立文件，无冲突                 |

#### 8.4.2 临时文件并发隔离机制

使用进程级 `.tmp.<pid>` 后缀 + 原子 `rename()` 实现并发安全：

```
并发 Dump 同一 Block 的处理流程 (dataDirShardBytes=3):

进程 A: Block X → data/012/{hash}.tmp.<pid_A> (写入中)
进程 B: Block X → data/012/{hash}.tmp.<pid_B> (写入中)

最终结果:
├─ 进程 A 成功 → rename(data/012/{hash}.tmp.<pid_A> → data/012/{hash}) ✅
└─ 进程 B 稍后 → rename(data/012/{hash}.tmp.<pid_B> → data/012/{hash})
                 → 文件已存在 (Status::DuplicateKey)
                 → 删除 .tmp.<pid_B>，返回成功
```

**设计优势**:

- ✅ 进程级隔离，完全避免多进程写入冲突
- ✅ 无需应用层锁机制
- ✅ 利用文件系统原子性保证
- ✅ 容错：失败进程的临时文件可被清理
- ✅ 与 PosixStore 设计理念一致，但更安全

### 8.5 常见问题排查


| 问题                 | 错误码                    | 解决方案                                        |
| -------------------- | ------------------------- | ----------------------------------------------- |
| "创建条带化文件失败" | `ELUSTRE_STRIPE_FAILED`   | 检查 Lustre API 可用性，已自动回退到普通文件    |
| "data/ 目录权限拒绝" | `Status::OsApiError`      | 确保 Lustre 挂载权限正确                        |
| "子目录创建失败"     | `Status::OsApiError`      | 检查 data/ 下子目录 (如 data/012/) 的创建权限   |
| "I/O 性能缓慢"       | N/A                       | 检查系统默认条带设置，确保 I/O 大小合理         |
| "查找超时"           | `ELUSTRE_IO_TIMEOUT`      | 增加`lookup_concurrency` 或检查 Lustre MDT 性能 |
| "OST 空间不足"       | `ELUSTRE_OST_FULL`        | 联系 Lustre 管理员扩容或清理数据                |
| "Lustre 连接丢失"    | `ELUSTRE_CONNECTION_LOST` | 等待自动重连或检查网络状态                      |
| "MDT 响应缓慢"       | `ELUSTRE_MDT_ERROR`       | 检查 MDT 负载，考虑降低 `dataDirShardBytes`     |

### 8.6 资源管理

#### 8.6.1 文件句柄管理

LustreStore 使用 RAII 模式确保资源正确释放：

```cpp
// PosixFile/LustreFile 使用 RAII
{
    LustreFile file(path);
    file.Open(...);
    // 使用文件
}  // 析构时自动关闭文件句柄
```

**资源防护措施**：

| 措施 | 说明 |
|------|------|
| **RAII 模式** | 析构函数自动调用 `close()` |
| **异常安全** | 使用 C++ 异常保证，即使抛异常也会释放资源 |
| **句柄上限监控** | 定期检查进程文件句柄数，接近上限时告警 |
| **超时机制** | 所有 I/O 操作支持超时配置，避免资源长时间占用 |

#### 8.6.2 配额管理

当 Lustre 配额不足时的处理策略：

```cpp
// Dump 操作遇到配额不足
Status HandleDumpTask(TaskDesc& task) {
    auto result = H2S(task);
    if (result.Code() == ELUSTRE_QUOTA_EXCEEDED) {
        // 策略选择：
        // 1. 直接返回错误（默认）
        // 2. 记录警告，尝试清理旧数据后重试（可选）
        UC_ERROR("Lustre quota exceeded, cannot dump block");
        return result;
    }
    return result;
}
```

**配额处理原则**：

- **不自动清理数据**：避免误删用户数据
- **明确错误报告**：返回 `ELUSTRE_QUOTA_EXCEEDED`，由上层决定处理策略
- **配额检查建议**：建议在初始化时验证配额，提前发现问题

### 8.7 监控与可观测性

#### 8.7.1 核心监控指标

| 指标类别 | 具体指标 | 用途 |
|----------|----------|------|
| **性能** | P50/P95/P99 延迟、吞吐量 | 性能调优 |
| **错误** | 错误码分布、错误率、失败任务数 | 故障诊断 |
| **资源** | 线程池使用率、队列长度 | 容量规划 |
| **业务** | Lookup 命中率、冷启动比例 | 缓存效果评估 |

#### 8.7.2 日志规范

```cpp
// 日志级别使用规范
UC_DEBUG("详细的 I/O 操作日志");    // 调试模式
UC_INFO("关键生命周期事件");       // 正常运行
UC_WARN("重试操作、降级操作");     // 需要关注
UC_ERROR("所有失败操作");          // 需要处理
```

**关键日志点**：

- 操作开始/完成（Load/Dump/Lookup）
- 文件创建/打开/关闭
- 条带化 API 调用结果
- 错误和重试操作

#### 8.7.3 性能统计

```cpp
struct LustreStoreMetrics {
    // 计数器
    std::atomic<uint64_t> lookupCount{0};
    std::atomic<uint64_t> loadCount{0};
    std::atomic<uint64_t> dumpCount{0};
    std::atomic<uint64_t> errorCount{0};

    // 延迟统计
    std::atomic<uint64_t> totalLatencyUs{0};
    std::atomic<uint64_t> maxLatencyUs{0};

    // 导出接口
    std::map<std::string, uint64_t> GetMetrics() const;
};
```

---

## 9. 实施路线图

### 9.1 基础功能实现


| 文件                 | 任务         | 参考模板   |
| -------------------- | ------------ | ---------- |
| `lustre_file.h/cc`   | 文件操作实现 | PosixStore |
| `space_layout.h/cc`  | 空间布局管理 | PosixStore |
| `space_manager.h/cc` | 并发查找     | PosixStore |

### 9.2 数据传输实现


| 文件                 | 任务         | 参考模板   |
| -------------------- | ------------ | ---------- |
| `trans_queue.h/cc`   | I/O 队列实现 | PosixStore |
| `trans_manager.h/cc` | 任务管理实现 | PosixStore |
| `trans_task.h`       | 完善接口     | PosixStore |


### 9.3 性能优化实现

```
阶段 1: 基础线程池实现
  ├── 分层线程池架构 (Lookup + Data Transfer)
  ├── CPU 亲和性支持
  └── 并发度可配置

阶段 2: 异步 I/O 实现
  ├── AsyncIOAdapter 抽象层
  ├── io_uring 后端
  ├── libaio 后端
  └── 批量 I/O 优化
```


### 9.4 构建配置


| 文件                    | 任务                   |
| ----------------------- | ---------------------- |
| `CMakeLists.txt`        | 添加 Lustre 库检测     |
| `pipeline/connector.py` | 注册 "Lustre" pipeline |

---

## 10. 测试策略

### 10.1 测试分层

```
┌─────────────────────────────────────────────────────────────────┐
│                      测试金字塔                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│                    ▲                                             │
│                   ╱ ╲        E2E 测试                           │
│                  ╱   ╱       • 真实 Lustre 环境                  │
│                 ╱   ╱        • 性能基准测试                      │
│                ╱   ╱         • 故障恢复测试                      │
│               ╱   ╱          • 并发压力测试                      │
│              ╱   ╱                                            │
│             ╱─────╲      集成测试                               │
│            ╱       ╲     • API 契约验证                         │
│           ╱         ╲    • 组件交互测试                          │
│          ╱───────────╲   • 错误传播测试                         │
│                                                                 │
│         ╱───────────────╲  单元测试 (完全 Mock)                  │
│        ╱                 ╱ • 单函数逻辑验证                      │
│       ╱                 ╱  • 边界条件测试                        │
│      ╱─────────────────╱   • 错误分支覆盖                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 10.2 单元测试

#### 10.2.1 测试范围与 Mock 策略


| 组件           | 测试内容               | Mock 对象                   |
| -------------- | ---------------------- | --------------------------- |
| `SpaceLayout`  | 路径生成逻辑、目录分片 | 无需 Mock（纯逻辑）         |
| `SpaceManager` | 并发查找、超时处理     | Mock`SpaceLayout::Access()` |
| `TransQueue`   | 任务分发、I/O 调度     | Mock`LustreFile` 操作       |
| `TransManager` | 任务生命周期管理       | Mock`TransQueue`            |
| `LustreFile`   | 文件操作封装           | Mock POSIX/Lustre API       |

#### 10.2.2 关键测试场景

**路径生成测试**：

```cpp
// 验证不同 dataDirShardBytes 配置下的路径生成
TEST(SpaceLayout, DataFilePath_GeneratesCorrectPath) {
    SpaceLayout layout;
    Config cfg = { .mountPoint = "/mnt/lustre", .dataDirShardBytes = 3 };
    layout.Setup(cfg);

    BlockId block = MakeBlockId("0123456789abcdef0123456789abcdef");

    // 正式文件路径: data/012/<hash> (shard_path 为前 3 个字符)
    EXPECT_EQ(layout.DataFilePath(block, false),
              "/mnt/lustre/data/012/0123456789abcdef0123456789abcdef");

    // 临时文件路径: data/012/<hash>.tmp.<pid> (进程级隔离)
    auto tmpPath = layout.DataFilePath(block, true);
    EXPECT_TRUE(tmpPath.find(".tmp.") != std::string::npos);  // 包含进程标识
    EXPECT_TRUE(tmpPath.find("/data/012/") != std::string::npos);  // 包含分片路径
}

// 测试不同分片配置
TEST(SpaceLayout, DataFilePath_DifferentShardLevels) {
    SpaceLayout layout;

    // dataDirShardBytes = 0: 无分片
    layout.Setup({ .mountPoint = "/mnt/lustre", .dataDirShardBytes = 0 });
    EXPECT_EQ(layout.DataFilePath(block, false),
              "/mnt/lustre/data/0123456789abcdef0123456789abcdef");

    // dataDirShardBytes = 1: 1 级分片
    layout.Setup({ .mountPoint = "/mnt/lustre", .dataDirShardBytes = 1 });
    EXPECT_EQ(layout.DataFilePath(block, false),
              "/mnt/lustre/data/0/0123456789abcdef0123456789abcdef");

    // dataDirShardBytes = 2: 2 级分片
    layout.Setup({ .mountPoint = "/mnt/lustre", .dataDirShardBytes = 2 });
    EXPECT_EQ(layout.DataFilePath(block, false),
              "/mnt/lustre/data/01/0123456789abcdef0123456789abcdef");
}
```

**原子提交测试**：

```cpp
TEST(SpaceLayout, CommitFile_AtomicRenameSuccess) {
    // Mock rename 系统调用
    EXPECT_CALL(mock_fs, rename)
        .WillOnce(Return(0));  // 成功

    EXPECT_EQ(layout.CommitFile(block, true), Status::OK());
}
```

**边界条件测试**：

```cpp
// 空列表处理
TEST(LustreStore, Lookup_EmptyBlockList) {
    std::vector<uint8_t> result = store->Lookup(nullptr, 0);
    EXPECT_TRUE(result.empty());
}

// 超大并发查找
TEST(LustreStore, Lookup_VeryLargeBlockList) {
    std::vector<BlockId> blocks(10000);
    auto result = store->Lookup(blocks.data(), blocks.size());
    EXPECT_EQ(result.size(), 10000);
}

// 无效设备地址
TEST(LustreStore, Load_InvalidDeviceAddress) {
    TaskDesc task = { .dstAddr = 0xDEADBEEF };
    auto result = store->Load(task);
    EXPECT_TRUE(result.Failure());
}

// 配置参数验证
TEST(LustreStore, Config_InvalidShardBytes) {
    Config cfg = { .dataDirShardBytes = 6 };  // > 5 应失败
    EXPECT_EQ(store->Setup(cfg), Status::InvalidParam());
}
```

### 10.3 集成测试

#### 10.3.1 Lustre API 模拟层

由于真实 Lustre 环境难以搭建，需要创建模拟层：

```cpp
// test/mock/lustre_mock.h
class MockLustreFS {
public:
    // 模拟条带化文件创建
    virtual int llapi_file_create(const char* path,
                                  unsigned long long stripe_size,
                                  int stripe_offset,
                                  int stripe_count,
                                  int pattern) = 0;

    // 模拟文件操作
    virtual int open(const char* path, int flags, ...);
    virtual ssize_t pwrite(int fd, const void* buf, size_t count, off_t offset);
    virtual ssize_t pread(int fd, void* buf, size_t count, off_t offset);

    // 模拟元数据操作
    virtual int access(const char* path, int mode);
    virtual int rename(const char* oldpath, const char* newpath);

    // 注入故障
    void inject_error(const std::string& operation, int error_code);
    void clear_errors();
};
```

#### 10.3.2 组件交互测试

**完整 Load 流程测试**：

```cpp
TEST(Integration, Load_CompleteFlow) {
    // 1. 准备测试数据
    MockLustreFS mock_fs;
    mock_fs.create_file("/data/test_block", test_data);

    // 2. 创建 Store
    LustreStore store;
    store Setup({"storage_backends": ["/mnt/lustre"]});

    // 3. 执行 Load
    TaskDesc task = MakeTask(block_id, dst_addr);
    TaskHandle handle = store->Load(task);

    // 4. 验证数据传输
    store->Wait(handle);
    EXPECT_EQ(memcmp(dst_addr, test_data, size), 0);
}
```

**Dump 临时文件提交流程测试**：

```cpp
TEST(Integration, Dump_TmpFileCommitFlow) {
    // 1. 执行 Dump
    TaskHandle handle = store->Dump(task);
    store->Wait(handle);

    // 2. 验证 .tmp.<pid> 文件被创建
    EXPECT_TRUE(mock_fs.file_exists(tmp_path));
    EXPECT_TRUE(tmp_path.find(".tmp.") != std::string::npos);  // 进程级隔离

    // 3. 验证 Commit 后正式文件存在
    EXPECT_TRUE(mock_fs.file_exists(final_path));
    EXPECT_FALSE(mock_fs.file_exists(tmp_path));
}
```

#### 10.3.3 错误传播测试

**Lustre API 降级测试**：

```cpp
TEST(ErrorPropagation, LustreAPI_FallbackToNormalFile) {
    // 注入 llapi_file_create 失败
    mock_fs.inject_error("llapi_file_create", ENOSYS);

    // 应该降级到普通文件创建
    EXPECT_EQ(store->Dump(task), Status::OK());
    EXPECT_TRUE(mock_fs.file_exists(final_path));
}
```

**磁盘空间不足测试**：

```cpp
TEST(ErrorPropagation, DiskFull_ReturnsProperError) {
    mock_fs.inject_error("write", ENOSPC);

    TaskHandle handle = store->Dump(task);
    store->Wait(handle);

    // 验证错误被正确上报
    EXPECT_EQ(store->Check(handle), false);  // 任务失败
}
```

### 10.4 E2E 测试

#### 10.4.1 测试环境准备

```bash
# 使用 Docker 模拟 Lustre 环境（或使用真实 Lustre）
docker-compose up -d lustre-test-env

# 验证 Lustre 挂载
mount | grep lustre
lfs df /mnt/lustre
```

#### 10.4.2 端到端场景


| 场景                | 描述                | 验证点                    |
| ------------------- | ------------------- | ------------------------- |
| **Cold Start**      | 首次启动，无缓存    | 所有 block 从 Lustre 加载 |
| **Warm Hit**        | 重复请求相同 prefix | 100% 命中率               |
| **Partial Hit**     | 部分 block 在存储   | 混合加载行为              |
| **Concurrent Dump** | 多个请求同时转储    | 并发安全，无数据损坏      |
| **Crash Recovery**  | 进程崩溃后重启      | 残留 .tmp.* 文件被清理    |

#### 10.4.3 E2E 测试示例

```python
# test/e2e/lustre_store_e2e.py
import pytest
from ucm.store.lustre import UcmLustreStore

class TestLustreStoreE2E:

    @pytest.fixture
    def lustre_store(self):
        config = {
            "storage_backends": ["/mnt/lustre"],
            "device_id": 0,
            "block_size": 4096,
            "data_dir_shard_bytes": 3,  # 使用 3 级目录分片
        }
        return UcmLustreStore(config)

    def test_full_dump_load_cycle(self, lustre_store):
        """完整的 Dump → Load 循环"""
        # 1. 生成测试数据
        test_blocks = generate_test_blocks(num_blocks=100)

        # 2. Dump 到 Lustre
        task = lustre_store.dump(test_blocks.block_ids,
                                  test_blocks.shard_index,
                                  test_blocks.tensors)
        lustre_store.wait(task)

        # 3. 验证 Lookup
        presence = lustre_store.lookup(test_blocks.block_ids)
        assert all(presence)

        # 4. Load 回来
        task = lustre_store.load(test_blocks.block_ids,
                                  test_blocks.shard_index,
                                  dst_tensors)
        lustre_store.wait(task)

        # 5. 验证数据一致性
        assert_tensors_equal(dst_tensors, test_blocks.tensors)

    def test_crash_recovery(self, lustre_store):
        """模拟进程崩溃恢复"""
        # 1. 创建一些 .tmp.* 文件
        create_tmp_files("/mnt/lustre/data/*.tmp.*")

        # 2. 重启 Store
        store2 = UcmLustreStore(config)

        # 3. 验证 .tmp.* 文件被清理
        assert not tmp_files_exist()
```

### 10.5 性能测试

#### 10.5.1 基准指标


| 指标          | 目标值   | 测量方法                 |
| ------------- | -------- | ------------------------ |
| 顺序读吞吐量  | > 10GB/s | `fio --rw=read --bs=1M`  |
| 顺序写吞吐量  | > 8GB/s  | `fio --rw=write --bs=1M` |
| 平均 I/O 延迟 | < 1ms    | iostat                   |
| Lookup 延迟   | < 100μs | 自定义基准               |
| 并发 Load QPS | > 10000  | vLLM 集成测试            |

#### 10.5.2 性能测试脚本

```python
# test/perf/lustre_benchmark.py
class LustreBenchmark:

    def benchmark_sequential_read(self, block_sizes):
        """测试不同 block 大小的顺序读性能"""
        for size in block_sizes:
            start = time.time()
            self.store.load(generate_blocks(1000, size))
            elapsed = time.time() - start
            throughput = (1000 * size) / elapsed
            print(f"Block size {size}: {throughput:.2f} GB/s")

    def benchmark_concurrent_load(self, concurrency_levels):
        """测试不同并发度的性能"""
        for concurrency in concurrency_levels:
            tasks = [self.store.load_async(blocks)
                     for _ in range(concurrency)]
            for task in tasks:
                self.store.wait(task)
            # 记录总时间和 QPS

    def benchmark_lookup_scalability(self, block_counts):
        """测试 Lookup 随 block 数量扩展性"""
        for count in block_counts:
            blocks = generate_blocks(count)
            start = time.time()
            presence = self.store.lookup(blocks)
            elapsed = time.time() - start
            print(f"{count} blocks: {elapsed*1000:.2f}ms")
```

#### 10.5.3 压力测试

```python
def test_stress_dump_load_mix(self):
    """混合 Dump/Load 压力测试"""
    for _ in range(1000):
        # 随机选择操作
        if random.random() < 0.5:
            self.store.dump(...)
        else:
            self.store.load(...)

    # 验证没有资源泄漏
    assert_no_file_descriptor_leak()
    assert_no_memory_leak()
```

### 10.6 测试实施路线图

```
阶段 1: 单元测试骨架 (Week 1)
├── 设置测试框架 (Google Test)
├── 创建 Mock 层
└── 基础接口测试

阶段 2: 集成测试 (Week 2-3)
├── Lustre API 模拟层
├── 组件交互测试
└── 错误处理验证

阶段 3: E2E 测试 (Week 4)
├── 真实环境准备
├── 端到端场景
└── 与 vLLM 集成测试

阶段 4: 性能测试 (Week 5)
├── 基准测试套件
├── 压力测试
└── 性能回归检测
```

### 10.7 测试环境配置

#### 10.7.1 环境变量

```bash
# 测试模式切换
export LUSTRE_MOCK_MODE=1     # 使用 Mock 模式（默认）
export LUSTRE_MOCK_MODE=0     # 使用真实 Lustre 环境

# 测试数据路径
export LUSTRE_TEST_PATH=/tmp/lustre_test

# 日志级别
export UC_LOGGER_LEVEL=debug
```

#### 10.7.2 Docker Compose 测试环境

```yaml
# docker-compose.test.yml
version: '3.8'
services:
  lustre-test:
    image: lustre/test-env:latest
    volumes:
      - /mnt/lustre:/lustre
    environment:
      - LUSTRE_MOCK_MODE=0
```

### 10.8 常见测试问题


| 问题             | 原因              | 解决方案                           |
| ---------------- | ----------------- | ---------------------------------- |
| 条带化 API 失败  | 未安装 Lustre SDK | 使用 Mock 模式或安装`lustre-devel` |
| 测试环境权限不足 | Lustre 挂载点权限 | 检查`/mnt/lustre` 目录权限         |
| 并发测试超时     | 并发度配置不当    | 增加`timeout_ms` 配置              |
| 内存泄漏检测失败 | 资源未正确释放    | 使用 Valgrind 检测                 |

---

## 11. 参考文档

### 11.1 内部文档

- [UCM 架构文档](../index.md)
- [Ds3fs Store](../../ds3fs_store.md) - 参考实现
- [PosixStore 源码](../../ucm/store/posix/cc/)

### 11.2 外部资源

- [Lustre 操作手册](https://wiki.lustre.org/)
- [Lustre API 文档](https://wiki.lustre.org/Lustre_Software)
- [io_uring 官方文档](https://kernel.dk/io_uring.pdf)
- [Linux AIO 文档](https://man7.org/linux/man-pages/man2/io_submit.2.html)

### 11.3 性能指标目标


| 指标              | 目标值            | 测量方法      |
| ----------------- | ----------------- | ------------- |
| **顺序读吞吐量**  | > 10GB/s (16 OST) | fio/iozone    |
| **顺序写吞吐量**  | > 8GB/s (16 OST)  | fio/iozone    |
| **平均 I/O 延迟** | < 1ms (小 I/O)    | iostat/自定义 |
| **CPU 利用率**    | < 80% (满负载)    | top/perf      |
| **元数据操作**    | < 100μs (lookup) | 自定义基准    |

---

## 附录 A: 接口兼容性

LustreStore 完全兼容 UCM StoreV1 接口，与 PosixStore 行为一致：


| 接口                 | 行为                     | 与 PosixStore 一致性 |
| -------------------- | ------------------------ | -------------------- |
| `lookup()`           | 返回存在性位图           | ✅                   |
| `lookup_on_prefix()` | 返回首个**缺失**块的索引 | ✅                   |
| `prefetch()`         | 预取提示                 | ✅                   |
| `load()`             | 异步任务，返回任务句柄   | ✅                   |
| `dump()`             | 异步任务，返回任务句柄   | ✅                   |
| `wait()`             | 阻塞直到任务完成         | ✅                   |
| `check()`            | 非阻塞轮询               | ✅                   |

**说明**: `lookup_on_prefix()` 返回首个缺失块的索引，若全部存在返回 -1。与 PosixStore 语义完全一致。

---

## 附录 B: 扩展预留

为未来版本 (V2+) 预留的扩展点：

```cpp
// V2: 目录分片
size_t dataDirShardBytes;     // 0→1→2 实现基于哈希的子目录

// V2: 目录条带化
bool enableDirStriping;       // 启用 Lustre 目录条带化

// V2: 临时文件条带化
bool stripeTempFile;          // 启用临时文件条带化

// V2: 自定义条带化参数
int stripeCount;              // 自定义条带数量
size_t stripeSize;            // 自定义条带大小
```
