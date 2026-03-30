# UCM 与 vLLM 集成机制详解

## 1. 集成架构概览

```mermaid
graph TB
    subgraph "用户启动命令"
        Cmd[vllm serve --kv-transfer-config]
    end

    subgraph "vLLM 框架"
        direction TB
        VLLMInit[vLLM 初始化]
        KVConnectorReg[KVConnector 注册表]
        Scheduler[Scheduler]
        ModelRunner[ModelRunner]
        AttentionLayer[Attention Layer]
    end

    subgraph "UCM 集成层"
        direction TB
        UCMInit[ucm/__init__.py<br/>自动执行]
        PatchApply[apply_patch.py<br/>Monkey Patch]
        UCMConnector[UCMDirectConnector<br/>继承 KVConnectorBase_V1]
    end

    subgraph "UCM 核心功能"
        Store[UcmKVStore<br/>存储后端]
        Sparse[UcmSparse<br/>稀疏注意力]
    end

    Cmd --> VLLMInit
    VLLMInit --> KVConnectorReg
    UCMInit --> PatchApply
    PatchApply --> Scheduler
    PatchApply --> ModelRunner
    PatchApply --> AttentionLayer
    KVConnectorReg --> UCMConnector
    UCMConnector --> Store
    UCMConnector --> Sparse

    style UCMInit fill:#90EE90
    style PatchApply fill:#90EE90
    style UCMConnector fill:#90EE90
```

## 2. 三种集成方式

### 方式一：继承 vLLM 基类

UCM 的 [`UCMDirectConnector`](../../ucm/integration/vllm/ucm_connector.py:82) 继承自 vLLM 的 `KVConnectorBase_V1`：

```python
# ucm/integration/vllm/ucm_connector.py
from vllm.distributed.kv_transfer.kv_connector.v1.base import (
    KVConnectorBase_V1,
    KVConnectorMetadata,
    KVConnectorRole,
)

class UCMDirectConnector(KVConnectorBase_V1):
    """
    This connector means synchronize:
    load -> forward -> save
    """
    def __init__(self, vllm_config: "VllmConfig", role: KVConnectorRole):
        super().__init__(vllm_config=vllm_config, role=role)
        # UCM 特有初始化
        self.store: UcmKVStoreBaseV1  # 存储后端
        ...
```

### 方式二：Monkey Patching

通过 [`apply_patch.py`](../../ucm/integration/vllm/patch/apply_patch.py) 动态修改 vLLM 的行为：

```python
# ucm/__init__.py - 自动执行
try:
    from ucm.integration.vllm.patch.apply_patch import (
        ensure_patches_applied,
        get_vllm_version,
    )
    if get_vllm_version() == "0.11.0":
        ensure_patches_applied()  # 应用所有 patch
except Exception as e:
    warnings.warn(f"Failed to apply vLLM patches: {e}")
```

**Patch 的主要内容：**

| Patch 目标 | 文件 | 作用 |
|-----------|------|------|
| SchedulerOutput | [`vllm_patch.py`](../../ucm/integration/vllm/patch/patch_funcs/v092/vllm_patch.py:79) | 添加 `kv_connector_metadata` 字段 |
| Attention Layer | [`vllm_patch.py`](../../ucm/integration/vllm/patch/patch_funcs/v092/vllm_patch.py:141) | 注入 `attention_begin/finished` hook |
| ModelRunner | [`vllm_patch.py`](../../ucm/integration/vllm/patch/patch_funcs/v092/vllm_patch.py) | 注入 `execute_begin/finished` hook |
| Scheduler | [`vllm_patch.py`](../../ucm/integration/vllm/patch/patch_funcs/v092/vllm_patch.py) | 注入调度决策 hook |

### 方式三：配置注入

通过 `--kv-transfer-config` 参数将 UCM 配置传入 vLLM：

