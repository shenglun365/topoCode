# TopoCode

> Version: v0.1.0 beta | [中文](README.md)

Source code architecture analysis and learning tool. Automatically parse project source code structure, generate multi-level component dependency graphs, call chain analysis, architecture analysis reports, with AI-assisted analysis.

## Features

- **Multi-language Source Parsing** — Tree-sitter based AST parsing, currently supports C/C++, Python, JavaScript/TypeScript, Go, Java, with more languages coming
- **Architecture Analysis** — Component dependency analysis, call chain analysis, community detection (Louvain algorithm)
- **AI-assisted Report Generation** — LLM-based component analysis, automated architecture document generation
- **Visualization** — Inline Mermaid / PlantUML diagram rendering
- **Web Document Preview** — Browse architecture documents and community directories via local HTTP service
- **Multi-project Management** — Project grouping, task management, analysis report management

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend Framework | Electron + Vue 3 + TypeScript + Vite |
| State Management | Pinia |
| Visualization | D3.js, Mermaid, Pixi.js |
| Backend Service | Python 3.10+, FastAPI, ZeroMQ |
| Source Parsing | Tree-sitter |
| Graph Computing | NetworkX, python-louvain |
| AI Integration | OpenAI / Ollama / LM Studio compatible API |

## Requirements

### General Dependencies

- **Node.js** >= 18
- **npm** >= 9
- **Python** >= 3.10 (required for backend runtime)

### Platform Build Environments

#### Linux (Native Build)

```bash
# Build dependencies
sudo apt install python3 python3-pip nodejs npm

# Build & package
npm run dist:linux
```

#### macOS (Native Build)

```bash
# Build dependencies
brew install node python@3.12

# Build & package
npm run dist:mac
```

#### Windows (Native Build — run on Windows)

```bash
# Build dependencies
# 1. Install Node.js >= 18 (https://nodejs.org)
# 2. Install Python >= 3.10 (https://python.org)
# 3. Install Visual Studio Build Tools (C++ build tools for native modules)
#    Download: https://visualstudio.microsoft.com/visual-cpp-build-tools/
#    Install workload: "Desktop development with C++"

# Build & package
npm run dist:win
```

#### Windows (Cross-compile from Linux)

To build Windows packages from Linux, additional Windows Electron runtime is required:

```bash
# 1. Download Windows Electron (match version in package.json)
#    Current version: 33.4.11
npx electron-download --version=33.4.11 --platform=win32 --arch=x64 -o ../electron-win

# 2. Build & package
npm run dist:win
```

During cross-compilation, the `afterPack` script will automatically download Windows Python wheels to the package directory.

## Source Installation

### Prerequisite: Python Virtual Environment (Recommended)

Using a virtual environment isolates Python dependencies and avoids conflicts with system packages.

```bash
# Create virtual environment (in project root)
python3 -m venv .venv

# Activate virtual environment
# Linux / macOS
source .venv/bin/activate
# Windows (cmd)
.venv\Scripts\activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# Install backend dependencies
pip install -r backend/requirements.txt
```

> Once the virtual environment is active, `findPython()` will automatically discover `.venv/bin/python` via PATH — no additional configuration needed.
> Run `deactivate` to exit the virtual environment when done.

### Installation Steps

```bash
# 1. Clone the repository
git clone https://github.com/topocode/topoone-ui.git
cd topoone-ui

# 2. Install frontend dependencies
npm install

# 3. Build the frontend
npm run build

# 4. Create and activate Python virtual environment (see above), then install dependencies
pip install -r backend/requirements.txt

# 5. Package the application (optional, directly generates executable)
npm run package
```

## Development

```bash
# Frontend dev mode (hot reload)
npm run dev:vite

# Python backend debugging (ensure virtual environment is activated first)
source .venv/bin/activate
python backend/main.py --http-port 3456

# Full app debugging (Electron + auto-start backend)
npm run dev
```

## Project Structure

```
topoone-ui/
├── src/                    # Frontend source code
│   ├── components/         # Vue components
│   ├── pages/              # Pages
│   ├── stores/             # Pinia state management
│   ├── services/           # IPC services
│   ├── composables/        # Composition API
│   ├── types/              # TypeScript type definitions
│   └── i18n/               # Internationalization
├── backend/                # Python backend
│   ├── main.py             # Backend entry point
│   ├── core_service.py     # Business logic
│   ├── llm_service.py      # LLM calls
│   ├── zmq_server.py       # ZMQ communication
│   ├── web_server.py       # HTTP document service
│   ├── plantuml_service.py # PlantUML rendering
│   ├── static/             # Web static files
│   └── config/             # Configuration files
├── electron/               # Electron main process
├── build/                  # Build scripts
│   └── afterPack.cjs       # Post-pack Python dependency install
├── website/                # Official website (static HTML)
├── docs/                   # Documentation
│   ├── 使用文档.md          # Usage documentation (Chinese)
│   └── images/             # Screenshots for documentation
├── electron-builder-win.json  # Windows cross-compile config
└── package.json
```

## License

Apache-2.0 License — see [LICENSE](LICENSE)
