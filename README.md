# TopoCode

> **English** · [English](README.en.md)

<p align="center">
  <picture>
    <source srcset="assets/star-logo-zh.svg" type="image/svg+xml">
    <img src="docs/logo-zh.png" alt="TopoCode" width="660">
  </picture>
</p>

> 源码架构深度分析工具 —— 面向「深度代码学习」场景的「分析显微镜」，提升人的架构认知水平。

TopoCode 不是一句提示词生成架构图的效率工具，而是帮助你逐层理解项目架构、**提升架构认知能力**的分析平台。通过静态代码解析、依赖图计算、社区发现算法和 AI 辅助分析，挖掘代码背后的设计逻辑与模块关系，帮助开发者真正理解陌生项目的架构设计。

---

> **隐私说明**：除用户自行配置的云端 LLM API 外，TopoCode 的代码解析、图计算、架构分析、Web 文档服务等所有功能均在**本地运行**，项目源码和解析数据不会上传至任何外部服务器，确保用户数据隐私安全。

## 功能特性

- **项目导入与管理** — 支持本地目录导入、文件树浏览、分组管理
- **多语言代码解析** — 基于 Tree-sitter 的 AST 解析，支持 18+ 编程语言
- **架构可视化** — 依赖图/调用图/社区结构图（D3.js / Cytoscape），支持交互式浏览
- **社区发现** — Louvain / Leiden 算法自动识别代码模块（社区）结构
- **AI 架构分析** — LLM 驱动的工作流，自动分析组件功能、生成架构概览文档
- **交互式 AI 助手** — 基于项目上下文的智能问答，支持工具调用（符号搜索、文件读取等），通过本地 Web 端口提供浏览器端对话界面
- **知识库** — 分析文档持久化存储（分类管理待实现）。知识库是迭代重点，目标是成为与用户认知高度契合的**外脑知识库**，不仅静态存储，未来还将支持通过多种对接方式，帮助用户指挥驾驭其他 Agent 工具，实现知识的**存储 → 分析 → 使用**闭环
- **Web 文档服务** — 本地 HTTP 服务（默认 3456 端口），浏览器中浏览架构文档和使用 AI 对话
- **多语言支持** — 中文 / English 界面与 AI 分析输出

---

## 技术栈

| 层级 | 技术 |
|---|---|
| **前端框架** | Vue 3 + TypeScript + Pinia + Vue Router |
| **UI 样式** | Tailwind CSS + SCSS + Heroicons |
| **可视化** | D3.js + Cytoscape + Mermaid + PlantUML + PixiJS |
| **桌面端** | Electron + electron-builder |
| **后端语言** | Python 3.10+ |
| **IPC 通信** | ZeroMQ (pyzmq) |
| **代码解析** | Tree-sitter (18+ 语言) |
| **图计算** | NetworkX + python-louvain + leidenalg + python-igraph |
| **Web 服务** | FastAPI + Uvicorn |
| **AI 推理** | OpenAI / Ollama / LM Studio 兼容接口 |
| **数据库** | SQLite + DuckDB |

---

## 使用教程

详细的使用流程请参考：
- [中文使用教程](docs/usage-guide-zh.md)
- [English Usage Guide](docs/usage-guide-en.md)

---

## 目录结构

