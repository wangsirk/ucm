# Qwen2.5-7B KVCache性能测试

本目录包含基于UCM（Unified Cache Management）的千问7B模型KVCache性能测试脚本。

## 测试场景

| 场景 | 输入tokens | 输出tokens | 并发数 | 样本数 | 目标KVCache命中率 | 目标首字时延 | 目标吞吐量提升 |
|------|-----------|-----------|--------|--------|------------------|-------------|---------------|
| 4K   | 4000      | 128       | 128    | 256    | ≥98%             | <10s        | ≥150%         |
| 32K  | 32000     | 128       | 16     | 32     | ≥98%             | <10s        | ≥300%         |

## 前置条件

1. **硬件要求**
   - GPU: 建议使用A100或同等算力GPU
   - 内存: 建议64GB以上
   - 存储: 建议使用SSD或Lustre并行文件系统

2. **软件要求**
   - Python 3.10+
   - PyTorch 2.0+
   - vLLM (已集成UCM patch)
   - Transformers

3. **模型准备**
   - 下载Qwen2.5-7B-Instruct模型到本地

## 快速开始

### 方式1: 使用Shell脚本（推荐）

```bash
# 进入测试目录
cd test/suites/perf

# 添加执行权限
chmod +x run_perf_test.sh

# 测试4K场景
./run_perf_test.sh --scenario 4k --model-path /path/to/Qwen2.5-7B-Instruct

# 测试32K场景
./run_perf_test.sh --scenario 32k --model-path /path/to/Qwen2.5-7B-Instruct

# 测试所有场景
./run_perf_test.sh --scenario all --model-path /path/to/Qwen2.5-7B-Instruct
```

### 方式2: 直接运行Python脚本

```bash
# 设置环境变量
export PYTHONPATH=/home/w2938/unified-cache-management:$PYTHONPATH
export UCM_CONFIG_FILE=test/suites/perf/ucm_config_qwen7b_perf.yaml

# 运行测试
python test/suites/perf/test_qwen7b_kvcache_perf.py \
    --scenario 4k \
    --model-path /path/to/Qwen2.5-7B-Instruct \
    --storage-path /home/w2938/test/ucm_kvcache_perf \
    --output perf_results.json
```

### 方式3: 使用pytest

```bash
pytest test/suites/perf/test_qwen7b_kvcache_perf.py -v -s
```

## 配置说明

### UCM配置文件

[`ucm_config_qwen7b_perf.yaml`](ucm_config_qwen7b_perf.yaml) 是性能测试专用的UCM配置文件：

```yaml
ucm_connectors:
  - ucm_connector_name: "UcmPipelineStore"
    ucm_connector_config:
      store_pipeline: "Posix"
      storage_backends:
        - "/home/w2938/test/ucm_kvcache_perf"
      io_direct: false
      posix_data_trans_concurrency: 32
      posix_lookup_concurrency: 32
```

### 关键参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `store_pipeline` | 存储管道类型 | Posix |
| `storage_backends` | KVCache存储路径 | - |
| `io_direct` | 是否使用直IO | false |
| `posix_data_trans_concurrency` | 数据传输并发数 | 32 |
| `posix_lookup_concurrency` | 查找操作并发数 | 32 |

## 测试流程

1. **数据准备**
   - 生成具有公共前缀（98%）和不同后缀（2%）的测试prompts
   - 公共前缀用于确保KVCache命中率

2. **预热阶段**
   - 运行第一个prompt，将KVCache写入存储
   - 等待KVCache持久化完成

3. **性能测试**
   - 批量提交所有测试请求
   - 收集时延、吞吐量等指标

4. **结果验证**
   - 验证KVCache命中率是否≥98%
   - 验证平均首字时延是否<10s
   - 验证吞吐量提升是否达标

## 输出结果

测试完成后会生成JSON格式的结果文件：

```json
{
  "4k": {
    "results": {
      "scenario_name": "4K输入_128输出_128并发",
      "total_requests": 256,
      "successful_requests": 256,
      "failed_requests": 0,
      "mean_ttft": 2.5,
      "p50_ttft": 2.3,
      "p90_ttft": 3.1,
      "p99_ttft": 4.2,
      "max_ttft": 5.0,
      "total_throughput": 1250.5,
      "mean_per_request_throughput": 45.2,
      "kvcache_hit_rate": 0.98,
      "total_time": 120.5
    },
    "validations": {
      "平均首字时延 < 10s": true,
      "KVCache命中率 >= 98%": true,
      "吞吐量提升达标": true
    }
  }
}
```

### 指标说明

| 指标 | 说明 |
|------|------|
| `mean_ttft` | 平均首字时延（秒） |
| `p50_ttft` | 首字时延P50（秒） |
| `p90_ttft` | 首字时延P90（秒） |
| `p99_ttft` | 首字时延P99（秒） |
| `max_ttft` | 最大首字时延（秒） |
| `total_throughput` | 总吞吐量（tokens/s） |
| `mean_per_request_throughput` | 平均每请求吞吐量（tokens/s） |
| `kvcache_hit_rate` | KVCache命中率 |

## 常见问题

### 1. KVCache命中率不达标

**原因分析**：
- 前缀token比例设置不正确
- KVCache未正确持久化到存储

**解决方案**：
- 检查`target_hit_rate`参数设置
- 增加预热等待时间

### 2. 首字时延过高

**原因分析**：
- GPU显存不足
- 并发数设置过高

**解决方案**：
- 降低`gpu_memory_utilization`
- 减少并发请求数

### 3. 内存不足

**原因分析**：
- 32K场景需要较大的`max_model_len`

**解决方案**：
- 增加系统内存
- 使用显存卸载策略

## 性能调优建议

1. **存储优化**
   - 使用NVMe SSD作为KVCache存储
   - 对于Lustre，增加stripe count以提高并发性能

2. **并发优化**
   - 根据GPU显存调整`posix_data_trans_concurrency`
   - 32K场景建议使用较低的并发数

3. **模型优化**
   - 使用FP16或BF16精度
   - 启用`enforce_eager`模式

## 相关文档

- [UCM用户指南](../../../docs/source/user-guide/prefix-cache/index.md)
- [vLLM集成说明](../../../docs/source/getting-started/quickstart_vllm.md)
- [性能指标说明](../../../docs/source/user-guide/metrics/metrics.md)
