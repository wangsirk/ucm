# P1 阶段实施步骤指南

**实施策略**: 自底向上，逐层验证
**原则**: 每个组件完成后立即编写测试，确保质量

---

## 实施顺序

```
Day 1-2:  IoUnit 定义 + 基础测试
    ↓
Day 3-5:  TransQueue::SplitTask + H2S/S2H
    ↓
Day 6:    TransQueue 单元测试验证
    ↓
Day 7:    TransManager 框架搭建
    ↓
Day 8-9:  Load/Dump 流程实现
    ↓
Day 10:   Wait/Check 状态查询
    ↓
Day 11-12: 集成测试 + 修复
    ↓
Day 13-14: 错误处理 + 并发测试 + 验收
```

---

## 第一步: IoUnit 结构定义 (Day 1-2)

### 1.1 检查现有结构

```bash
# 查看现有的 trans_task.h
cat ucm/store/lustre/cc/trans_task.h
```

### 1.2 完善 IoUnit 定义

在 `trans_task.h` 中添加:

```cpp
struct IoUnit {
    // 标识
    Detail::BlockId blockId;
    size_t shardIndex;

    // 数据位置
    void* srcAddr;
    void* dstAddr;
    size_t offset;
    size_t size;

    // 状态
    std::atomic<bool> completed{false};
    Status result{Status::OK()};
};
```

### 1.3 编写 IoUnit 测试

创建 `ucm/store/lustre/tests/io_unit_test.cc`:

```cpp
TEST(IoUnit, Construction) {
    BlockId bid = MakeBlockId("test");
    IoUnit unit(bid, 0, src, dst, 0, 4096);

    EXPECT_EQ(unit.blockId, bid);
    EXPECT_EQ(unit.shardIndex, 0);
    EXPECT_FALSE(unit.completed);
}
```

### 1.4 验收标准

- [ ] IoUnit 结构编译通过
- [ ] 单元测试通过
- [ ] 无编译警告

---

## 第二步: TransQueue 任务拆分 (Day 3-4)

### 2.1 实现 SplitTask

```cpp
std::vector<std::unique_ptr<IoUnit>>
TransQueue::SplitTask(const TransTask& task) {
    // 实现代码...
}
```

### 2.2 测试任务拆分

```cpp
TEST(TransQueue, SplitTask_SingleShard) {
    // 测试单个 Shard 拆分
}

TEST(TransQueue, SplitTask_MultiShard) {
    // 测试多个 Shard 拆分
}
```

### 验收标准

- [ ] 拆分后 IoUnit 数量正确
- [ ] 地址偏移计算正确
- [ ] 单元测试全部通过

---

## 第三步: TransQueue H2S/S2H 实现 (Day 4-5)

### 3.1 实现 H2S (Dump)

```cpp
Status TransQueue::H2S(IoUnit& ios) {
    // 1. 生成临时文件路径
    // 2. 创建临时文件
    // 3. 写入数据
    // 4. 提交文件 (最后一个 Shard 时)
}
```

### 3.2 实现 S2H (Load)

```cpp
Status TransQueue::S2H(IoUnit& ios) {
    // 1. 生成正式文件路径
    // 2. 检查文件存在
    // 3. 读取数据
}
```

### 验收标准

- [ ] H2S 测试通过
- [ ] S2H 测试通过
- [ ] 临时文件正确清理

---

## 第四步: TransManager 框架 (Day 7)

### 4.1 实现 Submit

```cpp
TaskHandle TransManager::Submit(std::shared_ptr<TransTask> task) {
    // 1. 生成 TaskHandle
    // 2. 拆分任务
    // 3. 推送到队列
    // 4. 返回句柄
}
```

### 验收标准

- [ ] 任务正确分发
- [ ] TaskHandle 唯一性

---

## 第五步: Load/Dump 流程 (Day 8-9)

### 5.1 实现 LustreStore::Load

```cpp
Expected<TaskHandle> LustreStore::Load(TaskDesc task) {
    // 1. 参数校验
    // 2. 自动填充参数
    // 3. 创建 TransTask
    // 4. 提交到 TransManager
}
```

### 5.2 实现 LustreStore::Dump

```cpp
Expected<TaskHandle> LustreStore::Dump(TaskDesc task) {
    // 同 Load，但 Type 为 DUMP
}
```

### 验收标准

- [ ] Python 集成测试通过
- [ ] Dump-Load 数据一致性验证

---

## 第六步: Wait/Check (Day 10)

### 6.1 实现 Wait

```cpp
Status LustreStore::Wait(TaskHandle taskId) {
    // 阻塞等待任务完成
}
```

### 6.2 实现 Check

```cpp
Expected<bool> LustreStore::Check(TaskHandle taskId) {
    // 非阻塞检查状态
}
```

### 验收标准

- [ ] Wait 正确阻塞
- [ ] Check 非阻塞返回

---

## 第七步: 集成测试 (Day 11-12)

### 7.1 运行 Python 测试

```bash
cd /home/w2938/tools/ucm
source /home/w2938/vllm/bin/activate
pytest test/suites/Unit/test_lustre_p1_data_transfer.py -v
```

### 7.2 修复发现的问题

### 验收标准

- [ ] 所有集成测试通过
- [ ] 代码覆盖率 ≥ 85%

---

## 第八步: 错误处理与并发测试 (Day 13-14)

### 8.1 错误注入测试

### 8.2 并发安全性测试

### 验收标准

- [ ] 错误场景正确处理
- [ ] 并发测试无数据损坏
- [ ] 最终验收通过

---

## 每日检查清单

每天结束时确认:

- [ ] 代码编译无警告
- [ ] 单元测试通过
- [ ] 提交代码到 git
- [ ] 更新进度文档

---

## 当前状态检查

在开始之前，先验证 P0 基础:

```bash
cd /home/w2938/tools/ucm
source /home/w2938/vllm/bin/activate
pytest test/suites/Unit/test_lustre_p0_infrastructure.py -v
```

预期输出: `16 passed`
