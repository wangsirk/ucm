# 四种 Store 线程池实现对比

本文档详细对比 UCM 中四种主要 Store 后端的线程池实现设计。

## 概述

UCM 定义了一个通用的线程池模板基类 [`ThreadPool<Task, WorkerArgs>`](../../shared/infra/thread/thread_pool.h)，各 Store 后端根据自身需求进行特化实现。

## 通用线程池模板

```cpp
template <class Task, class WorkerArgs = void*>
class ThreadPool {
    using WorkerInitFn = std::function<bool(WorkerArgs&)>;
    using WorkerFn = std::function<void(Task&, const WorkerArgs&)>;
    using WorkerTimeoutFn = std::function<void(Task&, const ssize_t)>;
    using WorkerExitFn = std::function<void(WorkerArgs&)>;
    // ...
};
```

### 关键回调函数

| 回调 | 说明 | 典型用途 |
|------|------|---------|
| `WorkerInitFn` | 线程初始化 | 创建设备上下文、分配资源 |
| `WorkerFn` | 任务处理 | 执行实际I/O操作 |
| `WorkerTimeoutFn` | 超时处理 | 清理超时任务 |
| `WorkerExitFn` | 线程退出 | 释放资源 |

---

---

## 总览对比表

| 特性 | PosixStore | Ds3fsStore | NFSStore | PcStore |
|------|-----------|------------|----------|---------|
| **线程池数量** | 2 (Trans + Lookup) | 1 (Trans) | N (多个PosixQueue) | 2 (dev + file) |
| **Task 类型** | `IoUnit` | `IoUnit` | `Task::Shard` | `BlockTask` |
| **WorkerArgs 类型** | `void*` | `WorkerContext` | `Device` | `void*` |
| **设备支持** | 无 | hf3fs 用户态I/O | CUDA/Ascend/MUSA | CUDA/Ascend |
| **查找方式** | 并行(线程池) | 同步串行 | 同步串行 | 同步串行 |
| **Host传输** | 支持 | 支持 | 支持 | 支持 |
| **Device传输** | 不支持 | 不支持 | 支持 | 支持 |

---

## 1. PosixStore

### 线程池定义

```cpp
// trans_queue.h
ThreadPool<IoUnit> pool_;  // 数据传输线程池

// space_manager.h
ThreadPool<LookupContext> lookupSrv_;  // 查找线程池
```

### Task 类型: IoUnit

```cpp
// trans_queue.h:46
struct IoUnit {
    Detail::TaskHandle owner;      // 任务归属ID
    TransTask::Type type;          // LOAD 或 DUMP
    Detail::Shard shard;           // 分片数据
    std::shared_ptr<Latch> waiter; // 完成等待器
    bool firstIo{false};           // 是否是首个IoUnit
};
```

### WorkerArgs 类型: void*

```cpp
// 无额外 Worker 上下文
ThreadPool<IoUnit> pool_;  // WorkerArgs = void* (默认)
```

---

## 2. Ds3fsStore

### 线程池定义

```cpp
// trans_queue.h:157
ThreadPool<IoUnit, std::unique_ptr<WorkerContext>> pool_;
```

### Task 类型: IoUnit

```cpp
// 与 PosixStore 相同
struct IoUnit {
    Detail::TaskHandle owner;
    TransTask::Type type;
    Detail::Shard shard;
    std::shared_ptr<Latch> waiter;
    bool firstIo{false};
};
```

### WorkerArgs 类型: WorkerContext

```cpp
// trans_queue.h:131
struct WorkerContext {
    IovGuard iov;       // I/O 缓冲区 (hf3fs_iov)
    IorGuard iorRead;   // 异步读队列 (hf3fs_ior)
    IorGuard iorWrite;  // 异步写队列 (hf3fs_ior)
    bool initialized;   // 是否初始化
};
```

**作用**: 每个 Worker 拥有独立的 hf3fs 用户态 I/O 资源

---

## 3. NFSStore

### 线程池定义

```cpp
// posix_queue.h:44
ThreadPool<Task::Shard, Device> backend_{};

// trans_manager.h - 多个 PosixQueue
std::vector<std::shared_ptr<PosixQueue>> queues_;
```

### Task 类型: Task::Shard

