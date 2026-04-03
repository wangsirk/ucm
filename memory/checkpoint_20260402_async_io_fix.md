---
name: 异步 I/O 文件描述符生命周期修复
description: 修复了文件描述符生命周期问题和完成处理线程缺失问题
type: checkpoint
date: 2026-04-02
---

# 异步 I/O 文件描述符生命周期修复

## 会话状态
- **日期**: 2026-04-02
- **分支**: lustre
- **状态**: 编译验证完成，待测试验证

## 问题诊断

### 问题1: 残留代码
**位置**: `trans_queue.cc:143`
```
units[0]->firstIo = true;  // ExtendedIoUnit 没有 firstIo 成员
```
**修复**: 删除此行代码

### 问题2: 文件描述符生命周期问题
**现象**: `I/O failed: fd=4, isWrite=true, error=Bad file descriptor`

**原因**:
```cpp
Status TransQueue::H2S(const std::shared_ptr<ExtendedIoUnit>& ios) {
    LustreFile file(tmpPath);  // 局部变量
    // ...
    return H2SAsync(ios, tmpPath, file.GetFd());  // 返回后 file 被析构，fd 被关闭！
}
```

**修复**: 使用 `shared_ptr<LustreFile>` 管理生命周期
```cpp
auto file = std::make_shared<LustreFile>(tmpPath);
// 在回调中捕获 shared_ptr，保持文件打开
[this, weakIos, tmpPath, file](...) { ... }
```

### 问题3: 完成处理线程缺失
**现象**: 异步回调永不触发，`Wait()` 永远阻塞

**原因**: 没有线程调用 `ProcessCompletion()` 处理完成队列

**修复**: 在 `ThreadPoolBackend` 添加完成处理线程
```cpp
void CompletionLoop(ThreadPoolBackend* adapter) {
    while (running.load() || !completionQueue.empty()) {
        adapter->ProcessCompletion(100);
    }
}
```

## 修改的文件

| 文件 | 修改内容 |
|------|----------|
| `ucm/store/lustre/cc/trans_queue.cc` | 1. 删除 `firstIo` 残留代码<br>2. `H2S`/`S2H` 使用 `shared_ptr<LustreFile>` |
| `ucm/store/lustre/cc/trans_queue.h` | 更新 `H2SAsync`/`S2HAsync` 签名 |
| `ucm/store/lustre/cc/async_io.cc` | 添加完成处理线程 |

## 编译结果

```
[ 85%] Built target lustrestore
Successfully installed uc-manager-0.3.0
```

## 下次会话

1. **测试验证**: 运行 `python test/test_lustre_store_flow.py`
2. **Lustre 客户端测试**: 在真实 Lustre 环境测试条带化功能
3. **单元测试**: 运行 P0-P3 单元测试验证修复
