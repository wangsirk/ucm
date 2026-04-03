---
title: Async I/O File Descriptor Lifecycle and Completion Handling Fix
date: 2026-04-02
category: runtime-errors
module: lustre_store
problem_type: runtime_error
component: async_io
severity: high
symptoms:
  - "Bad file descriptor" error during async I/O operations
  - Async callbacks never triggering
  - "waiter->Done()" not being called, causing permanent blocking
root_cause: async_timing
resolution_type: code_fix
tags:
  - async-io
  - file-descriptor
  - callback-lifetime
  - shared_ptr
  - threadpool
  - completion-queue
  - lustre
---

# Async I/O File Descriptor Lifecycle and Completion Handling Fix

## Problem

Async I/O operations in Lustre Store's P2 performance optimization experienced **runtime errors due to object lifecycle management issues**. The asynchronous callback system had race conditions where:

1. **File descriptors became invalid** before callbacks executed (`Bad file descriptor`)
2. **Callbacks never triggered** because completion queue wasn't being processed
3. **Dangling references** to temporary objects caused undefined behavior

## Symptoms

- Error: `I/O failed: fd=4, isWrite=true, error=Bad file descriptor` during async operations
- Async write/read callbacks not executing
- `waiter->Done()` not being called, causing permanent blocking in `Latch::Wait()`
- Test hangs at `wait()` step
- Occasional crashes or undefined behavior under concurrent load

## What Didn't Work

Initial approach used stack-allocated objects and opportunistic completion processing:

- **`LustreFile` as local variable**: Object destroyed when function returned, closing file descriptor before async I/O completed
- **`ProcessCompletion(0)` after submission**: Non-blocking call only processed already-completed events, missing most callbacks
- **No dedicated completion thread**: Completion queue was populated but never drained
- **Raw `this` capture in callbacks**: Unsafe if object destroyed before callback execution

## Solution

### 1. Use `shared_ptr` for File Object Lifecycle Management

**Before** (`trans_queue.cc:195-231`):
```cpp
Status TransQueue::H2S(const std::shared_ptr<ExtendedIoUnit>& ios)
{
    std::string tmpPath = layout_->DataFilePath(ios->blockId, true);
    LustreFile file(tmpPath);  // Local variable - destroyed when H2S returns!
    // ...
    return H2SAsync(ios, tmpPath, file.GetFd());  // fd becomes invalid here
}
```

**After** (`trans_queue.cc:195-231`):
```cpp
Status TransQueue::H2S(const std::shared_ptr<ExtendedIoUnit>& ios)
{
    std::string tmpPath = layout_->DataFilePath(ios->blockId, true);
    auto file = std::make_shared<LustreFile>(tmpPath);  // shared_ptr manages lifetime
    // ...
    return H2SAsync(ios, tmpPath, file);  // Pass shared_ptr
}
```

### 2. Capture `shared_ptr` in Callback to Keep File Open

**trans_queue.cc** - H2SAsync callback:
```cpp
Status TransQueue::H2SAsync(const std::shared_ptr<ExtendedIoUnit>& ios,
                             const std::string& tmpPath,
                             const std::shared_ptr<LustreFile>& file)
{
    std::weak_ptr<ExtendedIoUnit> weakIos = ios;

    int fd = file->GetFd();
    IoRequest req(
        fd, ios->srcAddr, ios->ioSize, static_cast<off64_t>(ios->fileOffset), true,
        [this, weakIos, tmpPath, file](IoRequest::Result result, ssize_t bytesTransferred) {
            // shared_ptr<LustreFile> captured in lambda keeps file descriptor valid
            auto ios = weakIos.lock();
            if (!ios) {
                UC_WARN("ExtendedIoUnit already destroyed, cleaning up temp file");
                LustreFile::Remove(tmpPath);
                return;
            }
            // ... callback logic using ios safely
        }
    );
    // ...
}
```

### 3. Add Dedicated Completion Processing Thread

**async_io.cc** - Added `CompletionLoop` to `ThreadPoolBackend::Impl`:
```cpp
struct ThreadPoolBackend::Impl {
    // ... existing fields ...

    // Completion processing thread
    std::thread completionThread;

    void CompletionLoop(ThreadPoolBackend* adapter)
    {
        UC_DEBUG("ThreadPoolBackend completion thread started");

        while (running.load() || !completionQueue.empty()) {
            adapter->ProcessCompletion(100);  // 100ms timeout
        }

        // Final pass for remaining completions
        while (!completionQueue.empty()) {
            adapter->ProcessCompletion(0);
        }

        UC_DEBUG("ThreadPoolBackend completion thread stopped");
    }
};
```

