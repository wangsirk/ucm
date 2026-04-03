---
module: lustre
date: 2026-04-03
problem_type: runtime_error
component: lustre
severity: high
symptoms:
  - "lfs getstripe shows stripe_count=1 instead of configured value (e.g., 4)"
  - "llapi_dir_create() returns 'stripe already set' error"
  - "Striped directory creation fails silently - directory created but with default stripe_count=1"
root_cause: incomplete_setup
resolution_type: code_fix
tags:
  - lustre
  - striping
  - llapi
  - lfs
related_components:
  - space-layout
---

# Lustre 条带化目录创建失败

## 问题

使用 `llapi_dir_create()` API 设置目录条带属性时，目录创建成功但 `stripe_count` 始终为 1，而不是配置的值（如 4）。

## 症状

```bash
# 配置 stripe_count=4
config = {
    'stripe_count': 4,
    'stripe_size': 1048576,
}

# 验证条带属性
$ lfs getstripe /mnt/lustre47/demo/data
stripe_count:  1  # ❌ 应该是 4
stripe_size:   1048576
pattern:       0
stripe_offset: -1
```

日志显示：
```
python: dirstripe error on '/mnt/lustre47/demo/data': stripe already set
```

## 根本原因

Lustre 在创建目录时会自动继承父目录的条带属性。当使用 `llapi_dir_create()` 尝试设置条带属性时：

1. 目录已存在（通过 `mkdir` 创建）
2. 目录自动继承了父目录的默认条带属性（stripe_count=1）
3. `llapi_dir_create()` 检测到条带属性已存在，返回 `EEXIST` 错误
4. 代码错误地认为这是成功状态，没有重新设置条带属性

## 尝试过的失败方案

### 方案 1: 直接使用 `llapi_dir_create()`

```cpp
// 失败 - 目录已继承父目录的默认条带属性
llapi_dir_create(path.c_str(), mode, &param);
// 返回: stripe already set
```

### 方案 2: 先删除目录再创建

```cpp
// 失败 - rmdir 后立即调用 llapi_dir_create 仍然失败
rmdir(parentPath.c_str());
llapi_dir_create(parentPath.c_str(), mode, &param);
// 仍然返回: stripe already set
```

## 解决方案

使用 `lfs setstripe` 命令在父目录设置条带属性，让子目录自动继承：

```cpp
Status LustreFile::SetStripedDirectory(const std::string& path,
                                       int stripeCount,
                                       size_t stripeSize,
                                       mode_t mode)
{
    // 1. 提取父目录（去掉 /data 后缀）
    std::string parentPath = path;
    const std::string dataSuffix = "/data";
    if (parentPath.length() > dataSuffix.length() &&
        parentPath.substr(parentPath.length() - dataSuffix.length()) == dataSuffix) {
        parentPath = parentPath.substr(0, parentPath.length() - dataSuffix.length());
    }

    // 2. 创建父目录
    auto s = MkDir(parentPath, mode);
    if (s.Failure()) {
        UC_ERROR("Failed to create parent directory {}: {}", parentPath, s.ToString());
        return s;
    }

    // 3. 使用 lfs setstripe 设置条带属性
    std::string cmd = "lfs setstripe " + parentPath + " -c " + std::to_string(stripeCount) +
                      " -S " + std::to_string(stripeSize) + " 2>&1";

    FILE* pipe = popen(cmd.c_str(), "r");
    if (pipe) {
        // ... 读取输出并检查状态
    }

    // 4. 创建 data 子目录（自动继承条带属性）
    s = MkDir(path, mode);
    return Status::OK();
}
```

## 验证

```bash
$ lfs getstripe /mnt/lustre47/final_test
stripe_count:  4  ✅
stripe_size:   1048576
pattern:       raid0
stripe_offset: -1

$ lfs getstripe /mnt/lustre47/final_test/data
stripe_count:  4  ✅ (自动继承)
stripe_size:   1048576
pattern:       raid0
stripe_offset: -1
```

## 预防措施

1. **使用命令行工具而非 API**: `lfs setstripe` 比 `llapi_dir_create()` 更可靠
2. **在父目录设置条带属性**: 子目录会自动继承，简化代码逻辑
3. **验证条带属性**: 在测试中使用 `lfs getstripe` 验证条带属性是否正确设置

## 相关代码

- `ucm/store/lustre/cc/lustre_file.cc` - `SetStripedDirectory()` 实现
- `ucm/store/lustre/cc/space_layout.cc` - 调用条带化目录创建
- `test/suites/Unit/test_lustre_p3_striping.py` - P3 条带化测试
