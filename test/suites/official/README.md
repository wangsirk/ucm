# TTFT基准测试用例

本目录包含用于测试TTFT (Time To First Token) 性能的官方测试用例。

## 概述

本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标。
### 主要特性
- 支持配置输入长度 (`input_tokens`)
- 支持配置并发请求数 (`num_concurrent`)
- 支持配置KVCache目标命中率 (`target_hit_rate`)
- 参考vllm官方代码的TTFT统计方式
### TTFT统计方式
参考vllm官方代码的TTFT计算方式为：
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```

### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model

# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml

# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
        --mode ucm \
        --model-path /path/to/model \
        --input-tokens 1024 \
        --num-concurrent 8 \
        --target-hit-rate 0.5 \
        --num-samples 100 \
        --output-json results.json
```

### 使用pytest运行
```bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline

# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v - s - -k test_ttft_comparison
```
### 禂述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标。
支持配置:
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)

- 参考vllm官方代码的TTFT统计方式

参考vllm官方代码的TTFT计算方式为:
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```

### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model

# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
        --mode ucm \
        --model-path /path/to/model \
        --input-tokens 1024 \
        --num-concurrent 8 \
        --target-hit-rate 0.5 \
        --num-samples 100 \
        --output-json results.json
```
### 使用pytest运行
```bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s -k test_ttft_comparison
```
### 禂述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标。
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为：
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```

### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model

# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
        --mode ucm \
        --model-path /path/to/model \
        --input-tokens 1024 \
        --num-concurrent 8 \
        --target-hit-rate 0.5 \
        --num-samples 100 \
        --output-json results.json
```
### 使用pytest运行
```bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s -k test_ttft_comparison
```
### 概述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标。
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为:
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```

### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model

# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
        --mode ucm \
        --model-path /path/to/model \
        --input-tokens 1024 \
        --num-concurrent 8 \
        --target-hit-rate 0.5 \
        --num-samples 100 \
        --output-json results.json
```
### 使用pytest运行
```bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s -k test_ttft_comparison
```
### 概述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标。
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为:
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```

### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model

# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
        --mode ucm \
        --model-path /path/to/model \
        --input-tokens 1024 \
        --num-concurrent 8 \
        --target-hit-rate 0.5 \
        --num-samples 100 \
        --output-json results.json
```
### 使用pytest运行
```bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s -k test_ttft_comparison
```
### 概述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标。
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```
### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model
# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
        --mode ucm \
        --model-path /path/to/model \
        --input-tokens 1024 \
        --num-concurrent 8 \
        --target-hit-rate 0.5 \
        --num-samples 100
        --output-json results.json
```
### 使用pytest运行
```bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s -k test_ttft_comparison
```
### 概述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标。
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为:
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```
### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model

# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
        --mode ucm \
        --model-path /path/to/model \
        --input-tokens 1024 \
        --num-concurrent 8 \
        --target-hit-rate 0.5 \
        --num-samples 100
        --output-json results.json
```
### 使用pytest运行
```bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v - s - k test_ttft_comparison
```
### 概述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标。
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```
### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model
# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
        --mode ucm \
        --model-path /path/to/model \
        --input-tokens 1024 \
        --num-concurrent 8 \
        --target-hit-rate 0.5 \
        --num-samples 100
        --output-json results.json
```
### 使用pytest运行
```bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s - k test_ttft_comparison
```
### 概述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标。
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为:
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```
### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model
# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --input-tokens 1024 \
    --num-concurrent 8 \
    --target-hit-rate 0.5 \
    --num-samples 100
    --output-json results.json
```
### 使用pytest运行
```bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s - k test_ttft_comparison
```
### 概述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标。
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```
### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model
# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --input-tokens 1024 \
        --num-concurrent 8 \
        --target-hit-rate 0.5 \
        --num-samples 100
        --output-json results.json
```
### 使用pytest运行
```bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s - k test_ttft_comparison
```
### 概述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标。
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```
### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model
# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --input-tokens 1024 \
    --num-concurrent 8 \
    --target-hit-rate 0.5
    --num-samples 100
    --output-json results.json
```
### 使用pytest运行
```bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s - k test_ttft_comparison
```
### 概述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标。
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```
### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model
# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --input-tokens 1024 \
    --num-concurrent 8 \
    --target-hit-rate 0.5
    --num-samples 100
    --output-json results.json
```
### 使用pytest运行
```bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s - k test_ttft_comparison
```
### 概述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```
### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model
# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --input-tokens 1024 \
    --num-concurrent 8 \
    --target-hit-rate 0.5
    --num-samples 100
    --output-json results.json
```
### 使用pytest运行
```bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s - k test_ttft_comparison
```
### 概述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标。
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```
### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model

# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --input-tokens 1024 \
    --num-concurrent 8 \
    --target-hit-rate 0.5 \
    --num-samples 100
    --output-json results.json
```
### 使用pytest运行
``` bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s - k test_ttft_comparison
```
### 概述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标。
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```
### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model

# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --input-tokens 1024 \
    --num-concurrent 8 \
    --target-hit-rate 0.5
    --num-samples 100
    --output-json results.json
```
### 使用pytest运行
```bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s - k test_ttft_comparison
```
### 概述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标。
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```
### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model
# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --input-tokens 1024 \
    --num-concurrent 8 \
    --target-hit-rate 0.5
    --num-samples 100
    --output-json results.json
```
### 使用pytest运行
```bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s - k test_ttft_comparison
```
### 概述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标。
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```
### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model
# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --input-tokens 1024 \
    --num-concurrent 8 \
    --target-hit-rate 0.5
    --num-samples 100
    --output-json results.json