```
topoOne-ui/
├── src/                          # 前端 Vue 3 应用
│   ├── components/               # UI 组件
│   │   ├── ai/                   # AI 助手面板
│   │   ├── analysis/             # 分析任务相关
│   │   ├── knowledge/            # 知识库
│   │   ├── project/              # 项目管理
│   │   ├── report/               # 架构报告
│   │   ├── settings/             # 设置页
│   │   ├── shell/                # 应用壳 (ActivityBar, TopBar, StatusBar)
│   │   └── visualization/        # 可视化组件
│   ├── composables/              # 组合式函数
│   ├── pages/                    # 路由页面
│   ├── router/                   # 路由配置
│   ├── services/                 # IPC 服务 (ZeroMQ 调用)
│   ├── stores/                   # Pinia 状态管理
│   ├── i18n/                     # 国际化 (zh-CN / en-US)
│   └── types/                    # TypeScript 类型定义
├── electron/                     # Electron 主进程
│   ├── main.ts                   # 主进程入口 + IPC 处理
│   ├── preload.ts                # contextBridge 安全桥接
│   ├── window-manager.ts         # 多窗口管理
│   ├── python-bridge.ts          # Python 后端进程管理
│   ├── zmq-router.ts             # ZeroMQ 消息路由
│   └── updater.ts                # 自动更新
├── backend-core/                 # Python 后端
│   ├── main.py                   # 后端入口 (单进程 / 分布式)
│   ├── zmq_server.py             # ZeroMQ RPC 服务
│   ├── core_service.py           # 核心业务方法注册
│   ├── llm_service.py            # LLM 推理服务
│   ├── task_manager.py           # 分析任务管理器
│   ├── sqlite_ctx.py             # SQLite 多数据库管理
│   ├── agent_workflow/           # AI Agent 工作流
│   │   ├── workflows/            # 预定义工作流 (overview, component 等)
│   │   ├── toolkits/             # 工具集 (文件、符号、图)
│   │   └── runtime.py            # Agent 运行时
│   ├── prompt_manager.py         # Prompt 模板管理
│   ├── providers/                # LLM 提供商适配 (OpenAI, Ollama)
│   ├── messaging/                # 内部消息总线
│   ├── ingest/                   # 数据 ingest 管道
│   ├── data_layer/               # 数据访问层 (cache, duckdb)
│   └── store/                    # 持久化存储
├── plugins/                      # 插件系统
│   ├── parsers/                  # 代码解析器 (Tree-sitter)
│   ├── community/                # 社区发现算法
│   ├── reports/                  # Web 文档服务 (FastAPI)
│   └── installer/                # AI 编码工具安装器
├── build/                        # 构建脚本
├── scripts/                      # 开发调试脚本
└── tests/                        # 单元测试
```

---

## 安装与运行

### 推荐运行环境

- **CPU**: 4 核心及以上
- **内存**: 16 GB 及以上
- **系统**: Linux / macOS / Windows（物理机或虚拟机均可）
- **硬盘**: 至少 10 GB 可用空间（用于存储解析数据和知识库）

> **本地模型硬件要求**：运行 Qwen3.6-9B-Q4 量化等本地模型建议 **NVIDIA RTX 4060 Ti 16GB 或以上** 显卡。如果没有独立 GPU，本地模型将使用 CPU 推理，速度会慢得多。如果仅使用云端模型（如 DeepSeek V4 Flash），4 核 8G 配置也可满足基本使用。

> **图形界面运行说明**：本软件包含 Electron 图形界面组件。在无桌面环境的虚拟机、云服务器或纯命令行系统中运行时，需手动安装虚拟显示服务以提供图形渲染支持。物理机或已安装桌面环境的系统无需额外配置。

### 系统环境与虚拟显示方案对照

| 系统环境 | 桌面环境 | 所需操作 | 安装命令 |
|---|---|---|---|
| 物理机 / 工作站 (Windows / macOS / Linux 桌面版) | 已预装 | 无需操作 | — |
| Linux 服务器 (Ubuntu / Debian) | 无 | 安装 xvfb | `sudo apt install xvfb` |
| Linux 服务器 (CentOS / RHEL / Fedora) | 无 | 安装 Xvfb | `sudo yum install xorg-x11-server-Xvfb` |
| 云服务器 / 虚拟机 (无 GUI) | 无 | 安装 xvfb | 同上，根据系统选择对应命令 |
| WSL 1/2 | 无 | 安装 VcXsrv + 配置 DISPLAY | Windows 安装 VcXsrv，WSL 中执行 `export DISPLAY=:0` |
| Docker 容器 | 无 | 使用 xvfb-run | `xvfb-run npm run dev` |

### LLM 分析效率预估

架构分析各阶段耗时受**代码规模**、**LLM 性能**和**并发配置**影响。以下为典型预估（单并发，50 tokens/s）：

| 阶段 | 预估耗时 | 说明 |
|---|---|---|
| **语法解析 + 组件关系分析** | 2~5 分钟 | 纯静态分析，不依赖 LLM |
| **5000 源码文件分析** | 10~20 分钟 | 文件遍历与基础元数据提取 |
| **文件预摘要** | ~1 分钟 / 个 | 数百文件需数小时，LLM 密集阶段 |
| **组件分析** | 1~5 分钟 / 个 | 受组件规模影响，需多轮 LLM 对话 |
| **整体架构生成** | 1~5 分钟 | 综合摘要生成架构概览 |

> **加速建议**：您可以注册账户，通过 **用户中心 → 资源中心** 获取预分析好的架构内容，资源中心会定期更新热门项目的分析数据，免去本地等待时间。

