---
title: feat: Add Lustre directory-level striping support
type: feat
status: active
date: 2026-04-02
origin: docs/brainstorms/2026-04-02-lustre-striping-requirements.md
---

# Lustre Store 条带化支持

## Overview

为 UCM LustreStore 添加目录级条带化支持。在数据根目录创建时设置默认条带属性，使该目录下所有 KV Cache 文件自动继承条带化配置，充分利用 Lustre 并行文件系统的多 OST 并行能力，提升大文件读写吞吐量。

## Problem Frame

Lustre Store 当前已实现了 `CreateStriped()` API，但在实际文件创建时使用的是 `CreateNormal()`，未启用 Lustre 并行文件系统的条带化能力。这导致：
- 多 OST (Object Storage Target) 无法并行服务同一文件
- 大文件读写吞吐量受限
- 未充分利用 Lustre 集群的并行能力

(参见 [origin document](docs/brainstorms/2026-04-02-lustre-striping-requirements.md))

## Requirements Trace

- R1. 使用目录级条带化属性设置，而非为每个文件单独设置
- R2. 在 SpaceManager 初始化时为数据根目录设置默认条带属性
- R3. 该目录下创建的所有文件自动继承条带属性
- R4. 优先使用用户配置的 `stripe_count` 和 `stripe_size`
- R5. 若用户配置为 0 或未配置，直接使用标准 `mkdir` 创建目录
- R6. 仅当用户配置了非零条带参数时，才调用 `llapi_layout_*` API
- R7. 仅在 Lustre 文件系统上启用（HAVE_LUSTRE_API 宏控制）
- R8. 非 Lustre 环境回退到普通文件创建
- R9. 目录条带化设置失败时记录警告但继续运行
- R10. 仅当用户配置了非零条带参数时，才调用 `llapi_layout_*` API

## Scope Boundaries

**不在范围内:**
- 运行时动态调整条带参数
- 为不同文件设置不同条带策略
- 自动探测 OST 数量并计算最佳参数
- 复合条带布局（Composite Layout）

## Context & Research

### Relevant Code and Patterns

**现有 Striping API** ([`ucm/store/lustre/cc/lustre_file.cc:62-102`](ucm/store/lustre/cc/lustre_file.cc)):
- `CreateStriped(int stripeCount, size_t stripeSize, mode_t mode)` 已实现
- 使用 `llapi_layout_alloc()`, `llapi_layout_stripe_count_set()`, `llapi_layout_stripe_size_set()`, `llapi_layout_create()`
- 有 `HAVE_LUSTRE_API` 宏保护和回退机制

**目录创建位置** ([`ucm/store/lustre/cc/space_layout.cc:116-128`](ucm/store/lustre/cc/space_layout.cc)):
```cpp
// SpaceLayout::Setup() 中为每个 backend 创建 /data 目录
for (const auto& backend : storageBackends_) {
    std::string dataDir = backend + "/data";
    LustreFile::MkDir(dataDir, 0755);
}
```

**Config 结构** ([`ucm/store/lustre/cc/global_config.h:82-83`](ucm/store/lustre/cc/global_config.h)):
- `int stripeCount{LUSTRE_DEFAULT_STRIPE_COUNT}`  // 默认 0
- `size_t stripeSize{LUSTRE_DEFAULT_STRIPE_SIZE}` // 默认 1MB

**测试模式** ([`test/suites/Unit/test_lustre_p0_infrastructure.py`](test/suites/Unit/test_lustre_p0_infrastructure.py)):
- P0/P1/P2 分阶段测试结构
- pytest fixtures 配置模式
- 临时目录创建和清理模式

### Institutional Learnings

- **配置模式** ([`docs/solutions/performance-optimization/lustre-store-p2-performance-optimization.md`](docs/solutions/performance-optimization/lustre-store-p2-performance-optimization.md)): 新增配置项需在 `global_config.h` 添加宏定义，在 `Config` 结构添加字段，更新 Python 连接器文档
- **失败回退**: 使用 `HAVE_LUSTRE_API` 宏控制，非 Lustre 环境自动回退

### External References

- Lustre `llapi_layout_file_create()` API: 用于创建文件/目录时指定 layout
- Lustre layout 继承机制: 子文件从父目录继承默认 layout 属性
- `llapi_layout.7` 手册: 条带化属性设置和继承规则

## Key Technical Decisions