```bash
vllm serve /path/to/model \
    --kv-transfer-config '{
        "kv_connector": "UCMConnector",
        "kv_connector_module_path": "ucm.integration.vllm.ucm_connector",
        "kv_role": "kv_producer",
        "kv_connector_extra_config": {
            "ucm_connector_name": "UcmNfsStore",
            "ucm_connector_config": {
                "storage_backends": "/mnt/nfs",
                "transferStreamNumber": 32
            }
        }
    }'
```

**配置解析流程：**

```mermaid
sequenceDiagram
    participant CLI as 命令行
    participant VLLM as vLLM Config
    participant Factory as UCMConnectorFactory
    participant Connector as UCMDirectConnector
    participant Store as UcmKVStore

    CLI->>VLLM: --kv-transfer-config JSON
    VLLM->>Factory: 根据 kv_connector 名称查找
    Factory->>Connector: 创建 UCMDirectConnector 实例
    Connector->>Store: 根据 ucm_connector_name 创建存储后端
    Store-->>Connector: 返回存储实例
    Connector-->>VLLM: 返回连接器实例
```

## 3. Hook 注入点详解

### 3.1 Scheduler 端 Hook

```mermaid
graph LR
    subgraph "Scheduler 流程"
        A[add_request] --> B[schedule]
        B --> C[finish_requests]
    end

    subgraph "UCM Hook"
        H1[request_begin]
        H2[get_num_new_matched_tokens]
        H3[build_connector_meta]
    end

    A -.-> H1
    B -.-> H2
    C -.-> H3
```

**代码示例：**

```python
# vLLM Scheduler 原始代码被 patch 后
def add_request(self, request):
    # UCM Hook: 计算外部存储命中
    if self.kv_connector:
        external_tokens, _ = self.kv_connector.get_num_new_matched_tokens(
            request, num_computed_tokens
        )
    # 原始逻辑...
```

### 3.2 Worker 端 Hook

```mermaid
graph TB
    subgraph "ModelRunner.execute_model"
        E1[execute_begin] --> E2[层循环]
        E2 --> L1[layer_begin]
        L1 --> A1[attention_begin]
        A1 --> Attn[注意力计算]
        Attn --> A2[attention_finished]
        A2 --> L2[layer_finished]
        L2 --> E2
        E2 --> E3[execute_finished]
    end

    subgraph "UCM Hook 点"
        H1[start_load_kv]
        H2[attention_begin]
        H3[attention_finished]
        H4[save_kv_caches]
    end

    E1 -.-> H1
    A1 -.-> H2
    A2 -.-> H3
    E3 -.-> H4
```

**Attention Layer Patch 示例：**

```python
# ucm/integration/vllm/patch/patch_funcs/v092/vllm_patch.py
def attn_forward(self, query, key, value, output_shape=None):
    # UCM Hook: attention_begin
    if has_ucm_sparse():
        ucm_sparse = get_ucm_sparse()
        query, key, value, output = ucm_sparse.attention_begin(
            query, key, value, layer_name, forward_context
        )

    # 原始注意力计算
    output = unified_attention_with_output(...)

    # UCM Hook: attention_finished
    if has_ucm_sparse():
        ucm_sparse.attention_finished(query, key, value, output, ...)

    return output
```