### 前置要求

- **Node.js** >= 20.0.0
- **Python** >= 3.10
- **npm** 或 **pnpm**
- **pip**

### 1. 安装前端依赖

```bash
# 使用国内镜像安装（一行命令，不修改环境变量）
ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/" \
  npm install --registry=https://registry.npmmirror.com

# Windows PowerShell 使用：
# $env:ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
# npm install --registry=https://registry.npmmirror.com

# 或使用 pnpm（更快，无需全局安装）
# npx pnpm install --registry=https://registry.npmmirror.com
```

### 2. 创建 Python 虚拟环境并安装依赖

> `npm run dev` 会自动检测项目根目录下的虚拟环境（`.venv/` 或 `venv/`），优先使用其中的 Python 解释器。

```bash
# 创建虚拟环境并一行命令安装依赖（不污染全局 Python）
python3 -m venv .venv && \
  source .venv/bin/activate && \
  cd backend-core && \
  pip install -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --trusted-host pypi.tuna.tsinghua.edu.cn

# Windows PowerShell：
# python3 -m venv .venv; `
#   .venv\Scripts\Activate.ps1; `
#   cd backend-core; `
#   pip install -r requirements.txt `
#     -i https://pypi.tuna.tsinghua.edu.cn/simple `
#     --trusted-host pypi.tuna.tsinghua.edu.cn

# 或使用阿里云镜像（替换上述 -i 和 --trusted-host 参数）：
#   -i https://mirrors.aliyun.com/pypi/simple/
#   --trusted-host mirrors.aliyun.com
```

### 3. 运行开发模式

```bash
# 启动前端 Vite 开发服务器 + Electron
npm run dev

# 仅启动 Vite 前端（浏览器中开发）
npm run dev:vite

# 调试模式（更多日志输出）
npm run dev:debug
```

首次启动时会自动启动 Python 后端进程。前端访问地址: `http://localhost:5173`

### 4. 构建生产版本

```bash
npm run build

# 打包为桌面应用
npm run dist:linux   # Linux
npm run dist:win     # Windows
npm run dist:mac     # macOS
npm run dist:all     # 全平台
```

---

## 配置 LLM

启动应用后，在 **设置 → 模型配置** 中添加 LLM 模型。支持任何兼容 OpenAI API 格式的提供商。

### 模型选择建议

| 用途 | 推荐方案 | 说明 |
|---|---|---|
| **架构解析 (Agent 工作流)** | 本地模型 Qwen3.6-9B 及以上 (Ollama / LM Studio) | 架构解析需要大量 token，涉及多轮工具调用和文件摘要。**建议本地部署**，节省费用且保证响应速度 |
| **AI Chat 对话** | 云端高级模型，如 **DeepSeek V4 Flash** | 交互式对话对模型能力要求较高，DeepSeek V4 Flash 性价比优异。也可根据需求选择 GPT-4o / Claude 等 |

### 常见配置

- **Ollama 本地模型**: `http://localhost:11434`
- **OpenAI 协议兼容**（支持所有兼容 OpenAI API 格式的模型服务，如 DeepSeek、Qwen 等）: `https://api.openai.com`
- **DeepSeek**: `https://api.deepseek.com`
- **LM Studio**: `http://localhost:1234`

---

## Web 文档服务 & AI 助手

应用运行后，**AI 助手交互界面和文档浏览均通过本地 Web 服务提供**，默认监听 `http://localhost:3456`：

- `/` — 项目文档首页
- `/doc` — 文档查看器（支持 Mermaid / PlantUML 渲染）
- `/chat` — AI 对话界面（无需 Electron，浏览器即可使用 AI 助手）

可通过 **设置 → 通用设置** 修改 HTTP 端口与绑定地址。

---

## 开发

```bash
# 代码检查
npm run type-check    # TypeScript 类型检查
npm run lint          # ESLint 代码风格检查

# 测试
npm run test          # 前端测试
cd backend-core && python -m pytest tests/  # 后端测试
```

---

## 许可证

[Apache License 2.0](LICENSE)

---

## 联系我们

- 开发者邮箱: **topocode@163.com**
- 项目地址: [https://github.com/topocode/topoone-ui](https://github.com/topocode/topoone-ui)
- 问题反馈: [https://github.com/topocode/topoone-ui/issues](https://github.com/topocode/topoone-ui/issues)
