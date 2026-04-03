---
date: 2026-04-02
topic: lustre-striping
---

# Lustre Store 条带化支持

## Problem Frame

Lustre Store 当前已实现了 `CreateStriped()` API，但在实际文件创建时使用的是 `CreateNormal()`，未启用 Lustre 并行文件系统的条带化能力。这导致：
- 多 OST (Object Storage Target) 无法并行服务同一文件
- 大文件读写吞吐量受限
- 未充分利用 Lustre 集群的并行能力

启用条带化后，单个文件的数据可以分散到多个 OST 上，实现并行读写，显著提升大文件场景的性能。

## Requirements

**文件创建策略**
- R1. 使用目录级条带化属性设置，而非为每个文件单独设置
- R2. 在 SpaceManager 初始化时为数据根目录设置默认条带属性
- R3. 该目录下创建的所有文件自动继承条带属性

**条带参数策略**
- R4. 优先使用用户配置的 `stripe_count` 和 `stripe_size`
- R5. 若用户配置为 0 或未配置，直接使用标准 `mkdir` 创建目录（Lustre 使用文件系统默认行为）
- R6. 配置值通过现有 Config 结构体传递（已存在 `stripeCount` 和 `stripeSize` 字段）
- R7. 仅当用户配置了非零条带参数时，才调用 `llapi_layout_*` API 设置目录属性

**兼容性处理**
- R8. 仅在 Lustre 文件系统上启用条带化（通过 HAVE_LUSTRE_API 宏控制）
- R9. 非 Lustre 环境或 API 不可用时，回退到普通文件创建
- R10. 目录条带化设置失败时记录警告但继续运行（不影响功能）

## Success Criteria
- [ ] 数据根目录成功设置条带化属性（当配置指定时）
- [ ] 创建的新文件自动继承目录的条带属性
- [ ] 配置为 0 时使用 Lustre 默认值（不强制指定）
- [ ] 非 Lustre 环境正常回退，不影响功能

## Scope Boundaries
- **不在范围内**:
  - 运行时动态调整条带参数
  - 为不同文件设置不同条带策略
  - 自动探测 OST 数量并计算最佳参数（由用户配置或系统默认）
  - 复合条带布局（Composite Layout）

## Key Decisions
- **目录级设置 vs 文件级设置**: 选择目录级设置，利用 Lustre 继承机制，减少文件创建开销
- **配置策略**: 有配置时设置目录条带属性，无配置时使用标准 mkdir（Lustre 默认行为）
- **失败处理**: 目录条带化设置失败时记录警告而非报错，保证系统可用性

## Dependencies / Assumptions
- 依赖 Lustre liblustreapi 提供的 `llapi_layout_*` API（仅当用户配置了条带参数时）
- 假设数据根目录在 SpaceManager::Setup() 时已创建
- 假设用户提供的条带参数在合理范围内（异常值应记录警告日志）

## Outstanding Questions

### Resolve Before Planning
无

### Deferred to Planning
- [Affects R2][Technical] `llapi_layout_file_create()` 设置目录条带属性的具体调用方式
- [Affects R2][Needs research] 验证目录条带属性设置后，新创建文件是否正确继承