```cpp
// 来自 ucmstore.h
struct Shard {
    TaskHandle owner;          // 任务归属ID
    std::string block;         // Block ID
    size_t offset;             // 偏移量
    uintptr_t address;         // 数据地址
    size_t length;             // 数据长度
    Type type;                 // LOAD 或 DUMP
    Location location;         // DEVICE 或 HOST
    std::function<void()> done; // 完成回调
    std::shared_ptr<void> buffer; // 缓冲区
};
```

### WorkerArgs 类型: Device

```cpp
// posix_queue.h:37
using Device = std::unique_ptr<IDevice>;

// IDevice 接口
class IDevice {
    virtual Status H2DSync(...) = 0;   // Host → Device 同步
    virtual Status D2HSync(...) = 0;   // Device → Host 同步
    virtual Status H2DAsync(...) = 0;  // Host → Device 异步
    virtual Status D2HAsync(...) = 0;  // Device → Host 异步
    virtual Status Synchronized() = 0;  // 同步等待
};

// 实现类: SimuDevice, CudaDevice, AscendDevice, MusaDevice
```

---

## 4. PcStore

### 线程池定义

```cpp
// trans_queue.h:69-70
ThreadPool<BlockTask> devPool_;   // Device 线程池
ThreadPool<BlockTask> filePool_;  // File 线程池
```

### Task 类型: BlockTask

```cpp
// trans_queue.h:40
struct BlockTask {
    size_t owner;                      // 任务归属ID
    std::string block;                 // Block ID
    TransTask::Type type;              // LOAD 或 DUMP
    std::vector<uintptr_t> shards;     // 数据地址列表
    std::shared_ptr<void> buffer;      // 缓冲区
    std::function<void(bool)> done;    // 完成回调
};
```

### WorkerArgs 类型: void*

```cpp
// 两个线程池都不使用 WorkerArgs
ThreadPool<BlockTask> devPool_;   // WorkerArgs = void*
ThreadPool<BlockTask> filePool_;  // WorkerArgs = void*
```

---

## 架构对比图

### PosixStore

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PosixStore                                      │
│  ┌─────────────────────┐    ┌─────────────────────┐                        │
│  │   TransQueue         │    │   SpaceManager       │                        │
│  │   ThreadPool<IoUnit> │    │   ThreadPool<        │                        │
│  │                     │    │   LookupContext>     │                        │
│  └─────────────────────┘    └─────────────────────┘                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Ds3fsStore

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Ds3fsStore                                      │
│  ┌─────────────────────────────────────────────────────┐                    │
│  │   TransQueue                                         │                    │
│  │   ThreadPool<IoUnit, unique_ptr<WorkerContext>>     │                    │
│  │   每个 Worker 拥有独立的 IOV/IOR                     │                    │
│  └─────────────────────────────────────────────────────┘                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### NFSStore

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              NFSStore                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │   TransManager                                                       │    │
│  │   ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                    │    │
│  │   │ PosixQueue 0│ │ PosixQueue 1│ │ PosixQueue N│                    │    │
│  │   │ ThreadPool< │ │ ThreadPool< │ │ ThreadPool< │                    │    │
│  │   │ Shard,Device>│ │Shard,Device>│ │Shard,Device>│                    │    │
│  │   └─────────────┘ └─────────────┘ └─────────────┘                    │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### PcStore

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PcStore                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │   TransQueue                                                         │    │
│  │   ┌─────────────────────┐    ┌─────────────────────┐                │    │
│  │   │ devPool_             │    │ filePool_            │                │    │
│  │   │ ThreadPool<BlockTask>│    │ ThreadPool<BlockTask>│                │    │
│  │   │ Device ↔ Host       │    │ Host ↔ Storage      │                │    │
│  │   └─────────────────────┘    └─────────────────────┘                │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 设计选择总结

| Store | 线程池设计 | 设计原因 |
|-------|-----------|---------|
| PosixStore | 2个独立池 | 分离 I/O 和查找，避免阻塞 |
| Ds3fsStore | 1个池 + WorkerContext | hf3fs 需要每个线程独立的 I/O 资源 |
| NFSStore | N个队列 + Device | 支持多种硬件加速器，每队列独立设备 |
| PcStore | 2个池分离 | Device 传输和 File I/O 流水线处理 |