### 4. Start/Stop Completion Thread

**async_io.cc** - Updated `StartWorkers`:
```cpp
Status StartWorkers(size_t numWorkers, int cpuAffinity, ThreadPoolBackend* adapter)
{
    running.store(true);

    for (size_t i = 0; i < numWorkers; ++i) {
        workers.emplace_back([this, i, workerCpu]() {
            WorkerFunc(i, workerCpu);
        });
    }

    // Start completion processing thread
    completionThread = std::thread([this, adapter]() {
        CompletionLoop(adapter);
    });

    return Status::OK();
}
```

**async_io.cc** - Updated `StopWorkers`:
```cpp
void StopWorkers()
{
    running.store(false);
    queueCV.notify_all();
    completionCV.notify_all();

    for (auto& worker : workers) {
        if (worker.joinable()) {
            worker.join();
        }
    }
    workers.clear();

    // Wait for completion thread
    if (completionThread.joinable()) {
        completionThread.join();
    }
}
```

### 5. Update Function Signatures

**trans_queue.h**:
```cpp
// Before:
Status H2SAsync(const std::shared_ptr<ExtendedIoUnit>& ios,
                const std::string& tmpPath, int fd);

// After:
Status H2SAsync(const std::shared_ptr<ExtendedIoUnit>& ios,
                const std::string& tmpPath,
                const std::shared_ptr<LustreFile>& file);
```

Same changes applied to `S2HAsync`.

## Why This Works

1. **`shared_ptr` reference counting**: `LustreFile` stays alive as long as any reference exists (main thread + callback). File descriptor remains valid until callback completes.

2. **`weak_ptr` safety check**: Callback can detect if original `ExtendedIoUnit` was destroyed and avoid accessing invalid memory, with graceful cleanup of temporary files.

3. **Dedicated completion thread**: Continuously processes completion queue, ensuring callbacks execute even if main thread is busy or blocked. No more "orphaned" completions.

4. **Graceful shutdown**: Completion thread drains remaining events before exit during cleanup.

## Prevention

1. **Always use `shared_ptr`/`weak_ptr` pattern** for objects accessed from async callbacks:
   ```cpp
   // Good: shared_ptr keeps object alive
   auto shared_obj = std::make_shared<MyObject>();
   std::weak_ptr<MyObject> weak_obj = shared_obj;
   callback = [weak_obj]() {
       if (auto obj = weak_obj.lock()) {
           // Safe to use obj
       }
   };

   // Bad: Raw pointer or reference
   MyObject* obj = &local_obj;  // Dangling!
   callback = [obj]() { /* UB */ };
   ```

2. **Dedicated completion processing**: Never rely on opportunistic `ProcessCompletion(0)` calls. Use a dedicated thread or `condition_variable` signaling for reliable callback execution.

3. **Test under concurrent load**:
   ```python
   def test_async_io_concurrent_operations():
       """Multiple simultaneous async I/O operations"""
       blocks = [generate_block_id(i) for i in range(100)]
       # Verify all callbacks execute within timeout
   ```

4. **Validate file descriptor lifecycle**: Ensure files opened for async I/O remain open until callback completes. Use `shared_ptr` or move ownership to callback.

5. **Add timeout mechanisms**: `ProcessCompletion()` should support timeout-based waiting, not just non-blocking mode.

## Related Files

| File | Change |
|------|--------|
| `ucm/store/lustre/cc/trans_queue.h` | Updated `H2SAsync`/`S2HAsync` signatures to accept `shared_ptr<LustreFile>` |
| `ucm/store/lustre/cc/trans_queue.cc` | Use `shared_ptr<LustreFile>` for lifecycle management |
| `ucm/store/lustre/cc/trans_queue.cc` | Removed `firstIo` dead code (line 143) |
| `ucm/store/lustre/cc/async_io.cc` | Added `completionThread` member and `CompletionLoop()` |
| `ucm/store/lustre/cc/async_io.cc` | Updated `StartWorkers()`/`StopWorkers()` for completion thread |

## Related Issues

- [Checkpoint: 异步 I/O 文件描述符生命周期修复](memory/checkpoint_20260402_async_io_fix.md) — Session checkpoint documenting these fixes
- [P2 Performance Optimization](performance-optimization/lustre-store-p2-performance-optimization.md) — Async I/O feature implementation that introduced this issue
