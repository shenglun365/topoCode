# TopoOne

> **English**: [README.en.md](README.en.md) | 源码架构分析与报告生成工具

自动解析项目源码结构，生成多层级的组件依赖图、调用关系分析、AI 架构分析报告。

## 功能特性

- **多语言源码解析** — Tree-sitter AST 解析，支持 C/C++、Python、JavaScript/TypeScript、Go、Java 等
- **架构分析** — 符号提取 → 调用图 → 依赖图 → Louvain 社区发现
- **AI 分析** — LLM 组件命名/摘要/图表，架构文档自动生成
- **可视化** — D3.js 力导向图、Mermaid / PlantUML 图表
- **报告生成** — 可编排的流水线：验证 → 概要 → 社区分析 → 整体架构
- **子文档管理** — Markdown 预览/编辑，支持按社区查看

## 技术栈

| 层 | 技术 |
|---|---|
| 前端框架 | Electron + Vue 3 + TypeScript + Vite |
| 状态管理 | Pinia |
| 可视化 | D3.js、Mermaid、Pixi.js |
| 后端服务 | Python 3.10+、ZeroMQ |
| 源码解析 | Tree-sitter |
| 图计算 | NetworkX、python-louvain |
| AI 集成 | 兼容 OpenAI / Ollama / LM Studio |

## 环境要求

- **Node.js** >= 18
- **npm** >= 9
- **Python** >= 3.10

## 快速开始

```bash
# 1. 安装前端依赖
npm install

# 2. 创建并激活 Python 虚拟环境
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# 3. 安装后端依赖
pip install -r backend-core/requirements.txt

# 4. 开发模式运行
npm run dev

# 5. 打包
npm run dist:linux  # Linux
npm run dist:mac    # macOS
npm run dist:win    # Windows
```

## 项目结构

```
topoone-ui/
├── src/                    # Vue 3 前端
│   ├── components/         # 组件 (15 个分组)
│   ├── pages/              # 页面 (6 个)
│   ├── stores/             # Pinia 状态 (22 个)
│   ├── services/           # IPC 服务层
│   ├── types/              # TypeScript 类型
│   ├── i18n/               # 国际化 (zh-CN/en-US)
│   ├── router/             # 路由
│   └── styles/             # 全局样式
├── backend-core/           # Python 后端
│   ├── main.py             # 入口 + 插件发现 + 方法注册
│   ├── zmq_server.py       # ZMQ RPC 服务器
│   ├── core_service.py     # 项目/分组/知识库/设置
│   ├── task_manager.py     # 分析任务 + 社区操作
│   ├── llm_service.py      # LLM 网关 + 会话管理
│   ├── prompt_manager.py   # 提示词模板 (3 种 mode)
│   ├── analyst_runner.py   # 6 步解析流水线
│   ├── report_tree_service.py # 报告文档持久化
│   ├── sqlite_ctx.py       # SQLite 连接管理 (4 库)
│   ├── config/             # 提示词模板 JSON
│   ├── store/              # 数据库 CRUD 层
│   ├── providers/          # LLM 提供者实现
│   ├── change_tracker/     # 变更追踪
│   └── mcp_server/         # MCP 协议桥
├── electron/               # Electron 主进程
│   ├── main.ts             # IPC 路由 + 窗口管理
│   ├── preload.ts          # contextBridge 暴露 API
│   ├── zmq-router.ts       # ZMQ RPC + 事件订阅
│   └── python-bridge.ts    # Python 子进程管理
├── plugins/                # 后端插件
├── docs/                   # 文档
└── build/                  # 构建脚本
```

## License

Apache-2.0 License
