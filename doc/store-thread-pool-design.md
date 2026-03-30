# Store 线程池设计与实现

本文档详细描述 UCM 中各种 Store 后端的线程池实现设计和对比。

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

## 四种 Store 线程池实现对比

### 总览对比表

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

### 1. PosixStore

#### 线程池定义

```cpp
// trans_queue.h
ThreadPool<IoUnit> pool_;  // 数据传输线程池

// space_manager.h
ThreadPool<LookupContext> lookupSrv_;  // 查找线程池
```

#### Task 类型: IoUnit

```cpp
struct IoUnit {
    Detail::TaskHandle owner;      // 任务归属ID
    TransTask::Type type;          // LOAD 或 DUMP
    Detail::Shard shard;           // 分片数据
    std::shared_ptr<Latch> waiter; // 完成等待器
    bool firstIo{false};           // 是否是首个IoUnit
};
```

#### WorkerArgs 类型: void*

```cpp
// 无额外 Worker 上下文
ThreadPool<IoUnit> pool_;  // WorkerArgs = void* (默认)
```

#### 数据流

```
┌─────────────────┐
│   Host Memory    │
└────────┬────────┘
         │
         │ pool_ (Worker)
         │ pread/pwrite 系统调用
         ▼
┌─────────────────┐
│    Storage       │
│ (本地磁盘/NFS)   │
└─────────────────┘
```

---

### 2. Ds3fsStore

#### 线程池定义

```cpp
// trans_queue.h:157
ThreadPool<IoUnit, std::unique_ptr<WorkerContext>> pool_;
```

#### Task 类型: IoUnit

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

#### WorkerArgs 类型: WorkerContext

```cpp
struct WorkerContext {
    IovGuard iov;       // I/O缓冲区
    IorGuard iorRead;   // 异步读队列
    IorGuard iorWrite;  // 异步写队列
    bool initialized;   // 是否初始化
};
```

**作用:** 每个工作线程拥有独立的 hf3fs 用户态 I/O 资源（IOV/IOR）

#### 数据流

```
┌─────────────────┐
│   Host Memory    │
└────────┬────────┘
         │
         │ pool_ (Worker + WorkerContext)
         │ hf3fs 用户态 I/O API
         ▼
┌─────────────────┐
│    DS3FS         │
│  (分布式存储)     │
└─────────────────┘
```

---

### 3. NFSStore

#### 线程池定义

```cpp
// posix_queue.h:44
ThreadPool<Task::Shard, Device> backend_{};
```

#### Task 类型: Task::Shard

```cpp
struct Shard {
    Detail::TaskHandle owner;    // 任务归属ID
    std::string block;           // Block ID
    size_t offset;               // 偏移量
    uintptr_t address;           // 数据地址
    size_t length;               // 数据长度
    Task::Type type;             // LOAD 或 DUMP
    Task::Location location;     // DEVICE 或 HOST
    std::shared_ptr<std::byte> buffer;  // 缓冲区
    std::function<void()> done;  // 完成回调
};
```

#### WorkerArgs 类型: Device

```cpp
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

#### 架构特点

```
┌─────────────────────────────────────────────────────────────────┐
│                      TransManager                            │
│  queues_: vector<shared_ptr<PosixQueue>>              │
│  每个队列包含独立的 ThreadPool + Device               │
└──────────────────────────┬──────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
    │ PosixQueue 0│ │ PosixQueue 1│ │ PosixQueue N│
    │             │ │             │ │             │
    │ ThreadPool │ │ ThreadPool │ │ ThreadPool │
    │ <Shard,     │ │ <Shard,     │ │ <Shard,     │
    │  Device>    │ │  Device>    │ │  Device>    │
    └─────────────┘ └─────────────┘ └─────────────┘
