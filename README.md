# TopoCode

> **English**: [README.en.md](README.en.md) | 版本: v0.1.0 beta

源码架构分析与学习工具。自动解析项目源码结构，生成多层级的组件依赖图、调用关系分析、架构分析报告，支持 AI 辅助分析。

## 功能特性

- **多语言源码解析** — 基于 Tree-sitter 的 AST 解析，当前支持 C/C++、Python、JavaScript/TypeScript、Go、Java、其他语言后续拓展
- **架构分析** — 组件依赖分析、调用链分析、社区检测（Louvain 算法）
- **AI 辅助报告生成** — 基于 LLM 的组件分析、架构文档自动生成
- **可视化** — 内联 Mermaid / PlantUML 图表渲染
- **Web 文档预览** — 浏览器访问本地 HTTP 服务，查看架构文档和社区目录
- **多项目管理** — 项目分组、任务管理、分析报告管理

## 技术栈

| 层 | 技术 |
|---|---|
| 前端框架 | Electron + Vue 3 + TypeScript + Vite |
| 状态管理 | Pinia |
| 可视化 | D3.js、Mermaid、Pixi.js |
| 后端服务 | Python 3.10+、FastAPI、ZeroMQ |
| 源码解析 | Tree-sitter |
| 图计算 | NetworkX、python-louvain |
| AI 集成 | 兼容 OpenAI / Ollama / LM Studio API |

## 环境要求

### 通用依赖

- **Node.js** >= 18
- **npm** >= 9
- **Python** >= 3.10（后端运行必需，客户机需要安装）

### 各平台编译环境

#### Linux（原生构建）

```bash
# 构建依赖
sudo apt install python3 python3-pip nodejs npm

# 构建打包
npm run dist:linux
```

#### macOS（原生构建）

```bash
# 构建依赖
brew install node python@3.12

# 构建打包
npm run dist:mac
```

#### Windows（原生构建 — 在 Windows 上执行）

```bash
# 构建依赖
# 1. 安装 Node.js >= 18（https://nodejs.org）
# 2. 安装 Python >= 3.10（https://python.org）
# 3. 安装 Visual Studio Build Tools（C++ 构建工具，用于编译 native 模块）
#    下载: https://visualstudio.microsoft.com/visual-cpp-build-tools/
#    安装工作负荷: "使用 C++ 的桌面开发"

# 构建打包
npm run dist:win
```

#### Windows（Linux 交叉编译）

从 Linux 为 Windows 编译安装包，需要额外准备 Windows Electron 运行时：

```bash
# 1. 下载 Windows Electron（与 package.json 中 electron 版本一致）
#    当前版本: 33.4.11
npx electron-download --version=33.4.11 --platform=win32 --arch=x64 -o ../electron-win

# 2. 构建打包
npm run dist:win
```

交叉编译时，`afterPack` 脚本会自动下载 Windows 版 Python wheel 到打包目录。

## 源码安装

### 前置准备：Python 虚拟环境（推荐）

开发时建议使用虚拟环境隔离 Python 依赖，避免与系统 Python 包冲突。

```bash
# 创建虚拟环境（在项目根目录下）
python3 -m venv .venv

# 激活虚拟环境
# Linux / macOS
source .venv/bin/activate
# Windows (cmd)
.venv\Scripts\activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# 安装后端依赖
pip install -r backend/requirements.txt
```

> 虚拟环境激活后，`findPython()` 会通过 PATH 自动发现 `.venv/bin/python`，无需额外配置。
> 开发完成后执行 `deactivate` 退出虚拟环境。

### 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/shenglun365/topoCode.git
cd topoCode

# 2. 安装前端依赖
npm install

# 3. 构建前端
npm run build

# 4. 创建并激活 Python 虚拟环境（见上方说明），然后安装依赖
pip install -r backend/requirements.txt

# 5. 打包应用（可选，直接生成可执行文件）
npm run package
```

## 开发运行

```bash
# 前端开发模式（热更新）
npm run dev

# Python 后端调试（确保先激活虚拟环境）
source .venv/bin/activate
# Windows: .venv\Scripts\activate
python backend/main.py --http-port 3456

# 完整应用调试（Electron + 后端自动启动）
npm run dev:electron
```

## 项目结构

```
topoCode/
├── src/                    # 前端源码
│   ├── components/         # Vue 组件
│   ├── pages/              # 页面
│   ├── stores/             # Pinia 状态管理
│   ├── services/           # IPC 服务
│   ├── composables/        # 组合式 API
│   ├── types/              # TypeScript 类型定义
│   └── i18n/               # 国际化
├── backend/                # Python 后端
│   ├── main.py             # 后端入口
│   ├── core_service.py     # 业务逻辑
│   ├── llm_service.py      # LLM 调用
│   ├── zmq_server.py       # ZMQ 通信
│   ├── web_server.py       # HTTP 文档服务
│   ├── plantuml_service.py # PlantUML 渲染
│   ├── static/             # Web 静态文件
│   └── config/             # 配置文件
├── electron/               # Electron 主进程
├── build/                  # 构建脚本
│   └── afterPack.cjs       # 打包后 Python 依赖安装
├── electron-builder-win.json  # Windows 交叉编译配置
└── package.json
```

## 许可

Apache-2.0 License — 详见 [LICENSE](LICENSE)
