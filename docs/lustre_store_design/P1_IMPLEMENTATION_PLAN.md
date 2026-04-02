# Lustre Store P1 阶段实施计划

**计划日期**: 2026-04-01
**阶段**: P1 - 数据传输核心
**预计工期**: 2 周 (Week 3-4)
**依赖**: P0 阶段已完成 ✅

---

## 目录

1. [阶段概述](#1-阶段概述)
2. [P1 阶段目标](#2-p1-阶段目标)
3. [实施前置条件](#3-实施前置条件)
4. [任务分解](#4-任务分解)
5. [技术实施细节](#5-技术实施细节)
6. [测试计划](#6-测试计划)
7. [验收标准](#7-验收标准)
8. [风险管理](#8-风险管理)

---

## 1. 阶段概述

### 1.1 P1 阶段范围

P1 阶段聚焦于**数据传输核心功能**的实现，使 LustreStore 能够完成完整的 Load/Dump 操作流程。

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           P1 阶段 - 数据传输核心                                   │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                          核心交付物                                         │   │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │   │
│  │  │   TransQueue     │  │   TransManager   │  │  Load/Dump/Wait  │          │   │
│  │  │   I/O 队列实现    │  │   任务管理实现    │  │     流程实现      │          │   │
│  │  └──────────────────┘  └──────────────────┘  └──────────────────┘          │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 与其他阶段的关系

| 阶段 | 状态 | 与 P1 的关系 |
|------|------|-------------|
| **P0** | ✅ 已完成 | P1 依赖 P0 的基础设施 (SpaceLayout, LustreFile, 参数校验) |
| **P1** | 🚧 本阶段 | 实现核心数据传输功能 |
| **P2** | ⏳ 待开始 | P2 将在 P1 基础上优化性能 (异步 I/O, 线程池) |
| **P3** | ⏳ 待开始 | P3 将完善监控和增强功能 |

---

## 2. P1 阶段目标

### 2.1 功能目标

| ID | 目标 | 优先级 | 验收方式 |
|----|------|--------|----------|
| **P1-1** | 实现 TransQueue I/O 队列 | P0 | 单元测试通过 |
| **P1-2** | 实现 TransManager 任务管理 | P0 | 单元测试通过 |
| **P1-3** | 实现 Load 流程 (Lustre → Device) | P0 | 集成测试通过 |
| **P1-4** | 实现 Dump 流程 (Device → Lustre) | P0 | 集成测试通过 |
| **P1-5** | 实现 Wait/Check 任务状态查询 | P1 | 单元测试通过 |
| **P1-6** | 错误处理与恢复机制 | P1 | 错误注入测试 |
| **P1-7** | 实现 Lookup 功能 | P1 | Lookup 测试通过 |

### 2.2 技术目标

| 指标 | 目标值 | 测量方法 |
|------|--------|----------|
| 代码覆盖率 | ≥ 85% | gcov |
| 编译警告 | 0 | gcc -Wall |
| 单元测试通过率 | 100% | pytest/googletest |

---

## 3. 实施前置条件

### 3.1 P0 阶段交付物验证

| 交付物 | 状态 | 验证命令 |
|--------|------|----------|
| 参数校验框架 | ✅ | `python test/suites/Unit/test_lustre_p0_infrastructure.py` |
| SpaceLayout 实现 | ✅ | 同上 |
| LustreFile 封装 | ✅ | 同上 |
| 配置管理 | ✅ | 同上 |

### 3.2 开发环境验证

```bash
# 1. 验证编译环境
cd /home/w2938/tools/ucm
cmake -B build -DCMAKE_BUILD_TYPE=Debug

# 2. 验证 Python 测试环境
source /home/w2938/vllm/bin/activate
pytest test/suites/Unit/test_lustre_p0_infrastructure.py -v

# 3. 验证 P0 测试全部通过
# 预期: 16 passed in 2.36s
```

---

## 4. 任务分解

### 4.1 任务依赖图

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              P1 阶段任务依赖关系                                    │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────┐                                                                   │
│  │   P1-1.0    │  IoUnit 结构定义与测试                                            │
│  │ IoUnit 定义 │                                                                   │
│  └──────┬──────┘                                                                   │
│         │                                                                          │
│         ▼                                                                          │
│  ┌─────────────┐     ┌─────────────┐                                               │
│  │   P1-1.1    │     │   P1-2.0    │                                               │
│  │ TransQueue  │────▶│ TransManager│ 任务管理框架                                  │
│  │ 任务拆分    │     │  框架搭建   │                                               │
│  └──────┬──────┘     └──────┬──────┘                                               │
│         │                   │                                                       │
│         ▼                   ▼                                                       │
│  ┌─────────────┐     ┌─────────────┐                                               │
│  │   P1-1.2    │     │   P1-2.1    │                                               │
│  │   H2S 实现   │     │ Load 流程   │                                               │
│  │ (Dump)      │     │   实现      │                                               │
│  └──────┬──────┘     └──────┬──────┘                                               │
│         │                   │                                                       │
│         ▼                   ▼                                                       │
│  ┌─────────────┐     ┌─────────────┐                                               │
│  │   P1-1.3    │     │   P1-2.2    │                                               │
│  │   S2H 实现   │     │ Dump 流程   │                                               │
│  │  (Load)     │     │   实现      │                                               │
│  └──────┬──────┘     └──────┬──────┘                                               │
│         │                   │                                                       │
│         └─────────┬─────────┘                                                       │
│                   ▼                                                                 │
│         ┌─────────────────┐                                                         │
│         │     P1-3.0      │  Wait/Check 状态查询                                   │
│         │  状态查询实现    │                                                         │
│         └────────┬────────┘                                                         │
│                  │                                                                 │
│                  ▼                                                                 │
│         ┌─────────────────┐                                                         │
│         │     P1-4.0      │  集成测试与验证                                        │
│         │   集成测试      │                                                         │
│         └─────────────────┘                                                         │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 详细任务列表

#### P1-1: TransQueue I/O 队列实现

| 子任务 ID | 描述 | 文件 | 预计工时 | 依赖 |
|----------|------|------|---------|------|
| **P1-1.0** | IoUnit 结构定义与测试 | `trans_task.h` | 0.5天 | P0 完成 |
| **P1-1.1** | TransQueue 任务拆分逻辑 | `trans_queue.cc` | 1天 | P1-1.0 |
| **P1-1.2** | H2S (Dump) I/O 实现 | `trans_queue.cc` | 1.5天 | P1-1.1 |
| **P1-1.3** | S2H (Load) I/O 实现 | `trans_queue.cc` | 1.5天 | P1-1.1 |
| **P1-1.4** | TransQueue 单元测试 | `trans_queue_test.cc` | 1天 | P1-1.2, P1-1.3 |

**合计**: 5.5 天

#### P1-2: TransManager 任务管理实现

| 子任务 ID | 描述 | 文件 | 预计工时 | 依赖 |
|----------|------|------|---------|------|
| **P1-2.0** | TransManager 框架搭建 | `trans_manager.cc` | 0.5天 | P0 完成 |
| **P1-2.1** | Load 流程实现 | `lustre_store.cc` | 1天 | P1-2.0, P1-1.3 |
| **P1-2.2** | Dump 流程实现 | `lustre_store.cc` | 1天 | P1-2.0, P1-1.2 |
| **P1-2.3** | TransManager 单元测试 | `trans_manager_test.cc` | 1天 | P1-2.1, P1-2.2 |

**合计**: 3.5 天

#### P1-3: 状态查询实现

| 子任务 ID | 描述 | 文件 | 预计工时 | 依赖 |
|----------|------|------|---------|------|
| **P1-3.1** | Wait 阻塞等待实现 | `lustre_store.cc` | 0.5天 | P1-2.0 |
| **P1-3.2** | Check 非阻塞查询实现 | `lustre_store.cc` | 0.5天 | P1-2.0 |
| **P1-3.3** | 状态查询单元测试 | `lustre_store_test.cc` | 0.5天 | P1-3.1, P1-3.2 |

**合计**: 1.5 天

#### P1-4: 集成测试与验证

| 子任务 ID | 描述 | 文件 | 预计工时 | 依赖 |
|----------|------|------|---------|------|
| **P1-4.1** | 端到端 Load/Dump 测试 | `test_lustre_p1_data_transfer.py` | 1天 | P1-2.x |
| **P1-4.2** | 错误注入测试 | `test_lustre_p1_error_handling.py` | 0.5天 | P1-4.1 |
| **P1-4.3** | 并发安全性测试 | `test_lustre_p1_concurrent.py` | 0.5天 | P1-4.1 |

**合计**: 2 天

### 4.3 总工时统计

| 任务组 | 工时 | 缓冲 | 总计 |
|--------|------|------|------|
| P1-1 TransQueue | 5.5天 | 0.5天 | 6天 |
| P1-2 TransManager | 3.5天 | 0.5天 | 4天 |
| P1-3 状态查询 | 1.5天 | - | 1.5天 |
| P1-4 集成测试 | 2天 | 0.5天 | 2.5天 |
| **总计** | **12.5天** | **1.5天** | **14天 (2周)** |

---

## 5. 技术实施细节

### 5.1 IoUnit 数据结构

**文件**: `ucm/store/lustre/cc/trans_task.h`

```cpp
// IoUnit - 最小 I/O 执行单元
struct IoUnit {
    // 标识
    Detail::BlockId blockId;      // 所属 Block
    size_t shardIndex;            // Shard 索引

    // 数据位置
    void* srcAddr;                // 源地址
    void* dstAddr;                // 目标地址
    size_t offset;                // 文件内偏移
    size_t size;                  // I/O 大小

    // 状态
    std::atomic<bool> completed{false};
    Status result{Status::OK()};

    // 构造函数
    IoUnit(Detail::BlockId bid, size_t sidx, void* src, void* dst,
           size_t off, size_t sz)
        : blockId(bid), shardIndex(sidx), srcAddr(src), dstAddr(dst),
          offset(off), size(sz) {}
};
```

### 5.2 TransQueue 任务拆分

**文件**: `ucm/store/lustre/cc/trans_queue.cc`

```cpp
std::vector<std::unique_ptr<IoUnit>>
TransQueue::SplitTask(const TransTask& task) {
    std::vector<std::unique_ptr<IoUnit>> units;

    const auto& desc = task.desc;
    size_t shardSize = config_.shardSize;

    // 为每个 Shard 创建一个 IoUnit
    for (size_t i = 0; i < desc.numShards; ++i) {
        // 计算地址偏移
        void* srcAddr = reinterpret_cast<char*>(desc.srcAddr) + i * shardSize;
        void* dstAddr = reinterpret_cast<char*>(desc.dstAddr) + i * shardSize;

        // 计算 Block 文件内偏移
        size_t offset = i * shardSize;

        units.push_back(std::make_unique<IoUnit>(
            desc.blockIds[i],     // BlockId
            i,                    // ShardIndex
            srcAddr,              // 源地址
            dstAddr,              // 目标地址
            offset,               // 文件偏移
            shardSize             // I/O 大小
        ));
    }

    return units;
}
```

### 5.3 H2S (Dump) 实现

**文件**: `ucm/store/lustre/cc/trans_queue.cc`

```cpp
Status TransQueue::H2S(IoUnit& ios) {
    // 1. 生成临时文件路径
    std::string tmpPath = layout_->DataFilePath(ios.blockId, true);

    // 2. 打开/创建临时文件 (进程级隔离)
    LustreFile file(tmpPath);
    Status status = file.Open(O_WRONLY | O_CREAT | O_TRUNC);
    if (!status.OK()) return status;

    // 3. 写入数据 (使用 pwrite 支持并发写入)
    status = file.Write(ios.srcAddr, ios.size, ios.offset);
    if (!status.OK()) {
        file.Remove();
        return status;
    }

    // 4. 如果是最后一个 Shard，提交文件
    if (ios.shardIndex == config_.nShardPerBlock - 1) {
        status = layout_->CommitFile(ios.blockId, true);
        if (!status.OK() && status.Code() != Status::DuplicateKey) {
            return status;
        }
    }

    ios.completed = true;
    return Status::OK();
}
```

### 5.4 S2H (Load) 实现

**文件**: `ucm/store/lustre/cc/trans_queue.cc`

```cpp
Status TransQueue::S2H(IoUnit& ios) {
    // 1. 生成正式文件路径
    std::string finalPath = layout_->DataFilePath(ios.blockId, false);

    // 2. 检查文件存在
    LustreFile file(finalPath);
    if (!file.Access(F_OK)) {
        return Status::NotFound("Block not found: " + finalPath);
    }

    // 3. 打开文件
    Status status = file.Open(O_RDONLY);
    if (!status.OK()) return status;

    // 4. 读取数据
    status = file.Read(ios.dstAddr, ios.size, ios.offset);
    if (!status.OK()) return status;

    ios.completed = true;
    return Status::OK();
}
```

### 5.5 Load 流程实现

**文件**: `ucm/store/lustre/cc/lustre_store.cc`

```cpp
Expected<Detail::TaskHandle> LustreStore::Load(Detail::TaskDesc task) {
    // ===== P1-2.1: 参数校验 =====
    CHECK_NOT_NULL(task.blockIds, "blockIds");
    CHECK_NOT_NULL(task.shardAddrs, "shardAddrs");
    CHECK_PARAM(task.numBlocks > 0, "numBlocks must be positive");

    // ===== 自动填充参数 (v1.1 设计) =====
    TaskDesc internalDesc = task;
    internalDesc.shardSize = config_.shardSize;
    internalDesc.numShards = config_.nShardPerBlock;
    internalDesc.blockSize = config_.shardSize * config_.nShardPerBlock;

    // ===== 创建传输任务 =====
    auto transTask = std::make_shared<TransTask>(
        TransTask::Type::LOAD,
        internalDesc
    );

    // ===== 提交到 TransManager =====
    TaskHandle handle = impl_->transManager->Submit(transTask);

    return handle;
}
```

### 5.6 Dump 流程实现

**文件**: `ucm/store/lustre/cc/lustre_store.cc`

```cpp
Expected<Detail::TaskHandle> LustreStore::Dump(Detail::TaskDesc task) {
    // ===== P1-2.2: 参数校验 =====
    CHECK_NOT_NULL(task.blockIds, "blockIds");
    CHECK_NOT_NULL(task.shardAddrs, "shardAddrs");
    CHECK_PARAM(task.numBlocks > 0, "numBlocks must be positive");

    // ===== 自动填充参数 (v1.1 设计) =====
    TaskDesc internalDesc = task;
    internalDesc.shardSize = config_.shardSize;
    internalDesc.numShards = config_.nShardPerBlock;
    internalDesc.blockSize = config_.shardSize * config_.nShardPerBlock;

    // ===== 创建传输任务 =====
    auto transTask = std::make_shared<TransTask>(
        TransTask::Type::DUMP,
        internalDesc
    );

    // ===== 提交到 TransManager =====
    TaskHandle handle = impl_->transManager->Submit(transTask);

    return handle;
}
```

### 5.7 Wait/Check 实现

**文件**: `ucm/store/lustre/cc/lustre_store.cc`

```cpp
Status LustreStore::Wait(Detail::TaskHandle taskId) {
    // ===== P1-3.1: 阻塞等待任务完成 =====
    return impl_->transManager->Wait(taskId);
}

Expected<bool> LustreStore::Check(Detail::TaskHandle taskId) {
    // ===== P1-3.2: 非阻塞检查任务状态 =====
    return impl_->transManager->Check(taskId);
}
```

### 5.8 Lookup 实现

**参考**: `P1_LOOKUP_DESIGN.md` 详细设计文档

#### 5.8.1 SpaceLayout::Exists()

**文件**: `ucm/store/lustre/cc/space_layout.h`

```cpp
class SpaceLayout {
public:
    // ... 现有方法 ...

    /**
     * 检查 Block 文件是否存在
     * @param blockId Block ID
     * @return true 文件存在，false 文件不存在
     */
    bool Exists(const Detail::BlockId& blockId) const;
};
```

**文件**: `ucm/store/lustre/cc/space_layout.cc`

```cpp
bool SpaceLayout::Exists(const Detail::BlockId& blockId) const
{
    std::string path = DataFilePath(blockId, false);
    return LustreFile::Exists(path);
}
```

#### 5.8.2 SpaceManager::Lookup()

**文件**: `ucm/store/lustre/cc/space_manager.cc`

```cpp
std::vector<uint8_t> SpaceManager::Lookup(const Detail::BlockId* blocks, size_t num)
{
    std::vector<uint8_t> result(num, 0);
    for (size_t i = 0; i < num; i++) {
        result[i] = LookupSingle(&blocks[i]);
    }
    return result;
}

uint8_t SpaceManager::LookupSingle(const Detail::BlockId* block)
{
    if (!block) return 0;
    return layout_.Exists(*block) ? 1 : 0;
}

ssize_t SpaceManager::LookupOnPrefix(const Detail::BlockId* blocks, size_t num)
{
    for (size_t i = 0; i < num; i++) {
        if (LookupSingle(&blocks[i]) == 0) {
            return static_cast<ssize_t>(i);
        }
    }
    return -1;
}
```

#### 5.8.3 LustreStore::Lookup()

**文件**: `ucm/store/lustre/cc/lustre_store.cc`

```cpp
Expected<std::vector<uint8_t>> LustreStore::Lookup(
    const Detail::BlockId* blocks, size_t num)
{
    if (num > 0) { CHECK_NOT_NULL(blocks, "blocks"); }
    CHECK_RANGE(num, 0, 1000000, "num");

    auto result = impl_->spaceMgr.Lookup(blocks, num);
    return result;
}

Expected<ssize_t> LustreStore::LookupOnPrefix(
    const Detail::BlockId* blocks, size_t num)
{
    if (num > 0) { CHECK_NOT_NULL(blocks, "blocks"); }
    CHECK_RANGE(num, 0, 1000000, "num");

    return impl_->spaceMgr.LookupOnPrefix(blocks, num);
}
```

---

## 6. 测试计划

### 6.1 单元测试

#### P1-1: TransQueue 测试

| 测试用例 | 描述 | 验证点 |
|----------|------|--------|
| `test_split_task_single_shard` | 单 Shard 任务拆分 | 返回 1 个 IoUnit |
| `test_split_task_multi_shard` | 多 Shard 任务拆分 | 返回 N 个 IoUnit，地址正确 |
| `test_h2s_success` | Dump 成功路径 | 临时文件创建、写入、提交 |
| `test_h2s_file_exists` | Dump 文件已存在 | 返回 DuplicateKey |
| `test_s2h_success` | Load 成功路径 | 文件读取、数据正确 |
| `test_s2h_not_found` | Load 文件不存在 | 返回 NotFound |
| `test_concurrent_write_same_offset` | 并发写入不同 offset | pwrite 线程安全 |

#### P1-2: TransManager 测试

| 测试用例 | 描述 | 验证点 |
|----------|------|--------|
| `test_submit_load` | 提交 Load 任务 | 返回有效 TaskHandle |
| `test_submit_dump` | 提交 Dump 任务 | 返回有效 TaskHandle |
| `test_auto_fill_params` | 参数自动填充 | shardSize/numShards 正确填充 |
| `test_wait_completion` | 等待任务完成 | 正确返回完成状态 |

#### P1-3: 状态查询测试

| 测试用例 | 描述 | 验证点 |
|----------|------|--------|
| `test_check_pending` | 检查进行中任务 | 返回 false |
| `test_check_completed` | 检查已完成任务 | 返回 true |
| `test_wait_timeout` | 等待超时处理 | 正确返回超时状态 |

#### P1-7: Lookup 测试

**文件**: `test/suites/Unit/test_lustre_p1_lookup.py`

| 测试用例 | 描述 | 验证点 |
|----------|------|--------|
| `test_lookup_single_block_exists` | 查询存在的 Block | 返回 [1] |
| `test_lookup_single_block_not_exists` | 查询不存在的 Block | 返回 [0] |
| `test_lookup_multiple_blocks` | 批量查询混合状态 | 正确返回 [1,1,0] |
| `test_lookup_on_prefix_all_exist` | 前缀查询全部存在 | 返回 -1 |
| `test_lookup_on_prefix_first_missing` | 前缀查询中间缺失 | 返回缺失索引 |
| `test_lookup_empty_list` | 空 Block 列表 | 返回 [] |
| `test_get_flow_with_lookup` | 完整 Get 流程 | Lookup → Load 成功 |

### 6.2 集成测试

**文件**: `test/suites/Unit/test_lustre_p1_data_transfer.py`

```python
import pytest
from ucm.store.lustre import UcmLustreStore

class TestLustreP1DataTransfer:

    @pytest.fixture
    def lustre_store(self):
        config = {
            "storage_backends": ["/home/w2938/tmp/lustre"],
            "device_id": -1,
            "block_size": 4096,
            "shard_size": 1024,
            "tensor_size": 256,
            "data_dir_shard_bytes": 3,
        }
        return UcmLustreStore(config)

    def test_dump_single_block(self, lustre_store):
        """P1-4.1: 单 Block Dump 测试"""
        # 生成测试数据
        block_ids = [generate_block_id()]
        shard_addrs = [allocate_host_memory(4096)]
        tensors = [[create_test_tensor()]]

        # 执行 Dump
        task = lustre_store.dump(block_ids, [0], tensors)
        result = lustre_store.wait(task)

        assert result.ok(), "Dump should succeed"

        # 验证 Lookup
        presence = lustre_store.lookup(block_ids)
        assert presence[0], "Block should exist after dump"

    def test_dump_load_cycle(self, lustre_store):
        """P1-4.1: Dump-Load 完整循环"""
        # 准备测试数据
        original_data = create_test_data()
        block_ids = [generate_block_id()]

        # Dump
        dump_task = lustre_store.dump(block_ids, [0], [[original_data]])
        assert lustre_store.wait(dump_task).ok()

        # Load
        loaded_data = allocate_host_memory(4096)
        load_task = lustre_store.load(block_ids, [0], [[loaded_data]])
        assert lustre_store.wait(load_task).ok()

        # 验证数据一致性
        assert_tensors_equal(loaded_data, original_data)

    def test_multi_block_dump_load(self, lustre_store):
        """P1-4.1: 多 Block 并发 Dump/Load"""
        num_blocks = 100
        block_ids = [generate_block_id() for _ in range(num_blocks)]
        data_list = [create_test_data() for _ in range(num_blocks)]

        # 批量 Dump
        dump_task = lustre_store.dump(block_ids, list(range(num_blocks)), data_list)
        assert lustre_store.wait(dump_task).ok()

        # 批量 Load
        loaded_data = [allocate_host_memory(4096) for _ in range(num_blocks)]
        load_task = lustre_store.load(block_ids, list(range(num_blocks)), loaded_data)
        assert lustre_store.wait(load_task).ok()

        # 验证所有数据
        for i in range(num_blocks):
            assert_tensors_equal(loaded_data[i], data_list[i])

    def test_check_task_status(self, lustre_store):
        """P1-3: Check 状态查询"""
        block_ids = [generate_block_id()]
        data = [[create_test_data()]]

        task = lustre_store.dump(block_ids, [0], data)

        # 检查进行中状态
        completed = lustre_store.check(task)
        # 可能已完成或进行中

        # 等待完成
        lustre_store.wait(task)

        # 检查完成状态
        completed = lustre_store.check(task)
        assert completed, "Task should be completed"
```

### 6.3 错误注入测试

**文件**: `test/suites/Unit/test_lustre_p1_error_handling.py`

```python
class TestLustreP1ErrorHandling:

    def test_dump_with_invalid_address(self, lustre_store):
        """P1-6: 无效地址处理"""
        block_ids = [generate_block_id()]
        invalid_addr = 0xDEADBEEF  # 无效地址

        task = lustre_store.dump(block_ids, [0], [[invalid_addr]])
        result = lustre_store.wait(task)

        assert not result.ok(), "Should fail with invalid address"

    def test_load_nonexistent_block(self, lustre_store):
        """P1-6: Load 不存在的 Block"""
        fake_block_id = generate_block_id()

        task = lustre_store.load([fake_block_id], [0], [[allocate_memory()]])
        result = lustre_store.wait(task)

        assert result.code() == Status.NotFound, "Should return NotFound"

    def test_dump_with_permission_denied(self, lustre_store):
        """P1-6: 权限拒绝处理"""
        # 创建只读目录
        readonly_path = "/home/w2938/tmp/lustre_readonly"
        os.makedirs(readonly_path, exist_ok=True)
        os.chmod(readonly_path, 0o444)

        config = {"storage_backends": [readonly_path], ...}
        store = UcmLustreStore(config)

        task = store.dump([generate_block_id()], [0], [[create_test_data()]])
        result = store.wait(task)

        assert not result.ok(), "Should fail with permission denied"
```

### 6.4 并发测试

**文件**: `test/suites/Unit/test_lustre_p1_concurrent.py`

```python
class TestLustreP1Concurrent:

    def test_concurrent_dump_same_block(self, lustre_store):
        """P1-6: 多进程 Dump 同一 Block (link() 原子性测试)"""
        block_id = generate_block_id()
        data = create_test_data()

        # 模拟两个进程同时 Dump 相同 Block
        results = []
        for i in range(2):
            task = lustre_store.dump([block_id], [0], [[data]])
            results.append(lustre_store.wait(task))

        # 至少一个成功，另一个可能是 DuplicateKey
        success_count = sum(1 for r in results if r.ok() or r.code() == Status.DuplicateKey)
        assert success_count == 2, "Both should complete (one success, one DuplicateKey)"

        # 验证文件只存在一份
        presence = lustre_store.lookup([block_id])
        assert presence[0], "Block should exist"
```

---

## 7. 验收标准

### 7.1 功能验收

| ID | 验收项 | 标准 | 验证方法 |
|----|--------|------|----------|
| **F-1** | Dump 操作 | 数据正确写入 Lustre | Load 回来验证一致性 |
| **F-2** | Load 操作 | 正确从 Lustre 读取数据 | 与原始数据对比 |
| **F-3** | Wait 操作 | 正确阻塞直到完成 | 单元测试 |
| **F-4** | Check 操作 | 正确返回任务状态 | 单元测试 |
| **F-5** | 并发安全 | 多进程/多线程无数据损坏 | 并发测试 |
| **F-6** | 错误处理 | 正确返回错误码 | 错误注入测试 |

### 7.2 质量验收

| 指标 | 标准 | 验证方法 |
|------|------|----------|
| **代码覆盖率** | ≥ 85% | gcov/lcov |
| **编译警告** | 0 | gcc -Wall -Wextra |
| **静态分析** | 无严重问题 | cppcheck |
| **内存泄漏** | 无 | valgrind |

### 7.3 性能基准 (初步)

| 指标 | 目标值 | 备注 |
|------|--------|------|
| 单 Block Dump | < 100ms | P1 阶段为功能优先 |
| 单 Block Load | < 100ms | P2 阶段优化 |
| 并发吞吐量 | > 100 MB/s | 保守目标 |

---

## 8. 风险管理

### 8.1 技术风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| **pwrite 并发问题** | 高 | 低 | 使用独立文件描述符测试验证 |
| **link() 原子性** | 高 | 低 | 参考 PosixStore 成熟实现 |
| **内存管理复杂度** | 中 | 中 | 使用 RAII 智能指针 |
| **测试环境不稳定** | 中 | 中 | 使用 Mock 层隔离 |

### 8.2 进度风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| **P0 依赖问题** | 高 | 低 | P0 已验证完成 |
| **人员变动** | 中 | 低 | 代码文档完善 |
| **需求变更** | 低 | 低 | P1 范围已明确定义 |

### 8.3 验收风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| **测试环境不匹配** | 中 | 中 | Docker 容器化测试环境 |
| **性能目标无法达成** | 低 | 低 | P1 优先功能，性能留 P2 |

---

## 9. 交付物清单

### 9.1 代码交付物

| 文件 | 类型 | 说明 |
|------|------|------|
| `trans_queue.cc` | 实现 | I/O 队列实现 |
| `trans_manager.cc` | 实现 | 任务管理实现 |
| `space_layout.cc` | 扩展 | 添加 Exists() 方法 |
| `space_manager.cc` | 扩展 | 完善 Lookup 实现 |
| `lustre_store.cc` | 扩展 | Load/Dump/Wait/Check/Lookup |
| `trans_task.h` | 修改 | IoUnit 定义 |

### 9.2 测试交付物

| 文件 | 类型 | 说明 |
|------|------|------|
| `trans_queue_test.cc` | 单元测试 | TransQueue 测试 |
| `trans_manager_test.cc` | 单元测试 | TransManager 测试 |
| `test_lustre_p1_data_transfer.py` | 集成测试 | 数据流测试 |
| `test_lustre_p1_error_handling.py` | 错误测试 | 错误处理测试 |
| `test_lustre_p1_concurrent.py` | 并发测试 | 并发安全测试 |
| `test_lustre_p1_lookup.py` | 集成测试 | Lookup 功能测试 |

### 9.3 文档交付物

| 文件 | 类型 | 说明 |
|------|------|------|
| `P1_LOOKUP_DESIGN.md` | 设计文档 | Lookup 功能详细设计 |
| `P1_VERIFICATION_REPORT.md` | 验证报告 | P1 阶段验收报告 |
| `P1_DESIGN_NOTES.md` | 设计笔记 | 实现过程中的设计决策 |

---

## 10. 下一步 (P2 阶段预览)

P2 阶段将在 P1 基础上进行性能优化：

- **异步 I/O**: io_uring/libaio 后端实现
- **分层线程池**: Lookup 和 DataTrans 独立线程池
- **CPU 亲和性**: 绑核优化
- **目录分片**: 减少单目录文件数量

---

**计划版本**: 1.0
**最后更新**: 2026-04-01
**负责人**: Implementation Team