- **目录级 vs 文件级**: 选择目录级设置（R1），利用 Lustre 继承机制，减少文件创建时的 API 调用开销
- **配置策略**: 有配置时设置目录条带属性，无配置时使用标准 `mkdir`（R5）。避免对无配置用户产生任何性能影响
- **实现位置**: 在 `SpaceLayout::Setup()` 创建数据目录后立即设置条带属性，与目录创建逻辑内聚
- **失败处理**: 条带化设置失败时记录警告继续运行（R9），保证系统可用性。目录仍存在，文件仍可创建，只是无条带化

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification.*

```
┌─────────────────────────────────────────────────────────────────┐
│                    LustreStore::Setup()                        │
│                           │                                    │
│                           ▼                                    │
│                  ┌──────────────────┐                          │
│                  │ SpaceManager::   │                          │
│                  │ Setup(config)    │                          │
│                  └────────┬─────────┘                          │
│                           │                                    │
│                           ▼                                    │
│                  ┌──────────────────┐                          │
│                  │  SpaceLayout::   │                          │
│                  │  Setup(config)   │                          │
│                  └────────┬─────────┘                          │
│                           │                                    │
│            ┌──────────────┴──────────────┐                    │
│            ▼                             ▼                    │
│   ┌─────────────────┐         ┌────────────────────┐          │
│   │ 创建 /data 目录  │         │ config.stripeCount │          │
│   │ (MkDir)         │         │      > 0 ?          │          │
│   └────────┬────────┘         └─────────┬──────────┘          │
│            │                           │                       │
│            └──────────────┬──────────────┘                    │
│                           │                                    │
│                           ▼                                    │
│                  ┌──────────────────┐                          │
│                  │   条件分支:       │                          │
│                  │  stripeCount > 0  │                          │
│                  │      且           │                          │
│                  │  HAVE_LUSTRE_API │                          │
│                  └────────┬─────────┘                          │
│                           │                                    │
│            ┌──────────────┴──────────────┐                    │
│            ▼ YES                        ▼ NO                 │
│   ┌─────────────────────┐        ┌──────────────┐             │
│   │ SetStripedDirectory │        │  跳过        │             │
│   │ (llapi_layout_*)    │        │  (普通目录)  │             │
│   └─────────┬───────────┘        └──────────────┘             │
│             │                                                     │
│             ▼                                                     │
│   ┌─────────────────────┐                                       │
│   │  新文件自动继承      │                                       │
│   │  条带属性            │                                       │
│   └─────────────────────┘                                       │
└─────────────────────────────────────────────────────────────────┘
```

## Implementation Units

- [ ] **Unit 1: 在 LustreFile 添加目录条带化方法**

**Goal:** 添加设置目录条带属性的静态方法

**Requirements:** R1, R2, R6, R7, R8, R9

**Dependencies:** None

**Files:**
- Modify: `ucm/store/lustre/cc/lustre_file.h`
- Modify: `ucm/store/lustre/cc/lustre_file.cc`
- Note: C++ 单元测试由 Unit 3 的 Python 测试覆盖（遵循项目测试模式）

**Approach:**
- 添加 `static Status SetStripedDirectory(const std::string& path, int stripeCount, size_t stripeSize, mode_t mode)` 方法
- 使用 `llapi_layout_alloc()` 创建 layout，设置条带参数
- 使用 `llapi_layout_file_create()` 对目录应用 layout
- 用 `#ifdef HAVE_LUSTRE_API` 保护，非 Lustre 环境返回 `Status::OK()`
- 失败时返回 Status，记录警告但不抛出异常

**Technical design:**
```cpp
// Directional guidance for implementation structure
#ifdef HAVE_LUSTRE_API
Status LustreFile::SetStripedDirectory(const std::string& path,
                                      int stripeCount,
                                      size_t stripeSize,
                                      mode_t mode) {
    struct llapi_layout* layout = llapi_layout_alloc();
    if (!layout) {
        UC_WARN("Failed to allocate layout for {}", path);
        return Status::Error("alloc failed");
    }

    // Set stripe parameters
    if (stripeCount > 0) {
        llapi_layout_stripe_count_set(layout, stripeCount, 0);
    }
    if (stripeSize > 0) {
        llapi_layout_stripe_size_set(layout, stripeSize);
    }

    // llapi_layout_file_create() creates the directory itself
    int rc = llapi_layout_file_create(path.c_str(), 0, mode, layout);
    llapi_layout_free(layout);

    if (rc != 0) {
        UC_WARN("Failed to create striped directory {}: {}", path, strerror(errno));
        return Status::Error("stripe create failed");
    }
    return Status::OK();
}
#else
Status LustreFile::SetStripedDirectory(...) {
    return Status::OK();  // No-op without Lustre API
}
#endif
```