```

---

### 4. PcStore

#### 线程池定义

```cpp
// trans_queue.h:69-70
ThreadPool<BlockTask> devPool_;   // Device 线程池
ThreadPool<BlockTask> filePool_;  // File 线程池
```

#### Task 类型: BlockTask

```cpp
struct BlockTask {
    size_t owner;                      // 任务归属ID
    std::string block;                 // Block ID
    TransTask::Type type;              // LOAD 或 DUMP
    std::vector<uintptr_t> shards;     // 数据地址列表
    std::shared_ptr<void> buffer;      // 缓冲区
    std::function<void(bool)> done;    // 完成回调
};
```

#### WorkerArgs 类型: void*

```cpp
// 两个线程池都不使用 WorkerArgs
ThreadPool<BlockTask> devPool_;   // WorkerArgs = void*
ThreadPool<BlockTask> filePool_;  // WorkerArgs = void*
```

#### 数据流

```
┌─────────────────┐
│   GPU Device    │
│  (CUDA/Ascend)  │
└────────┬────────┘
         │
         │ devPool_ (DeviceWorker)
         │ 使用 Trans::Stream 进行异步传输
         ▼
┌─────────────────┐
│   Host Memory   │
│   (pinned)       │
└────────┬────────┘
         │
         │ filePool_ (FileWorker)
         │ 使用 POSIX I/O 写入文件
         ▼
┌─────────────────┐
│    Storage       │
│ (SSD/NFS/Disk)  │
└─────────────────┘
```

---

## 设计选择总结

| Store | 线程池设计 | 设计原因 |
|-------|-----------|----------|
| **PosixStore** | 2个独立池 | 分离 I/O 和查找，避免阻塞 |
| **Ds3fsStore** | 1个池 + WorkerContext | hf3fs 需要每个线程独立的 I/O 资源 |
| **NFSStore** | N个队列 + Device | 支持多种硬件加速器，每队列独立设备 |
| **PcStore** | 2个池分离 | Device 传输和 File I/O 流水线处理 |

---

## Lustre Store 条带化优化设计

### Lustre 条带化原理

```
┌─────────────────────────────────────────────────────────────────┐
│                        Lustre 文件系统                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    MDS (元数据服务器)                      │   │
│  │              管理文件布局和条带配置                        │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                      │
│                           ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    客户端缓存                            │   │
│  │              页缓存、预读、回写                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                      │
│           ┌───────────────┼───────────────┐                    │
│           ▼               ▼               ▼                    │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐              │
│  │   OST 0     │ │   OST 1     │ │   OST N     │              │
│  │ (存储目标)   │ │ (存储目标)   │ │ (存储目标)   │              │
│  │  条带 0     │ │  条带 1     │ │  条带 N     │              │
│  │  条带 3     │ │  条带 4     │ │  条带 7     │              │
│  │  ...        │ │  ...        │ │  ...        │              │
│  └─────────────┘ └─────────────┘ └─────────────┘              │
└─────────────────────────────────────────────────────────────────┘

文件被条带化到多个 OST，可以并行读写
```

---

### 优化设计：条带感知的线程池

```cpp
// lustre/cc/trans_queue.h
class TransQueue {
private:
    // 基本I/O单元
    struct IoUnit {
        Detail::TaskHandle owner;
        TransTask::Type type;
        Detail::Shard shard;
        std::shared_ptr<Latch> waiter;
        bool firstIo{false};
    };
    
    // 条带化I/O单元 - 用于并行条带写入
    struct StripeIoUnit {
        Detail::TaskHandle owner;
        int fd;
        size_t offset;
        size_t size;
        void* buffer;
        int stripeIndex;
        std::shared_ptr<Latch> waiter;
    };

    ThreadPool<IoUnit> pool_;           // 主I/O线程池
    ThreadPool<StripeIoUnit> stripePool_;  // 条带化并行I/O线程池
    
    bool stripeIoEnable_{false};        // 是否启用条带化并行I/O
    int stripeCount_{0};                // 条带数量
    size_t stripeSize_{0};              // 条带大小
};
```

---

### 条带化并行写入实现

```cpp
Status TransQueue::H2S(IoUnit& ios) {
    if (stripeIoEnable_ && stripeCount_ > 1) {
        // 使用条带化并行写入
        return H2SParallelStripe(ios);
    } else {
        // 回退到顺序写入
        return H2SSequential(ios);
    }
}

