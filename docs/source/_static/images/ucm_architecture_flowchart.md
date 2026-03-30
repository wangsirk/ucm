# UCM 整体框架流程图

## 1. 系统架构总览

```mermaid
graph TB
    subgraph "vLLM 框架 (v0.9.2+)"
        Scheduler[Scheduler<br/>调度器]
        ModelRunner[ModelRunner<br/>模型执行器]
        Attention[unified_attention<br/>统一注意力层]
        KVCacheManager[KVCacheManager<br/>缓存管理器]
    end

    subgraph "UCM 核心层"
        UcmConnector[UCMDirectConnector<br/>UCM连接器]
        SparseFactory[UcmSparseFactory<br/>稀疏算法工厂]
        StoreFactory[UcmConnectorFactoryV1<br/>存储连接器工厂]
    end

    subgraph "稀疏注意力算法层"
        UcmSparseBase[UcmSparseBase<br/>稀疏算法基类]
        ESA[ESA<br/>精确稀疏注意力]
        GSA[GSAOnDevice<br/>设备端全局稀疏注意力]
        KVStar[KVStarMultiStep<br/>KVStar多步检索]
        Blend[Blend<br/>缓存融合]
    end

    subgraph "存储后端层"
        UcmKVStoreBase[UcmKVStoreBaseV1<br/>存储抽象基类]
        NFSStore[UcmNfsStore<br/>NFS存储]
        PipelineStore[UcmPipelineStore<br/>流水线存储]
        LustreStore[UcmLustreStore<br/>Lustre存储]
    end

    subgraph "外部存储"
        LocalFS[本地文件系统]
        NFS[NFS挂载点]
        Lustre[Lustre并行文件系统]
    end

    %% vLLM -> UCM 连接
    Scheduler --> UcmConnector
    ModelRunner --> UcmConnector
    Attention --> UcmConnector
    KVCacheManager --> UcmConnector

    %% UCM 核心连接
    UcmConnector --> SparseFactory
    UcmConnector --> StoreFactory

    %% 稀疏算法工厂连接
    SparseFactory --> UcmSparseBase
    UcmSparseBase --> ESA
    UcmSparseBase --> GSA
    UcmSparseBase --> KVStar
    UcmSparseBase --> Blend

    %% 存储工厂连接
    StoreFactory --> UcmKVStoreBase
    UcmKVStoreBase --> NFSStore
    UcmKVStoreBase --> PipelineStore
    UcmKVStoreBase --> LustreStore

    %% 存储后端连接
    NFSStore --> LocalFS
    NFSStore --> NFS
    LustreStore --> Lustre

    style UcmConnector fill:#90EE90
    style SparseFactory fill:#90EE90
    style StoreFactory fill:#90EE90
    style UcmSparseBase fill:#98FB98
    style UcmKVStoreBase fill:#98FB98
```

## 2. 请求处理流程

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant Scheduler as vLLM Scheduler
    participant UcmConn as UCM Connector
    participant Sparse as UcmSparseBase
    participant Store as UcmKVStoreBase
    participant Storage as 外部存储
    participant Worker as Worker进程
    participant Model as ModelRunner

    %% 请求开始阶段
    Client->>Scheduler: 发送请求
    Scheduler->>UcmConn: request_begin()
    UcmConn->>Store: lookup(block_ids)
    Store-->>UcmConn: 返回命中信息
    
    %% 调度阶段
    Scheduler->>Sparse: estimate_num_slots_sparsed()
    Sparse-->>Scheduler: 返回所需slot数量
    Scheduler->>Sparse: update_state_after_alloc()
    Scheduler->>UcmConn: build_connector_meta()
    
    %% Worker执行阶段
    Scheduler->>Worker: 发送SchedulerOutput
    Worker->>UcmConn: bind_connector_metadata()
    Worker->>UcmConn: start_load_kv()
    UcmConn->>Store: load(block_ids, tensors)
    Store->>Storage: 读取KV缓存
    Storage-->>Store: 返回数据
    Store-->>UcmConn: Task完成
    UcmConn->>Worker: wait_for_load()
    
    %% 模型执行阶段
    Worker->>Model: execute_model()
    Model->>Sparse: attention_begin()
    Sparse->>Sparse: 修改attn_metadata
    Model->>Sparse: attention_finished()
    Model-->>Worker: 返回logits
    
    %% 请求结束阶段
    Worker->>UcmConn: request_finished()
    UcmConn->>Store: dump(block_ids, tensors)
    Store->>Storage: 写入KV缓存
    Scheduler->>Sparse: request_finished_in_scheduler()
    Scheduler-->>Client: 返回响应