**Patterns to follow:**
- 参考 `lustre_file.cc:62-102` `CreateStriped()` 的实现模式
- 使用相同的宏保护和回退策略

**Test scenarios:**
- **Happy path**: stripeCount=4, stripeSize=1048576, path=/tmp/test_xxxxx → 返回 Status::OK()
- **Edge case**: stripeCount=0 → 跳过 layout 设置，返回 OK（使用系统默认）
- **Edge case**: stripeSize=0 → 使用 API 默认值（1MB），返回 OK
- **Error path**: HAVE_LUSTRE_API 未定义 → 返回 Status::OK()（no-op）
- **Error path**: 无效路径（父目录不存在）→ 返回 Status::Error()，由调用方决定如何处理
- **Integration**: 与 SpaceLayout 集成，验证目录创建成功且条带属性设置

**Verification:**
- 在真实 Lustre 挂载点上编译并运行（HAVE_LUSTRE_API 定义）
- 使用 `lfs getstripe -c <dir>` 验证目录条带属性设置正确
- 非 Lustre 环境编译通过（HAVE_LUSTRE_API 未定义）
- Unit 3 的 Python 测试提供端到端验证

- [ ] **Unit 2: SpaceLayout 集成目录条带化**

**Goal:** 在 SpaceLayout::Setup() 中调用目录条带化设置

**Requirements:** R1, R2, R4, R5, R7

**Dependencies:** Unit 1

**Files:**
- Modify: `ucm/store/lustre/cc/space_layout.h`
- Modify: `ucm/store/lustre/cc/space_layout.cc`
- Test: `ucm/store/test/case/lustre/space_layout_test.cc` (extend existing tests)

**Approach:**
- 在 `SpaceLayout` 类添加 `int stripeCount_` 和 `size_t stripeSize_` 成员
- 在 `Setup()` 方法中接收 config 的条带参数
- 创建 `/data` 目录后，检查 `stripeCount_ > 0`
- 若条件满足，调用 `LustreFile::SetStripedDirectory()`
- 传递 `stripeCount_` 和 `stripeSize_` 参数

**Technical design:**
```cpp
// Directional guidance for Setup() modification
Status SpaceLayout::Setup(const Config& config) {
    // ... existing backend setup ...
    
    // Store stripe config
    stripeCount_ = config.stripeCount;
    stripeSize_ = config.stripeSize;
    
    for (const auto& backend : storageBackends_) {
        std::string dataDir = backend + "/data";
        
        // IMPORTANT: llapi_layout_file_create() creates the directory itself
        // When stripeCount > 0, use SetStripedDirectory which internally creates dir
        // When stripeCount == 0, use normal MkDir
        
        if (stripeCount_ > 0) {
            // SetStripedDirectory creates dir with stripe attributes
            if (auto s = LustreFile::SetStripedDirectory(
                    dataDir, stripeCount_, stripeSize_, 0755); 
                s.Failure()) {
                UC_WARN("Failed to set stripe on {}: {}", dataDir, s.ToString());
                // Fallback: create normal directory
                if (auto s2 = LustreFile::MkDir(dataDir, 0755); s2.Failure()) {
                    return s2;  // Only fail if both striping and normal mkdir fail
                }
            }
        } else {
            // No striping, use normal directory creation
            if (auto s = LustreFile::MkDir(dataDir, 0755); s.Failure()) {
                return s;
            }
        }
    }
    return Status::OK();
}
```

**Patterns to follow:**
- 参照 `space_layout.cc:97-129` 现有目录创建逻辑
- 遵循配置参数传递模式（如 `dataDirShardBytes_` 的处理方式）

**Test scenarios:**
- **Happy path**: stripeCount=4, stripeSize=1048576 → 目录创建成功，Setup 返回 OK
- **Happy path**: stripeCount=0 → 跳过条带化，使用 MkDir 创建普通目录
- **Edge case**: 多个 storage backend → 每个目录都被正确处理
- **Error path**: SetStripedDirectory 失败 → 记录警告，回退到普通目录创建，Setup 返回 OK
- **Integration**: 验证后续创建的文件继承了目录条带属性

**Verification:**
- C++ 单元测试覆盖各种配置组合
- 验证目录创建和条带化设置的调用顺序