## 4. 数据流完整流程

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant VLLM as vLLM API Server
    participant Sched as Scheduler
    participant UCM as UCMConnector
    participant Store as UcmKVStore
    participant Worker as Worker/ModelRunner
    participant GPU as GPU

    Note over Client,GPU: 1. 请求接收阶段
    Client->>VLLM: POST /v1/completions
    VLLM->>Sched: add_request(request)

    Note over Sched,Store: 2. Scheduler 端处理
    Sched->>UCM: get_num_new_matched_tokens()
    UCM->>Store: lookup(block_ids)
    Store-->>UCM: [True, True, False, ...]
    UCM-->>Sched: external_hit_tokens=256

    Note over Sched,Worker: 3. 调度阶段
    Sched->>UCM: build_connector_meta()
    UCM-->>Sched: UCMConnectorMetadata
    Sched->>Worker: SchedulerOutput (含 metadata)

    Note over Worker,GPU: 4. Worker 端执行
    Worker->>UCM: bind_connector_metadata()
    Worker->>UCM: start_load_kv()
    UCM->>Store: load_data(block_ids, ptrs)
    Store->>GPU: DMA 传输 KV 缓存
    Store-->>UCM: Task 完成
    UCM->>Worker: wait_for_load()

    Worker->>GPU: execute_model()
    GPU-->>Worker: logits

    Worker->>UCM: save_kv_caches()
    UCM->>Store: dump_data(block_ids, ptrs)
    Store-->>UCM: Task 完成

    Note over Worker,Client: 5. 响应返回
    Worker-->>Sched: 输出结果
    Sched-->>VLLM: 生成文本
    VLLM-->>Client: HTTP Response
```

## 5. 关键类关系图

```mermaid
classDiagram
    class KVConnectorBase_V1 {
        <<vLLM>>
        +vllm_config: VllmConfig
        +role: KVConnectorRole
        +get_num_new_matched_tokens()
        +build_connector_meta()
    }

    class UCMDirectConnector {
        +store: UcmKVStoreBaseV1
        +requests_meta: dict
        +request_hasher: RequestHasher
        +get_num_new_matched_tokens()
        +build_connector_meta()
        +start_load_kv()
        +save_kv_caches()
    }

    class UCMLayerWiseConnector {
        +load_tasks: dict
        +dump_tasks: list
        +use_layerwise: bool
    }

    class UcmKVStoreBaseV1 {
        <<abstract>>
        +lookup()
        +load()
        +dump()
        +wait()
    }

    class UcmPcStoreV1 {
        +cc_store()
        +lookup()
        +load_data()
        +dump_data()
    }

    class UcmSparseBase {
        <<abstract>>
        +attention_begin()
        +attention_finished()
        +execute_begin()
        +execute_finished()
    }

    KVConnectorBase_V1 <|-- UCMDirectConnector
    UCMDirectConnector <|-- UCMLayerWiseConnector
    UCMDirectConnector --> UcmKVStoreBaseV1 : uses
    UcmKVStoreBaseV1 <|-- UcmPcStoreV1
    UCMDirectConnector --> UcmSparseBase : optionally uses
```

## 6. 启动流程时序

```mermaid
sequenceDiagram
    participant User as 用户
    participant Bash as Shell
    participant Python as Python VM
    participant UCM as ucm/__init__.py
    participant Patch as apply_patch.py
    participant VLLM as vLLM
    participant Conn as UCMConnector

    User->>Bash: vllm serve --kv-transfer-config
    Bash->>Python: python -m vllm.entrypoints.openai.api_server

    Note over Python,UCM: import ucm 时自动执行
    Python->>UCM: import ucm
    UCM->>Patch: ensure_patches_applied()
    Patch->>VLLM: Monkey Patch vLLM 类
    Patch-->>UCM: patches applied

    Note over Python,Conn: vLLM 初始化
    Python->>VLLM: Engine 初始化
    VLLM->>Conn: 根据 kv_connector 配置创建实例
    Conn->>Conn: _create_store()
    Conn-->>VLLM: connector ready

    VLLM-->>User: Server ready on port 8000
```

## 7. 总结

UCM 与 vLLM 的集成通过三个层次实现：

| 层次 | 机制 | 作用 |
|------|------|------|
| **配置层** | `--kv-transfer-config` | 声明式指定 UCM 组件 |
| **继承层** | `KVConnectorBase_V1` | 实现 vLLM 定义的接口 |
| **Patch层** | Monkey Patching | 在关键路径注入 UCM 逻辑 |

这种设计使得 UCM 能够：
1. **非侵入式集成**：不需要修改 vLLM 源码
2. **灵活配置**：通过配置文件选择不同的存储后端和稀疏算法
3. **版本兼容**：针对不同 vLLM 版本提供不同的 patch