```

## 3. UcmSparseBase 双端架构

```mermaid
graph LR
    subgraph "Scheduler进程"
        direction TB
        SchedMethods[Scheduler端方法]
        SchedMethods --> request_begin
        SchedMethods --> estimate_num_slots_sparsed
        SchedMethods --> update_state_after_alloc
        SchedMethods --> build_sparse_meta
        SchedMethods --> request_finished_in_scheduler
    end

    subgraph "Worker进程"
        direction TB
        WorkerMethods[Worker端方法]
        WorkerMethods --> execute_begin
        WorkerMethods --> execute_finished
        WorkerMethods --> attention_begin
        WorkerMethods --> attention_finished
        WorkerMethods --> layer_begin/layer_finished
        WorkerMethods --> ffn_begin/ffn_finished
        WorkerMethods --> request_finished_in_worker
    end

    subgraph "通信机制"
        Metadata[UcmSparseMetadata<br/>元数据传递]
    end

    SchedMethods --> Metadata
    Metadata --> WorkerMethods

    style SchedMethods fill:#E6E6FA
    style WorkerMethods fill:#FFE4E1
    style Metadata fill:#FFFACD
```

## 4. 存储层操作流程

```mermaid
graph TB
    subgraph "存储操作接口"
        Lookup[lookup<br/>查找块是否存在]
        Prefetch[prefetch<br/>异步预取]
        Load[load<br/>加载KV缓存]
        Dump[dump<br/>转储KV缓存]
        Wait[wait<br/>等待任务完成]
        Check[check<br/>检查任务状态]
    end

    subgraph "数据流向"
        direction LR
        GPU[GPU显存]
        CPU[CPU内存]
        Storage[外部存储]
    end

    subgraph "任务管理"
        Task[Task异步任务句柄]
    end

    %% 查找流程
    Lookup --> Storage
    
    %% 预取流程
    Prefetch --> CPU
    
    %% 加载流程
    Load --> CPU
    CPU --> GPU
    Load --> Task
    
    %% 转储流程
    Dump --> GPU
    GPU --> CPU
    CPU --> Storage
    Dump --> Task
    
    %% 任务管理
    Task --> Wait
    Task --> Check

    style Lookup fill:#87CEEB
    style Prefetch fill:#87CEEB
    style Load fill:#90EE90
    style Dump fill:#FFB6C1
    style Task fill:#DDA0DD
```

## 5. 稀疏注意力算法选择

```mermaid
graph LR
    subgraph "配置文件"
        Config[ucm_config.yaml]
    end

    subgraph "工厂模式"
        Factory[UcmSparseFactory]
    end

    subgraph "算法实现"
        ESA[ESA<br/>精确稀疏注意力<br/>适合长序列检索]
        GSA[GSAOnDevice<br/>设备端全局稀疏<br/>适合GPU加速]
        KVStar[KVStarMultiStep<br/>多步检索<br/>适合分层检索]
        Blend[Blend<br/>缓存融合<br/>适合Prefix Cache]
    end

    Config --> Factory
    Factory --> ESA
    Factory --> GSA
    Factory --> KVStar
    Factory --> Blend

    style Factory fill:#98FB98
    style ESA fill:#87CEEB
    style GSA fill:#87CEEB
    style KVStar fill:#87CEEB
    style Blend fill:#87CEEB
```

## 6. PD分离架构

```mermaid
graph TB
    subgraph "Prefill节点 (P)"
        P_Scheduler[Scheduler]
        P_Model[ModelRunner]
        P_UcmConn[UCM Connector]
        P_Sparse[UcmSparse]
    end

    subgraph "Decode节点 (D)"
        D_Scheduler[Scheduler]
        D_Model[ModelRunner]
        D_UcmConn[UCM Connector]
        D_Sparse[UcmSparse]
    end

    subgraph "共享存储层"
        SharedStore[UCM KV Store]
    end

    subgraph "外部存储"
        ExternalStorage[分布式存储<br/>NFS/Lustre]
    end

    %% Prefill流程
    P_Scheduler --> P_UcmConn
    P_Model --> P_Sparse
    P_Sparse --> P_UcmConn
    P_UcmConn --> SharedStore

    %% Decode流程
    D_Scheduler --> D_UcmConn
    D_Model --> D_Sparse
    D_Sparse --> D_UcmConn
    D_UcmConn --> SharedStore

    %% 共享存储
    SharedStore <--> ExternalStorage

    style P_UcmConn fill:#90EE90
    style D_UcmConn fill:#90EE90
    style SharedStore fill:#87CEEB
