---
title: Pytest 测试数据自动清理导致调试困难
date: 2026-04-02
category: workflow-issues
module: ucm.testing
problem_type: workflow_issue
component: testing_framework
severity: low
applies_when:
  - 需要保留测试数据用于调试
  - 需要验证文件写入内容正确性
  - pytest fixture 自动清理影响开发效率
tags:
  - pytest
  - testing
  - debugging
  - fixture-cleanup
---

# Pytest 测试数据自动清理导致调试困难

## Context

在开发 Lustre Store 测试时，需要在测试结束后检查数据文件内容以验证 I/O 操作正确性。但由于 pytest fixture 的自动清理机制，测试完成后数据目录为空，无法进行事后检查。

同时，测试过程中缺乏详细的数据打印，无法在测试运行时验证数据内容。

## Guidance

### 禁用测试数据自动清理

pytest fixture 在 `yield` 后执行的清理代码会删除测试数据。对于需要保留数据的调试场景，注释掉清理逻辑：

```python
@pytest.fixture
def test_config():
    backend = "/tmp/test_data"
    os.makedirs(backend, exist_ok=True)

    # 🔧 保留测试数据 - 不清理
    # cleanup_store_backend(backend)

    yield {"backend": backend}

    # 🔧 保留测试数据 - 测试结束后不清理
    # cleanup_store_backend(backend)
```

同样，注释掉 `pytest_sessionfinish` 中的目录删除：

```python
def pytest_sessionfinish(session, exitstatus):
    # 🔧 保留测试数据用于调试
    logger.info("📦 测试数据已保留，用于调试和验证")
    logger.info("   清理命令: rm -rf /tmp/test_data")

    # # 清理测试目录（已禁用）
    # shutil.rmtree(backend)
```

### 添加数据打印和验证函数

添加辅助函数在测试过程中打印和验证数据：

```python
def print_tensor_info(tensor, label="Tensor"):
    """打印 Tensor 详细信息用于调试"""
    logger.info(f"📊 [{label}] 信息:")
    logger.info(f"   - 形状: {tensor.shape}")
    logger.info(f"   - 数据类型: {tensor.dtype}")
    logger.info(f"   - 元素数量: {tensor.numel()}")
    logger.info(f"   - 前16字节: {tensor[:16].tolist()}")
    logger.info(f"   - 后16字节: {tensor[-16:].tolist()}")
    tensor_hash = hashlib.sha256(tensor.numpy().tobytes()).hexdigest()[:16]
    logger.info(f"   - SHA256前16位: {tensor_hash}")


def verify_tensor_equal(original, loaded, test_name=""):
    """验证两个 Tensor 是否相等，打印详细信息"""
    logger.info(f"🔍 [{test_name}] 数据验证:")
    logger.info(f"   - 原始形状: {original.shape}, 加载形状: {loaded.shape}")

    if torch.equal(original, loaded):
        logger.info(f"   ✅ 数据完全匹配")
        return True
    else:
        logger.warning(f"   ❌ 数据不匹配!")
        return False
```

### 在测试用例中使用

```python
def test_dump_and_load(lustre_store):
    # 打印输入数据
    test_data = create_test_tensor(1024, 0xAB)
    print_tensor_info(test_data, "输入数据")

    # Dump
    block_id = generate_block_id(0)
    store.dump([block_id], [0], [[test_data]])
    store.wait(task)

    # Load 并验证
    load_buffer = create_test_tensor(1024, 0xCC)
    print_tensor_info(load_buffer, "Load前")
    store.load([block_id], [0], [[load_buffer]])
    store.wait(task)

    print_tensor_info(load_buffer, "Load后")
    verify_tensor_equal(test_data, load_buffer, "Dump/Load")
```

## Why This Matters

- **调试效率**: 测试失败时可以查看实际写入的文件内容，而不需要重新运行
- **数据验证**: 可以使用外部工具（如 `xxd`, `sha256sum`）验证文件内容
- **问题定位**: 当 I/O 行为不符合预期时，可以事后检查文件系统状态

## When to Apply

- 开发新的存储后端或 I/O 功能时
- 调试数据损坏或写入错误时
- 需要验证文件格式正确性时
- 演示或展示测试结果时

## Examples

### 调试输出示例

```
📊 [输入数据] 信息:
   - 形状: torch.Size([1024])
   - 数据类型: torch.uint8
   - 元素数量: 1024
   - 前16字节: [171, 171, 171, 171, 171, 171, 171, 171, ...]
   - 后16字节: [171, 171, 171, 171, 171, 171, 171, 171, ...]
   - SHA256前16位: 4555555dc68d872c

🔍 数据验证:
   - 原始形状: torch.Size([1024]), 加载形状: torch.Size([1024])
   ✅ 数据完全匹配
```

### 文件系统验证

```bash
# 测试保留的数据文件
$ ls -la /tmp/test_data/data/
-rw-r--r-- 1 root root 1024 Apr  2 15:44 cff3c48e547f28a5eb7ea65c856cbc64

# 验证文件内容
$ python3 -c "with open('cff3c48e547f28a5eb7ea65c856cbc64', 'rb') as f: print(f.read()[:16])"
b'\xab\xab\xab\xab\xab\xab\xab\xab\xab\xab\xab\xab\xab\xab\xab\xab'
```

## Related

- [pytest fixture 文档](https://docs.pytest.org/en/stable/fixture.html#fixture-finalization-teardown)
- UCM 项目: `test/suites/Unit/test_lustre_p2_performance.py`