```
### 使用pytest运行
```bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s - k test_ttft_comparison
```
### 概述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标。
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```
### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model
# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --input-tokens 1024 \
    --num-concurrent 8 \
    --target-hit-rate 0.5
    --num-samples 100
    --output-json results.json
```
### 使用pytest运行
``` bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s - k test_ttft_comparison
```
### 概述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```
### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model
# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --input-tokens 1024 \
    --num-concurrent 8 \
    --target-hit-rate 0.5
    --num-samples 100
    --output-json results.json
```
### 使用pytest运行
```bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s - k test_ttft_comparison
```
### 概述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```
### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model
# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --input-tokens 1024 \
    --num-concurrent 8 \
    --target-hit-rate 0.5
    --num-samples 100
    --output-json results.json
```
### 使用pytest运行
``` bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
```
### 对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s - k test_ttft_comparison
```
### 概述
本测试用例用于对比测试**裸推TTFT**和**存在UCM TTFT**的具体指标
支持配置
- 输入长度 (`input_tokens`): 默认值: 100
- 并发请求数 (`num_concurrent`): 默认值: 8
- KVCache目标命中率 (`target_hit_rate`): 默认值: 0.5 (50%)
- 参考vllm官方代码的TTFT统计方式
参考vllm官方代码的TTFT计算方式为
```python
ttft = output.metrics.first_token_time - output.metrics.arrival_time
```
### 使用方法
#### 命令行运行
```bash
# 运行裸推测试(无UCM)
python test/suites/official/test_ttft_benchmark.py \
    --mode baseline \
    --model-path /path/to/model
# 运行UCM测试
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --ucm-config /path/to/ucm_config.yaml
# 自定义参数
python test/suites/official/test_ttft_benchmark.py \
    --mode ucm \
    --model-path /path/to/model \
    --input-tokens 1024 \
    --num-concurrent 8 \
    --target-hit-rate 0.5 \
    --num-samples 100 \
    --output-json results.json
```

### 使用pytest运行
```bash
# 运行基线测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode baseline
# 运行UCM测试
pytest test/suites/official/test_ttft_benchmark.py -v -s --mode ucm
# 运行对比测试
pytest test/suites/official/test_ttft_benchmark.py -v -s -k test_ttft_comparison
```
### 环境变量
| 变量名 | 描述 | 默认值 |
| `-------|------|--------|
| `MODEL_PATH` | 模型路径 | `/home/models/Qwen2.5-7B-Instruct` |
| `UCM_CONFIG` | UCM配置文件路径 | `test/test_ucm_config.yaml` |
## 参数说明
| 参数 | 描述 | 默认值 |
    `------|------|--------|
    | `--mode` | 测试模式: `ucm` |
    | `--model-path` | 模型路径 | 环境变量 `MODEL_PATH` |
    | `--ucm-config` | UCM配置文件路径 | 环境变量 `UCM_CONFIG` |
    | `--input-tokens` | 输入token数量 | 100 |
    | `--num-concurrent` | 并发请求数 | 8 |
    | `--target-hit-rate` | 目标KVCache命中率 | 0.5 |
    | `--num-samples` | 测试样本数量 | 50 |
    | `--output-tokens` | 输出token数量 | 64 |
    | `--output-json` | 结果输出JSON文件路径 | None |
## 测试结果说明
测试完成后会输出以下统计指标：
### TTFT统计指标
| 指标 | 描述 |
    `------|------|
| `mean_ttft_ms` | 平均TTFT (毫秒) |
| `median_ttft_ms` | TTFT中位数 (毫秒) |
| `std_ttft_ms` | TTFT标准差 (毫秒) |
| `min_ttft_ms` | 最小TTFT (毫秒) |
| `max_ttft_ms` | 最大TTFT (毫秒) |
| `p50_ttft_ms` | TTFT 50百分位 (毫秒) |
| `p90_ttft_ms` | TTFT 90百分位 (毫秒) |
    `p99_ttft_ms` | TTFT 99百分位 (毫秒) |
### 缓存统计指标
| 指标 | 描述 |
    `------|------|
    `actual_hit_rate` | 实际KVCache命中率 |
    `total_cached_tokens` | 缓存命中的总token数 |
    `total_input_tokens` | 总输入token数 |
## KVCache命中率模拟
为了模拟50%的KVCache命中率，测试用例采用以下策略
1. **公共前缀**: 50%的tokens来自公共前缀
2. **唯一后缀**: 50%的tokens来自每个请求的唯一后缀
例如，对于1024个输入tokens:
- 公共前缀: 512 tokens
- 唯一后缀: 512 tokens
这样，当第二个及后续请求处理时， 前512个tokens可以命中缓存。
## 注意事项
1. 硸保模型路径正确且模型已下载
2. UCM模式下需要提供正确的UCM配置文件
3. 测试前建议先进行预热，确保缓存已填充
4. 建议多次运行取平均值以获得更准确的结果
## 示例输出
```
============================================================
TTFT Benchmark Test - Mode: ucm
============================================================

Test Configuration:
  Mode: ucm
  Input Tokens: 512
  Concurrent Requests: 4
  Target Hit Rate: 50.0%
  Samples: 50

Summary:
  Total Requests: 50
  Successful Requests: 50
  Failed Requests: 0

TTFT Statistics:
  Mean TTFT: 123.456 ms
  Median TTFT: 118.234 ms
  Std TTFT: 25.678 ms
  Min TTFT: 85.123 ms
  Max TTFT: 256.789 ms
  P50 TTFT: 118.234 ms
  P90 TTFT: 178.456 ms
  P99 TTFT: 245.678 ms

Cache Statistics:
  Actual Hit Rate: 48.52%
  Total Cached Tokens: 12800
  Total Input Tokens: 25600

============================================================