```

## 7. 核心类继承关系

```mermaid
classDiagram
    class KVConnectorBase_V1 {
        <<vLLM抽象类>>
        +vllm_config: VllmConfig
        +role: KVConnectorRole
    }

    class UCMDirectConnector {
        +store: UcmKVStoreBaseV1
        +requests_meta: dict
        +request_hasher: RequestHasher
        +start_load_kv()
        +wait_for_load()
        +save_kv_caches()
    }

    class UcmSparseBase {
        <<抽象类>>
        +role: UcmSparseRole
        +request_begin()
        +attention_begin()
        +attention_finished()
        +execute_begin()
        +execute_finished()
    }

    class ESA {
        +retrieval_worker
        +attention_begin()
        +execute_finished()
    }

    class GSAOnDevice {
        +hash_encoder
        +hamming_topk
        +attention_begin()
    }

    class KVStarMultiStep {
        +retrieve_impl
        +multistep_retrieve()
    }

    class Blend {
        +blockwise_rope
        +attention_begin()
    }

    class UcmKVStoreBaseV1 {
        <<抽象类>>
        +lookup()
        +prefetch()
        +load()
        +dump()
        +wait()
        +check()
    }

    class UcmPcStoreV1 {
        +cc_store()
        +lookup()
        +load()
        +dump()
    }

    class UcmPipelineStore {
        +cc_store()
        +lookup()
        +load()
        +dump()
    }

    class UcmLustreStore {
        +cc_store()
        +lookup()
        +load()
        +dump()
    }

    KVConnectorBase_V1 <|-- UCMDirectConnector
    UcmSparseBase <|-- ESA
    UcmSparseBase <|-- GSAOnDevice
    UcmSparseBase <|-- KVStarMultiStep
    UcmSparseBase <|-- Blend
    UcmKVStoreBaseV1 <|-- UcmPcStoreV1
    UcmKVStoreBaseV1 <|-- UcmPipelineStore
    UcmKVStoreBaseV1 <|-- UcmLustreStore
    UCMDirectConnector --> UcmKVStoreBaseV1 : uses
    UCMDirectConnector --> UcmSparseBase : uses
```

## 8. 数据流详细流程

```mermaid
flowchart TD
    Start([请求开始]) --> Hash[计算Block Hash]
    Hash --> Lookup{查询存储}
    
    Lookup -->|命中| Prefetch[预取到高速缓存]
    Lookup -->|未命中| Alloc[分配新Block]
    
    Prefetch --> Load[加载到GPU]
    Load --> Wait1[等待加载完成]
    Wait1 --> Execute[模型执行]
    
    Alloc --> Compute[计算KV Cache]
    Compute --> Execute
    
    Execute --> Attention{注意力计算}
    Attention -->|稀疏模式| SparseAttn[稀疏注意力检索]
    Attention -->|完整模式| FullAttn[完整注意力]
    
    SparseAttn --> Retrieve[检索相关Token]
    Retrieve --> AttnCompute[注意力计算]
    FullAttn --> AttnCompute
    
    AttnCompute --> Dump{需要转储?}
    Dump -->|是| SaveKV[保存KV Cache]
    Dump -->|否| Finish[请求完成]
    SaveKV --> Store[写入存储]
    Store --> Finish
    Finish --> End([结束])

    style Start fill:#90EE90
    style End fill:#FFB6C1
    style SparseAttn fill:#87CEEB
    style Load fill:#DDA0DD
    style SaveKV fill:#DDA0DD
```

## 关键组件说明

### 1. UCMDirectConnector
- **作用**: 连接vLLM框架与UCM系统的桥梁
- **职责**: 
  - 管理请求元数据
  - 协调KV缓存的加载和转储
  - 与存储后端交互

### 2. UcmSparseBase
- **作用**: 稀疏注意力算法的抽象基类
- **设计模式**: 模板方法模式
- **双端设计**:
  - Scheduler端: 负责调度决策和资源估算
  - Worker端: 负责实际的KV缓存操作和注意力计算

### 3. UcmKVStoreBaseV1
- **作用**: 存储后端的统一抽象接口
- **核心方法**:
  - `lookup`: 查询块是否存在
  - `load/dump`: 异步数据传输
  - `wait/check`: 任务同步

### 4. 工厂类
- **UcmSparseFactory**: 根据配置创建稀疏算法实例
- **UcmConnectorFactoryV1**: 根据配置创建存储连接器实例
