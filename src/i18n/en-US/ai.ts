export default {
  aiAssistant: {
    title: 'AI Assistant',
    emptyHint: 'How can I help you with your code today?',
    placeholder: 'Ask a question... (Shift+Enter for new line)',
    you: 'You',
    ai: 'AI',
    commands: {
      help: '/help',
    },
    context: {
      codeAnalysis: 'Code Analysis',
      architectureAnalysis: 'Architecture Analysis',
      freeChat: 'Free Chat',
      project: 'Project "{name}"',
      task: 'Task "{name}"',
      currentContext: 'Current context: {parts}',
    },
    pipeline: {
      completed: 'Pipeline execution completed',
      firstSuccess: 'First success: {completed} steps',
      retrySuccess: 'Success after retry: ({retries} retries total)',
      executionFailed: 'Execution failed: (content not written)',
      retryCount: '(retried {count} times)',
      retryHint: 'Use /retry to re-execute (skips successful tasks by default, --force to overwrite).',
      forceOverwriteAll: '(force overwrite all)',
      skipCompleted: '(skip completed)',
      started: 'Pipeline started{hint}. Order: project summary → pre-summary P0→P1→P2 → component analysis L0→L5 → overall architecture analysis. Check the Task panel for progress.',
    },
    errors: {
      noActiveTask: 'No active task found.',
      noCommunityList: 'Community list not loaded yet. Please open the structure graph on the left first.',
      noMatchingCommunity: 'No matching community found.',
      noComponents: 'No components found. Please open the structure graph on the left first.',
      startFailed: 'Start failed: {msg}',
    },
    select: {
      modeActive: 'Activated',
      modeExited: 'Exited',
      modeStatus: 'Component selection mode {status}. Select components in the structure graph or tag view, then enter an analysis request.',
      cleared: 'Cleared all component selections.',
      componentsSelected: '{count} components selected. Enter /analyze to start batch analysis...',
      etcMore: ' and {count} more',
      count: '{count}',
      typeCommunity: 'Community',
      typeExternal: 'External Package',
      removeRef: 'Remove Reference',
      exitMode: 'Exit Component Selection Mode',
      selectComponent: 'Select Component',
    },
    analyze: {
      forceOverwrite: ', force overwrite',
      skipAnalyzed: '(skip analyzed)',
      submitted: 'Submitted {count} components for Agent multi-round analysis{hint}: {names}. Check the Task panel for progress.',
    },
    presummary: {
      started: 'Pre-summary P0→P1→P2 started{hint}. Check the Task panel for progress.',
    },
    overview: {
      started: 'Architecture overview generation task started, please check back later...',
      pendingAnalysis: 'Component analysis is not yet complete. Please run /analyze or /pipeline first.',
    },
    retry: {
      forceOverwriteAll: '(force overwrite all)',
      skipSuccessful: '(skip successful steps)',
      started: 'Re-execution started{hint}. Check the Task panel for progress.',
    },
    messages: {
      showEarlier: 'Show earlier messages ({count})',
    },
    helpEntry: {
      hint: 'Type /help to see all available commands and modes',
    },
    langHint: {
      zh: '(中文)',
      en: '(English)',
    },
    common: {
      concurrency: '(concurrency {n})',
    },
  },
  ai: {
    assistantTitle: 'AI Assistant',
    chatTab: 'Chat',
    assistantWelcome: 'Hello! I am the TopoCode AI assistant. I can help you with software usage questions. Type /help to see available commands.',
    assistantNotConfigured: 'LLM API is not configured. Please configure it in settings.',
    goConfigure: 'Go to Settings',
    inputPlaceholder: 'Type a question... (Shift+Enter for new line)',
    typing: 'AI is typing...',
    clearChat: 'Clear chat',
  },

  // ====== System Prompt: Role Definition ======
  systemPromptRole: `You are the TopoCode Desktop usage assistant, developed by the TopoCode team.
You only answer questions related to TopoCode software features and usage.
Reply in English. Keep responses concise.`,

  // ====== System Prompt: Scope Rules ======
  systemPromptScope: `## ✅ Allowed topics
- TopoCode software feature explanations (project management, analysis tasks, architecture analysis, code parsing, etc.)
- Step-by-step operation guides (how to create a project, configure tasks, clear cache, etc.)
- Command usage explanations (/select, /analyze, /pipeline, /overview, /presummary, /retry, /help, etc.)
- Settings and configuration (LLM model add/delete, backend host/port/memory, language switching, etc.)
- UI navigation guidance (panels, page switching, button functions, etc.)
- Common troubleshooting (task failure reasons, cache clearing, import/export issues, etc.)

## ❌ Prohibited topics
- Analysis of the user's project code architecture, design patterns, or implementation details (guide them to use the Web AI Assistant: http://localhost:3456/chat)
- General programming questions, algorithm implementation, technology selection advice
- Usage of third-party tools not related to TopoCode
- Politics, personal opinions, sensitive topics

For out-of-scope questions, reply directly: "Sorry, this is beyond my scope. I am the TopoCode usage assistant and only answer questions related to software usage."`,

  // ====== Built-in Knowledge: Project Management ======
  docProject: `## Project Management
### Creating a Project
- Click "New Project" or drag a directory to the import area
- Select the source code directory to analyze; the system will automatically scan the file structure

### Import / Export
- Import: Click the "Import" button in the toolbar, select a previously exported .zip archive
- Export: Click the "Export" button in the toolbar, select the tasks to export, and download the .zip file

### Project Operations
- Sync: Refresh the project file tree and detect file changes
- Delete: Remove a project and its analysis data (can be confirmed in settings)
- Edit: Modify project name or path
- Group: Assign projects to different groups for management
- Favorite / Pin: Mark frequently used projects for quick access`,

  // ====== Built-in Knowledge: Analysis Tasks ======
  docAnalysisTask: `## Analysis Tasks
### Creating a Task
- Click the "New Task" button in the toolbar to open the configuration form
- Select language type: Python, JavaScript/TypeScript, Java, Go, C/C++, Rust, etc.
- Select scan directory scope (optional subdirectory)
- Select report type:
  - Dependency analysis: Analyzes dependency relationships between files/modules
  - Call chain analysis: Analyzes function call relationships
  - Multiple types can be selected simultaneously
- Click confirm; the task will enter the queue and execute automatically

### Task Operations
- Run / Stop: Control task execution status
- Re-run: Re-execute completed or failed tasks
- View results: Click "Architecture Analysis" on the task row to jump to the analysis page
- View logs: View detailed logs during task execution
- Edit configuration: Modify task parameter settings
- Favorite / Pin: Mark important tasks

### Task Status
- pending: Waiting in queue
- running: Currently executing
- completed: Execution finished
- failed: Execution failed
- cancelled: Cancelled`,

  // ====== Built-in Knowledge: Architecture Analysis ======
  docArchAnalysis: `## Architecture Analysis
The architecture analysis page displays the module structure analysis results.

### Community Graph
- Displays module relationships as a force-directed graph
- Each node represents a community (functional module), edges represent dependency/call relationships
- Supports zoom, drag, and click to view details

### Commands (enter in the AI assistant input box)
- /select: Component selection mode. No args for manual selection; supports --all (select all), --include/--call (filter by edge type), --l0~--l5 (filter by level), --clear (clear), --unanalyzed (unanalyzed only)
- /analyze [-j N] [--force] [-L zh/en]: Batch component analysis. --force to overwrite, -j concurrency 1-5, -L language
- /presummary [-j N] [--force]: File pre-summary P0→P1→P2
- /overview [--force] [-L zh/en]: Generate overall architecture overview
- /pipeline [-j N] [--force] [-L zh/en]: One-click pipeline: project summary → pre-summary → component analysis → architecture overview
- /retry [--force]: Re-run the pipeline`,

  // ====== Built-in Knowledge: Code Parsing ======
  docCodeAnalysis: `## Code Parsing
### Browsing Files
- The left file tree shows the project's directory and file structure; directories expand lazily
- Click a file name to view source code on the right with syntax highlighting
- The file tree search box at the top allows quick filtering by file name

### Task Management
- View each task's status, progress, and results in the task list
- Re-run completed or failed tasks, stop running tasks
- Click "Architecture Analysis" on a task row to jump to the detailed report page`,

  // ====== Built-in Knowledge: Cache Management ======
  docCache: `## Cache Management
### Clearing Cache
In the toolbar ⚙️ menu → "Clear Cache", you can selectively clear by category:
- Call chain analysis cache
- AI Q&A cache
- Symbol index cache
- Community analysis cache
- File summary cache
- Overview document cache

After clearing, the relevant data will be regenerated.`,

  // ====== Built-in Knowledge: Settings ======
  docSettings: `## Settings
### LLM Model Configuration
- Supports adding multiple model providers: Ollama (local), OpenAI-compatible API, vLLM, etc.
- Fill in the API URL, model name, API Key, etc.
- Set a default model and test the connection

### Backend Configuration
- HTTP Host: Backend service listening address (default: 127.0.0.1)
- HTTP Port: Backend service port (default: 3456)
- Memory Limit: Maximum memory usage for the Python backend process (in MB)

### Other Settings
- Language: Supports 简体中文, English
- Font Size: Adjust the editor font size
- Auto-save Interval: Set auto-save interval (seconds)`,

  // ====== Built-in Knowledge: Group Management ======
  docGroups: `## Group Management
- Create a group: Name it and select a parent group (supports tree hierarchy)
- Edit a group: Modify the group name
- Delete a group: Remove the group (does not delete projects within it)
- Assign projects to groups for easier management by category
- Filter projects by group at the top of the project list`,

  // ====== Built-in Knowledge: Troubleshooting ======
  docTroubleshooting: `## Troubleshooting
### Task Execution Failed
- Check if the source directory contains analyzable files
- Confirm the correct language type is selected
- Check task logs for detailed error information
- Try re-executing the task

### Backend Failed to Start
- Check if the port (default 3456) is already in use
- Verify the Python environment is correctly installed
- Adjust the memory limit in settings

### LLM Connection Failed
- Confirm the model service is running
- Check the API URL and port
- Click "Test Connection" to verify the configuration

### Analysis Results Not Updating
- Click "Sync" to refresh file changes
- Re-execute the analysis task
- Clear cache and re-analyze if necessary`,

  helpHint: 'Type /help to see all available commands and modes.',

  // ====== ChatView (Report Page Architecture Analysis Agent) ======
  chatSystemPrompt: `You are the TopoCode Architecture Analysis Agent, developed by the TopoCode team.
You focus on helping users analyze project architecture, understand code structure, and discover dependency and call chain relationships.

## Scope
- Analyze project module partitioning and architecture layers
- Explain dependency and call relationships between components
- Generate architecture overviews and documentation
- Check code architecture quality issues (circular dependencies, hub overload, etc.)

## Prohibited
- TopoCode software usage questions (please use the right sidebar AI assistant)
- General programming questions, algorithm implementation

Keep responses concise and professional, using diagrams (Mermaid/PlantUML) for illustration.`,

  chatWelcome: 'Hello! I am the TopoCode Architecture Analysis Agent. I can help you analyze project architecture, generate documentation, and check code quality.',

  // ====== Command Reference ======
  helpCommands: `## Available Commands
| Command | Description |
|---------|-------------|
| /help | Show this help |
| /select [--all/--include/--call/--l0~/--l5/--clear/--unanalyzed] | Component selection mode. No args to toggle; --all select all; --include/--call filter by edge type; --l0~--l5 filter by level; --clear clear; --unanalyzed unanalyzed only |
| /presummary [-j N] [--force] | File pre-summary P0→P1→P2. --force overwrite, -j N concurrency 1-5 |
| /analyze [-j N] [--force] [-L zh/en] | Batch component analysis. --force overwrite, -j concurrency, -L language |
| /overview [--force] [-L zh/en] | Generate overall architecture overview |
| /pipeline [-j N] [--force] [-L zh/en] | One-click pipeline: project summary → pre-summary → component analysis → architecture overview |
| /retry [--force] | Re-run pipeline |

## Interaction Modes
- **Free Chat**: Ask TopoCode usage-related questions
- **Component Selection Mode**: /select to toggle, then /analyze to analyze
- **Pipeline Mode**: /pipeline for one-click full workflow`,

  // ====== Code Parsing Help (for code parsing page) ======
  helpCode: `## Code Parsing Guide

### 1. Browsing Project Files
- The left **file tree** shows the project's directory and file structure; directories expand lazily
- Click a file name to view source code on the right with syntax highlighting
- The file tree search box at the top allows quick filtering by file name

### 2. Creating Analysis Tasks
- Click the **"New Task"** button in the toolbar to open the configuration form
- Select the **language type** (Python, JavaScript, etc.) and **directory scope** to scan
- Select the **report type**: Dependency analysis or Call chain analysis
- Click confirm; the task will enter the queue and execute automatically

### 3. Managing Tasks
- View each task's status, progress, and results in the task list
- **Re-run** completed or failed tasks, **stop** running tasks
- Click **"Architecture Analysis"** on a task row to jump to the detailed report page

### 4. Data Management
- **Import** analysis results: Click the "Import" button, select a previously exported .zip archive
- **Export** analysis results: Click the "Export" button, select tasks, and download
- **Verify files**: Click the "Verify" button to check file hash consistency with analysis data
- **Clear cache**: Toolbar ⚙️ menu → Clear cache, selectively clear by category`,
}
