# TopoCode 使用手册 — 总索引

> 本手册供 AI Agent 检索使用。每个文件覆盖一个话题域，文件内按关键词和问答结构组织，适合 grep / RAG 直接定位。

## 手册文件清单

| 文件 | 话题 | 关键词 |
|------|------|--------|
| [projects-and-tasks.md](projects-and-tasks.md) | 项目管理与任务流程 | 导入项目、创建项目、任务创建、任务列表、删除项目、收藏项目、分组筛选 |
| [code-parsing.md](code-parsing.md) | 代码解析与符号提取 | 代码解析、符号提取、AST、Tree-sitter、文件范围、排除目录、任务执行 |
| [architecture-graph.md](architecture-graph.md) | 架构图操作 | 力导向图、表格视图、热力图、全屏、缩放、图配置、齿轮面板、节点位置保存 |
| [community-analysis.md](community-analysis.md) | 社区分析 | 社区、Louvain、下钻、面包屑、层级、回滚、社区命名 |
| [node-filtering.md](node-filtering.md) | 节点筛选 | 筛选面板、隐藏节点、分类筛选、诊断面板、搜索节点、高亮 |
| [snapshot-comparison.md](snapshot-comparison.md) | 版本对比 | 对比、快照、diff、变更、版本、新增社区、删除社区 |
| [ai-assistant.md](ai-assistant.md) | AI 助手 | AI 对话、LLM、模型、会话、Coder、结构化输出、Agent 分析 |
| [architecture-docs.md](architecture-docs.md) | 架构文档 | 架构报告、生成文档、Markdown、Mermaid、PlantUML、社区文档 |
| [settings-config.md](settings-config.md) | 配置与设置 | 设置、模型配置、Ollama、OpenAI、Theme、语言、ZMQ |
| [troubleshooting.md](troubleshooting.md) | 故障排查 | 报错、后端未启动、解析失败、LLM 不可用、ZMQ 连接 |
| [shortcuts.md](shortcuts.md) | 快捷键 | 键盘快捷键、热键、快速操作 |

## 快速查找指南

### 按用户问题类型查找

| 用户问题 | 查哪份文档 |
|---------|----------|
| "怎么导入项目" "如何新建项目" | projects-and-tasks.md |
| "分析任务怎么创建" "任务失败怎么办" | projects-and-tasks.md, code-parsing.md |
| "图怎么看" "怎么放大缩小" "怎么全屏" | architecture-graph.md |
| "什么是指标" "社区是什么意思" | community-analysis.md |
| "怎么只看某些节点" | node-filtering.md |
| "怎么对比两个版本" | snapshot-comparison.md |
| "AI 怎么用" "大模型怎么配" | ai-assistant.md, settings-config.md |
| "怎么生成文档" | architecture-docs.md |
| "怎么切换语言" "怎么换主题" | settings-config.md |
| "后端连不上" "报错了" | troubleshooting.md |

## 产品概述

**TopoCode** 是一款源码架构分析与学习工具。核心流程：

```
导入项目 → 创建分析任务 → 代码解析(符号提取+调用分析) → 社区发现(Louvain) → 架构图可视化 → AI 报告生成
```

**主要页面**：
- `/home` — 项目导入与管理
- `/code` — 代码解析与符号浏览
- `/analysis` — 架构图、社区分析、报告
- `/knowledge` — 知识库
- `/coder` — AI 助手对话
- `/user` — 设置与模型配置
