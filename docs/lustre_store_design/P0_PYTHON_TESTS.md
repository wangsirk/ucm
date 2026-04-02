# Lustre Store P0 Python 测试

## 测试文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `test/test_lustre_p0.py` | 独立脚本 | 可直接运行，带完整输出 |
| `test/suites/Unit/test_lustre_store_p0.py` | pytest 风格 | 9 个测试用例，与项目测试风格一致 |

## 运行方式

### 方式 1: 独立脚本 (快速验证)

```bash
cd /home/w2938/tools/ucm
python test/test_lustre_p0.py
```

### 方式 2: pytest (集成测试)

```bash
cd /home/wown38/tools/ucm
pytest test/suites/Unit/test_lustre_store_p0.py -v
```

## 测试覆盖

| ID | 测试用例 | 覆盖模块 |
|----|----------|----------|
| 1.1 | 空 blocks 列表 | 参数校验 |
| 1.2 | 不存在 blocks | 参数校验 |
| 2.1 | Dump + Lookup | 文件操作 |
| 3.1 | 数据目录创建 | 目录结构 |
| 3.2 | 分片目录创建 | 目录结构 |
| 4.1 | Dump 幂等性 | CommitFile |
| 5.1 | Dump-Load 一致性 | 数据完整性 |
| 6.1 | 多 block 操作 | 批量处理 |
| 7.1 | 无效 block 查询 | 错误处理 |
| 8.1 | 并发相同 block | 并发安全 |

## 与 C++ 测试对比

| 方面 | Python 测试 | C++ 测试 |
|------|------------|----------|
| 环境配置 | ✅ 无需额外配置 | ❌ 需要 GoogleTest |
| 测试框架 | pytest | GoogleTest |
| 运行方式 | Python 直接运行 | 需要编译 |
| 调试便利性 | ✅ 易于调试 | ❌ 需要重新编译 |
| 与项目集成 | ✅ 完全兼容 | ⚠️ 需要配置 |

## 结论

**推荐使用 Python 测试框架** - 无需额外环境配置，与项目测试风格一致。
