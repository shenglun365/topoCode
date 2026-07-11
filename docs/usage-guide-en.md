# TopoCode Usage Guide

> Developer Email: **topocode@163.com**

This guide covers the complete workflow from project import to AI-assisted architecture analysis.

---

> **Privacy Notice**: Except for user-configured cloud LLM APIs, all features of TopoCode — code parsing, graph computing, architecture analysis, web document service, etc. — run **locally**. Your project source code and analysis data are never uploaded to any external server, ensuring your data privacy and security.

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Project Import](#2-project-import)
3. [Creating Analysis Tasks](#3-creating-analysis-tasks)
4. [Code Parsing (AST)](#4-code-parsing-ast)
5. [Architecture Analysis & Visualization](#5-architecture-analysis--visualization)
6. [AI-Assisted Analysis](#6-ai-assisted-analysis)
7. [Document Viewer](#7-document-viewer)
8. [AI Chat](#8-ai-chat)
9. [Knowledge-Based Analysis Chat](#9-knowledge-based-analysis-chat)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Prerequisites

### 1.1 Verify Backend Status

After launching the app, check the status bar at the bottom:

- 🟢 **Connected** — Python backend is running
- 🔴 **Disconnected** — Check Python environment, install dependencies per README
- ⏳ **Connecting** — Backend is starting (typically 3-10 seconds)

If the status stays red for a long time, check:

1. Python 3.10+ is installed correctly
2. Dependencies are installed (`pip install -r requirements.txt`)
3. Ports 5671/5680/3456 are not occupied

### 1.2 Configure LLM Model

Go to **Settings → Model Config** to add a model (see README's LLM Configuration section). Local models are recommended for architecture analysis to ensure response speed.

### 1.3 Verify Web Service

Open `http://localhost:3456` in a browser to confirm the Web document service is responding.

---

## 2. Project Import

> Screenshot: `docs/images/usage/en/project-import.png`

### Steps

1. Go to **Home** (first icon in the left navigation bar)
2. Click **Import Project**
3. Select the **local source directory** of your project
4. The system will scan the directory structure and begin importing

### Import Process

- Scan file types and count lines of code
- Build file tree index
- Identify primary language

Import progress is shown in a global overlay. Large projects (tens of thousands of files) may take 1-5 minutes.

### Success Indicator

After import, a project card appears on the home page showing the project name, file count, and primary language.

### Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| Import button unresponsive | Insufficient directory permissions | Run the application with admin privileges |
| Import progress stuck | Too many files or symlink loops | Check project directory, exclude node_modules/.git etc. |
| Zero files after import | Empty directory or unsupported source type | Ensure the directory contains supported language files |
| "Path not found" after import | Directory moved or deleted | Click "Update Path" on the project card or re-import |

---

## 3. Creating Analysis Tasks

> Screenshot: `docs/images/usage/en/create-task.png`

After importing a project, click the project node in the left file tree, then:

1. Click the **Analysis** tab
2. Click **Create Task**
3. Fill in task details:
   - **Task Name** — give the analysis a name
   - **Analysis Type** — select scope (full parse / incremental, etc.)
   - **Scope** — specify subdirectory (defaults to entire project)
   - **File Filter** — limit file extensions and exclude directories
4. Click **OK** to create the task

### Task Status Reference

| Status | Meaning |
|---|---|
| `pending` | Waiting to run |
| `running` | Analysis in progress |
| `done` | Analysis complete |
| `error` | Analysis failed |
| `cancelled` | Cancelled |

---

## 4. Code Parsing (AST)

> Screenshot: `docs/images/usage/en/task-running.png`

After creating a task, find it in the task list and click **Run**:

### Parse Flow

1. **File Scan** — traverse the project file tree, identify all source files
2. **AST Parsing** — use Tree-sitter to parse each file, extracting:
   - Symbol definitions (functions, classes, interfaces, variables, etc.)
   - Reference relationships (calls, inheritance, implementation, imports, etc.)
   - Inter-file dependencies
3. **Graph Construction** — build symbol and dependency graphs
4. **Community Detection** — use Louvain/Leiden algorithms to cluster related nodes into "communities" (logical modules)

### Time Estimates (AST Parsing)

The following are reference values for **single-concurrency, full parse**. Actual time varies with CPU, disk I/O, and language (C/C++ is slower):

| Project Size | Files | AST Parsing | Graph + Community | Total |
|---|---|---|---|---|
| Small | < 500 | 1 - 5 min | 30s - 2 min | 2 - 7 min |
| Medium | 500 - 5,000 | 10 - 30 min | 2 - 10 min | 15 - 40 min |
| Large | 5,000 - 50,000 | 1 - 3 hours | 10 - 30 min | 1.5 - 4 hours |
| Extra Large | > 50,000 | 3 - 8 hours | 30 - 60 min | 4 - 9 hours |

> **Note**: The initial parse is the slowest as it builds the complete index database. Subsequent incremental syncs are much faster. C/C++ projects are slower due to macro/template expansion; Python/JS projects are typically faster.

### Truncated Execution

For large projects, you can limit the analysis scope to specific subdirectories:

1. When creating a task, specify a subdirectory under **Scope** (e.g., `src/core/`)
2. The system will only parse files in that directory and its dependencies
3. Results reflect only that sub-module's architecture

**Automatic skip on re-run**: If a task is interrupted (or you manually stop it), **re-running the same task will automatically skip already-completed files** and continue processing unfinished ones. No extra configuration or `--force` needed.

### Monitoring

While the task is running, you can monitor progress:

- **Task list** shows current progress percentage
- **Run logs** show which file is being processed
- **Right panel** shows running status

### Completion

The task status changes to `done`, and the file statistics panel shows a summary (symbol count, edge count, community count, etc.).

### Re-run Mechanism

> **AST parsing tasks cannot be re-run directly after completion.** This is to maintain analysis data consistency. Since subsequent AI analysis and document generation depend on AST results, allowing partial overrides could cause data inconsistency.

To re-parse, follow these steps:

1. **Delete the existing task** — find the completed task in the task list and delete it
2. **Create a new task** — follow the steps in [Section 3](#3-creating-analysis-tasks) to create and run a new task

If you've only modified project code (added/removed files), you can also use the **Sync** function to update the file index before creating a new task.

### Clearing Cache

Analysis cache data (file summaries, community results, etc.) is stored in the local database. To clear:

1. **Single project cache** — in task details, select **Clear Cache**; you can choose specific tables (file summaries, community results, etc.)
2. **All cache** — clear all project analysis caches in Settings

### Force Override

Certain LLM analysis steps support the `--force` parameter to ignore cached results and regenerate:

```bash
# In AI Chat, re-run the full pipeline with --force
/pipeline --force

# Force regenerate architecture overview
/overview --force

# Force re-analyze components (ignore existing results)
/analyze_components --force
```

### Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| Task stuck on `pending` | Backend busy or queue blocked | Restart the app and retry |
| Task hangs during execution | File parse timeout or out of memory | Reduce scope, exclude large directories |
| Zero symbols in results | Language not supported by Tree-sitter | Check supported languages (18+ major languages) |
| Very few or zero edges | Non-standard import syntax | Not critical; LLM analysis can still proceed |

---

## 5. Architecture Analysis & Visualization

> Screenshot: `docs/images/usage/en/community-graph.png`

After the analysis task completes, click the task in the list to enter the analysis view:

### 5.1 Community Structure Graph

- The center shows the project's **community structure graph** (include/call relationships)
- Each node represents a "community" (functional module)
- Node size indicates module scale, color indicates hierarchy level
- Interactive controls:
  - **Drag** — move nodes
  - **Scroll** — zoom in/out
  - **Click** — view community details
  - **Right-click** — context menu (drill down, view document, save to notes)

### 5.2 Switching Views

- **Include Graph (INCLUDE)** — shows module dependency/include relationships
- **Call Graph (CALL)** — shows function-level call relationships
- **Heatmap** — displays module distribution by file
- **File Mode** — switches from component to file perspective

### 5.3 Drill Down

Click a community node or right-click and select "Drill Down" to view sub-structures within that module.

### Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| Graph fails to render | Too many nodes/edges | Reduce scope or lower granularity |
| Abnormal community count | Clustering parameters unsuitable | Adjust parameters (requires code changes) |
| View doesn't match code | Analysis incomplete | Re-run the task with correct analysis type |

---

## 6. AI-Assisted Analysis

> Screenshot: `docs/images/usage/en/architecture-overview.png`

### 6.1 Generate Architecture Overview

In the report view, click **Generate Architecture Overview**. The system will:

1. Collect community analysis results and file summaries
2. Call the LLM for comprehensive analysis
3. Generate a Markdown architecture document

### 6.2 Component Analysis

Select a specific community in the community graph to:

- **View Component Details** — see key files, symbols, and dependencies
- **AI Analyze Component** — have the LLM analyze the component's function, role, and dependencies
- **Name Component** — assign meaningful names (instead of default community IDs)

### 6.3 LLM Analysis Time Estimates

> Reference values for **single-concurrency, single-request**. LLM inference speed varies greatly by model and hardware.

#### Pre-summary (per 100 files)

| Model Type | Per 100 files |
|---|---|
| Local (Qwen3.6-9B, ~10-20 tok/s) | 30 - 60 min |
| Cloud (DeepSeek V4 Flash, etc.) | 5 - 15 min |

#### Component Analysis (per community)

Each community goes through: read subgraph → batch file summaries → synthesize → output JSON.

| Model Type | Per community |
|---|---|
| Local (Qwen3.6-9B, etc.) | 3 - 8 min |
| Cloud (DeepSeek V4 Flash, etc.) | 30s - 2 min |

> **Current limitation**: Component analysis involves multi-turn tool calls (reading files, searching symbols, summarizing). It currently runs as **single-request serial processing** without internal concurrency. Running multiple concurrent requests would overload local models with limited benefit — not recommended.

Example: 30 communities with a local model at single concurrency takes **90 - 240 min** total.

#### Architecture Overview (single LLM call)

| Model Type | Time |
|---|---|
| Local | 3 - 10 min |
| Cloud | 30s - 2 min |

#### Full Pipeline Total

| Project Size | Communities | Local (1 concurrency) | Cloud (1 concurrency) |
|---|---|---|---|
| Small | 5 - 10 | 30 - 90 min | 5 - 20 min |
| Medium | 10 - 30 | 2 - 6 hours | 20 - 60 min |
| Large | 30 - 100 | 6 - 20 hours | 1 - 4 hours |

> **Concurrency note**: Component analysis currently runs as single-request serial processing; the `-j` parameter is not applicable. Local models should run at default single concurrency. For large community sets, let it run overnight.

### Alternative: Use Pre-analyzed Projects

If local analysis takes too long, or your local model capabilities are insufficient:

1. Sign up at **[topocode.cn](https://topocode.cn)**
2. Browse or search for pre-analyzed open-source projects
3. **Link local code**: manually associate the pre-analyzed results with your local source directory to view architecture docs and graphs in the app
4. **Browse docs only**: you can also view the architecture analysis documents directly on the platform without linking any code

Pre-analyzed projects are processed by cloud-based high-performance models, delivering higher quality results with zero waiting time.

### 6.4 Component Re-analysis & Model Switching

If you're not satisfied with a component's analysis result or find errors, **there is no need to re-run the entire task**. You can **single-select and re-run a single component**:

#### Workflow

1. **Locate the target component** (node) in the community structure graph
2. **Right-click** the component node to open the context menu
3. Select **AI Analyze Component** or **Re-analyze**
4. The system will **re-run the LLM analysis for that single component only**, leaving other components' results untouched

#### Switching Models Before Re-analysis

Before re-running, you can switch to a more powerful model:

1. Go to **Settings → Model Config**
2. Add or switch to a more capable model (e.g., from Qwen3.6-9B to DeepSeek V4 Flash)
3. Ensure the new model is set as the **default model**
4. Return to the analysis view and **single-select re-run** the target component

The new model takes effect immediately; the re-run result will be generated with the new model.

#### Use Cases

| Scenario | Action |
|---|---|
| Component name is inaccurate | Single-select → re-run, or manually edit the name |
| Component summary is too brief | Single-select → re-run (or use `/analyze_components --force` in Chat) |
| Some results correct, others wrong | **Single-select re-run** only the incorrect ones; correct results stay untouched |
| Want better quality with a stronger model | Set new model → single-select component → re-run |
| All results unsatisfactory | Use `/analyze_components --force` to force full re-run |

### 6.5 Truncated Execution & Skip-Completed

#### Truncated Execution (Partial Analysis)

For large projects, you can analyze only specific communities:

- **Select a target community node** in the community structure graph
- Right-click and choose **Analyze This Component** — only that community and its direct sub-communities will be analyzed
- Or use the `/analyze_components` command in Chat with specific component IDs

#### Skip-Completed on Re-run

LLM analysis supports **resume-from-interruption**:

- **Without `--force`**: re-running checks existing results and **automatically skips completed components**, only processing unfinished ones
- **With `--force`**: ignores all cached results and regenerates everything
- This is useful when: analysis was interrupted mid-way, adding a few new files, or just completing partial results

```bash
# Only process unfinished components (skip completed)
/pipeline

# Force full re-run (ignore all cache)
/pipeline --force
```

### 6.6 Pre-Summary

For large projects, run pre-summary first:

1. Click **Pre-Summary** in the task details
2. The system ranks files by importance and summarizes core files first
3. Results are cached for subsequent LLM analysis

### Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| LLM call timeout | Slow model response or network issues | Check model config, try a local model or lower max_tokens |
| Empty analysis results | Insufficient community data | Ensure analysis is complete and community detection finished |
| Token limit exceeded | Project too large | Reduce scope or use a larger-context model |
| Inaccurate component naming | LLM context deviation | Manually edit names or provide a more detailed project summary |

---

## 7. Document Viewer

> Screenshot: `docs/images/usage/en/subdoc-viewer.png`

The Web document service provides a full document browsing experience at `http://localhost:3456`:

### 7.1 Document Home

- `/` — shows all projects and their analysis tasks
- Completed tasks show a green dot; click to view the document
- Supports search and pagination

### 7.2 Document Viewer (`/doc`)

- Left panel: document content (Markdown rendered)
- Right panel: community structure graph
- Mermaid / PlantUML diagram rendering support
- Toolbar:
  - **Follow Mode** — linked nodes move together when dragging
  - **Component/File Mode** toggle
  - **Graph/Heatmap** toggle
  - **Filter** — search and filter nodes
  - **Reset** — restore default layout

### 7.3 Notes Feature

- Select text in the document and **save to notes**
- Notes can be edited, referenced, and sent to AI for analysis
- Filter by project and sort by order/time

### Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| Web page won't load | HTTP port not started | Check HTTP port settings, ensure port is not occupied |
| Empty document content | Summary not generated yet | Run AI overview generation or pre-summary first |
| Abnormal diagram rendering | Mermaid/PUML syntax issues | Check the diagram code in community analysis results |
| "Backend not ready" displayed | Backend not ready yet | Wait for backend startup then refresh the page |

---

## 8. AI Chat

> Screenshot: `docs/images/usage/en/ai-chat.png`

AI Chat is served through the Web service at `http://localhost:3456/chat` — no Electron needed, works in any browser.

### 8.1 Start a Conversation

1. Visit `http://localhost:3456/chat`
2. Click **+ New Session** in the left sidebar
3. Type your question in the input box at the bottom

### 8.2 Chat Capabilities

- **Architecture Q&A** — ask about project structure, module responsibilities, code organization
- **Symbol Lookup** — search for specific function, class, and interface definitions and call relationships
- **Code Explanation** — explain code logic and design patterns
- **Architecture Advice** — suggest architecture improvements based on analysis results

### 8.3 Tool Calling

The AI assistant can invoke tools to gather project information:

- `search_symbols` — search for symbol definitions
- `read_file` — read file contents
- `summarize_file` — batch-summarize files
- `get_community_subgraph` — get community subgraph
- `get_call_chain` — get call chains

The AI autonomously decides when to call tools; no manual intervention needed.

### 8.4 Chat Commands & Parameters

AI Chat supports the following slash commands for triggering backend analysis workflows:

| Command | Description | Parameters |
|---|---|---|
| `/overview` | Generate project architecture overview document | `--force` ignore cache and regenerate |
| `/analyze_components` | Run per-component LLM analysis on the project's communities | `--force` overwrite existing results; `-L zh/en` output language |
| `/presummary` | Run file pre-summary for core files | `--force` regenerate |
| `/pipeline` | Run the full analysis pipeline (pre-summary → component analysis → overview) | `--force` regenerate; `-L zh/en` output language |

Examples:

```bash
# Full pipeline, English output, force override
/pipeline -L en --force

# Regenerate architecture overview only
/overview --force

# Re-analyze all components (force overwrite)
/analyze_components --force
```

> **Note**: Component analysis involves multi-turn tool calls and runs as **single-request serial processing**; the `-j` concurrency parameter is not applicable.

### 8.5 Notes Integration

Text selected in the document viewer is automatically saved to notes. In the Chat interface you can:

- View and manage note drafts
- Send note content to AI for analysis
- Reference document content as conversation context

### Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| No response from chat | LLM not configured or network error | Check model configuration |
| Irrelevant AI replies | Insufficient context or wrong model | Provide more background context or switch to a stronger model |
| Tool call failure | Incomplete project index | Ensure analysis is complete, try re-running |
| Lost chat history | Browser storage cleared | Session data is stored in localStorage |

---

## 9. Knowledge-Based Analysis Chat

> Screenshot: `docs/images/usage/en/knowledge-chat.png`

The Knowledge Base feature is used for persistent storage and management of architecture analysis documents.

### 9.1 Knowledge Base Entry

- Click the **Knowledge Base** icon in the left navigation bar
- Use the notes feature in `http://localhost:3456/chat`

### 9.2 Document Management

- **View** — browse saved architecture analysis documents
- **Categorize** — classify by lifecycle, tech stack, abstraction level, and purpose
- **Search** — search document content by keyword
- **Edit** — modify document content and tags

### 9.3 Knowledge-Based Chat

In the AI Chat, you can reference knowledge base content as conversation context:

1. In the document viewer: **select text → save to notes**
2. Switch to Chat — notes sync automatically
3. Reference note content in the input box (use `#number` format)
4. The AI analyzes based on the referenced materials

### 9.4 Conversation Persistence & Cross-Session Reference

- AI Chat conversations are **automatically persisted** locally — they survive page refreshes and browser restarts
- Persisted conversations themselves can be used as context: while chatting in **Session A**, you can reference content from **Session B** by specifying its session ID. For example, mention `@session:xxx` in the Chat input to link a specific session's content for analysis
- Conversations are not yet incorporated into the knowledge base — **not because archiving is missing**, but because conversation content needs to be normalized and structured first; importing raw conversations would compromise knowledge base quality
- **Future versions** will extract structured insights from conversations and merge them into the knowledge base, enabling one-click archival of important conclusions

### Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| Notes not syncing | Page cache issue | Refresh the Chat page |
| Reference not working | Wrong note format | Use `#number` format (e.g. `#1`) |
| Archive failed | Insufficient storage | Clean old archives or increase storage quota |

---

## 10. Troubleshooting

### 10.1 Backend Issues

```bash
# View backend logs
# Electron app log directory:
# Linux: ~/.topocode/logs/
# macOS: ~/Library/Application Support/TopoOne/logs/
# Windows: %APPDATA%/TopoOne/logs/

# Manually start backend for testing
cd backend-core
python main.py --http-port 3456
```

### 10.2 Port Conflicts

If ports 5671/5680/3456 are occupied:

1. Change the HTTP port in **Settings → General Settings**
2. Or specify via environment variables:
   ```bash
   export ZMQ_DEALER_PORT=5672
   export ZMQ_PUB_PORT=5681
   ```

### 10.3 Out of Memory

Large project analysis may consume significant memory:

- Allocate at least 4GB of memory to the application
- Set memory limit in startup args: `--memory-limit 4096`
- Reduce analysis task concurrency

### 10.4 Contact Support

If you encounter issues that cannot be resolved, contact us:

- Developer Email: **topocode@163.com**
- GitHub Issues: [https://github.com/topocode/topoone-ui/issues](https://github.com/topocode/topoone-ui/issues)

Please attach log files and a description of the issue. We will respond as soon as possible.

---

> Maintained by the TopoCode Team. Updated 2026-07
