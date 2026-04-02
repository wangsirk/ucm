# P1 Lookup 功能设计文档

**文档版本**: 1.0
**创建日期**: 2026-04-02
**阶段**: P1 - 数据传输核心（补充）
**参考**: PosixStore Lookup 实现

---

## 目录

1. [设计概述](#1-设计概述)
2. [接口定义](#2-接口定义)
3. [实现方案](#3-实现方案)
4. [测试用例](#4-测试用例)
5. [P2 优化方向](#5-p2-优化方向)

---

## 1. 设计概述

### 1.1 背景

原计划中 Lookup 功能被遗漏：
- P0 阶段：未实现
- P1 阶段：未包含
- P2 阶段：假设已存在，仅做性能优化

### 1.2 目标

在 P1 阶段补充**基础 Lookup 功能**，支持：
- 检查 Block 是否存在（文件存在性检查）
- 批量查找（同步版本）
- 前缀查找（第一个缺失 Block）

### 1.3 设计原则

| 原则 | 说明 |
|------|------|
| **简单优先** | P1 实现同步版本，P2 再优化为并发 |
| **参考 PosixStore** | 复用成熟的实现模式 |
| **兼容 StoreV1** | 保持接口一致性 |
| **可测试性** | 支持单元测试和集成测试 |

---

## 2. 接口定义

### 2.1 SpaceLayout::Exists()

```cpp
// space_layout.h
namespace UC::LustreStore {

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

}  // namespace UC::LustreStore
```

### 2.2 SpaceManager::Lookup()

```cpp
// space_manager.h
namespace UC::LustreStore {

class SpaceManager {
public:
    // ... 现有方法 ...

    /**
     * 批量查找 Block 是否存在（P1 同步版本）
     * @param blocks Block ID 数组
     * @param num Block 数量
     * @return 存在性位图 (1=存在, 0=不存在)
     */
    std::vector<uint8_t> Lookup(const Detail::BlockId* blocks, size_t num);

    /**
     * 前缀查找，返回第一个缺失的 Block 索引
     * @param blocks Block ID 数组（按前缀顺序）
     * @param num Block 数量
     * @return 第一个缺失 Block 的索引，-1 表示全部存在
     */
    ssize_t LookupOnPrefix(const Detail::BlockId* blocks, size_t num);

private:
    /**
     * 单个 Block 查找
     * @param block Block ID
     * @return 1=存在, 0=不存在
     */
    uint8_t LookupSingle(const Detail::BlockId* block);
};

}  // namespace UC::LustreStore
```

### 2.3 LustreStore::Lookup()

```cpp
// lustre_store.cc
namespace UC::LustreStore {

Expected<std::vector<uint8_t>> LustreStore::Lookup(
    const Detail::BlockId* blocks, size_t num)
{
    // 参数校验
    if (num > 0) {
        CHECK_NOT_NULL(blocks, "blocks");
    }
    CHECK_RANGE(num, 0, 1000000, "num");

    // 委托给 SpaceManager
    auto result = impl_->spaceMgr.Lookup(blocks, num);
    UC_DEBUG("LustreStore::Lookup - {} blocks, {} found",
             num, std::count(result.begin(), result.end(), 1));
    return result;
}

Expected<ssize_t> LustreStore::LookupOnPrefix(
    const Detail::BlockId* blocks, size_t num)
{
    // 参数校验
    if (num > 0) {
        CHECK_NOT_NULL(blocks, "blocks");
    }
    CHECK_RANGE(num, 0, 1000000, "num");

    // 委托给 SpaceManager
    return impl_->spaceMgr.LookupOnPrefix(blocks, num);
}

}  // namespace UC::LustreStore
```

---

## 3. 实现方案

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                       LustreStore::Lookup                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SpaceManager::Lookup                        │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  for each block:                                         │    │
│  │    result[i] = LookupSingle(&blocks[i]);               │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  SpaceManager::LookupSingle                     │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  path = layout_.DataFilePath(*block, false);           │    │
│  │  return LustreFile::Exists(path);                       │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SpaceLayout::Exists                         │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  std::string path = DataFilePath(blockId, false);       │    │
│  │  return LustreFile::Exists(path);                       │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 SpaceLayout::Exists() 实现

```cpp
// space_layout.cc
namespace UC::LustreStore {

bool SpaceLayout::Exists(const Detail::BlockId& blockId) const
{
    // 生成正式文件路径
    std::string path = DataFilePath(blockId, false);

    // 检查文件是否存在
    return LustreFile::Exists(path);
}

}  // namespace UC::LustreStore
```

### 3.3 SpaceManager::LookupSingle() 实现

```cpp
// space_manager.cc
namespace UC::LustreStore {

uint8_t SpaceManager::LookupSingle(const Detail::BlockId* block)
{
    if (!block) {
        return 0;
    }

    // 使用 SpaceLayout 检查文件存在
    bool exists = layout_.Exists(*block);

    UC_DEBUG("LustreSpaceManager::LookupSingle - block={}, exists={}",
             (*block)[0], exists);

    return exists ? 1 : 0;
}

}  // namespace UC::LustreStore
```

### 3.4 SpaceManager::LookupOnPrefix() 实现

```cpp
// space_manager.cc
namespace UC::LustreStore {

ssize_t SpaceManager::LookupOnPrefix(const Detail::BlockId* blocks, size_t num)
{
    if (!blocks || num == 0) {
        return -1;
    }

    // 遍历 blocks，找到第一个不存在的
    for (size_t i = 0; i < num; i++) {
        if (LookupSingle(&blocks[i]) == 0) {
            UC_DEBUG("LustreSpaceManager::LookupOnPrefix - first missing at index={}", i);
            return static_cast<ssize_t>(i);
        }
    }

    UC_DEBUG("LustreSpaceManager::LookupOnPrefix - all blocks exist");
    return -1;  // 全部存在
}

}  // namespace UC::LustreStore
```

---

## 4. 测试用例

### 4.1 单元测试

```python
# test_lustre_p1_lookup.py

def test_lookup_single_block_exists():
    """[P1-L1-T1] 查询存在的 Block"""
    block_id = generate_block_id(1000)
    data = create_test_tensor(1024, 0xAB)

    # 先 Dump 创建文件
    task = lustre_store.dump([block_id], [0], [[data]])
    lustre_store.wait(task)

    # Lookup 应该返回 [1]
    result = lustre_store.lookup([block_id])
    assert result == [1], f"Expected [1], got {result}"
    log_test_pass("P1-L1-T1 查询存在的Block")


def test_lookup_single_block_not_exists():
    """[P1-L1-T2] 查询不存在的 Block"""
    block_id = generate_block_id(2000)

    # Lookup 应该返回 [0]
    result = lustre_store.lookup([block_id])
    assert result == [0], f"Expected [0], got {result}"
    log_test_pass("P1-L1-T2 查询不存在的Block")


def test_lookup_multiple_blocks():
    """[P1-L1-T3] 批量查询多个 Blocks"""
    # Dump 3 个 blocks
    block_ids = [generate_block_id(3000 + i) for i in range(3)]
    for i, bid in enumerate(block_ids):
        data = create_test_tensor(1024, 0x10 + i)
        task = lustre_store.dump([bid], [0], [[data]])
        lustre_store.wait(task)

    # 查询：2 个存在 + 1 个不存在
    test_ids = block_ids + [generate_block_id(9999)]
    result = lustre_store.lookup(test_ids)
    assert result == [1, 1, 1, 0], f"Expected [1,1,1,0], got {result}"
    log_test_pass("P1-L1-T3 批量查询混合状态")


def test_lookup_on_prefix_all_exist():
    """[P1-L1-T4] 前缀查询 - 全部存在"""
    block_ids = [generate_block_id(4000 + i) for i in range(3)]
    for bid in block_ids:
        data = create_test_tensor(1024, 0xAB)
        task = lustre_store.dump([bid], [0], [[data]])
        lustre_store.wait(task)

    # LookupOnPrefix 应该返回 -1（全部存在）
    result = lustre_store.lookup_on_prefix(block_ids)
    assert result == -1, f"Expected -1, got {result}"
    log_test_pass("P1-L1-T4 前缀查询全部存在")


def test_lookup_on_prefix_first_missing():
    """[P1-L1-T5] 前缀查询 - 中间缺失"""
    block_ids = [generate_block_id(5000 + i) for i in range(5)]
    # 只 Dump 前 2 个
    for i in range(2):
        data = create_test_tensor(1024, 0x10 + i)
        task = lustre_store.dump([block_ids[i]], [0], [[data]])
        lustre_store.wait(task)

    # LookupOnPrefix 应该返回 2（第 3 个 block 缺失，索引为 2）
    result = lustre_store.lookup_on_prefix(block_ids)
    assert result == 2, f"Expected 2, got {result}"
    log_test_pass("P1-L1-T5 前缀查询中间缺失")


def test_lookup_empty_list():
    """[P1-L1-T6] 空 Block 列表"""
    result = lustre_store.lookup([])
    assert result == [], f"Expected [], got {result}"
    log_test_pass("P1-L1-T6 空Block列表")
```

### 4.2 集成测试

```python
def test_get_flow_with_lookup():
    """[P1-L2-T1] 完整 Get 流程：Lookup → Load"""
    block_id = generate_block_id(6000)
    data = create_test_tensor(1024, 0xCD)

    # 1. 先 Dump 数据
    task = lustre_store.dump([block_id], [0], [[data]])
    lustre_store.wait(task)

    # 2. Lookup 检查存在
    result = lustre_store.lookup([block_id])
    assert result == [1], "Block should exist after Dump"

    # 3. Load 数据
    loaded = torch.zeros(1024, dtype=torch.uint8)
    task = lustre_store.load([block_id], [0], [[loaded]])
    lustre_store.wait(task)

    # 4. 验证数据
    assert_tensors_equal(loaded, data, "Loaded data should match")
    log_test_pass("P1-L2-T1 完整Get流程")
```

---

## 5. P2 优化方向

### 5.1 并发查找

参考 PosixStore 的实现，P2 阶段可添加：

```cpp
class SpaceManager {
    ThreadPool<LookupContext> lookupSrv_;  // P2 添加

    std::vector<uint8_t> Lookup(const Detail::BlockId* blocks, size_t num) {
        // P2: 并发查找
        // 1. 创建查找上下文
        // 2. 推送到线程池
        // 3. 等待完成
    }
};
```

### 5.2 性能目标

| 指标 | P1 目标 | P2 目标 |
|------|---------|---------|
| Lookup 延迟 | < 1ms | < 100μs |
| 吞吐量 | 10K ops/s | 100K ops/s |
| 并发支持 | 单线程 | 多线程池 |

---

## 附录：文件清单

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `ucm/store/lustre/cc/space_layout.h` | 新增方法 | 添加 `Exists()` 声明 |
| `ucm/store/lustre/cc/space_layout.cc` | 新增实现 | 实现 `Exists()` |
| `ucm/store/lustre/cc/space_manager.h` | 修改方法签名 | 添加 `LookupOnPrefix()` |
| `ucm/store/lustre/cc/space_manager.cc` | 完善实现 | 替换 TODO |
| `ucm/store/lustre/cc/lustre_store.cc` | 完善实现 | 替换 TODO |
| `test/suites/Unit/test_lustre_p1_lookup.py` | 新增文件 | Lookup 测试 |

---

**文档结束**
