# UCM Project - Claude Code 配置

本项目使用 Unified Cache Management (UCM) 框架，为 LLM 提供统一的 KV Cache 存储管理。

## 项目概览

- **项目**: UCM (Unified Cache Management)
- **语言**: C++ (后端) + Python (前端)
- **分支**: `lustre` (Lustre Store 实现分支)

### 项目结构

- `docs/solutions/` — 问题解决方案文档（bug、最佳实践、工作流程），按分类组织，带 YAML frontmatter 用于搜索

## gstack 网页浏览工具

**重要**: 使用 gstack 的 `/browse` 技能进行所有网页浏览，永远不要使用 `mcp__claude-in-chrome__*` 工具。

### 可用技能列表

/office-hours、/plan-ceo-review、/plan-eng-review、/plan-design-review、/design-consultation、/design-shotgun、/design-html、/review、/ship、/land-and-deploy、/canary、/benchmark、/browse、/connect-chrome、/qa、/qa-only、/design-review、/setup-browser-cookies、/setup-deploy、/retro、/investigate、/document-release、/codex、/cso、/autoplan、/careful、/freeze、/guard、/unfreeze、/gstack-upgrade、/learn

### 故障排除

如果 gstack 技能无法正常工作，运行以下命令重新构建：
```bash
cd .claude/skills/gstack && ~/.bun/bin/bun install && ~/.bun/bin/bun run build
```

## Lustre Store 开发

当前重点: Lustre 文件系统存储后端的实现。

### 测试命令

```bash
# 运行所有单元测试
source /home/w2938/vllm/bin/activate
python -m pytest test/suites/Unit/test_lustre_p*.py -v

# 运行流程测试
python test/test_lustre_store_flow.py
```

### 构建命令

```bash
# 重新编译 C++ 组件
cd build && make -j8

# 重新安装 Python 包
pip install -v -e . --no-build-isolation
```
