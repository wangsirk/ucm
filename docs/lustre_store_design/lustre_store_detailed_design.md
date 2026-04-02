# Lustre Store 详细设计文档

## 文档版本信息

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| 1.0 | 2026-04-01 | Design Team | 初始版本 |

---

## 目录

1. [系统概述](#1-系统概述)
2. [系统架构设计](#2-系统架构设计)
3. [核心组件设计](#3-核心组件设计)
4. [API接口定义](#4-api接口定义)
5. [数据模型设计](#5-数据模型设计)
6. [技术选型建议](#6-技术选型建议)
7. [线程池架构设计](#7-线程池架构设计)
8. [异步I/O架构](#8-异步io架构)
9. [错误处理机制](#9-错误处理机制)
10. [性能优化策略](#10-性能优化策略)
11. [配置管理设计](#11-配置管理设计)
12. [监控与可观测性](#12-监控与可观测性)

---

## 1. 系统概述

### 1.1 设计目标

LustreStore 是 UCM (Unified Cache Management) 的存储后端实现，专门针对 Lustre 并行文件系统进行优化。

| 目标 | 描述 |
|------|------|
| **高性能** | 利用 Lustre 条带化特性，实现高吞吐量数据传输 |
| **可扩展性** | 支持目录分片，优化元数据操作性能 |
| **兼容性** | 完全兼容 UCM StoreV1 接口，可与其他 Store 串联使用 |
| **可靠性** | 采用原子操作和临时文件机制，保证数据一致性 |
| **可观测性** | 提供完善的监控指标和日志记录 |

### 1.2 系统边界

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         LustreStore 系统边界                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐         ┌─────────────────┐         ┌──────────────┐ │
│  │ vLLM/PyTorch │────────▶│  LustreStore    │────────▶│ Lustre Files │ │
│  │   Framework  │◀────────│                 │◀────────│   System     │ │
│  └──────────────┘         └─────────────────┘         └──────────────┘ │
│                                     │                              │
│                                     ▼                              │
│                            ┌─────────────────┐                      │
│                            │  UCM Framework  │                      │
│                            │  (Optional)     │                      │
│                            └─────────────────┘                      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.3 设计原则

| 原则 | 说明 | 应用场景 |
|------|------|----------|
| **简单性** | 避免不必要的复杂功能 | 复用 PosixStore 设计模式 |
| **解耦** | 独立部署，无需上报状态 | 标准接口，无外部依赖 |
| **性能优先** | 利用 Lustre 特性优化 | 条带化文件创建，异步 I/O |
| **兼容性** | 与 UCM 生态保持一致 | 数据格式、错误处理、并发控制 |

---

## 2. 系统架构设计

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              LustreStore 整体架构                                   │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         UCM Application Layer                               │   │
│  │                    (vLLM / PyTorch / Custom)                               │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                         │                                          │
│                                         ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                      UCM StoreV1 Interface Layer                            │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  StoreV1 Interface:                                                   │ │   │
│  │  │  • Setup()              • Lookup()     • LookupOnPrefix()             │ │   │
│  │  │  • Prefetch()           • Load()       • Dump()                       │ │   │
│  │  │  • Check()              • Wait()                                     │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                         │                                          │
│                                         ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         LustreStore Implementation                          │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │                        LustreStoreImpl                                │ │   │
│  │  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                 │ │   │
│  │  │  │SpaceManager  │  │TransManager  │  │ Configuration│                 │ │   │
│  │  │  │              │  │              │  │              │                 │ │   │
│  │  │  │- Lookup      │  │- Load/Dump   │  │- Parameters  │                 │ │   │
│  │  │  │- Prefix check│  │- Task mgmt   │  │- Validation  │                 │ │   │
│  │  │  └──────────────┘  └──────────────┘  └──────────────┘                 │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                         │                                          │
│                                         ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         Component Layer                                     │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │   │
│  │  │SpaceLayout   │  │TransQueue    │  │LustreFile    │  │AsyncIOAdapter│     │   │
│  │  │              │  │              │  │              │  │              │     │   │
│  │  │- Path gen    │  │- IO schedule │  │- File ops    │  │- io_uring    │     │   │
│  │  │- Sharding    │  │- IoUnit mgmt │  │- Stripe API  │  │- libaio      │     │   │
│  │  │- Commit      │  │- H2S/S2H     │  │- POSIX API   │  │- ThreadPool  │     │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘     │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                         │                                          │
│                                         ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         Thread Pool Layer                                   │   │
│  │  ┌─────────────────────────────────────┐  ┌───────────────────────────────┐  │   │
│  │  │      Lookup Thread Pool             │  │   Data Transfer Thread Pool   │  │   │
│  │  │  • Concurrency: 8 (default)         │  │  • Concurrency: 16 (default)  │  │   │
│  │  │  • Purpose: Metadata operations     │  │  • Purpose: Data I/O           │  │   │
│  │  │  • CPU Affinity: Optional           │  │  • CPU Affinity: Optional      │  │   │
│  │  └─────────────────────────────────────┘  └───────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                         │                                          │
│                                         ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                    Storage Backend (Lustre File System)                     │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │   │
│  │  │     MDT      │  │     OST      │  │     OSS      │  │  Networking  │     │   │
│  │  │  (Metadata)  │  │  (Storage)   │  │  (Server)    │  │   (LNet)     │     │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘     │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 组件交互图

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         组件交互序列图 - Load 操作                                  │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  App          LustreStore    SpaceManager    TransQueue    LustreFile    Lustre FS │
│  │                │                │              │              │              │   │
│  │  Load()        │                │              │              │              │   │
│  │───────────────▶│                │              │              │              │   │
│  │                │                │              │              │              │   │
│  │                │  Lookup()      │              │              │              │   │
│  │                │───────────────▶│              │              │              │   │
│  │                │                │  access()    │              │              │   │
│  │                │                │─────────────▶│              │              │   │
│  │                │                │              │              │              │   │
│  │                │                │  Results     │              │              │   │
│  │                │                │◀─────────────│              │              │   │
│  │                │◀───────────────│              │              │              │   │
│  │                │                │              │              │              │   │
│  │                │  Submit(Task)  │              │              │              │   │
│  │                │──────────────────────────────▶│              │              │   │
│  │                │                │              │              │              │   │
│  │                │                │              │  Push(IoUnit)│              │   │
│  │                │                │              │─────────────▶│              │   │
│  │                │                │              │              │              │   │
│  │                │                │              │              │  Open()     │   │
│  │                │                │              │              │─────────────▶│   │
│  │                │                │              │              │              │   │
│  │                │                │              │              │  Read()     │   │
│  │                │                │              │              │─────────────▶│   │
│  │                │                │              │              │◀────────────│   │
│  │                │                │              │              │              │   │
│  │                │                │              │  Data        │              │   │
│  │                │                │              │◀─────────────│              │   │
│  │                │                │              │              │              │   │
│  │                │  TaskHandle    │              │              │              │   │
│  │◀───────────────│                │              │              │              │   │
│  │                │                │              │              │              │   │
│  │  Check(handle) │                │              │              │              │   │
│  │───────────────▶│                │              │              │              │   │
│  │  ...           │                │              │              │              │   │
│  │                │                │              │              │              │   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 分层架构

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              分层架构设计                                          │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  Layer 7: Application Layer (vLLM, PyTorch, etc.)                           │   │
│  │  • KV Cache 管理  • 模型推理  • 训练流程                                     │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                        │                                           │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  Layer 6: UCM Framework Layer                                               │   │
│  │  • PipelineStore  • CacheStore  • Store V1 Interface                       │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                        │                                           │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  Layer 5: Store Interface Layer (LustreStore)                               │   │
│  │  • StoreV1 实现  • 统一错误处理  • 配置管理                                  │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                        │                                           │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  Layer 4: Business Logic Layer (LustreStoreImpl)                            │   │
│  │  • 空间管理  • 传输管理  • 任务调度  • 并发控制                              │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                        │                                           │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  Layer 3: Component Layer                                                   │   │
│  │  • SpaceLayout  • TransQueue  • TransTask  • LustreFile  • AsyncIOAdapter  │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                        │                                           │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  Layer 2: I/O Abstraction Layer                                            │   │
│  │  • POSIX API  • Lustre API  • io_uring  • libaio                           │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                        │                                           │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  Layer 1: Storage Layer (Lustre File System)                               │   │
│  │  • MDT/MDS  • OST/OSS  • LNet Network                                       │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心组件设计

### 3.1 组件层次结构

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              组件层次结构图                                        │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  LustreStore                                                                        │
│  │                                                                                   │
│  ├─── LustreStoreImpl (核心实现)                                                    │
│  │    │                                                                              │
│  │    ├─── SpaceManager (空间管理)                                                  │
│  │    │    │                                                                         │
│  │    │    └─── SpaceLayout (空间布局)                                              │
│  │    │         │                                                                    │
│  │    │         ├─── PathGenerator (路径生成)                                       │
│  │    │         └─── FileCommiter (文件提交)                                        │
│  │    │                                                                            │
│  │    └─── TransManager (传输管理)                                                  │
│  │         │                                                                        │
│  │         └─── TransQueue (传输队列)                                               │
│  │              │                                                                   │
│  │              ├─── IoUnitPool (I/O 单元池)                                        │
│  │              └─── IoExecutor (I/O 执行器)                                        │
│  │                   │                                                              │
│  │                   └─── LustreFile (文件操作)                                     │
│  │                        │                                                         │
│  │                        └─── AsyncIOAdapter (异步 I/O 适配器)                     │
│  │                             │                                                    │
│  │                             ├─── IoUringBackend (io_uring 后端)                  │
│  │                             ├─── LibaioBackend (libaio 后端)                     │
│  │                             └─── ThreadPoolBackend (线程池后端)                   │
│  │                                                                                  │
│  └─── Configuration (配置管理)                                                       │
│       │                                                                             │
│       ├─── ConfigValidator (配置验证器)                                             │
│       └─── ConfigMapper (配置映射器)                                                │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 组件职责矩阵

| 组件 | 职责 | 依赖 | 输出 |
|------|------|------|------|
| **LustreStore** | StoreV1 接口实现，入口点 | LustreStoreImpl | Status, TaskHandle |
| **LustreStoreImpl** | 核心业务逻辑协调 | SpaceManager, TransManager | 协调结果 |
| **SpaceManager** | 空间查找，前缀检查 | SpaceLayout | 存在性位图 |
| **SpaceLayout** | 路径生成，文件提交 | 无 | 文件路径 |
| **TransManager** | 传输任务管理 | TransQueue | TaskHandle |
| **TransQueue** | I/O 任务调度 | LustreFile | I/O 结果 |
| **LustreFile** | 文件操作封装 | AsyncIOAdapter | Status |
| **AsyncIOAdapter** | 异步 I/O 抽象 | io_uring/libaio | I/O 结果 |
| **Configuration** | 配置管理 | 无 | Config 对象 |

### 3.3 组件间依赖关系

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                            组件依赖关系图 (DAG)                                     │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│    ┌──────────────┐                                                                │
│    │ LustreStore  │                                                                │
│    └──────┬───────┘                                                                │
│           │                                                                        │
│           ▼                                                                        │
│    ┌──────────────┐     ┌──────────────┐                                           │
│    │LustreStore   │────▶│Configuration │                                           │
│    │    Impl      │     └──────────────┘                                           │
│    └──┬───────┬──┘                                                                 │
│       │       │                                                                     │
│       ▼       ▼                                                                     │
│    ┌──────┐ ┌──────────┐                                                           │
│    │Space │ │  Trans  │                                                           │
│    │Mgr   │ │ Manager  │                                                           │
│    └──┬───┘ └────┬─────┘                                                           │
│       │          │                                                                 │
│       ▼          ▼                                                                 │
│    ┌──────┐  ┌──────────┐                                                         │
│    │Space │  │  Trans   │                                                         │
│    │Layout│  │  Queue   │                                                         │
│    └──────┘  └────┬─────┘                                                         │
│                  │                                                                 │
│                  ▼                                                                 │
│            ┌──────────┐                                                           │
│            │LustreFile│                                                           │
│            └────┬─────┘                                                           │
│                 │                                                                │
│                 ▼                                                                │
│        ┌──────────────────┐                                                       │
│        │ AsyncIOAdapter   │                                                       │
│        └──────────────────┘                                                       │
│                 │                                                                │
│       ┌───────────┼───────────┐                                                  │
│       ▼           ▼           ▼                                                  │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐                                            │
│  │io_uring │ │ libaio  │ │Thread   │                                            │
│  │Backend  │ │Backend  │ │Pool     │                                            │
│  │         │ │         │ │Backend  │                                            │
│  └─────────┘ └─────────┘ └─────────┘                                            │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. API接口定义

### 4.1 StoreV1 接口实现

```cpp
namespace UC {

class LustreStore : public StoreV1 {
public:
    // ===== 生命周期管理 =====

    // 使用配置初始化存储
    // @param config 配置参数
    // @return Status 初始化状态
    Status Setup(const Config& config) override;

    // 析构，自动清理资源
    ~LustreStore() override;

    // ===== 元数据操作 =====

    // 批量检查块是否存在
    // @param blocks 块ID数组
    // @param num 块数量
    // @return std::vector<uint8_t> 存在性位图 (1=存在, 0=不存在)
    std::vector<uint8_t> Lookup(const BlockId* blocks, size_t num) override;

    // 查找前缀序列中首个缺失块
    // @param blocks 块ID数组 (前缀有序)
    // @param num 块数量
    // @return Expected<ssize_t> 首个缺失块索引，全部存在返回 -1
    Expected<ssize_t> LookupOnPrefix(const BlockId* blocks, size_t num) override;

    // 预取提示 (非阻塞)
    // @param blocks 块ID数组
    // @param num 块数量
    void Prefetch(const BlockId* blocks, size_t num) override;

    // ===== 数据传输操作 =====

    // 启动异步加载任务 (Lustre → Device)
    // @param blocks 块ID数组
    // @param num 块数量
    // @param addrs 设备内存地址数组
    // @return TaskHandle 任务句柄
    TaskHandle Load(const BlockId* blocks, size_t num,
                    const void* const* addrs) override;

    // 启动异步转储任务 (Device → Lustre)
    // @param blocks 块ID数组
    // @param num 块数量
    // @param addrs 设备内存地址数组
    // @return TaskHandle 任务句柄
    TaskHandle Dump(const BlockId* blocks, size_t num,
                    const void* const* addrs) override;

    // ===== 任务管理 =====

    // 轮询任务完成状态 (非阻塞)
    // @param handle 任务句柄
    // @return bool true=完成, false=进行中
    bool Check(TaskHandle handle) const override;

    // 阻塞等待任务完成
    // @param handle 任务句柄
    // @return Status 任务执行状态
    Status Wait(TaskHandle handle) const override;

private:
    std::unique_ptr<LustreStoreImpl> impl_;
};

} // namespace UC
```

### 4.2 SpaceManager API

```cpp
namespace UC::LustreStore {

class SpaceManager {
public:
    // ===== 初始化 =====

    // 初始化空间管理器
    // @param config 配置参数
    // @return Status 初始化状态
    Status Setup(const Config& config, const SpaceLayout* layout);

    // ===== 查询操作 =====

    // 批量块查找
    // @param blocks 块ID数组
    // @param num 块数量
    // @return std::vector<uint8_t> 存在性位图
    std::vector<uint8_t> Lookup(const BlockId* blocks, size_t num);

    // 查找前缀序列中首个缺失块
    // @param blocks 块ID数组 (前缀有序)
    // @param num 块数量
    // @return Expected<ssize_t> 首个缺失块索引
    Expected<ssize_t> LookupOnPrefix(const BlockId* blocks, size_t num);

    // ===== 内部接口 =====

    // 检查单个块是否存在
    // @param block 块ID
    // @return bool true=存在, false=不存在
    bool CheckBlock(const BlockId& block);

private:
    const SpaceLayout* layout_;          // 空间布局管理器
    ThreadPool lookupThreadPool_;        // 查找线程池
    size_t lookupConcurrency_;           // 并发度
};

} // namespace UC::LustreStore
```

### 4.3 SpaceLayout API

```cpp
namespace UC::LustreStore {

class SpaceLayout {
public:
    // ===== 初始化 =====

    // 初始化空间布局
    // @param config 配置参数
    // @return Status 初始化状态
    Status Setup(const Config& config);

    // ===== 路径生成 =====

    // 生成块文件路径
    // @param blockId 块ID
    // @param activated 是否为临时文件
    // @return std::string 文件路径
    //   - activated=false: "data/{shard_path}/{hash}"
    //   - activated=true:  "data/{shard_path}/{hash}.tmp.{pid}"
    std::string DataFilePath(const BlockId& blockId, bool activated) const;

    // 生成目录分片路径
    // @param blockId 块ID
    // @return std::string 分片目录路径 "data/{shard_path}/"
    std::string ShardPath(const BlockId& blockId) const;

    // 生成完整数据目录路径
    // @return std::string "data/" 或 "data/{shard_path}/"
    std::string DataDir() const;

    // ===== 文件操作 =====

    // 提交临时文件为正式文件
    // @param blockId 块ID
    // @param success 是否成功 (true=rename, false=remove)
    // @return Status 操作状态
    Status CommitFile(const BlockId& blockId, bool success) const;

    // 检查文件是否存在
    // @param blockId 块ID
    // @param isTemp 是否检查临时文件
    // @return bool true=存在, false=不存在
    bool FileExists(const BlockId& blockId, bool isTemp = false) const;

    // 创建必要的目录结构
    // @param blockId 块ID (用于确定需要创建的分片目录)
    // @return Status 操作状态
    Status EnsureDirectories(const BlockId& blockId);

    // ===== 清理操作 =====

    // 清理残留的临时文件
    // @return Status 清理状态
    Status CleanupTempFiles();

private:
    std::string mountPoint_;           // Lustre 挂载点
    size_t dataDirShardBytes_;         // 目录分片层级 (0-3)
    pid_t pid_;                        // 进程 ID

    // 辅助函数
    std::string BlockIdToHex(const BlockId& blockId) const;
    std::string GetShardPath(const std::string& hexHash) const;
};

} // namespace UC::LustreStore
```

### 4.4 TransManager API

```cpp
namespace UC::LustreStore {

class TransManager : public TaskWrapper<TransTask, TaskHandle> {
public:
    // ===== 初始化 =====

    // 使用配置初始化传输管理器
    // @param config 配置参数
    // @param layout 空间布局管理器
    // @return Status 初始化状态
    Status Setup(const Config& config, const SpaceLayout* layout);

    // ===== 任务提交 =====

    // 提交 Load 任务
    // @param desc 任务描述
    // @return TaskHandle 任务句柄
    TaskHandle SubmitLoad(const TaskDesc& desc);

    // 提交 Dump 任务
    // @param desc 任务描述
    // @return TaskHandle 任务句柄
    TaskHandle SubmitDump(const TaskDesc& desc);

    // ===== 控制 =====

    // 启用/禁用数据传输
    // @param enable true=启用, false=禁用
    void SetTransEnabled(bool enable);

    // 检查传输是否启用
    // @return bool true=启用, false=禁用
    bool IsTransEnabled() const;

protected:
    // ===== 任务分发 (TaskWrapper 接口) =====

    // 分发任务到队列
    // @param task 任务对象
    // @param waiter 等待器
    void Dispatch(TaskPtr task, WaiterPtr waiter) override;

private:
    std::unique_ptr<TransQueue> queue_;  // 传输队列
    const SpaceLayout* layout_;          // 空间布局
    bool transEnable_;                   // 传输启用标志
};

} // namespace UC::LustreStore
```

### 4.5 TransQueue API

```cpp
namespace UC::LustreStore {

class TransQueue {
public:
    // ===== 数据结构 =====

    // I/O 单元 - 最小 I/O 任务单位
    struct IoUnit {
        BlockId blockId;                // 块 ID
        size_t shardIndex;              // 分片索引
        void* dstAddr;                  // 目标地址
        size_t offset;                  // 文件偏移
        size_t size;                    // I/O 大小
        TransTask::Type type;           // 操作类型 (LOAD/DUMP)
    };

    // ===== 初始化 =====

    // 初始化传输队列
    // @param config 配置参数
    // @param failureSet 失败任务集合
    // @param layout 空间布局管理器
    // @return Status 初始化状态
    Status Setup(const Config& config, TaskIdSet* failureSet,
                 const SpaceLayout* layout);

    // ===== 任务管理 =====

    // 推送任务到队列
    // @param task 任务对象
    // @param waiter 等待器
    void Push(TaskPtr task, WaiterPtr waiter);

    // 停止队列处理
    void Stop();

private:
    // ===== I/O 处理 =====

    // 写入存储 (Dump 操作 - Host to Storage)
    // @param ios I/O 单元
    // @return Status 操作状态
    Status H2S(IoUnit& ios);

    // 读取存储 (Load 操作 - Storage to Host)
    // @param ios I/O 单元
    // @return Status 操作状态
    Status S2H(IoUnit& ios);

    // ===== 任务拆分 =====

    // 将任务拆分为 I/O 单元
    // @param task 任务对象
    // @return std::vector<IoUnit> I/O 单元列表
    std::vector<IoUnit> SplitTask(const TransTask& task);

private:
    ThreadPool workerPool_;             // 工作线程池
    const SpaceLayout* layout_;         // 空间布局
    TaskIdSet* failureSet_;             // 失败任务集合
    std::unique_ptr<LustreFile> file_;  // 文件操作器
};

} // namespace UC::LustreStore
```

### 4.6 LustreFile API

```cpp
namespace UC::LustreStore {

class LustreFile {
public:
    // ===== 构造/析构 =====

    // 构造函数
    // @param path 文件路径
    explicit LustreFile(const std::string& path);

    // 析构函数 - 自动关闭文件
    ~LustreFile();

    // 禁止拷贝
    LustreFile(const LustreFile&) = delete;
    LustreFile& operator=(const LustreFile&) = delete;

    // ===== 文件创建 =====

    // 创建条带化文件 (Lustre API)
    // @param mode 文件权限
    // @return Status 操作状态
    Status CreateStriped(mode_t mode = 0644);

    // 创建普通文件 (POSIX)
    // @param flags 文件标志
    // @param mode 文件权限
    // @return Status 操作状态
    Status CreateNormal(uint32_t flags, mode_t mode = 0644);

    // ===== 文件操作 =====

    // 打开文件
    // @param flags 打开标志 (O_RDONLY, O_WRONLY, O_RDWR)
    // @return Status 操作状态
    Status Open(uint32_t flags);

    // 读取文件
    // @param buffer 缓冲区
    // @param size 读取大小
    // @param offset 文件偏移
    // @return Status 操作状态
    Status Read(void* buffer, size_t size, off64_t offset);

    // 写入文件
    // @param buffer 数据缓冲区
    // @param size 写入大小
    // @param offset 文件偏移
    // @return Status 操作状态
    Status Write(const void* buffer, size_t size, off64_t offset);

    // 关闭文件
    void Close();

    // ===== 目录操作 =====

    // 创建目录
    // @param path 目录路径
    // @param mode 目录权限
    // @return Status 操作状态
    static Status MkDir(const std::string& path, mode_t mode = 0755);

    // 检查文件/目录访问权限
    // @param mode 访问模式 (F_OK, R_OK, W_OK, X_OK)
    // @return bool true=可访问, false=不可访问
    bool Access(int32_t mode) const;

    // ===== 文件管理 =====

    // 重命名文件
    // @param newName 新文件名
    // @return Status 操作状态
    Status Rename(const std::string& newName);

    // 删除文件
    // @param path 文件路径
    // @return Status 操作状态
    static Status Remove(const std::string& path);

    // 获取文件大小
    // @return size_t 文件大小 (失败返回 0)
    size_t GetSize() const;

    // ===== 状态查询 =====

    // 检查文件是否打开
    // @return bool true=已打开, false=未打开
    bool IsOpen() const { return fd_ >= 0; }

    // 获取文件描述符
    // @return int 文件描述符 (-1 表示未打开)
    int GetFd() const { return fd_; }

    // 获取文件路径
    // @return std::string 文件路径
    const std::string& GetPath() const { return path_; }

private:
    std::string path_;                 // 文件路径
    int fd_;                           // 文件描述符 (-1=未打开)

    // 辅助函数
    Status CheckOpen() const;
};

} // namespace UC::LustreStore
```

### 4.7 AsyncIOAdapter API

```cpp
namespace UC::LustreStore {

class AsyncIOAdapter {
public:
    // ===== 数据结构 =====

    // I/O 请求
    struct IoRequest {
        void* buffer;                          // 缓冲区地址
        size_t size;                           // I/O 大小
        off64_t offset;                        // 文件偏移
        int fd;                                // 文件描述符

        enum Op { READ, WRITE } op;            // 操作类型

        // 完成回调
        // @param status 操作状态
        // @param bytesTransferred 实际传输字节数
        std::function<void(const Status&, size_t)> callback;
    };

    // I/O 结果
    struct IoResult {
        Status status;                         // 操作状态
        size_t bytesTransferred;               // 实际传输字节数
        int errorCode;                         // 系统错误码 (如果有)
    };

    // ===== 工厂方法 =====

    // 创建最佳可用的异步 I/O 适配器
    // @param queueDepth 队列深度
    // @return std::unique_ptr<AsyncIOAdapter> 适配器实例
    static std::unique_ptr<AsyncIOAdapter> Create(
        size_t queueDepth = 256);

    // ===== 虚析构 =====

    virtual ~AsyncIOAdapter() = default;

    // ===== 初始化 =====

    // 初始化适配器
    // @param queueDepth 队列深度
    // @param sqThreadCpu SQ 线程 CPU 亲和性 (-1=不绑定)
    // @return Status 初始化状态
    virtual Status Setup(size_t queueDepth, int sqThreadCpu = -1) = 0;

    // ===== I/O 操作 =====

    // 提交读请求
    // @param req I/O 请求
    // @return Status 提交状态
    virtual Status SubmitRead(const IoRequest& req) = 0;

    // 提交写请求
    // @param req I/O 请求
    // @return Status 提交状态
    virtual Status SubmitWrite(const IoRequest& req) = 0;

    // ===== 完成处理 =====

    // 处理完成队列
    // @param timeoutMs 超时时间 (毫秒, 0=非阻塞)
    // @return size_t 处理的完成事件数量
    virtual size_t ProcessCompletion(int timeoutMs = 0) = 0;

    // 获取待处理完成数量
    // @return size_t 待处理完成数量
    virtual size_t GetPendingCompletions() const = 0;

    // ===== 同步包装 =====

    // 同步读取 (便捷方法)
    // @param fd 文件描述符
    // @param buffer 缓冲区
    // @param size 大小
    // @param offset 偏移
    // @return Status 操作状态
    virtual Status ReadSync(int fd, void* buffer, size_t size, off64_t offset) = 0;

    // 同步写入 (便捷方法)
    // @param fd 文件描述符
    // @param buffer 数据
    // @param size 大小
    // @param offset 偏移
    // @return Status 操作状态
    virtual Status WriteSync(int fd, const void* buffer, size_t size, off64_t offset) = 0;
};

// ===== 具体后端实现 =====

// io_uring 后端
class IoUringBackend : public AsyncIOAdapter { /* ... */ };

// libaio 后端
class LibaioBackend : public AsyncIOAdapter { /* ... */ };

// 线程池模拟后端
class ThreadPoolBackend : public AsyncIOAdapter { /* ... */ };

} // namespace UC::LustreStore
```

---

## 5. 数据模型设计

### 5.1 数据层次结构

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              数据层次结构                                           │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  Transformer Model                                                                  │
│  │                                                                                   │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │  │                        KV Cache                                        │    │
│  │  └─────────────────────────────────────────────────────────────────────────┘    │
│  │                                                                                   │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │  │                        Block (块)                                       │    │
│  │  │  • 包含多个 Shard                                                         │    │
│  │  │  • 大小: blockSize = shardSize × nShardPerBlock                          │    │
│  │  │  • 标识: BlockId (16 bytes, SHA-256 prefix)                              │    │
│  │  └─────────────────────────────────────────────────────────────────────────┘    │
│  │                                                                                   │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │  │                        Shard (分片)                                      │    │
│  │  │  • 对应一个 Transformer Layer                                            │    │
│  │  │  • 大小: shardSize = tensorSize × nTensorPerShard                        │    │
│  │  │  • 索引: [0, nShardPerBlock)                                             │    │
│  │  └─────────────────────────────────────────────────────────────────────────┘    │
│  │                                                                                   │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │  │                        Tensor (张量)                                     │    │
│  │  │  • 每层的键值对数据                                                       │    │
│  │  │  • 大小: tensorSize (固定)                                                │    │
│  │  │  • 类型: FP16/BF16/FP32                                                   │    │
│  │  └─────────────────────────────────────────────────────────────────────────┘    │
│  │                                                                                   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Block 文件格式

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         Block 文件布局 (无 Header)                                  │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  文件: {block_hash_hex} (32 个十六进制字符)                                         │
│  路径: {mount}/data/{shard_path}/{block_hash_hex}                                   │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                           Block Data                                       │   │
│  ├─────────────────────────────────────────────────────────────────────────────┤   │
│  │                                                                             │   │
│  │  Offset 0                                                             ┌─────┤   │
│  │                                                                       │Shard│   │
│  │  ┌─────────────────────────────────────────────────────────────────┐│  0  │   │
│  │  │  Shard 0 数据                                                   ││     │   │
│  │  │  • 大小: shardSize                                              ││     │   │
│  │  │  • 包含 nTensorPerShard 个 Tensor                                ││     │   │
│  │  └─────────────────────────────────────────────────────────────────┘│     │   │
│  │                                                                       │     │   │
│  │  Offset S                                                       ┌─────┤     │   │
│  │                                                                 │Shard│     │   │
│  │  ┌─────────────────────────────────────────────────────────────────┐│  1  │     │   │
│  │  │  Shard 1 数据                                                   ││     │     │   │
│  │  │  • 大小: shardSize                                              ││     │     │   │
│  │  └─────────────────────────────────────────────────────────────────┘│     │     │   │
│  │                                                                       │     │     │   │
│  │  Offset 2S                                                      ┌─────┤     │     │   │
│  │                                                                 │Shard│     │     │   │
│  │  ┌─────────────────────────────────────────────────────────────────┐│  2  │     │     │   │
│  │  │  ...                                                            ││     │     │     │   │
│  │  └─────────────────────────────────────────────────────────────────┘│     │     │     │   │
│  │                                                                       │     │     │     │   │
│  │  Offset (n-1)×S                                               ┌─────┤     │     │     │   │
│  │                                                                 │Shard│     │     │     │   │
│  │  ┌─────────────────────────────────────────────────────────────────┐│ n-1 │     │     │     │   │
│  │  │  Shard n-1 数据                                                 ││     │     │     │     │   │
│  │  │  • 大小: shardSize                                              ││     │     │     │     │   │
│  │  └─────────────────────────────────────────────────────────────────┘│     │     │     │     │   │
│  │                                                                       │     │     │     │     │   │
│  │  Offset n×S (文件末尾)                                               └─────┴─────┴─────┘   │   │
│  │                                                                             │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  其中:                                                                              │
│  • S = shardSize (单个 Shard 大小)                                                   │
│  • n = nShardPerBlock (每个 Block 的 Shard 数量)                                     │
│  • blockSize = n × S                                                                │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Shard 文件布局

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           Shard 内部布局                                            │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  Shard Size = Tensor Size × nTensorPerShard                                         │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                           Shard Data                                       │   │
│  ├─────────────────────────────────────────────────────────────────────────────┤   │
│  │                                                                             │   │
│  │  Offset 0                                                       ┌─────────┤   │
│  │                                                             │  Tensor 0  │   │
│  │  ┌─────────────────────────────────────────────────────────┐│           │   │
│  │  │  Tensor 0 (Key Cache)                                   ││           │   │
│  │  │  • 大小: tensorSize                                     ││           │   │
│  │  │  • 形状: [num_heads, head_dim, ...]                     ││           │   │
│  │  └─────────────────────────────────────────────────────────┘│           │   │
│  │                                                             │           │   │
│  │  Offset T                                              ┌─────┤           │   │
│  │                                                       │Tens│           │   │
│  │  ┌─────────────────────────────────────────────────────┐│or 1│           │   │
│  │  │  Tensor 1 (Value Cache)                              ││    │           │   │
│  │  │  • 大小: tensorSize                                   ││    │           │   │
│  │  └─────────────────────────────────────────────────────┘│    │           │   │
│  │                                                       │    │           │   │
│  │  Offset 2T                                        ┌─────┤    │           │   │
│  │                                                  │Tens│or  │           │   │
│  │  ┌───────────────────────────────────────────────┐│ 2  │    │           │   │
│  │  │  ...                                          ││    │    │           │   │
│  │  └───────────────────────────────────────────────┘│    │    │           │   │
│  │                                                  │    │    │           │   │
│  │  Offset (m-1)×T                             ┌─────┤    │    │           │   │
│  │                                            │Tens│or  │    │           │   │
│  │  ┌───────────────────────────────────────────┐│ m-1│    │    │           │   │
│  │  │  Tensor m-1                                ││    │    │    │           │   │
│  │  │  • 大小: tensorSize                        ││    │    │    │           │   │
│  │  └───────────────────────────────────────────┘│    │    │    │           │   │
│  │                                            │    │    │    │           │   │
│  │  Offset m×T (Shard 末尾)                      └────┴────┴────┴───────────┘   │
│  │                                                                             │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  其中:                                                                              │
│  • T = tensorSize (单个 Tensor 大小)                                                │
│  • m = nTensorPerShard (每个 Shard 的 Tensor 数量)                                   │
│  • shardSize = m × T                                                               │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 5.4 BlockId 映射

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                          BlockId 到文件路径映射                                     │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  输入: BlockId (16 bytes)                                                           │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         BlockId (原始)                                     │   │
│  ├─────────────────────────────────────────────────────────────────────────────┤   │
│  │  Byte 0  │ Byte 1  │ Byte 2  │ ... │ Byte 14 │ Byte 15 │                   │   │
│  │  0x01    │ 0x23    │ 0x45    │ ... │ 0xAB    │ 0xCD    │                   │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                    │                                               │
│                                    ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         十六进制编码                                         │   │
│  ├─────────────────────────────────────────────────────────────────────────────┤   │
│  │  "0123456789abcdef0123456789abcdef"  (32 个十六进制字符)                     │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                    │                                               │
│                                    ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         提取分片路径                                         │   │
│  ├─────────────────────────────────────────────────────────────────────────────┤   │
│  │  shard_path = hash[0:dataDirShardBytes]                                      │   │
│  │                                                                             │   │
│  │  dataDirShardBytes=0: shard_path = ""                                       │   │
│  │  dataDirShardBytes=1: shard_path = "0"                                       │   │
│  │  dataDirShardBytes=2: shard_path = "01"                                      │   │
│  │  dataDirShardBytes=3: shard_path = "012"                                     │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                    │                                               │
│                                    ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         完整路径                                             │   │
│  ├─────────────────────────────────────────────────────────────────────────────┤   │
│  │  正式文件: {mount}/data/{shard_path}/{hash}                                  │   │
│  │  临时文件: {mount}/data/{shard_path}/{hash}.tmp.{pid}                        │   │
│  │                                                                             │   │
│  │  示例 (dataDirShardBytes=3, mount=/mnt/lustre, pid=12345):                   │   │
│  │  正式: /mnt/lustre/data/012/0123456789abcdef0123456789abcdef                 │   │
│  │  临时: /mnt/lustre/data/012/0123456789abcdef0123456789abcdef.tmp.12345       │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 5.5 数据模型定义

```cpp
namespace UC::LustreStore {

// ===== BlockId 定义 =====

// BlockId: 16 字节，存储为 std::array
using BlockId = std::array<uint8_t, 16>;

// BlockId 哈希比较
struct BlockIdHash {
    size_t operator()(const BlockId& id) const {
        return std::hash<std::string_view>()(
            std::string_view(reinterpret_cast<const char*>(id.data()), 16));
    }
};

// BlockId 相等比较
struct BlockIdEqual {
    bool operator()(const BlockId& a, const BlockId& b) const {
        return std::equal(a.begin(), a.end(), b.begin());
    }
};

// ===== 数据模型定义 =====

struct DataModel {
    // Block 相关
    static constexpr size_t BLOCK_ID_SIZE = 16;           // BlockId 字节大小
    static constexpr size_t BLOCK_ID_HEX_SIZE = 32;       // 十六进制字符串长度

    // Shard 相关
    size_t nShardPerBlock;        // 每个 Block 的 Shard 数量
    size_t shardSize;             // 单个 Shard 大小 (字节)

    // Tensor 相关
    size_t nTensorPerShard;       // 每个 Shard 的 Tensor 数量
    size_t tensorSize;            // 单个 Tensor 大小 (字节)

    // 计算属性
    size_t GetBlockSize() const {
        return shardSize * nShardPerBlock;
    }

    size_t GetShardOffset(size_t shardIndex) const {
        return shardIndex * shardSize;
    }

    size_t GetTensorOffset(size_t shardIndex, size_t tensorIndex) const {
        return GetShardOffset(shardIndex) + tensorIndex * tensorSize;
    }
};

// ===== 任务描述符 =====

struct TaskDesc {
    // 块信息
    const BlockId* blockIds;      // 块 ID 数组
    size_t numBlocks;             // 块数量

    // 目标地址
    const void* const* addrs;     // 设备内存地址数组

    // 分片信息
    size_t shardIndex;            // 起始分片索引
    size_t numShards;             // 分片数量

    // 大小信息
    size_t tensorSize;            // 单个 Tensor 大小
    size_t shardSize;             // 单个 Shard 大小
    size_t blockSize;             // 单个 Block 大小

    // 构造函数
    TaskDesc() : blockIds(nullptr), numBlocks(0), addrs(nullptr),
                 shardIndex(0), numShards(0),
                 tensorSize(0), shardSize(0), blockSize(0) {}
};

} // namespace UC::LustreStore
```

---

## 6. 技术选型建议

### 6.1 技术栈概览

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              技术栈选型                                            │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  编程语言与标准                                                               │   │
│  │  • C++17/20  • STL  • POSIX  • CMake                                         │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  文件系统接口                                                                 │   │
│  │  • POSIX API  • Lustre API (llapi_*)  • io_uring  • libaio                  │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  并发与同步                                                                   │   │
│  │  • std::thread  • std::mutex  • std::condition_variable  • std::atomic      │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  线程池                                                                       │   │
│  │  • 自实现线程池  • CPU 亲和性支持  • 任务队列  • 工作窃取                   │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  配置管理                                                                     │   │
│  │  • YAML  • JSON  • 配置验证  • 类型映射                                       │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  日志与监控                                                                   │   │
│  │  • spdlog  • Prometheus  • 自定义指标                                        │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  测试框架                                                                     │   │
│  │  • Google Test  • Google Mock  • pytest (Python E2E)                         │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 异步 I/O 技术选型

| 方案 | 优势 | 劣势 | 推荐场景 | 优先级 |
|------|------|------|----------|--------|
| **io_uring** | • 最先进内核接口<br>• 零拷贝<br>• 批量提交<br>• 统一异步接口 | • Linux 5.1+<br>• API 较新 | 现代系统首选 | ⭐⭐⭐⭐⭐ |
| **libaio** | • 内核级支持<br>• 高性能<br>• 成熟稳定 | • 仅支持 O_DIRECT<br>• 即将废弃 | 高性能场景 | ⭐⭐⭐ |
| **线程池模拟** | • 兼容性最好<br>• 实现简单<br>• 跨平台 | • 线程开销<br>• 性能较低 | 备选方案 | ⭐⭐ |

**选型决策**:
```
优先级: io_uring > libaio > 线程池模拟

if (kernel >= 5.1 && has_io_uring) {
    使用 io_uring
} else if (has_libaio) {
    使用 libaio
} else {
    使用线程池模拟
}
```

### 6.3 线程池设计选型

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           线程池架构选型                                            │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  方案 1: 单一线程池 (简单)                                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  统一线程池                                                                   │   │
│  │  • 所有任务共享同一池                                                         │   │
│  │  • 优点: 简单、资源统一管理                                                    │   │
│  │  • 缺点: 无法区分轻重任务、资源竞争                                           │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  方案 2: 分层线程池 (推荐) ✅                                                        │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  Lookup 线程池              Data Transfer 线程池                            │   │
│  │  • 轻量级 MDT 查询          • 重量级数据传输                                 │   │
│  │  • 较少线程 (8)             • 较多线程 (16)                                  │   │
│  │  • 短暂任务                 • 长时间任务                                     │   │
│  │  • 避免 MDT 压力            • 充分利用带宽                                   │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  方案 3: NUMA 感知线程池 (高级)                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  NUMA Node 0              NUMA Node 1                                       │   │
│  │  • 线程绑定本地节点        • 线程绑定本地节点                                │   │
│  │  • 内存本地分配            • 内存本地分配                                    │   │
│  │  • 优点: 最低延迟          • 优点: 负载均衡                                  │   │
│  │  • 缺点: 复杂度高          • 缺点: 配置复杂                                  │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  选型: 方案 2 (分层线程池)                                                           │
│  理由: 平衡复杂度与性能，满足 Lustre 场景需求                                        │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 6.4 配置管理技术选型

| 方案 | 优势 | 劣势 | 推荐场景 |
|------|------|------|----------|
| **YAML** | • 可读性好<br>• 注释支持<br>• 广泛使用 | • 解析稍慢 | 配置文件 ✅ |
| **JSON** | • 解析快<br>• 标准格式 | • 无注释<br>• 可读性差 | 程序接口 |
| **TOML** | • 简洁<br>• 类型友好 | • 生态较小 | 简单配置 |

**选型**: YAML (配置文件) + JSON (程序接口)

### 6.5 日志技术选型

| 方案 | 优势 | 劣势 | 推荐场景 |
|------|------|------|----------|
| **spdlog** | • 高性能<br>• 异步日志<br>• 格式化丰富 | • 额外依赖 | 生产环境 ✅ |
| **glog** | • Google 出品<br>• 功能完善 | • 性能较低 | 已有项目 |
| **自实现** | • 无依赖<br>• 轻量级 | • 功能有限 | 轻量级应用 |

**选型**: spdlog

### 6.6 监控技术选型

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           监控架构                                                  │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  应用层监控                                                                   │   │
│  │  • 计数器: lookupCount, loadCount, dumpCount, errorCount                      │   │
│  │  • 延迟: P50/P95/P99, 总延迟                                                  │   │
│  │  • 资源: 线程池使用率, 队列长度                                                 │   │
│  │  • 业务: 命中率, 冷启动比例                                                     │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                    │                                               │
│                                    ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  指标暴露                                                                     │   │
│  │  • Prometheus Exposer (HTTP /metrics)                                        │   │
│  │  • 文本格式 (OpenMetrics)                                                     │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                    │                                               │
│                                    ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  监控系统集成                                                               │   │
│  │  • Prometheus Server  • Grafana Dashboard  • AlertManager                    │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 6.7 测试技术选型

| 类型 | 工具 | 用途 |
|------|------|------|
| **单元测试** | Google Test | C++ 单元测试 |
| **Mock 框架** | Google Mock | 接口模拟 |
| **集成测试** | pytest + mock | Python 集成测试 |
| **E2E 测试** | pytest + Lustre 环境 | 端到端测试 |
| **性能测试** | fio, 自定义基准 | 性能基准 |
| **内存检查** | Valgrind, ASan | 内存泄漏检测 |
| **覆盖测试** | gcov, lcov | 代码覆盖率 |

---

## 7. 线程池架构设计

### 7.1 分层线程池架构

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         分层线程池架构                                              │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                       Lookup Thread Pool (轻量级)                            │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  配置                                                                  │ │   │
│  │  │  • 并发度: lookup_concurrency (默认: 8)                               │ │   │
│  │  │  • 任务类型: 短暂、I/O 密集型                                          │ │   │
│  │  │  • CPU 亲和性: 可选                                                    │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  任务特点                                                              │ │   │
│  │  │  • 文件存在性检查 (access())                                           │ │   │
│  │  │  • MDT 元数据查询                                                      │ │   │
│  │  │  • 低延迟要求                                                          │ │   │
│  │  │  • 避免压垮 MDT                                                        │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐          │   │
│  │  │ W0  │ │ W1  │ │ W2  │ │ W3  │ │ W4  │ │ W5  │ │ W6  │ │ W7  │          │   │
│  │  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘          │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                    │                                               │
│                                    │ 任务提交                                       │
│                                    ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                    Data Transfer Thread Pool (重量级)                        │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  配置                                                                  │ │   │
│  │  │  • 并发度: data_trans_concurrency (默认: 16)                          │ │   │
│  │  │  • 任务类型: 长时间、大 I/O                                            │ │   │
│  │  │  • CPU 亲和性: 可选                                                    │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  任务特点                                                              │ │   │
│  │  │  • Load 操作 (读取)                                                   │ │   │
│  │  │  • Dump 操作 (写入)                                                   │ │   │
│  │  │  • 高吞吐要求                                                          │ │   │
│  │  │  • 充分利用网络带宽                                                    │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐          │   │
│  │  │ W0  │ │ W1  │ │ W2  │ │ W3  │ │ W4  │ │ W5  │ │ W6  │ │ W7  │          │   │
│  │  ├─────┤ ├─────┤ ├─────┤ ├─────┤ ├─────┤ ├─────┤ ├─────┤ ├─────┤          │   │
│  │  │ W8  │ │ W9  │ │ W10 │ │ W11 │ │ W12 │ │ W13 │ │ W14 │ │ W15 │         │   │
│  │  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘          │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 线程池实现设计

```cpp
namespace UC::LustreStore {

// ===== 任务包装器 =====

template<typename Task>
class ThreadPool {
public:
    // 任务类型
    using Job = std::function<void()>;

    // 构造函数
    // @param numThreads 线程数量
    // @param name 线程池名称 (用于日志)
    // @param cpuAffinity CPU 亲和性列表 (空表示不绑定)
    ThreadPool(size_t numThreads,
               const std::string& name,
               const std::vector<int>& cpuAffinity = {});

    // 析构函数 - 停止线程池
    ~ThreadPool();

    // ===== 任务提交 =====

    // 提交任务
    // @param job 任务函数
    void Submit(Job&& job);

    // 提交任务并返回 future
    // @param func 任务函数
    // @return std::future<decltype(func())> 任务结果
    template<typename F>
    auto SubmitWithFuture(F&& func) -> std::future<decltype(func())>;

    // ===== 控制 =====

    // 停止线程池 (等待当前任务完成)
    void Stop();

    // 立即停止线程池 (丢弃等待中的任务)
    void StopNow();

    // 获取线程数量
    size_t GetThreadCount() const { return threads_.size(); }

    // 获取等待中的任务数量
    size_t GetPendingTaskCount() const;

private:
    // 工作线程函数
    void WorkerThread(size_t index);

    // 设置 CPU 亲和性
    void SetCpuAffinity(size_t index);

private:
    std::vector<std::thread> threads_;       // 工作线程
    std::queue<Job> taskQueue_;              // 任务队列
    std::mutex queueMutex_;                  // 队列互斥锁
    std::condition_variable queueCV_;        // 条件变量
    std::atomic<bool> running_{true};        // 运行标志
    std::string name_;                       // 线程池名称
    std::vector<int> cpuAffinity_;           // CPU 亲和性
};

} // namespace UC::LustreStore
```

### 7.3 CPU 亲和性设计

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         CPU 亲和性设计                                             │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  CPU 亲和性策略                                                               │   │
│  ├─────────────────────────────────────────────────────────────────────────────┤   │
│  │                                                                             │   │
│  │  Policy: COMPACT (紧凑分配)                                                 │   │
│  │  ┌─────────┬─────────┬─────────┬─────────┐                                │   │
│  │  │ CPU 0   │ CPU 1   │ CPU 2   │ CPU 3   │                                │   │
│  │  │ W0,W1   │ W2,W3   │ W4,W5   │ W6,W7   │  线程集中到少数 CPU              │   │
│  │  └─────────┴─────────┴─────────┴─────────┘                                │   │
│  │                                                                             │   │
│  │  Policy: SPREAD (分散分配)                                                 │   │
│  │  ┌─────────┬─────────┬─────────┬─────────┬─────────┬─────────┬─────────┬   │   │
│  │  │ CPU 0   │ CPU 1   │ CPU 2   │ CPU 3   │ CPU 4   │ CPU 5   │ CPU 6   │   │   │
│  │  │ W0      │ W1      │ W2      │ W3      │ W4      │ W5      │ W6      │   │   │
│  │  └─────────┴─────────┴─────────┴─────────┴─────────┴─────────┴─────────┘   │   │
│  │                                                                             │   │
│  │  Policy: NUMA (NUMA 感知)                                                  │   │
│  │  ┌───────────────────────────┐  ┌───────────────────────────┐              │   │
│  │  │ NUMA Node 0              │  │ NUMA Node 1              │              │   │
│  │  │ CPU 0-7                  │  │ CPU 8-15                 │              │   │
│  │  │ W0-W3                    │  │ W4-W7                    │              │   │
│  │  └───────────────────────────┘  └───────────────────────────┘              │   │
│  │                                                                             │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

```cpp
namespace UC::LustreStore {

class CpuAffinityManager {
public:
    // ===== 亲和性策略 =====

    enum class Policy {
        COMPACT,    // 紧凑分配: 线程集中到少数 CPU
        SPREAD,     // 分散分配: 线程均匀分布
        NUMA,       // NUMA 感知: 按 NUMA 节点分配
        CUSTOM      // 自定义: 使用指定 CPU 列表
    };

    // ===== CPU 操作 =====

    // 设置线程 CPU 亲和性
    // @param tid 线程 ID
    // @param cpuList CPU 列表
    // @return Status 操作状态
    static Status SetAffinity(pid_t tid, const std::vector<int>& cpuList);

    // 获取线程 CPU 亲和性
    // @param tid 线程 ID
    // @return std::vector<int> CPU 列表
    static std::vector<int> GetAffinity(pid_t tid);

    // ===== CPU 分配 =====

    // 根据策略分配 CPU
    // @param policy 分配策略
    // @param numThreads 线程数量
    // @param numaNode NUMA 节点 (-1 表示任意)
    // @return std::vector<std::vector<int>> 每个线程的 CPU 列表
    static std::vector<std::vector<int>> AllocateCpus(
        Policy policy,
        size_t numThreads,
        int numaNode = -1);

    // ===== NUMA 操作 =====

    // 获取 NUMA 节点数量
    static int GetNumNumaNodes();

    // 获取指定 NUMA 节点的 CPU 列表
    static std::vector<int> GetNumaCpus(int node);

    // ===== 工具函数 =====

    // 获取系统 CPU 总数
    static int GetCpuCount();

    // 获取当前线程 ID
    static pid_t GetThreadId();
};

} // namespace UC::LustreStore
```

---

## 8. 异步I/O架构

### 8.1 异步I/O分层设计

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         异步 I/O 分层架构                                           │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                        应用层 (LustreFile)                                  │   │
│  │  • 提供同步接口                                                             │   │
│  │  • 内部委托给 AsyncIOAdapter                                                │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                    │                                               │
│                                    ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                     AsyncIOAdapter (抽象层)                                │   │
│  │  • 统一的异步 I/O 接口                                                      │   │
│  │  • 自动选择最佳后端                                                          │   │
│  │  • 提供同步包装方法                                                          │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                    │                                               │
│          ┌─────────────────────────┼─────────────────────────┐                    │
│          ▼                         ▼                         ▼                    │
│  ┌───────────────┐         ┌───────────────┐         ┌───────────────┐           │
│  │ IoUringBackend│         │ LibaioBackend │         │ThreadPoolBack │           │
│  │               │         │               │         │               │           │
│  │ • Linux 5.1+  │         │ • libaio      │         │ • 线程池模拟   │           │
│  │ • 零拷贝       │         │ • O_DIRECT    │         │ • 最大兼容性   │           │
│  │ • 批量提交     │         │ • 高性能      │         │ • 备选方案     │           │
│  │ • SQ/CQ 队列   │         │ • 仅支持 aio  │         │ • POSIX I/O    │           │
│  └───────────────┘         └───────────────┘         └───────────────┘           │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 8.2 io_uring 后端设计

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                        io_uring 架构设计                                           │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         应用空间                                            │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │                     Submission Queue (SQ)                             │ │   │
│  │  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐                      │ │   │
│  │  │  │ SQE │ │ S QE│ │ SQE │ │ SQE │ │ SQE │ │ SQE │ ...                  │ │   │
│  │  │  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘                      │ │   │
│  │  │                                                                   ↑     │ │   │
│  │  │                                                            tail───│     │ │   │
│  │  │                                                            head───│     │ │   │
│  │  └─────────────────────────────────────────────────────────────────────────┘ │   │
│  │                                      │                                       │   │
│  │                                      │ mmap 共享内存                          │   │
│  │                                      │                                       │   │
│  └──────────────────────────────────────┼───────────────────────────────────────┘   │
│                                         │                                          │
│                                         │ 系统调用 (io_uring_enter)               │
│                                         │                                          │
│  ┌──────────────────────────────────────┼───────────────────────────────────────┐   │
│  │                         内核空间  │                                       │   │
│  │                                      ▼                                       │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │                       I/O 处理                                         │ │   │
│  │  │  • 文件系统  • 块设备  • 网络存储                                       │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  │                                      │                                       │   │
│  │                                      ▼                                       │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │                    Completion Queue (CQ)                              │ │   │
│  │  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐                      │ │   │
│  │  │  │ CQE │ │ CQE │ │ CQE │ │ CQE │ │ CQE │ │ CQE │ ...                  │ │   │
│  │  │  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘                      │ │   │
│  │  │                                                                   ↑     │ │   │
│  │  │                                                            tail───│     │ │   │
│  │  │                                                            head───│     │ │   │
│  │  └─────────────────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

```cpp
namespace UC::LustreStore {

class IoUringBackend : public AsyncIOAdapter {
public:
    // ===== 初始化 =====

    Status Setup(size_t queueDepth, int sqThreadCpu = -1) override;

    // ===== I/O 提交 =====

    Status SubmitRead(const IoRequest& req) override;
    Status SubmitWrite(const IoRequest& req) override;

    // ===== 完成处理 =====

    size_t ProcessCompletion(int timeoutMs = 0) override;
    size_t GetPendingCompletions() const override;

    // ===== 同步包装 =====

    Status ReadSync(int fd, void* buffer, size_t size, off64_t offset) override;
    Status WriteSync(int fd, const void* buffer, size_t size, off64_t offset) override;

private:
    // ===== io_uring 数据结构 =====

    struct io_uring ring_;
    size_t queueDepth_;

    // ===== 辅助方法 =====

    Status SubmitIoRequest(const IoRequest& req);
    Status WaitForCompletion(int timeoutMs);
    void HandleCompletion(struct io_uring_cqe* cqe);
};

} // namespace UC::LustreStore
```

### 8.3 异步I/O选择决策树

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                       异步 I/O 后端选择决策树                                       │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  检查内核版本                                                                       │
│  │                                                                                  │
│  ├─内核 >= 5.1?                                                                     │
│  │  │                                                                               │
│  │  ├─是──▶ 检查 io_uring 可用性                                                    │
│  │  │       │                                                                       │
│  │  │       ├─可用──▶ 使用 io_uring (最佳性能) ✅                                   │
│  │  │       │                                                                       │
│  │  │       └─不可用─▶ 继续检查                                                     │
│  │  │                                                                               │
│  │  └─否──▶ 继续检查                                                                │
│  │                                                                                  │
│  ├─检查 libaio 可用性                                                               │
│  │  │                                                                               │
│  │  ├─可用──▶ 使用 libaio (高性能) ✅                                               │
│  │  │       注: 需要 O_DIRECT                                                       │
│  │  │                                                                               │
│  │  └─不可用─▶ 使用线程池模拟 (兼容性) ✅                                            │
│  │                                                                                  │
│  └─运行时降级: 初始化失败时自动切换到下一个可用后端                                  │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. 错误处理机制

### 9.1 错误码体系

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         错误码体系设计                                              │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  UCM 基础错误码 (-50000 ~ -50010)                                            │   │
│  │  • -50000: OK                                                               │   │
│  │  • -50001: InvalidParam                                                      │   │
│  │  • -50002: OsApiError                                                        │   │
│  │  • -50003: DuplicateKey                                                      │   │
│  │  • -50004: NotFound                                                          │   │
│  │  • ...                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  Lustre 扩展错误码 (-50100 ~ -50199)                                         │   │
│  │                                                                               │   │
│  │  配置错误 (-50100 ~ -50109)                                                   │   │
│  │  • -50100: ELUSTRE_CONFIG          通用配置错误                              │   │
│  │  • -50101: ELUSTRE_NO_BACKEND       无可用存储后端                           │   │
│  │  • -50102: ELUSTRE_INVALID_MOUNT    挂载点无效                               │   │
│  │  • -50103: ELUSTRE_INVALID_STRIPE   条带化参数无效                           │   │
│  │                                                                               │   │
│  │  Lustre API 错误 (-50110 ~ -50119)                                           │   │
│  │  • -50110: ELUSTRE_API_FAILED        Lustre API 调用失败                     │   │
│  │  • -50111: ELUSTRE_NO_API            Lustre API 不可用                       │   │
│  │  • -50112: ELUSTRE_STRIPE_FAILED     条带化创建失败                          │   │
│  │                                                                               │   │
│  │  空间错误 (-50120 ~ -50129)                                                    │   │
│  │  • -50120: ELUSTRE_NO_SPACE          OST 空间不足                            │   │
│  │  • -50121: ELUSTRE_QUOTA_EXCEEDED    配额超限                                │   │
│  │  • -50122: ELUSTRE_OST_FULL          特定 OST 已满                            │   │
│  │                                                                               │   │
│  │  I/O 错误 (-50130 ~ -50139)                                                     │   │
│  │  • -50130: ELUSTRE_IO_ERROR           通用 I/O 错误                           │   │
│  │  • -50131: ELUSTRE_READ_FAILED        读操作失败                              │   │
│  │  • -50132: ELUSTRE_WRITE_FAILED       写操作失败                              │   │
│  │  • -50133: ELUSTRE_IO_TIMEOUT         I/O 超时                                │   │
│  │                                                                               │   │
│  │  元数据错误 (-50140 ~ -50149)                                                  │   │
│  │  • -50140: ELUSTRE_MDT_ERROR          MDT 操作失败                            │   │
│  │  • -50141: ELUSTRE_LOOKUP_FAILED     查找操作失败                            │   │
│  │  • -50142: ELUSTRE_MDC_TIMEOUT        MDC 连接超时                            │   │
│  │                                                                               │   │
│  │  连接错误 (-50150 ~ -50159)                                                    │   │
│  │  • -50150: ELUSTRE_NOT_CONNECTED      未连接到 Lustre                         │   │
│  │  • -50151: ELUSTRE_CONNECTION_LOST    连接丢失                                │   │
│  │  • -50152: ELUSTRE_RECOVERING         正在恢复连接                            │   │
│  │                                                                               │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 9.2 错误处理决策树

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                       错误处理决策树                                               │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  错误发生                                                                           │
│  │                                                                                  │
│  ├─错误类型判断                                                                     │
│  │  │                                                                               │
│  │  ├─配置错误? ──▶ 立即返回，不重试                                               │
│  │  │                                                                              │
│  │  ├─权限错误? ──▶ 立即返回，不重试                                               │
│  │  │                                                                              │
│  │  ├─磁盘空间不足? ──▶ 立即返回，不重试                                           │
│  │  │                                                                              │
│  │  ├─Lustre API 失败? ──▶ 降级到 POSIX，不重试                                    │
│  │  │                                                                              │
│  │  ├─I/O 超时? ──▶ 重试 1 次                                                     │
│  │  │                                                                              │
│  │  ├─网络瞬断? ──▶ 重试 3 次，指数退避                                           │
│  │  │                                                                              │
│  │  └─MDT 响应缓慢? ──▶ 降低并发度，重试                                          │
│  │                                                                                  │
│  ├─重试处理                                                                         │
│  │  │                                                                              │
│  │  ├─达到重试上限? ──▶ 标记任务失败                                               │
│  │  │                                                                              │
│  │  └─重试成功? ──▶ 继续处理                                                      │
│  │                                                                                  │
│  └─错误记录                                                                         │
│     │                                                                              │
│     ├─DEBUG: 详细 I/O 操作日志                                                     │
│     ├─INFO: 关键生命周期事件                                                       │
│     ├─WARN: 重试操作、降级操作                                                      │
│     └─ERROR: 所有失败操作                                                          │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 9.3 错误恢复策略

| 错误类型 | 重试策略 | 降级处理 | 日志级别 | 用户通知 |
|----------|----------|----------|----------|----------|
| 网络瞬断 | 3 次，指数退避 | 否 | WARN | 否 |
| OST 空间不足 | 否 | 尝试其他 OST | ERROR | 是 |
| 条带化 API 失败 | 否 | 普通文件创建 | INFO | 否 |
| I/O 超时 | 1 次 | 否 | WARN | 否 |
| 权限拒绝 | 否 | 否 | ERROR | 是 |
| MDT 响应缓慢 | 否 | 降低并发度重试 | WARN | 否 |

---

## 10. 性能优化策略

### 10.1 性能优化概览

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         性能优化策略                                               │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  I/O 优化                                                                     │   │
│  │  • 异步 I/O (io_uring)     • 批量操作     • 预取                              │   │
│  │  • Direct I/O              • 条带化文件   • 大块 I/O                          │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  并发优化                                                                     │   │
│  │  • 分层线程池              • CPU 亲和性   • 任务窃取                          │   │
│  │  • 可配置并发度            • 负载均衡     • 无锁队列                          │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  元数据优化                                                                   │   │
│  │  • 目录分片 (4096 子目录)  • 批量 Lookup • 减少 stat 调用                     │   │
│  │  • MDT 负载分散            • 并发控制     • 缓存文件存在性                    │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  内存优化                                                                     │   │
│  │  • 内存池                  • 对象复用     • 零拷贝                            │   │
│  │  • 预分配缓冲区            • RAII        • 避免频繁分配                      │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 10.2 I/O 优化策略

| 优化项 | 策略 | 预期收益 |
|--------|------|----------|
| **异步 I/O** | 使用 io_uring 替代同步 I/O | 降低 CPU 开销 30-50% |
| **批量操作** | 合并多个小 I/O 为大 I/O | 提高 IOPS 2-5x |
| **预取** | 提前读取后续 Block | 降低延迟 50-80% |
| **Direct I/O** | 绕过页缓存 | 节省内存 20-40% |
| **条带化** | 使用 Lustre 条带化文件 | 提高带宽 3-10x |
| **大块 I/O** | 使用 1MB+ I/O 大小 | 提高吞吐 2-3x |

### 10.3 并发优化策略

| 优化项 | 策略 | 预期收益 |
|--------|------|----------|
| **分层线程池** | Lookup 和 Data Transfer 分离 | 降低延迟 20-30% |
| **CPU 亲和性** | 绑定线程到特定 CPU | 降低 CPU 开销 10-20% |
| **可配置并发度** | 根据 MDT/OSS 能力调整 | 避免过载 |
| **任务窃取** | 工作线程间负载均衡 | 提高 CPU 利用率 10-15% |
| **无锁队列** | 减少锁竞争 | 降低延迟 5-10% |

### 10.4 元数据优化策略

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                       元数据优化 - 目录分片设计                                     │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  无分片 (dataDirShardBytes=0)                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  data/                                                                      │   │
│  │  ├── 0123456789abcdef0123456789abcdef                                       │   │
│  │  ├── abcdef0123456789abcdef012345678                                         │   │
│  │  └── ... (百万级文件)                                                        │   │
│  │                                                                             │   │
│  │  问题: 单目录文件过多，MDT 负载高，查找慢                                      │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  3 级分片 (dataDirShardBytes=3, 推荐) ✅                                           │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  data/                                                                      │   │
│  │  ├── 000/                              │   │
│  │  │   ├── 000/                          │   │
│  │  │   │   ├── 000/                      │   │
│  │  │   │   │   └── ... (每个目录 ~250 文件)                    │   │
│  │  │   │   └── fff/                      │   │
│  │  │   └── fff/                          │   │
│  │  ├── fff/                              │   │
│  │  └── ... (4096 个叶子目录)                                                │   │
│  │                                                                             │   │
│  │  优势: 文件分散，MDT 负载均衡，查找快                                          │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 10.5 性能目标

| 指标 | 目标值 | 测量方法 |
|------|--------|----------|
| 顺序读吞吐量 | > 10GB/s (16 OST) | fio --rw=read --bs=1M |
| 顺序写吞吐量 | > 8GB/s (16 OST) | fio --rw=write --bs=1M |
| 平均 I/O 延迟 | < 1ms (小 I/O) | iostat, 自定义基准 |
| Lookup 延迟 | < 100μs | 自定义基准 |
| 并发 Load QPS | > 10000 | vLLM 集成测试 |
| CPU 利用率 | < 80% (满负载) | top, perf |

---

## 11. 配置管理设计

### 11.1 配置参数结构

```cpp
namespace UC::LustreStore {

struct Config {
    // ===== 必需参数 =====

    // Lustre 挂载路径列表
    std::vector<std::string> storageBackends{};

    // 设备 ID (-1=仅CPU, >=0=GPU/NPU ID)
    int32_t deviceId{-1};

    // ===== 块大小参数 =====

    // 单个 tensor 大小 (字节)
    size_t tensorSize{0};

    // 单个 shard 大小 (字节)
    size_t shardSize{0};

    // 单个 block 大小 (字节)
    size_t blockSize{0};

    // 每个 block 的 shard 数量
    size_t nShardPerBlock{0};

    // 每个 shard 的 tensor 数量
    size_t nTensorPerShard{0};

    // ===== Lustre 特性 =====

    // V1: 使用系统默认条带配置
    // stripe_count = -1 (由 Lustre FS 自动管理)
    // stripe_size = 0 (使用系统默认值)

    // ===== I/O 优化 =====

    // Direct I/O 标志
    bool ioDirect{false};

    // 数据传输并发度
    size_t dataTransConcurrency{16};

    // 查找并发度
    size_t lookupConcurrency{8};

    // 操作超时 (毫秒)
    size_t timeoutMs{30000};

    // ===== 目录布局 =====

    // 目录分片层级 (0-3)
    // 0 = 单目录 "data/"
    // 1 = 16 个子目录 "data/0/" ~ "data/f/"
    // 2 = 256 个子目录 "data/00/" ~ "data/ff/"
    // 3 = 4096 个子目录 "data/000/" ~ "data/fff/" [推荐]
    size_t dataDirShardBytes{3};

    // ===== CPU 亲和性 =====

    // CPU 亲和性策略
    enum class CpuAffinityPolicy {
        NONE,       // 不绑定
        COMPACT,    // 紧凑分配
        SPREAD,     // 分散分配
        NUMA        // NUMA 感知
    };
    CpuAffinityPolicy cpuAffinityPolicy{CpuAffinityPolicy::NONE};

    // 自定义 CPU 列表 (policy=CUSTOM 时使用)
    std::vector<int> customCpuList{};

    // NUMA 节点 (policy=NUMA 时使用)
    int numaNode{-1};

    // ===== 异步 I/O =====

    // 异步 I/O 后端选择
    enum class AsyncIOBackend {
        AUTO,       // 自动选择
        IO_URING,   // io_uring
        LIBAIO,     // libaio
        THREADPOOL  // 线程池模拟
    };
    AsyncIOBackend asyncIOBackend{AsyncIOBackend::AUTO};

    // io_uring 队列深度
    size_t ioUringQueueDepth{256};

    // ===== 监控 =====

    // 是否启用性能监控
    bool enableMetrics{true};

    // 监控指标导出端口
    int metricsPort{9090};

    // ===== 验证 =====

    // 验证配置有效性
    Status Validate() const;
};

} // namespace UC::LustreStore
```

### 11.2 YAML 配置示例

```yaml
# 基础配置
ucm_connectors:
  - ucm_connector_name: "UcmPipelineStore"
    ucm_connector_config:
      # 存储管道配置
      store_pipeline: "Lustre"  # 或 "Cache|Lustre"

      # ===== 必需参数 =====
      storage_backends: ["/mnt/lustre"]
      device_id: -1  # -1=仅CPU, 0+=GPU/NPU ID
      block_size: 4194304  # 4MB

      # ===== 可选参数 =====
      tensor_size: 1024
      shard_size: 1048576  # 1MB
      n_shard_per_block: 4
      n_tensor_per_shard: 1024

      # ===== I/O 优化 =====
      io_direct: false  # Direct I/O (默认: 关闭)
      lustre_data_trans_concurrency: 16  # 数据传输并发数
      lustre_lookup_concurrency: 8  # 查找并发数
      timeout_ms: 30000  # 操作超时 (毫秒)

      # ===== 目录布局 =====
      data_dir_shard_bytes: 3  # 目录分片层级: 0=无分片, 3=4096子目录(推荐)

      # ===== CPU 亲和性 =====
      cpu_affinity_policy: "NONE"  # NONE, COMPACT, SPREAD, NUMA
      # numa_node: 0  # policy=NUMA 时指定

      # ===== 异步 I/O =====
      async_io_backend: "AUTO"  # AUTO, IO_URING, LIBAIO, THREADPOOL
      io_uring_queue_depth: 256

      # ===== 监控 =====
      enable_metrics: true
      metrics_port: 9090

# 高级配置示例
ucm_connectors:
  - ucm_connector_name: "UcmPipelineStore"
    ucm_connector_config:
      store_pipeline: "Cache|Lustre"  # 先 Cache，后 Lustre

      storage_backends:
        - "/mnt/lustre/fs1"
        - "/mnt/lustre/fs2"  # 多路径负载均衡

      device_id: 0  # GPU 0

      # 性能调优
      io_direct: true  # 启用 Direct I/O
      lustre_data_trans_concurrency: 32  # 高并发
      lustre_lookup_concurrency: 16

      # CPU 亲和性
      cpu_affinity_policy: "COMPACT"
      custom_cpu_list: [0, 1, 2, 3, 4, 5, 6, 7]

      # 异步 I/O
      async_io_backend: "IO_URING"
      io_uring_queue_depth: 512

      # 监控
      enable_metrics: true
      metrics_port: 9090
```

### 11.3 配置验证规则

```cpp
namespace UC::LustreStore {

Status Config::Validate() const {
    // 必需参数检查
    if (storageBackends.empty()) {
        return Status::InvalidParam("storage_backends is required");
    }

    // 路径有效性检查
    for (const auto& path : storageBackends) {
        if (path.empty()) {
            return Status::InvalidParam("storage_backend path cannot be empty");
        }
    }

    // 块大小一致性检查
    if (blockSize > 0 && shardSize > 0 && nShardPerBlock > 0) {
        if (blockSize != shardSize * nShardPerBlock) {
            return Status::InvalidParam(
                "blockSize must equal shardSize * nShardPerBlock");
        }
    }

    // 目录分片层级检查
    if (dataDirShardBytes > 3) {
        return Status::InvalidParam(
            "dataDirShardBytes must be <= 3");
    }

    // 并发度检查
    if (dataTransConcurrency == 0) {
        return Status::InvalidParam(
            "dataTransConcurrency must be > 0");
    }

    if (lookupConcurrency == 0) {
        return Status::InvalidParam(
            "lookupConcurrency must be > 0");
    }

    // 超时检查
    if (timeoutMs == 0) {
        return Status::InvalidParam(
            "timeoutMs must be > 0");
    }

    return Status::OK();
}

} // namespace UC::LustreStore
```

---

## 12. 监控与可观测性

### 12.1 监控指标体系

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         监控指标体系                                               │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  性能指标 (Performance Metrics)                                             │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  延迟指标                                                               │ │   │
│  │  │  • lookup_latency_p50/p95/p99      Lookup 操作延迟百分位             │ │   │
│  │  │  • load_latency_p50/p95/p99        Load 操作延迟百分位               │ │   │
│  │  │  • dump_latency_p50/p95/p99        Dump 操作延迟百分位               │ │   │
│  │  │  • io_latency_avg                  平均 I/O 延迟                       │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  吞吐指标                                                               │ │   │
│  │  │  • read_bytes_per_second            每秒读取字节数                     │ │   │
│  │  │  • write_bytes_per_second           每秒写入字节数                     │ │   │
│  │  │  • read_ops_per_second              每秒读操作数                       │ │   │
│  │  │  • write_ops_per_second             每秒写操作数                       │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  业务指标 (Business Metrics)                                               │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  计数器                                                                 │ │   │
│  │  │  • lookup_count_total              总 Lookup 次数                     │ │   │
│  │  │  • lookup_hit_count                Lookup 命中次数                     │   │
│  │  │  • load_count_total                总 Load 次数                       │   │
│  │  │  • dump_count_total                总 Dump 次数                       │ │   │
│  │  │  • block_cache_hit_ratio           Block 缓存命中率                   │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  资源指标 (Resource Metrics)                                                │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  线程池                                                                 │ │   │
│  │  │  • lookup_pool_active_threads        Lookup 线程池活跃线程数           │ │   │
│  │  │  • transfer_pool_active_threads     Transfer 线程池活跃线程数          │ │   │
│  │  │  • lookup_pool_queue_depth          Lookup 队列深度                    │ │   │
│  │  │  • transfer_pool_queue_depth        Transfer 队列深度                  │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  文件系统                                                               │ │   │
│  │  │  • open_files                       打开文件数                         │ │   │
│  │  │  • temp_files                       临时文件数                         │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  错误指标 (Error Metrics)                                                   │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  错误计数                                                               │ │   │
│  │  │  • error_count_total                 总错误数                           │ │   │
│  │  │  • io_error_count                   I/O 错误数                         │ │   │
│  │  │  • lustre_api_error_count           Lustre API 错误数                 │ │   │
│  │  │  • timeout_count                    超时次数                           │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  错误分布                                                               │ │   │
│  │  │  • error_by_code{code="..."}      按错误码统计                        │ │   │
│  │  │  • error_by_operation{op="..."}    按操作类型统计                      │ │   │
│  │  └───────────────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 12.2 Prometheus 指标定义

```cpp
namespace UC::LustreStore {

class LustreStoreMetrics {
public:
    // ===== 性能指标 =====

    // Lookup 延迟直方图
    Histogram lookupLatency{
        "ucm_lustre_lookup_latency_seconds",
        "Lookup operation latency",
        Buckets{0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1}
    };

    // Load 延迟直方图
    Histogram loadLatency{
        "ucm_lustre_load_latency_seconds",
        "Load operation latency",
        Buckets{0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0}
    };

    // Dump 延迟直方图
    Histogram dumpLatency{
        "ucm_lustre_dump_latency_seconds",
        "Dump operation latency",
        Buckets{0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0}
    };

    // ===== 业务指标 =====

    // Lookup 计数器
    Counter lookupCount{
        "ucm_lustre_lookup_total",
        "Total number of lookup operations"
    };

    // Lookup 命中计数器
    Counter lookupHitCount{
        "ucm_lustre_lookup_hit_total",
        "Total number of lookup hits"
    };

    // Load 计数器
    Counter loadCount{
        "ucm_lustre_load_total",
        "Total number of load operations"
    };

    // Dump 计数器
    Counter dumpCount{
        "ucm_lustre_dump_total",
        "Total number of dump operations"
    };

    // Block 大小直方图
    Histogram blockSize{
        "ucm_lustre_block_size_bytes",
        "Block size in bytes",
        Buckets{1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216}
    };

    // ===== 资源指标 =====

    // 线程池活跃线程
    Gauge activeThreads{
        "ucm_lustre_active_threads",
        "Number of active threads",
        Labels{{"pool", "lookup"}, {"pool", "transfer"}}
    };

    // 队列深度
    Gauge queueDepth{
        "ucm_lustre_queue_depth",
        "Queue depth",
        Labels{{"queue", "lookup"}, {"queue", "transfer"}}
    };

    // 打开文件数
    Gauge openFiles{
        "ucm_lustre_open_files",
        "Number of open files"
    };

    // 临时文件数
    Gauge tempFiles{
        "ucm_lustre_temp_files",
        "Number of temporary files"
    };

    // ===== 错误指标 =====

    // 错误计数器
    Counter errorCount{
        "ucm_lustre_errors_total",
        "Total number of errors",
        Labels{
            {"code", "io_error"},
            {"code", "timeout"},
            {"code", "lustre_api_failed"},
            {"code", "no_space"}
        }
    };

    // 操作失败计数器
    Counter operationFailures{
        "ucm_lustre_operation_failures_total",
        "Total number of operation failures",
        Labels{{"operation", "lookup"}, {"operation", "load"}, {"operation", "dump"}}
    };

    // ===== 导出接口 =====

    // 收集所有指标
    std::string Collect() const;

    // 导出到 Prometheus 格式
    std::string ExportPrometheus() const;
};

} // namespace UC::LustreStore
```

### 12.3 日志规范

```cpp
// 日志级别使用规范
namespace UC::LustreStore {

// DEBUG: 详细的 I/O 操作日志 (调试模式)
UC_DEBUG("LustreFile::Read fd={} offset={} size={}", fd_, offset, size);

// INFO: 关键生命周期事件
UC_INFO("LustreStore initialized with backend={}", config_.storageBackends[0]);
UC_INFO("Block {} dumped successfully", BlockIdToString(blockId));

// WARN: 需要关注的事件
UC_WARN("Lustre API failed, falling back to POSIX: {}", error_msg);
UC_WARN("Retry {} after timeout: attempt {}", operation_name, retry_count);

// ERROR: 需要处理的错误
UC_ERROR("Failed to dump block {}: {}", BlockIdToString(blockId), status.ToString());
UC_ERROR("OST space exhausted, cannot dump block {}", BlockIdToString(blockId));

} // namespace UC::LustreStore
```

---

## 附录 A: 术语表

| 术语 | 定义 |
|------|------|
| **Block** | 一个完整的 KV Cache 块，包含多个 Shard |
| **Shard** | Block 的分片，对应一个 Transformer Layer |
| **Tensor** | 每层的键值对数据张量 |
| **BlockId** | 16 字节标识符，取自 SHA-256 哈希值的前 16 字节 |
| **MDT** | Metadata Target，Lustre 元数据服务器 |
| **OST** | Object Storage Target，Lustre 对象存储目标 |
| **OSS** | Object Storage Server，Lustre 对象存储服务器 |
| **H2S** | Host to Storage，写入操作 |
| **S2H** | Storage to Host，读取操作 |

---

## 附录 B: 配置参数速查表

| YAML 参数 | C++ 成员 | 类型 | 默认值 | 说明 |
|-----------|----------|------|--------|------|
| `storage_backends` | `storageBackends` | vector<string> | 必需 | Lustre 挂载路径 |
| `device_id` | `deviceId` | int32_t | -1 | 设备 ID |
| `block_size` | `blockSize` | size_t | 0 | Block 大小 |
| `tensor_size` | `tensorSize` | size_t | 0 | Tensor 大小 |
| `shard_size` | `shardSize` | size_t | 0 | Shard 大小 |
| `io_direct` | `ioDirect` | bool | false | Direct I/O |
| `lustre_data_trans_concurrency` | `dataTransConcurrency` | size_t | 16 | 数据传输并发度 |
| `lustre_lookup_concurrency` | `lookupConcurrency` | size_t | 8 | 查找并发度 |
| `timeout_ms` | `timeoutMs` | size_t | 30000 | 超时时间 (毫秒) |
| `data_dir_shard_bytes` | `dataDirShardBytes` | size_t | 3 | 目录分片层级 (0-3) |

---

## 附录 C: 文件清单

| 文件 | 组件 | 类型 | 说明 |
|------|------|------|------|
| `lustre_store.h/cc` | LustreStore | 接口+实现 | StoreV1 接口实现 |
| `space_layout.h/cc` | SpaceLayout | 组件 | 空间布局管理 |
| `space_manager.h/cc` | SpaceManager | 组件 | 空间查找管理 |
| `trans_queue.h/cc` | TransQueue | 组件 | 传输队列 |
| `trans_manager.h/cc` | TransManager | 组件 | 传输管理 |
| `trans_task.h` | TransTask | 数据 | 任务定义 |
| `lustre_file.h/cc` | LustreFile | 组件 | 文件操作 |
| `async_io_adapter.h` | AsyncIOAdapter | 抽象 | 异步 I/O 适配器 |
| `io_uring_backend.h/cc` | IoUringBackend | 后端 | io_uring 实现 |
| `libaio_backend.h/cc` | LibaioBackend | 后端 | libaio 实现 |
| `thread_pool_backend.h/cc` | ThreadPoolBackend | 后端 | 线程池实现 |
| `config.h` | Config | 配置 | 配置定义 |
| `metrics.h` | Metrics | 监控 | 监控指标 |

---

**文档结束**