Status TransQueue::H2SParallelStripe(IoUnit& ios) {
    const auto& path = layout_->DataFilePath(ios.shard.owner, true);
    PosixFile file{path};
    
    auto s = file.Open(PosixFile::OpenFlag::CREATE | PosixFile::OpenFlag::WRITE_ONLY);
    if (s.Failure()) return s;
    
    int fd = file.ReleaseHandle();
    
    // 为每个条带创建并行I/O任务
    std::vector<StripeIoUnit> stripeIos;
    for (int i = 0; i < stripeCount_; i++) {
        stripeIos.push_back({
            ios.owner, fd,
            CalcStripeOffset(shardSize_ * ios.shard.index, i),
            ioSize_,
            (void*)ios.shard.addrs[i],
            i,
            ios.waiter
        });
    }
    
    // 设置等待计数
    ios.waiter->Set(stripeCount_);
    
    // 提交到条带化线程池
    stripePool_.Push(stripeIos);
    
    return Status::OK();
}

// 条带化工作线程
void TransQueue::StripeWorker(StripeIoUnit& ios) {
    ssize_t nBytes = pwrite(ios.fd, ios.buffer, ios.size, ios.offset);
    
    if (nBytes != static_cast<ssize_t>(ios.size)) {
        failureSet_->Insert(ios.owner);
    }
    
    ios.waiter->Done();
}

// 计算条带偏移
size_t TransQueue::CalcStripeOffset(size_t fileOffset, int stripeIndex) {
    // Lustre 条带化布局计算
    // stripe_offset = stripe_size * (file_offset / (stripe_size * stripe_count)) * stripe_count
    //              + stripe_size * stripe_index + (file_offset % stripe_size)
    size_t stripeIndex = (fileOffset / stripeSize_) % stripeCount_;
    size_t stripeBase = fileOffset / (stripeSize_ * stripeCount_) * stripeSize_ * stripeCount_;
    
    return stripeBase + stripeSize_ * stripeIndex + (fileOffset % stripeSize_);
}
```

---

### 配置参数扩展

```cpp
// lustre/cc/global_config.h
struct Config {
    std::vector<std::string> storageBackends;
    size_t blockSize{0};
    size_t shardSize{0};
    size_t tensorSize{0};
    bool ioDirect{false};
    size_t dataTransConcurrency{8};
    size_t timeoutMs{30000};
    size_t dataDirShardBytes{3};
    
    // Lustre 条带化参数
    bool stripeIoEnable{true};           // 是否启用条带化并行I/O
    int stripeCount{0};                  // 条带数量（0=自动检测）
    size_t stripeSize{0};                // 条带大小（0=自动检测）
};
```

---

### 性能对比

| 场景 | 顺序I/O | 条带化并行I/O |
|------|---------|--------------|
| **单OST** | 基准 | 相同 |
| **4 OST** | 1x | ~4x |
| **8 OST** | 1x | ~8x |
| **大文件** | 慢 | 快 |

---

### 使用建议

1. **自动检测** - 默认启用，自动检测条带化配置
2. **手动配置** - 可通过配置文件指定条带参数
3. **回退机制** - 检测失败时自动回退到顺序I/O
4. **性能监控** - 添加条带化I/O的性能指标

---

## 参考资料

- [ThreadPool 模板类实现](../../../shared/infra/thread/thread_pool.h)
- [PosixStore 实现](../../../store/posix/cc/trans_queue.h)
- [Ds3fsStore 实现](../../../store/ds3fs/cc/trans_queue.h)
- [NFSStore 实现](../../../store/nfsstore/cc/domain/trans/posix_queue.h)
- [PcStore 实现](../../../store/pcstore/cc/domain/trans/trans_queue.h)
