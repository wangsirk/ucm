# UCM 整体组件介绍 PPT 大纲

## PPT 概述
- **主题**: UCM (Unified Cache Management) 整体组件介绍
- **页数**: 2-3页
- **目标受众**: 技术团队/管理层

---

## 第1页：UCM 概述与核心价值

### 标题
**统一缓存管理器 (UCM) - LLM推理加速框架**

### 核心内容

#### 什么是UCM？
- **定义**: 统一缓存管理器（Unified Cache Management）
- **核心原理**: 持久化LLM的KVCache，通过多种检索机制替代冗余计算
- **性能提升**: 与vLLM集成后，推理延迟降低 **3-10倍**

#### 核心价值
| 场景 | 效果 |
|------|------|
| 多轮对话 | 显著降低首Token延迟 |
| 长上下文推理 | 支持超长序列处理 |
| 异构计算资源 | 灵活管理PD分离架构 |

#### 支持特性
- ✅ 前缀缓存 (Prefix Cache)
- ✅ 缓存融合 (Cache Blend)
- ✅ 稀疏注意力 (Sparse Attention)
- ✅ 预填充卸载 (Prefill Offload)
- ✅ 异构PD分离 (PD Disaggregation)

### 建议配图
- 使用 `docs/source/_static/images/idea.png` 展示整体架构理念

---

## 第2页：UCM 系统架构

### 标题
**UCM 分层架构设计**

### 架构层次与数据流向

```
┌─────────────────────────────────────────────────────────────┐
│                    vLLM 框架层 (v0.9.2+)                      │
│   Scheduler │ ModelRunner │ unified_attention │ KVCacheManager │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                   UCM 核心协调层                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              UCMDirectConnector                       │   │
│  │        (中心协调器 - 继承自 KVConnectorBase_V1)         │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                    ↙                      ↘
┌──────────────────────────┐    ┌──────────────────────────────┐
│    稀疏注意力算法层        │    │        存储后端层             │
│  ┌──────────────────┐    │    │  ┌────────────────────┐      │
│  │ UcmSparseFactory │    │    │  │UcmConnectorFactoryV1│      │
│  │   (稀疏算法工厂)   │    │    │  │   (存储连接器工厂)    │      │
│  └──────────────────┘    │    │  └────────────────────┘      │
│           ↓              │    │            ↓                 │
│  ┌─────┐ ┌─────┐ ┌─────┐ │    │  ┌─────┐ ┌─────────┐ ┌────┐ │
│  │ ESA │ │ GSA │ │KVStar│ │    │  │ NFS │ │ Pipeline│ │Lustre│ │
│  │     │ │     │ │Blend │ │    │  │Store│ │  Store  │ │Store│ │
│  └─────┘ └─────┘ └─────┘ │    │  └─────┘ └─────────┘ └────┘ │
└──────────────────────────┘    └──────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                      外部存储                                │
│       本地文件系统 │ NFS │ Lustre │ 分布式存储               │
└─────────────────────────────────────────────────────────────┘
```

### 数据流向说明

**请求处理流程：**
1. **vLLM → UCMDirectConnector**: Scheduler/ModelRunner 调用 UCM 连接器
2. **UCMDirectConnector 并行调用两个工厂**:
   - → `UcmSparseFactory`: 获取/创建稀疏算法实例
   - → `UcmConnectorFactoryV1`: 获取/创建存储实例
3. **算法层与存储层协作**: 稀疏算法通过存储接口读写 KV Cache

### 核心组件说明

| 组件 | 职责 |
|------|------|
| **UCMDirectConnector** | 连接vLLM与UCM，管理KV缓存的加载/保存 |
| **UcmSparseBase** | 稀疏算法基类，定义统一的算法接口 |
| **UcmKVStoreBaseV1** | 存储抽象基类，解耦算法与存储 |

### 建议配图
- 使用 `docs/source/_static/images/ucm_store_architecture.png`

---

## 第3页：核心功能与典型应用场景

### 标题
**UCM 核心功能与应用场景**

### 左侧：稀疏注意力算法对比

| 算法 | 特点 | 适用场景 |
|------|------|----------|
| **ESA** | 精确稀疏注意力 | 长序列检索任务 |
| **GSA** | 设备端全局稀疏 | GPU加速场景 |
| **KVStar** | 多步分层检索 | 分层检索需求 |
| **Blend** | 缓存融合 | Prefix Cache优化 |

### 右侧：PD分离架构

```
┌──────────────────┐         ┌──────────────────┐
│  Prefill节点 (P)  │         │  Decode节点 (D)   │
│  ┌────────────┐  │         │  ┌────────────┐  │
│  │  Scheduler │  │         │  │  Scheduler │  │
│  │  ModelRunner│  │         │  │  ModelRunner│  │
│  │  UCM Conn  │──┼─────────┼─→│  UCM Conn  │  │
│  └────────────┘  │         │  └────────────┘  │
└──────────────────┘         └──────────────────┘
         │                           │
         └───────────┬───────────────┘
                     ↓
         ┌───────────────────────┐
         │    共享存储层 (UCM)    │
         │  NFS / Lustre / DS3FS │
         └───────────────────────┘
```

### 典型应用场景

1. **多轮对话系统**
   - 利用前缀缓存复用历史KV
   - 降低TTFT（首Token延迟）

2. **长文档问答**
   - 稀疏注意力减少显存占用
   - 支持超长上下文处理

3. **异构推理集群**
   - PD分离实现计算资源解耦
   - Prefill/Decode独立扩展

### 性能数据参考
- 推理延迟降低: **3-10x**
- 支持vLLM版本: **v0.9.2**

### 建议配图
- 使用 `docs/source/_static/images/pd_disaggregation.jpg`
- 使用 `docs/source/_static/images/prefix_cache.jpg`

---

## PPT 制作建议

### 配色方案
- 主色调: 绿色系（与UCM Logo一致）
- 辅助色: 蓝色、灰色
- 背景: 白色或浅灰

### 可用图片资源
| 图片路径 | 用途 |
|----------|------|
| `docs/source/logos/UCM-light.png` | 封面Logo |
| `docs/source/_static/images/idea.png` | 架构理念图 |
| `docs/source/_static/images/ucm_store_architecture.png` | 存储架构图 |
| `docs/source/_static/images/pd_disaggregation.jpg` | PD分离示意图 |
| `docs/source/_static/images/prefix_cache.jpg` | 前缀缓存示意图 |

### 关键信息强调
- **3-10x** 性能提升（用大字体/高亮）
- **vLLM v0.9.2** 兼容版本
- **无需训练** (training-free) 的稀疏注意力

---

## 附录：技术细节（可选补充页）

### 存储操作接口
```python
class UcmKVStoreBaseV1:
    def lookup(block_ids)    # 查找块是否存在
    def prefetch(block_ids)  # 异步预取
    def load(block_ids)      # 加载KV缓存
    def dump(block_ids)      # 转储KV缓存
    def wait(task)           # 等待任务完成
```

### 请求处理流程
1. 客户端发送请求
2. Scheduler调用 `request_begin()` 查询缓存
3. 命中: 加载KV → 跳过计算
4. 未命中: 正常计算 → 保存KV
5. 返回响应

---

*文档生成时间: 2026-03-27*
*UCM版本: 基于 main/develop 分支*
