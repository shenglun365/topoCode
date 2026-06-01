# TopoCode Usage Guide

> Version: 0.1.0 | Source Code Architecture Analysis & Learning Tool

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Installation & Setup](#2-installation--setup)
3. [Interface Overview](#3-interface-overview)
4. [Project Management](#4-project-management)
5. [Code Parsing](#5-code-parsing)
6. [Code Analysis](#6-code-analysis)
7. [AI Assistant](#7-ai-assistant)
8. [Knowledge Base](#8-knowledge-base)
9. [Settings & Configuration](#9-settings--configuration)
10. [FAQ](#10-faq)

---

## 1. Introduction

TopoCode is a **source code architecture analysis and learning tool** for developers. It automatically parses project source code, generates multi-level component dependency graphs, call chain analysis, and architecture analysis reports with AI assistance.

### Core Capabilities

| Capability | Description |
|---|---|
| **Multi-language Parsing** | Tree-sitter based AST parsing, supports 11 languages (C, C++, C#, Java, JS, TS, Python, Go, Rust, PHP, Swift) |
| **Architecture Analysis** | Symbol extraction → Call graph → Dependency graph → Louvain community detection |
| **AI Report Generation** | LLM-powered component analysis, automated architecture document generation |
| **Visualization** | D3.js force-directed graphs, Mermaid/PlantUML diagrams, Pixi.js rendering |
| **Knowledge Management** (Planned) | Knowledge graphs, multi-dimensional classification, TopoScript animation demos |
| **Multi-project** | Project grouping, task management, analysis report management |

---

## 2. Installation & Setup

### System Requirements

| Dependency | Version |
|---|---|
| Node.js | >= 18 |
| npm | >= 9 |
| Python | >= 3.10 |
| OS | Windows / macOS / Linux |

### Install from Source

```bash
# 1. Clone the repository
git clone https://github.com/topocode/topoone-ui.git
cd topoone-ui

# 2. Install frontend dependencies
npm install

# 3. Create Python virtual environment and install backend dependencies
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
pip install -r backend/requirements.txt

# 4. Build and package
npm run build
npm run package
```

### Development Mode

```bash
# Terminal 1: Start frontend dev server
npm run dev:vite

# Terminal 2: Start Python backend
source .venv/bin/activate
python backend/main.py --http-port 3456

# Or all-in-one (Electron + backend auto-start)
npm run dev
```

### Build Distributables

```bash
npm run dist:linux   # Linux (.AppImage/.deb/.rpm)
npm run dist:mac     # macOS (.dmg/.zip)
npm run dist:win     # Windows (.exe NSIS installer)
```

---

## 3. Interface Overview

TopoCode features a VS Code-style IDE layout.

![Interface Layout](images/screenshot-interface-layout.png)

*Interface overview: Activity Bar, side panels, content area, status bar*

### Layout Elements

| Area | Function |
|---|---|
| **Activity Bar** | Left navigation: Home (Projects), Code, Analysis, Knowledge, Settings |
| **Top Bar** | Menu bar + theme switcher + import button + zoom controls |
| **Left Panel** | Project list, file tree |
| **Content Area** | Main page content (routed) |
| **Right Panel** | AI assistant, code index, report task list, debug panel |
| **Status Bar** | Backend status, AST readiness, Git branch, AI model |

![Status Bar](images/screenshot-status-bar.png)

*Status bar: backend / AST / Git / model info*

### Page Routes

| Route | Page | Function |
|---|---|---|
| `/home` | Project Import | Project management, grouping, file tree, task creation |
| `/code` | Code Parsing | Task creation, file statistics, code preview |
| `/analysis` | Code Analysis | Analysis reports, community graph, AI analysis |
| `/knowledge` | Knowledge Base (Planned) | Knowledge graph, document management, animation player |
| `/coder` | AI Assistant (Planned) | Multi-session chat, code Q&A |
| `/user` | Settings | Model config, theme editor, general settings |

---

## 4. Project Management

### 4.1 Project List

![Project List](images/screenshot-home-project-list.png)

*Home page project list: card grid showing all imported projects*

The home page displays all imported projects as a grid of cards, supporting search, group filtering, and favorites filtering.

### 4.2 Import a Project

![Project Import](images/screenshot-home-project-import.png)

*Drag-and-drop import zone supporting both file dialog and drag-and-drop*

1. Click the **Import** button on the Top Bar, or drag-and-drop onto the `ImportZone`
2. Select a local source code directory
3. The system automatically detects the project language and file structure

### 4.3 Project Group Management

![Project Groups 1](images/screenshot-home-project-groups-1.png)

*Project groups 1: group list and manager*

![Project Groups 2](images/screenshot-home-project-groups-2.png)

*Project groups 2: drag-and-drop grouping*

![Project Groups 3](images/screenshot-home-project-groups-3.png)

*Project groups 3: group project management*

![Project Groups 4](images/screenshot-home-project-groups.png)

*Project groups 4: full group view*

The `GroupManager` supports creating tree-structured groups (M:N relationship):

- Create/edit/delete groups
- Projects can belong to multiple groups
- Filter by group using `GroupFilter`

### 4.4 File Tree Browser

![File Tree](images/screenshot-home-file-tree.png)

*File tree: expand/collapse, search, file preview*

- **File Tree**: Left panel displays the project file tree with lazy loading, search, and filtering
- **Code Preview**: Click a file to view highlighted code in `FilePreview`
- **File Statistics**: `FileStatsPanel` shows line counts per language

### 4.5 Project Management Actions

| Action | Description |
|---|---|
| Favorite | Star a project for quick access |
| Pin | Pin to top of list |
| Clear Cache | Selectively clear analysis cache data |
| Delete | Remove project (does not affect source files) |

---

## 5. Code Parsing

### 5.1 Create an Analysis Task

![Create Task](images/screenshot-code-task-create.png)

*Task creation form: select scope, file extensions, exclude directories, report type*

Configure in `TaskCreateForm`:

| Setting | Description |
|---|---|
| Scope | Select files/directories to analyze |
| File Extensions | Limit file types (e.g., `.py`, `.js`) |
| Exclude Directories | Skip directories like `node_modules` |
| Report Type | Select which analysis reports to generate |

### 5.2 Task List

![Task List](images/screenshot-code-task-list.png)

*Task list: displays all analysis tasks with status and progress*

### 5.3 Analysis Pipeline

Once created, the system runs a **6-step analysis pipeline**:

```
Step 1: AST Parsing        → Tree-sitter syntax tree
Step 2: Symbol Extraction  → Extract functions, classes, etc.
Step 3: Call Graph         → Function call relationships
Step 4: Dependency Graph   → Module/file dependency analysis
Step 5: Community Detection → Louvain algorithm for functional modules
Step 6: Result Summary     → Aggregate analysis results
```

### 5.4 Task Details

![Task Detail](images/screenshot-code-task-detail.png)

*Task details: AST view, call chain, dependency graph, community results, execution logs*

After completion, view results in `TaskDetailDialog`:

- **AST View**: Syntax tree structure
- **Call Chain**: Function call relationships
- **Dependency Graph**: Module/file dependency relationships
- **Community Results**: Louvain functional modules
- **Execution Logs**: Logs from each step

### 5.5 File Statistics

![File Statistics](images/screenshot-code-file-stats.png)

*File statistics panel: line count distribution by language, directory tree filtering*

---

## 6. Code Analysis

### 6.1 Report Generation Pipeline

![Report Pipeline](images/screenshot-analysis-report-pipeline.png)

*Report generation pipeline: multi-step LLM-driven architecture analysis*

`ReportGenerationPipeline` provides LLM-driven report generation:

```
Step 0: File Summary Preprocessing  → Extract README/dependency files
Step 1-5: Architecture Analysis     → LLM layer-by-layer analysis
Community AI Analysis               → AI interpretation per community
Overall Architecture Doc            → Global architecture report
```

### 6.2 Community Analysis

![Community Graph](images/screenshot-analysis-community-graph.png)

*Community graph: Louvain-detected functional modules with multi-level expansion*

Community analysis uses the Louvain algorithm to detect functional modules:

- **Multi-level**: Supports L0/L1 multi-level community expansion
- **Edge Types**: Supports `call` and `include` relationships
- **AI Interpretation**: LLM auto-generates descriptions and architecture explanations
- **Diagram Rendering**: Generates Mermaid/PlantUML diagrams per community

### 6.3 Sub-document Viewer

![Sub-doc Viewer](images/screenshot-analysis-subdoc-viewer.png)

*Sub-document viewer: Markdown rendering with inline Mermaid/PlantUML diagrams*

`SubDocViewer` supports:

- Markdown document rendering
- Inline Mermaid diagram rendering
- Inline PlantUML diagram rendering
- Community link navigation
- Edit and save

### 6.4 Mermaid Diagram Rendering

![Mermaid Diagram](images/screenshot-analysis-mermaid-diagram.png)

*Mermaid diagram: inline architecture and flowchart rendering*

### 6.5 Web Viewer

Once the backend is running, visit `http://localhost:3456` in a browser to view:

- Architecture documents
- Community directories
- Source code viewer

---

## 7. AI Assistant

> ⚠️ **Under Development**: AI Assistant is currently under development and not available in v0.1.0 beta. The following describes planned features.

### 7.1 Session Management

![AI Chat Sessions](images/screenshot-ai-chat-sessions.png)

*AI assistant: multi-session tab bar with streaming messages*

- **Multi-session**: Create multiple independent conversations
- **Session Switching**: Quick switch via tab bar
- **Session Delete/Clear**: Manage conversation history

### 7.2 Chat Interface

![AI Chat Messages](images/screenshot-ai-chat-messages.png)

*AI chat: message bubbles, context cards, input area*

The AI assistant supports three interaction modes:

| Mode | Description |
|---|---|
| **Chat** | Free-form conversation, code Q&A |
| **Tools** | Invoke analysis tools (PlantUML rendering, etc.) |
| **Structured Output** | Generate structured reports from templates |

### 7.3 Context Management

- **Context Cards**: Show relevant knowledge, code, and analysis context
- **Spec Cards**: Requirement/specification document context
- **Task Status Cards**: LLM task execution status

### 7.4 LLM Configuration

The AI assistant is compatible with:

- Ollama (local)
- LM Studio (local)
- OpenAI-compatible API

Configure a model in Settings before first use.

---

## 8. Knowledge Base

> ⚠️ **Under Development**: Knowledge Base is currently under development and not available in v0.1.0 beta. The following describes planned features.

### 8.1 Knowledge Graph

![Knowledge Graph](images/screenshot-knowledge-graph.png)

*Knowledge graph: D3.js force-directed graph showing knowledge relationships*

`KnowledgeGraph` visualizes knowledge relationships:

- D3.js force-directed graph
- Mermaid graph view

### 8.2 Document Management

![Knowledge Documents](images/screenshot-knowledge-docs.png)

*Knowledge documents: cards with dimension tags, favorites, and pinning*

- **CRUD**: Create, edit, delete knowledge documents
- **Dimension Classification**: Four dimensions (lifecycle, tech stack, abstraction, purpose)
- **Favorite/Pin**: Mark important documents

### 8.3 Category Management

`CategoryManager` manages four dimensions of classification tags:

| Dimension | Description |
|---|---|
| Lifecycle | Requirements / Design / Development / Testing / Deployment / Operations |
| Tech Stack | Frontend / Backend / Database / Infrastructure |
| Abstraction | Architecture / Component / Module / Function |
| Purpose | Business / Technical / Management / Learning |

### 8.4 TopoScript Animation

![Animation Player](images/screenshot-knowledge-animation.png)

*TopoScript animation player: step-by-step teaching demonstrations*

The built-in **TopoScript** animation engine supports:

- Script-driven animation choreography
- Multi-stage step synchronization
- SVG/Canvas dual renderer
- Export to HTML/Image

---

## 9. Settings & Configuration

### 9.1 Model Configuration

![Model Settings](images/screenshot-settings-models.png)

*Model configuration: add, test, and manage LLM models*

| Feature | Description |
|---|---|
| Add Model | Configure name, provider, API URL, API key |
| Test Connection | Verify the model is reachable |
| Default Model | Set the default for AI assistant |
| Usage Stats | View usage statistics per model |

### 9.2 Agent & Skills (Planned)

> ⚠️ Agent & Skills is currently under development and not available in v0.1.0 beta.

- **Agent Management**: Add/remove/detect agent status
- **Skill Management**: Enable/disable analysis skills

### 9.3 Theme System

![Theme Manager](images/screenshot-settings-themes.png)

*Theme manager: preset themes list, custom theme editor*

Built on the Catppuccin Mocha color system:

- **Preset Themes**: Built-in dark/light themes
- **Custom Themes**: Free color customization via `ThemeEditor`
- **Import/Export**: Share custom themes

### 9.4 General Settings

![General Settings](images/screenshot-settings-general.png)

*General settings: language, font size, auto-save, port configuration*

| Setting | Description |
|---|---|
| Language | 中文 / English |
| Font Size | Applies in real-time |
| Auto Save | Auto-save interval |
| Page Size | Items per page in project list |
| ZMQ Ports | DEALER / PUB port configuration |

---

## 10. FAQ

### Q: Which programming languages are supported?

Currently 11 languages: C, C++, C#, Java, JavaScript, TypeScript, Python, Go, Rust, PHP, Swift. More languages are being added.

### Q: The backend is not running during analysis?

Make sure the Python backend has started. Check the Status Bar for backend connection status (green = connected, red = error).

### Q: How do I configure an AI model?

Go to Settings → Model Configuration → Add Model. We recommend using Ollama or an OpenAI-compatible API.

### Q: How do I export analysis reports?

Reports can be viewed in `SubDocViewer`, or via the browser at `http://localhost:3456`.

### Q: How do I clear analysis cache?

Right-click on a project card → Clear Cache, then select tables to clear (base_node, graph_node, etc.).

### Q: Can I export reports as PDF?

Direct PDF export is not currently supported. You can use the browser's Print to PDF feature from the web viewer.

---

> **Found an issue?** Please report it on [GitHub Issues](https://github.com/topocode/topoone-ui/issues).