- [ ] **Unit 3: Python 测试验证**

**Goal:** 添加 Python 测试验证条带化功能端到端

**Requirements:** R1, R2, R3, R5, R8

**Dependencies:** Unit 1, Unit 2

**Files:**
- Create: `test/suites/Unit/test_lustre_p3_striping.py`

**Approach:**
- 创建新的 P3 阶段测试文件（按项目测试阶段命名约定）
- 使用 pytest fixture 创建测试配置
- 测试有/无条带配置的场景
- 验证数据目录创建和文件继承

**Patterns to follow:**
- 参考 `test_lustre_p0_infrastructure.py` 的 fixture 模式
- 参考 `test_lustre_p1_data_transfer.py` 的测试结构

**Test scenarios:**
- **Happy path**: config={"stripe_count": 4, "stripe_size": 1048576} → 目录创建成功
- **Happy path**: config={"stripe_count": 0} → 普通目录创建（无条带化）
- **Integration**: 创建测试文件，运行 `lfs getstripe <file>` 验证 stripe_count == 4
- **Integration**: stripe_count=0 时，`lfs getstripe` 显示系统默认值
- **Error path**: HAVE_LUSTRE_API 未定义时，Setup 正常完成，文件正常创建

**Verification:**
- 所有测试用例通过
- 在真实 Lustre 环境中验证文件条带属性继承

- [ ] **Unit 4: Python 连接器文档更新**

**Goal:** 更新 Python 连接器的配置文档

**Requirements:** R4, R6

**Dependencies:** Unit 1, Unit 2

**Files:**
- Modify: `ucm/store/lustre/lustre_connector.py`

**Approach:**
- 在类的 docstring 中确认 `stripe_count` 和 `stripe_size` 配置项已存在
- 更新 docstring 说明：当 `stripe_count > 0` 时，数据目录将使用条带化
- 添加配置示例说明有效配置值和预期的性能影响
- 说明如何验证条带化是否生效（使用 `lfs getstripe` 命令）
- 配置项字段已存在，无需添加新字段

**Patterns to follow:**
- 参照 `lustre_connector.py:70-71` 现有条带配置文档格式

**Test scenarios:**
- Test expectation: none -- documentation only change

**Verification:**
- 文档描述与实现行为一致
- 配置项类型和默认值描述正确

## System-Wide Impact

- **Interaction graph:** 无回调或中间件影响，修改限定在 SpaceLayout 初始化阶段
- **Error propagation:** 条带化设置失败不影响后续初始化流程，Setup 仍返回成功
- **State lifecycle risks:** 无状态变更风险，目录创建是一次性操作
- **API surface parity:** Python 连接器 API 无变化，仅行为增强
- **Integration coverage:** 需要端到端测试验证文件实际继承了条带属性（Unit 3）

## Risks & Dependencies

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Lustre API 调用失败导致 Setup 失败 | Low | Medium | 失败时记录警告继续运行，目录仍可正常使用 |
| 非 Lustre 环境编译失败 | Low | Low | HAVE_LUSTRE_API 宏保护，自动回退 |
| 条带参数配置不合理导致性能下降 | Medium | Low | 用户负责配置，系统记录异常值警告 |
| 文件未正确继承目录条带属性 | Medium | Medium | 测试验证继承机制，记录属性到日志 |
| 配置迁移导致性能不一致 | Medium | Low | 启动时记录目录条带状态，文档说明迁移路径 |

## Documentation / Operational Notes

- **配置说明**: 用户通过 `stripe_count` 和 `stripe_size` 配置项控制条带化
- **日志输出**: 成功设置时记录 INFO 级别日志，失败时记录 WARN 级别日志
- **验证方法**:
  - 目录: `lfs getstripe -c <directory>` 查看目录默认条带属性
  - 文件: `lfs getstripe <file>` 验证文件是否继承目录条带属性
  - 预期输出显示 stripe_count == 配置值

## Sources & References

- **Origin document:** [docs/brainstorms/2026-04-02-lustre-striping-requirements.md](docs/brainstorms/2026-04-02-lustre-striping-requirements.md)
- Related code: [ucm/store/lustre/cc/lustre_file.cc](ucm/store/lustre/cc/lustre_file.cc), [ucm/store/lustre/cc/space_layout.cc](ucm/store/lustre/cc/space_layout.cc)
- External docs: Lustre `llapi_layout` API (man 7 llapi_layout, lfs-setdirstripe)
