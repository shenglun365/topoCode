# TopoOne

> [中文](README.md) | Source code architecture analysis & report generation tool

Automatically parse project source code, generate multi-level component dependency graphs, call chain analysis, and AI-powered architecture analysis reports.

## Features

- **Multi-language Parsing** — Tree-sitter based AST parsing (C/C++, Python, JavaScript/TypeScript, Go, Java, and more)
- **Architecture Analysis** — Symbol extraction → Call graph → Dependency graph → Louvain community detection
- **AI Analysis** — LLM-powered component naming/summary/diagrams, automated architecture document generation
- **Visualization** — D3.js force-directed graphs, Mermaid / PlantUML rendering
- **Report Generation** — Orchestrated pipeline: validation → summary → community analysis → overall architecture
- **Sub-document Management** — Markdown preview/edit, per-community document viewing

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Electron + Vue 3 + TypeScript + Vite |
| State Management | Pinia |
| Visualization | D3.js, Mermaid, Pixi.js |
| Backend | Python 3.10+, ZeroMQ |
| Source Parsing | Tree-sitter |
| Graph Computing | NetworkX, python-louvain |
| AI Integration | OpenAI / Ollama / LM Studio compatible |

## Requirements

- **Node.js** >= 18
- **npm** >= 9
- **Python** >= 3.10

## Quick Start

```bash
# 1. Install frontend dependencies
npm install

# 2. Create and activate Python virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS

# 3. Install backend dependencies
pip install -r backend-core/requirements.txt

# 4. Run in development mode
npm run dev

# 5. Package
npm run dist:linux
npm run dist:mac
npm run dist:win
```

## Project Structure

```
topoone-ui/
├── src/                    # Vue 3 frontend
│   ├── components/         # Components (15 categories)
│   ├── pages/              # Pages (6)
│   ├── stores/             # Pinia stores (22)
│   ├── services/           # IPC service layer
│   ├── types/              # TypeScript types
│   ├── i18n/               # Internationalization (zh-CN/en-US)
│   ├── router/             # Vue Router
│   └── styles/             # Global styles
├── backend-core/           # Python backend
│   ├── main.py             # Entry point + plugin discovery
│   ├── zmq_server.py       # ZMQ RPC server
│   ├── core_service.py     # Projects/groups/knowledge/settings
│   ├── task_manager.py     # Analysis tasks + communities
│   ├── llm_service.py      # LLM gateway + sessions
│   ├── prompt_manager.py   # Prompt templates (3 modes)
│   ├── analyst_runner.py   # 6-step parsing pipeline
│   ├── report_tree_service.py # Report document persistence
│   ├── sqlite_ctx.py       # SQLite connection manager (4 DBs)
│   ├── config/             # Prompt template JSON
│   ├── store/              # Database CRUD layer
│   ├── providers/          # LLM provider implementations
│   ├── change_tracker/     # Change tracking
│   └── mcp_server/         # MCP protocol bridge
├── electron/               # Electron main process
│   ├── main.ts             # IPC routing + window management
│   ├── preload.ts          # contextBridge API exposure
│   ├── zmq-router.ts       # ZMQ RPC + event subscription
│   └── python-bridge.ts    # Python child process management
├── plugins/                # Backend plugins
├── docs/                   # Documentation
└── build/                  # Build scripts
```

## License

Apache-2.0 License
