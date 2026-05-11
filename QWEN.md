# TopoOne UI — Qwen Code 指南

## 项目定位

本地化、插件化、AI 驱动的源码架构分析与可视化教学工具。

## 技术栈

- **前端**: Electron + Vue 3.5 + TypeScript + Element Plus + Tailwind CSS
- **可视化**: Mermaid, PlantUML, D3.js, PixiJS v8, TopoScript 动画引擎
- **后端**: Python (pyzmq) + Tree-sitter + SQLite (30 文件)
- **通信**: Electron IPC + ZeroMQ RPC (5671/5680)

## 目录结构要点

| 目录 | 用途 | 注意 |
|------|------|------|
| `src/lib/topo-animation/` | TopoScript 动画引擎 (45 文件) | 从 transplant-animation/ 迁移 |
| `backend/` | Python 后端 (30 文件) | 从 transplant-parser-service/ 移植 |
| `src/components/visualization/` | 可视化组件 (6 文件) | AnimationStage 已对接 AnimationEngine |
| `transplant-animation/` | DEPRECATED | 已迁移至 src/lib/topo-animation/ |
| `transplant-parser-service/` | DEPRECATED | 已移植至 backend/ |

## 关键架构决策

1. **渲染架构**: 混合 — Mermaid/D3 布局走 Worker, PlantUML 走 Python 后端, PixiJS/AnimationEngine 走主线程
2. **ZeroMQ**: 端口 5671 (DEALER RPC) + 5680 (PUB 事件), 3 帧消息格式, requestId 追踪
3. **SQLite**: 4 类独立数据库 (主库 10 表 / 知识库 1 表 / 会话库 2 表 / 项目库 13 表), WAL 并发模式
4. **i18n**: 全部组件已完成迁移, Pinia store 中直接导入 i18n 实例 (不能调用 useI18n())
5. **图标**: 统一使用 Heroicons (`@heroicons/vue/24/outline`), 禁止 Unicode emoji

## 关键约定

- 代码风格: 单引号、无分号、2 空格缩进
- Vue 组件: `<script setup lang="ts">` + composables
- 类型: strict mode, 显式类型标注
- 测试: vitest, tests/ 目录

## 参考文档

- `docs/源码文件说明.md` — 完整文件清单 (260+ 文件)
- `docs/前后端服务通讯协议.md` — 56 个后端方法
- `docs/数据库结构说明.md` — 26 张表
- `docs/需求文档.md` — 功能需求
- `docs/GUI交互层设计方案.md` — UI 设计
