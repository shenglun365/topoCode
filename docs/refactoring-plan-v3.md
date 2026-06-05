# TopoCode-UI 下一步重构方案

> 基于 `docs/code-analysis-report-v2.md` 现存问题 + Tree-sitter Query / Stack Graphs / MCP 架构升级建议
> 日期: 2026-06-05

---

## 总览

本次重构分为**四个维度、七个阶段**:

| 维度 | 目标 | 来源 |
|------|------|------|
| **前端代码质量** | 消除 P0/P1 债务，提升架构评分 B→A | v2 报告 |
| **后端分析管线** | Tree-sitter Query + Symbol 模型 + Stack Graphs | 用户建议 |
| **变更感知能力** | 版本跟踪 + 变更检测 + 变更可视化 + 影响评估 | 用户建议 |
| **MCP 生态接入** | MCP Server + Tool/Skill + Tool Calling | 用户建议 |

---

## 第一阶段: 前端 P0 修复 + 后端基础设施清理 (2-3天)

### 1.1 前端 P0 立即修复

| # | 任务 | 文件 | 工时 | 验收 |
|---|------|------|------|------|
| P0-3 | 修复 PlantUML IPC 路径 `api.backend.renderPlantuml` → `api.render.renderPlantuml` | `composables/usePlantUmlRender.ts:33` | 0.5h | Electron 中 PlantUML 可正常渲染 |
| P0-2 | 统一类型: 以 `ipc.ts` 为准, `index.ts` 用 `Pick/Omit` 派生, 修正 `KnowledgeDoc.dimensions↔tags` 不一致 | `types/index.ts`, `types/ipc.ts` | 1.5h | 两个文件无同名不同类型冲突 |
| P0-4 | 删除 `analysis-service.ts` / `backend-service.ts` 中从未消费的回调数组死代码 | `services/ipc/analysis-service.ts:193-219`, `services/ipc/backend-service.ts:40-46` | 0.5h | 代码量减少, 无功能变化 |
| P1-1 | 移除 `project.ts` 中死导入 `useSettingsStore` + tab 透传方法标记 `@deprecated` | `stores/project.ts:14` | 0.5h | lint 无未使用变量警告 |

### 1.2 后端清理

| # | 任务 | 工时 | 验收 |
|---|------|------|------|
| B1 | 删除 `backend/` 旧目录, 仅保留 `backend-core/` | 0.5h | 项目只有一个后端源码目录 |
| B2 | 删除 `backup/` 或移至独立归档仓库 | 0.5h | `backup/` 不在主项目中 |
| B3 | 删除 `tmp-module-build/` (构建临时目录, 已 gitignore) | 0.1h | 清理残留 |

**第一阶段产出**: 4 个 P0 全部消除, 项目结构干净, 无死代码。

---

## 第二阶段: 后端分析管线升级 — Tree-sitter Query + Symbol 模型 (4-6天)

> **核心思路**: 用声明式 Tree-sitter Query (`.scm`) 替代手写 AST 遍历, 构建统一 Symbol 模型, 在 Symbol 层做引用解析。80% 确定性分析用 Tree-sitter, 20% 歧义部分用 Stack Graphs。

### 2.1 编写 Tree-sitter Query 脚本 (`.scm`)

**现状**: `extract_node_info()` 手写 DFS 遍历 AST, 用 `important_node_types` 字典筛选节点, 逻辑紧耦合在 Python 遍历代码中。

**目标**: 用 Query 模式匹配替代大部分 DFS, Python 侧只做"装载捕获结果→构建 Symbol"。

**实施步骤**:

#### Step 1: 为一种语言 (TypeScript) 编写 prototype

在 `plugins/parsers/parsers/queries/` 下新建:
```
queries/
  typescript/
    definitions.scm    # 捕获: function, class, variable, parameter, interface, type alias
    references.scm     # 捕获: identifier, call_expression, member_expression
    imports.scm        # 捕获: import_statement, require_call
```

**`definitions.scm` 示例**:
```scheme
; 函数声明
(function_declaration
  name: (identifier) @func.name
  parameters: (formal_parameters) @func.params
  body: (statement_block) @func.body) @func.def

; 类声明
(class_declaration
  name: (type_identifier) @class.name
  body: (class_body) @class.body) @class.def

; 变量声明
(variable_declarator
  name: (identifier) @var.name
  value: (_)? @var.value) @var.def

; 方法定义
(method_definition
  name: (property_identifier) @method.name
  parameters: (formal_parameters) @method.params) @method.def
```

**`references.scm` 示例**:
```scheme
; 调用表达式
(call_expression
  function: (identifier) @call.callee
  arguments: (arguments) @call.args) @call.expr

; 成员访问
(member_expression
  object: (_) @member.object
  property: (property_identifier) @member.prop) @member.expr

; 标识符引用 (非定义位置)
(identifier) @ref.name
```

#### Step 2: 实现 QueryLoader 工具类

在 `plugins/parsers/parsers/query_loader.py`:

```python
from dataclasses import dataclass
from pathlib import Path
from tree_sitter import Language, Query

@dataclass
class QuerySet:
    language: str
    definitions: Query
    references: Query
    imports: Query

class QueryLoader:
    """加载 .scm 文件并编译为 Tree-sitter Query 对象"""
    _cache: dict[str, QuerySet] = {}

    @classmethod
    def load(cls, lang_name: str, language: Language) -> QuerySet:
        if lang_name in cls._cache:
            return cls._cache[lang_name]

        base = Path(__file__).parent / "queries" / lang_name
        qs = QuerySet(
            language=lang_name,
            definitions=language.query((base / "definitions.scm").read_text()),
            references=language.query((base / "references.scm").read_text()),
            imports=language.query((base / "imports.scm").read_text()),
        )
        cls._cache[lang_name] = qs
        return qs
```

#### Step 3: 用 AI 辅助批量生成其他语言的 Query

用现有的 Ollama/OpenAI API 调用 (`llm_service.py`), 以 TypeScript Query 为示例, prompt:
```
请根据以下 TypeScript Tree-sitter Query (.scm) 模式,
为 {language} 语言编写等效的 definitions.scm 和 references.scm。
已知 {language} 的 Tree-sitter 节点类型包括: {node_types}

[粘贴 typescript/*.scm 内容]
```

人工审核边界 case 后纳入版本管理。

**工时**: TypeScript prototype 1天, AI 辅助生成 6 语言 → 1天, 审核修正 → 1天。总计 **3天**。

---

### 2.2 构建统一 Symbol 模型

**现状**: 当前在 `extract_node_info()` 中直接将 AST 节点信息写入 SQL `base_node` 表。后续 Step 2-4 各自从 SQL 重新读取、重新构建中间结构, 导致每个 Step 都有大量重复的"扫 SQL → 构建临时结构"代码。

**目标**: 在 `parse_file()` 和后续 Step 之间插入一层 **内存 Symbol 模型**, 所有 Step 共享同一份结构化数据。

#### 数据模型设计

在 `plugins/parsers/parsers/symbol_model.py`:

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class SymbolKind(Enum):
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    VARIABLE = "variable"
    PARAMETER = "parameter"
    INTERFACE = "interface"
    TYPE_ALIAS = "type_alias"
    ENUM = "enum"
    MODULE = "module"
    MACRO = "macro"          # C/C++

class RefKind(Enum):
    CALL = "call"            # foo()
    MEMBER = "member"        # obj.prop
    IMPORT = "import"        # import / require / #include
    TYPE_REF = "type_ref"    # Type annotation reference
    IDENT = "ident"          # Generic identifier

@dataclass
class SourceLocation:
    file_path: str
    start_byte: int
    end_byte: int
    start_line: int
    start_col: int
    end_line: int
    end_col: int

@dataclass
class Symbol:
    """统一符号定义模型"""
    name: str
    kind: SymbolKind
    location: SourceLocation
    scope: str                          # "module", "class.Foo", "class.Foo.method.bar"
    is_definition: bool = True
    doc_comment: Optional[str] = None   # 关联的 JSDoc/docstring

@dataclass
class Reference:
    """统一引用模型"""
    name: str
    kind: RefKind
    location: SourceLocation           # 引用发生位置
    scope: str                         # 引用所在作用域
    target: Optional[str] = None       # 解析后的目标符号全限定名 (if resolved)

@dataclass
class FileSymbolTable:
    """单文件符号表"""
    file_path: str
    language: str
    symbols: list[Symbol] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    imports: list[dict] = field(default_factory=list)   # [{from, import, resolved_file}]
    exports: list[str] = field(default_factory=list)    # 对外暴露的符号名
```

#### 解析流程改造

```
旧流程:
  parse_file() → 手写DFS → 逐节点写入 base_node (SQL)
       ↓
  Step 2 extract_global_symbols() → 重读 base_node → 构建临时结构 → 写 graph_node
       ↓
  Step 3 extract_call_graph()     → 重读 base_node → 构建临时结构 → 写 graph_node

新流程:
  parse_file() → Query 引擎抓取 → Symbol/Reference 列表 (内存)
       ↓
  resolve_scopes() → 文件内引用绑定 (内存)
       ↓
  persist() → 批量写入 base_node + graph_node (SQL)
       ↓
  Step 2/3/4 → 直接读取 graph_node (不再重复构建临时结构)
```

**工时**: Symbol 模型 + 改造 `parse_file()` + 改造 Step 2-4 → **2天**。

---

### 2.3 实现轻量级名称绑定器 (Simplified Binder)

**目标**: 基于统一 Symbol 模型, 在文件内和跨文件做快速引用解析, 覆盖 80% 常见模式。

在 `plugins/parsers/parsers/binder.py`:

```python
@dataclass
class ResolveResult:
    target: Optional[Symbol]
    confidence: float       # 0.0 ~ 1.0
    candidates: list[Symbol] = field(default_factory=list)
    method: str = "local"   # "local", "import", "qualified", "unresolved"

class SimpleBinder:
    """基于作用域栈 + 导出的快速名称绑定器"""

    def __init__(self, file_tables: dict[str, FileSymbolTable]):
        self.file_tables = file_tables
        self._scope_index: dict[str, list[Symbol]] = {}  # scope → symbols
        self._export_index: dict[str, set[str]] = {}     # file → exported names
        self._build_index()

    def resolve(self, ref: Reference) -> ResolveResult:
        """解析引用: 本地作用域 → 导入 → 未解析"""
        # 1. 本地作用域链向上查找
        local = self._resolve_local(ref)
        if local and local.confidence > 0.9:
            return local

        # 2. 如果引用处有同名 import, 查跨文件导出
        imported = self._resolve_via_import(ref)
        if imported and imported.confidence > 0.7:
            return imported

        # 3. 返回低置信度结果, 标记为需要 Stack Graphs
        return ResolveResult(target=None, confidence=0.0,
                             method="unresolved")
```

**工时**: 1天。

---

## 第三阶段: Stack Graphs 集成 (3-4天)

### 3.1 总体策略

Stack Graphs 定位为**外部精确引擎**, 仅在 SimpleBinder 返回低置信度时调用。两者通过统一的 `Symbol` 模型衔接, 用户完全无感。

```
源代码
  │
  ├─→ [Tree-sitter Query] ──→ Symbol/Reference ──→ SimpleBinder ──→ 快速结果 (80%)
  │
  └─→ [Stack Graphs 索引] ──→ SQLite DB ──→ StackGraphsService ──→ 精确结果 (20%)
                              (stack-graphs CLI)
```

### 3.2 实施步骤

#### Step 1: 封装 StackGraphsService

在 `backend-core/stack_graphs_service.py`:

```python
import asyncio
import json

class StackGraphsService:
    """管理 stack-graphs CLI 子进程生命周期"""

    def __init__(self, project_root: str, language: str):
        self.project_root = project_root
        self.language = language
        self._process: asyncio.subprocess.Process | None = None

    async def start(self):
        """启动子进程, 索引项目"""
        self._process = await asyncio.create_subprocess_exec(
            "stack-graphs", "index",
            "--project", self.project_root,
            "--language", self.language,
            cwd=self.project_root,
        )
        await self._process.wait()

    async def definition(self, file: str, line: int, col: int) -> dict | None:
        """查询定义位置"""
        cmd = json.dumps({
            "command": "definition",
            "file": file, "line": line, "column": col
        })
        # 通过 stdin/stdout JSON 协议通信 (已在前序讨论中确定)
        proc = await asyncio.create_subprocess_exec(
            "stack-graphs", "query",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate(cmd.encode())
        return json.loads(stdout) if stdout else None

    async def references(self, file: str, line: int, col: int) -> list[dict]:
        """查询所有引用"""
        ...

    async def shutdown(self):
        if self._process:
            self._process.terminate()
            await self._process.wait()
```

#### Step 2: 实现 HybridResolver

在 `backend-core/hybrid_resolver.py`:

```python
class HybridResolver:
    def __init__(self, binder: SimpleBinder, sg: StackGraphsService):
        self.binder = binder
        self.sg = sg

    async def resolve(self, ref: Reference) -> ResolveResult:
        # 第一步: 快速路径 (确定性分析)
        result = self.binder.resolve(ref)
        if result.confidence >= 0.9:
            return result

        # 第二步: 精确路径 (Stack Graphs)
        try:
            sg_result = await self.sg.definition(
                ref.location.file_path,
                ref.location.start_line,
                ref.location.start_col,
            )
            if sg_result:
                return ResolveResult(
                    target=self._to_symbol(sg_result),
                    confidence=1.0,
                    method="stack-graphs"
                )
        except Exception as e:
            logger.warn(f"Stack Graphs resolve failed: {e}")

        return result  # 回退到低置信度结果
```

#### Step 3: 融合图构建

在 Community Analysis 阶段, 将两种来源的边融合到 NetworkX 图中:
- **确定性边** (confidence ≥ 0.9): 来自 SimpleBinder, 实线
- **精确边**: 来自 Stack Graphs, 实线
- **低置信度边** (confidence < 0.9): 虚线显示, 标记 `unresolved`, 等待用户验证或 AI 增强

#### Step 4: AI 辅助生成 .tsg 规则

对于社区规则不完善的语言, 用 AI 辅助生成 Stack Graphs 规则:
1. 手工编写典型语法结构 (函数定义/调用/方法调用) 的正确规则。
2. 将这些规则 + Tree-sitter 节点类型定义作为 prompt, 让 LLM 生成其他结构的规则草案。
3. 用 `stack-graphs test` 验证, 人工修正后纳入版本管理。

**工时**: StackGraphsService 封装 1天, HybridResolver 1天, 融合图 0.5天, AI 辅助规则 1天。总计 **3.5天**。

---

## 第四阶段: 前端架构债务清理 (5-7天)

### 4.1 Store 拆分 (2天)

| 任务 | 文件 | 工时 |
|------|------|------|
| 拆分 `community-store.ts` (519行) → `community-analysis-store` + `child-analysis-store` | `stores/community-store.ts` | 4h |
| 拆分 `model-store.ts` (137行) → `model-config-store` + `agent-store` + `usage-stats-store` | `stores/model-store.ts` | 2h |
| 迁移 `report-store.ts` 中 analysis IPC 到 `community-store` | `stores/report-store.ts` | 2h |
| 拆分 `project.ts` 导入工作流到 `import-store` | `stores/project.ts` | 3h |
| 迁移 `theme.ts` DOM 操作到 `App.vue` composable | `stores/theme.ts` | 2h |
| 添加 `debug.ts` 副作用延迟初始化 | `stores/debug.ts` | 0.5h |

### 4.2 Composables 提取 (1.5天)

| 任务 | 工时 |
|------|------|
| 创建 `useSearchFilter(items, accessor)` — 消除 7+ 处搜索过滤重复 | 2h |
| 创建 `usePolling(callback, interval)` — 消除 3 处轮询重复 | 1h |
| 提取 `utils/flattenTree.ts` 通用树扁平化函数 | 1h |
| 提取 `utils/community.ts` 社区ID格式化函数 | 0.5h |
| 统一 8 处状态徽章映射改为使用 `statusBadge.ts` | 2h |

### 4.3 大组件拆分 (3天)

| 组件 | 当前 | 目标 | 工时 |
|------|------|------|------|
| `SubDocViewer.vue` | 960行 | 抽出 `useMarkdownRenderer` composable + `DiagramsPanel.vue` + `DocRegenDialog.vue` | 6h |
| `ReportHome.vue` | 981行 | 抽出 `CommunityGrid.vue` + `ReportSummaryCard.vue` | 4h |
| `ModelConfig.vue` | 908行 | 抽出 `UsageStatsPanel.vue` | 3h |
| `ProjectCard.vue` | 859行 | 抽出 `EditProjectDialog.vue` + `GroupSelector.vue` | 4h |
| `shell/RightPanel.vue` | 249行 | 解耦跨层依赖, 改为动态组件注册 | 2h |

### 4.4 类型 + 小修 (1天)

| 任务 | 工时 |
|------|------|
| 填充 16 个空 catch 块 (至少 `console.warn`) | 1h |
| 提取硬编码 URL 到 `constants/providers.ts` | 1h |
| `window-api.ts` 类型补齐 (用 `IPCAPI` 接口逐步替换 `any`) | 3h |
| 修复 `usePixiCanvas.ts` ticker 泄漏 | 0.5h |
| 修复 `useD3Graph` / `useMermaidRender` 重布局 hack | 1h |

---

## 第五阶段: MCP Server 基础设施 + 核心 Tools (4-5天)

> **核心思路**: 将 TopoCode 打造成 MCP (Model Context Protocol) 服务器, 把 Tree-sitter Query / Stack Graphs / 文档生成能力封装为标准 Tool, 供第三方 AI Coding Agent (Continue, Cline, Aider 等) 直接调用。TopoCode 从独立桌面应用升级为 **本地 AI 研发生态的核心语义基础设施**。

### 5.1 整体架构

```
第三方 Coding Agent (Continue / Cline / Aider ...)
        │
        ▼  MCP 协议 (JSON-RPC 2.0 over stdio)
┌──────────────────────────┐
│     MCP Server 模块       │  ← 新增 (Python, 可独立进程)
│  ┌──────────────────────┐│
│  │  Tool Registry       ││  ← tools/list, tools/call
│  │  Skill Composer      ││  ← Skills 编排引擎
│  │  Prompt Templates    ││  ← prompts/list, prompts/get
│  │  Request Cache (LRU) ││  ← 高频查询缓存
│  └──────────┬───────────┘│
│             │ 内部调用     │
└─────────────┼─────────────┘
              │
   ┌──────────▼──────────┐
   │ 方案A: 直接库调用     │  ← 初期推荐 (零延迟)
   │ HybridResolver       │
   │ SymbolGraph          │
   │ DocumentGenerator    │
   └──────────────────────┘

   ┌──────────▼──────────┐
   │ 方案B: ZeroMQ 消息    │  ← 未来演进 (跨进程隔离)
   │ zmq_router.call(...) │
   └──────────────────────┘
```

**MCP Server 定位**:
- 以独立 Python 进程运行, 通过 **stdio** 与 Agent 通信 (JSON-RPC 2.0)
- 内部复用已有分析管线 (HybridResolver, SymbolGraph, CommunityDetector)
- Electron 主进程负责管理 MCP Server 生命周期: 用户打开项目 → 自动启动, 关闭项目 → 自动终止

### 5.2 MCP Server 启动方式

**Agent 侧配置示例** (Continue/Cline 的 `mcp_config.json`):
```json
{
  "mcpServers": {
    "topocode": {
      "command": "python",
      "args": ["-m", "topocode.mcp_server", "--project-root", "${workspaceFolder}"],
      "env": {
        "TOPOCODE_BACKEND_PORT": "5671",
        "TOPOCODE_LOG_LEVEL": "WARN"
      }
    }
  }
}
```

**Electron 侧生命周期管理** (在 `main.ts` 或新增 `mcp-manager.ts`):
```typescript
// 项目打开时自动启动 MCP Server
ipcMain.handle('mcp:start', async (_, projectRoot: string) => {
    const proc = spawn('python', [
        '-m', 'topocode.mcp_server',
        '--project-root', projectRoot,
        '--zmq-port', String(zmqPort),
    ], { stdio: ['pipe', 'pipe', 'pipe'] })
    // 通过 stdio 直接注入到 Agent 或监听端口供外部连接
})
```

### 5.3 核心 Tool 设计 (第一级: 原子能力)

**Tool 必须以严格的 JSON Schema 定义输入输出**, 方便 AI 准确调用。

**`backend-core/mcp_server/tools.py`**:

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class ToolDefinition:
    name: str
    description: str
    inputSchema: dict[str, Any]

# ===== 符号导航类 =====

GET_DEFINITION = ToolDefinition(
    name="get_definition",
    description="Resolve the definition location of a symbol at the given file/position.",
    inputSchema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute or project-relative file path."},
            "line": {"type": "integer"},
            "character": {"type": "integer"}
        },
        "required": ["file_path", "line", "character"]
    }
)

GET_REFERENCES = ToolDefinition(
    name="get_references",
    description="Find all references to a symbol at the given file/position. Results grouped by file.",
    inputSchema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "line": {"type": "integer"},
            "character": {"type": "integer"},
            "max_results": {"type": "integer", "default": 500, "description": "Max references to return"}
        },
        "required": ["file_path", "line", "character"]
    }
)

GET_SYMBOL_INFO = ToolDefinition(
    name="get_symbol_info",
    description="Get detailed information about a symbol: name, kind, signature, docstring, location, modifiers.",
    inputSchema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "line": {"type": "integer"},
            "character": {"type": "integer"}
        },
        "required": ["file_path", "line", "character"]
    }
)

# ===== 项目级架构理解 =====

GET_CALL_HIERARCHY = ToolDefinition(
    name="get_call_hierarchy",
    description="Get the call hierarchy for a function: who calls it (incoming) and what it calls (outgoing).",
    inputSchema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "line": {"type": "integer"},
            "character": {"type": "integer"},
            "direction": {"type": "string", "enum": ["incoming", "outgoing", "both"], "default": "both"},
            "max_depth": {"type": "integer", "default": 3}
        },
        "required": ["file_path", "line", "character"]
    }
)

GET_FILE_SYMBOLS = ToolDefinition(
    name="get_file_symbols",
    description="Get all top-level symbols (functions, classes, variables) defined in a file. Like IDE outline.",
    inputSchema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "kind_filter": {"type": "array", "items": {"type": "string"},
                           "description": "Filter by symbol kind: function, class, variable, interface, enum"}
        },
        "required": ["file_path"]
    }
)

GET_DEPENDENCIES = ToolDefinition(
    name="get_dependencies",
    description="Get module-level dependency information: what this file imports, or what files depend on it.",
    inputSchema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "direction": {"type": "string", "enum": ["imports", "imported_by", "both"], "default": "both"}
        },
        "required": ["file_path"]
    }
)

SEARCH_SYMBOL = ToolDefinition(
    name="search_symbol",
    description="Fuzzy search for symbols across the entire project by name.",
    inputSchema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Symbol name (partial match)"},
            "kind_filter": {"type": "string", "description": "Filter: function, class, variable, interface, all"},
            "max_results": {"type": "integer", "default": 20}
        },
        "required": ["query"]
    }
)

# ===== 所有核心 Tools 注册表 =====

CORE_TOOLS = [
    GET_DEFINITION,
    GET_REFERENCES,
    GET_SYMBOL_INFO,
    GET_CALL_HIERARCHY,
    GET_FILE_SYMBOLS,
    GET_DEPENDENCIES,
    SEARCH_SYMBOL,
]
```

### 5.4 Tool 执行分发器

**`backend-core/mcp_server/dispatcher.py`**:

```python
from typing import Any
from functools import lru_cache

class ToolDispatcher:
    """接收 MCP tools/call 请求, 调度到对应 Handler 执行"""

    def __init__(self, resolver: HybridResolver, graph: SymbolGraph):
        self.resolver = resolver
        self.graph = graph
        self._handlers = {
            "get_definition": self._handle_definition,
            "get_references": self._handle_references,
            "get_symbol_info": self._handle_symbol_info,
            "get_call_hierarchy": self._handle_call_hierarchy,
            "get_file_symbols": self._handle_file_symbols,
            "get_dependencies": self._handle_dependencies,
            "search_symbol": self._handle_search_symbol,
        }

    @lru_cache(maxsize=512)
    def _handle_definition(self, file_path: str, line: int, character: int) -> dict:
        result = self.resolver.resolve(file_path, line, character)
        if result.target:
            sym = result.target
            return {
                "found": True,
                "file_path": sym.location.file_path,
                "line": sym.location.start_line,
                "character": sym.location.start_col,
                "symbol_name": sym.name,
                "symbol_kind": sym.kind.value,
                "scope": sym.scope,
                "docstring": sym.doc_comment,
                "confidence": result.confidence,
                "method": result.method,
            }
        return {"found": False, "candidates": [s.name for s in result.candidates]}

    async def dispatch(self, tool_name: str, arguments: dict) -> dict:
        handler = self._handlers.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}

        # 安全检查: 路径遍历防护
        if "file_path" in arguments:
            self._validate_path(arguments["file_path"])

        return await handler(**arguments)

    def _validate_path(self, file_path: str):
        """确保 file_path 在项目根目录下"""
        resolved = Path(file_path).resolve()
        if not str(resolved).startswith(str(self.project_root)):
            raise ValueError(f"Access denied: {file_path} outside project root")
```

### 5.5 MCP 协议实现 (stdio JSON-RPC)

**`backend-core/mcp_server/server.py`**:

```python
import sys
import json
import asyncio

class MCPServer:
    """MCP 协议 JSON-RPC 2.0 over stdio 服务器"""

    def __init__(self, dispatcher: ToolDispatcher):
        self.dispatcher = dispatcher
        self.tools = CORE_TOOLS  # 从 tools.py 导入

    async def run(self):
        """从 stdin 读取 JSON-RPC 请求, 处理, 写入 stdout"""
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            line = await reader.readline()
            if not line:
                break

            request = json.loads(line.decode())
            response = await self._handle_request(request)
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

    async def _handle_request(self, req: dict) -> dict:
        method = req.get("method")
        req_id = req.get("id")

        if method == "tools/list":
            return self._response(req_id, {
                "tools": [{"name": t.name, "description": t.description,
                           "inputSchema": t.inputSchema} for t in self.tools]
            })

        elif method == "tools/call":
            tool_name = req["params"]["name"]
            arguments = req["params"].get("arguments", {})
            try:
                result = await self.dispatcher.dispatch(tool_name, arguments)
                return self._response(req_id, {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]})
            except Exception as e:
                return self._error(req_id, -32000, str(e))

        else:
            return self._error(req_id, -32601, f"Method not found: {method}")

    def _response(self, req_id, result):
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _error(self, req_id, code, message):
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

# 入口点
if __name__ == "__main__":
    project_root = sys.argv[sys.argv.index("--project-root") + 1]
    # 复用已有分析管线
    from topocode.hybrid_resolver import HybridResolver
    from topocode.symbol_graph import SymbolGraph
    ...
    dispatcher = ToolDispatcher(resolver, graph)
    server = MCPServer(dispatcher)
    asyncio.run(server.run())
```

**工时**: Tool 定义 0.5天, Dispatcher 1天, MCP 协议 Server 1天, Electron 生命周期管理 0.5天, 集成测试 1天。总计 **4天**。

**第五阶段产出**: MCP Server 可被 Continue/Cline 等 Agent 通过 stdio 发现和调用, 7 个核心 Tool 可用。

---

## 第六阶段: Skills 编排引擎 + 复合 Tool (3-4天)

> **核心思路**: Skills 是比 Tool 更高阶的概念——它将多个原子 Tool 组合成"一键式"复合操作, 大幅减少 AI 的往返调用次数, 专门解决 AI 上下文窗口有限和推理成本问题。

### 6.1 Skill 设计原则

| 原则 | 说明 |
|------|------|
| **原子 Tool 对外暴露** | 高级 Agent 可自定义流程 |
| **复合 Skill 一键调用** | 常见场景预编排, 减少往返 |
| **结果摘要优先** | 大量结果先聚合再返回, 避免超出 token 限制 |
| **上下文夹带** | 返回结果时尽量带几行代码片段, 减少 AI 再次查询 |

### 6.2 核心 Skill 定义

**`backend-core/mcp_server/skills.py`**:

```python
class SkillRegistry:
    """Skills = 预设 Tool 编排流程, 对外暴露为复合 Tool"""

    SKILLS = {
        "get_context_for_symbol": {
            "description": "为指定符号拉取'完整上下文包': 定义+文档+前5个引用+直接调用者/被调用者+所在模块导出表",
            "steps": [
                {"tool": "get_symbol_info", "from_input": ["file_path", "line", "character"]},
                {"tool": "get_references", "from_input": ["file_path", "line", "character"],
                 "post_process": "limit_top_5"},
                {"tool": "get_call_hierarchy", "from_input": ["file_path", "line", "character"],
                 "override": {"direction": "both", "max_depth": 1}},
                {"tool": "get_dependencies", "from_input": ["file_path"],
                 "override": {"direction": "imports"}},
            ],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "line": {"type": "integer"},
                    "character": {"type": "integer"}
                },
                "required": ["file_path", "line", "character"]
            }
        },

        "get_impact_analysis": {
            "description": "分析修改某个符号的完整影响范围: 所有直接引用+下游调用链统计+可能受影响的测试文件",
            "steps": [
                {"tool": "get_references", "from_input": ["file_path", "line", "character"]},
                {"tool": "get_call_hierarchy", "from_input": ["file_path", "line", "character"],
                 "override": {"direction": "both", "max_depth": 5}},
                {"tool": "search_symbol", "from_context": {
                    "query": {"build_from": "symbol_name", "suffix": "_test"},
                    "max_results": 20
                }},
            ],
            "inputSchema": { /* 同上 */ }
        },

        "explain_code_block": {
            "description": "解释指定代码范围内的逻辑: 提取范围内所有符号, 构建摘要",
            "steps": [
                {"tool": "get_file_symbols", "from_input": ["file_path"]},
            ],
            "post_process": "filter_by_range",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"}
                },
                "required": ["file_path", "start_line", "end_line"]
            }
        },

        "prepare_refactor": {
            "description": "为重构做准备: 获取函数定义+所有引用点+影响分析, 返回需修改的所有位置和风险点",
            "steps": [
                {"tool": "get_symbol_info", "from_input": ["file_path", "line", "character"]},
                {"tool": "get_references", "from_input": ["file_path", "line", "character"]},
                {"tool": "get_call_hierarchy", "from_input": ["file_path", "line", "character"],
                 "override": {"direction": "both", "max_depth": 3}},
            ],
            "inputSchema": { /* 同上 */ }
        },

        "generate_docstring": {
            "description": "为指定符号生成文档注释 (支持 Google/NumPy/Sphinx 风格)",
            "steps": [
                {"tool": "get_symbol_info", "from_input": ["file_path", "line", "character"]},
            ],
            "post_process": "invoke_llm_doc_gen",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "line": {"type": "integer"},
                    "character": {"type": "integer"},
                    "style": {"type": "string", "enum": ["google", "numpy", "sphinx"], "default": "google"}
                },
                "required": ["file_path", "line", "character"]
            }
        },
    }
```

### 6.3 Skill 编排引擎

**`backend-core/mcp_server/skill_executor.py`**:

```python
class SkillExecutor:
    """按 Skill 定义的 steps 顺序执行各 Tool, 聚合结果"""

    def __init__(self, dispatcher: ToolDispatcher):
        self.dispatcher = dispatcher

    async def execute(self, skill_name: str, arguments: dict) -> dict:
        skill = SkillRegistry.SKILLS.get(skill_name)
        if not skill:
            return {"error": f"Unknown skill: {skill_name}"}

        results = []
        symbol_name = None  # 在第一步中捕获, 供后续 step 使用

        for step in skill["steps"]:
            step_args = self._build_step_args(step, arguments, {"symbol_name": symbol_name})
            result = await self.dispatcher.dispatch(step["tool"], step_args)

            # 捕获符号名供后续 step 使用
            if "symbol_name" in result and not symbol_name:
                symbol_name = result.get("symbol_name")

            # 结果压缩: 大量引用按文件分组摘要
            if "post_process" in step:
                result = self._post_process(step["post_process"], result)

            results.append({"tool": step["tool"], "result": result})

        # 聚合最终输出
        return {
            "skill": skill_name,
            "summary": self._build_summary(results),
            "details": results
        }

    def _build_step_args(self, step, inputs, context):
        """从用户输入 + 上下文构建每个 step 的参数"""
        args = {}
        for key in step.get("from_input", []):
            if key in inputs:
                args[key] = inputs[key]
        if "override" in step:
            args.update(step["override"])
        if "from_context" in step:
            for k, v in step["from_context"].items():
                if isinstance(v, dict) and "build_from" in v:
                    args[k] = context.get(v["build_from"], "") + v.get("suffix", "")
                else:
                    args[k] = v
        return args

    def _post_process(self, mode: str, result: dict) -> dict:
        if mode == "limit_top_5":
            if "references" in result:
                result["references"] = result["references"][:5]
        elif mode == "filter_by_range":
            # 按 start_line/end_line 过滤符号
            ...
        elif mode == "invoke_llm_doc_gen":
            # 调用 LLM 生成文档字符串
            ...
        return result

    def _build_summary(self, results: list) -> str:
        """生成人类可读的摘要文本 (限制长度, 适合 AI 上下文窗口)"""
        ...
```

### 6.4 Agent 协作流程示例

以用户用 Continue 提问为例:
```
User: "这个 process_data 函数改了会影响哪些地方?"

Agent 内部:
  1. tools/call get_definition → 确认函数位置
  2. tools/call get_impact_analysis → 一键获取完整影响报告
     (内部执行: get_references + get_call_hierarchy + search_symbol "_test")
  3. 收到聚合 JSON:
     {
       "skill": "get_impact_analysis",
       "summary": "process_data 在 3 个文件中被直接调用 (5 个引用点),
                   影响下游 8 个函数, 可能涉及 2 个测试文件",
       "details": [
         {"tool": "get_references", "result": {"files": ["main.py(2)", "utils.py(1)", "api.py(2)"]}},
         {"tool": "get_call_hierarchy", "result": {"downstream": ["validate", "export", "transform", ...]}},
         {"tool": "search_symbol", "result": {"matches": ["test_process_data", "test_pipeline"]}}
       ]
     }
  4. Agent 解析生成回答: "它在 main.py 中被 run_pipeline 调用, 影响下游 export_report..."
```

整个过程只需要 **2 次 Tool Call** (而非 5-6 次), 对用户透明。

### 6.5 结果压缩策略 (Token Budget 管理)

对大规模结果必须做聚合, 防止超出 Agent token 限制:

```python
def compress_references(refs: list[dict], max_items: int = 500) -> dict:
    """将引用列表按文件分组, 每文件只保留前3条 + 计数"""
    by_file = {}
    for r in refs:
        by_file.setdefault(r["file_path"], []).append(r)

    return {
        "total_count": len(refs),
        "truncated": len(refs) > max_items,
        "by_file": {
            f: {"count": len(items), "samples": items[:3]}
            for f, items in list(by_file.items())[:50]  # 最多50个文件
        }
    }
```

### 6.6 安全约束

| 约束 | 实现 |
|------|------|
| **文件路径限制** | 所有 `file_path` 校验必须在项目根目录范围内 |
| **stdio 模式, 无网络暴露** | 仅监听 stdin/stdout, 天然的本地沙箱 |
| **只读默认** | 查询和文档生成只读。写操作 Tool (`apply_docstring`) 需显式授权 |
| **结果上限** | 引用 ≤500, 符号搜索 ≤20, 调用层级 ≤5 |
| **无文件内容直接暴露** | 仅返回符号元数据和代码片段(≤3行上下文), 不返回完整文件 |

**工时**: Skill 定义 1天, SkillExecutor 编排引擎 1.5天, 结果压缩 0.5天, 集成测试 1天。总计 **4天**。

**第六阶段产出**: 5 个复合 Skill 可用, MCP Server 完整能力矩阵: 7 个原子 Tool + 5 个复合 Skill。

---

## 第七阶段: 变更感知与分析 (5-6天)

> **核心思路**: 将 TopoCode 的分析能力从"快照式"升级为"时序式"——以 Git 版本历史为锚点, 在两次分析快照之间自动检测符号/依赖/调用链变更, 可视化变更影响范围, 并向 Agent 提供变更摘要和风险评估。这使 TopoCode 成为 **AI 编码代理的变更感知引擎**。

### 7.1 变更分析数据模型

在 `backend-core/change_tracker/change_model.py`:

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

# ===== 快照模型 (复用 Phase 2 Symbol) =====

@dataclass
class ProjectSnapshot:
    """一次完整分析结果快照, 按 commit 锚定"""
    snapshot_id: str                       # UUID
    project_id: str
    commit_hash: str                       # Git commit SHA
    commit_message: str
    commit_author: str
    commit_timestamp: datetime
    parent_commit: Optional[str]           # 父 commit (用于 diff 链)
    file_tables: dict[str, "FileSymbolTable"]  # 复用 Phase 2 模型
    call_graph: dict[str, list[str]]       # caller → callees
    dependency_graph: dict[str, list[str]] # file → imported files
    community_graph: Optional[dict]        # Louvain 社区结果
    created_at: datetime

# ===== 变更检测模型 =====

class ChangeKind(Enum):
    ADDED = "added"          # 新增
    REMOVED = "removed"      # 删除
    MODIFIED = "modified"    # 修改 (签名/类型/文档变化)
    RENAMED = "renamed"      # 重命名
    MOVED = "moved"          # 跨文件移动

class ChangeScope(Enum):
    FILE = "file"            # 文件级
    SYMBOL = "symbol"        # 符号级
    DEPENDENCY = "dependency"# 依赖关系
    CALL_CHAIN = "call_chain"# 调用链
    ARCHITECTURE = "architecture"  # 架构级 (社区/模块)

@dataclass
class SymbolChange:
    """单个符号的变更详情"""
    kind: ChangeKind
    scope: ChangeScope
    symbol_name: str
    symbol_kind: str                    # function/class/variable/...
    file_path: str
    old_location: Optional["SourceLocation"] = None
    new_location: Optional["SourceLocation"] = None
    old_signature: Optional[str] = None # 变更前后的签名 (用于语义比较)
    new_signature: Optional[str] = None
    old_doc: Optional[str] = None
    new_doc: Optional[str] = None
    downstream_impact: list[str] = field(default_factory=list)  # 受影响的调用方符号
    test_files_affected: list[str] = field(default_factory=list)

@dataclass
class FileChange:
    """文件级变更"""
    file_path: str
    kind: ChangeKind
    symbols_added: int = 0
    symbols_removed: int = 0
    symbols_modified: int = 0
    lines_added: int = 0
    lines_removed: int = 0

@dataclass
class ChangeReport:
    """一次 diff 的完整变更报告"""
    report_id: str
    from_commit: str
    to_commit: str
    from_snapshot_id: str
    to_snapshot_id: str
    summary: "ChangeSummary"
    file_changes: list[FileChange] = field(default_factory=list)
    symbol_changes: list[SymbolChange] = field(default_factory=list)
    dependency_changes: list[dict] = field(default_factory=list)
    call_chain_changes: list[dict] = field(default_factory=list)
    architecture_changes: list[dict] = field(default_factory=list)

@dataclass
class ChangeSummary:
    """变更聚合摘要 (Agent 友好)"""
    total_files_changed: int
    files_added: int
    files_removed: int
    files_modified: int
    total_symbols_changed: int
    symbols_added: int
    symbols_removed: int
    symbols_modified: int
    downstream_files_affected: list[str]       # 受影响的下游文件
    test_files_impacted: list[str]             # 可能受影响的测试
    risk_score: float                          # 0.0 ~ 1.0 风险评分
    risk_level: str                            # "low" / "medium" / "high" / "critical"
    breaking_changes: list[str]                # 破坏性变更的符号列表
    key_insight: str                           # 一句话总结 (LLM 生成)
```

### 7.2 快照存储与版本跟踪

**`backend-core/change_tracker/snapshot_store.py`**:

```python
import hashlib
import json
import sqlite3
from datetime import datetime

class SnapshotStore:
    """管理 ProjectSnapshot 的 SQLite 存储 (与 project DB 分离)"""

    def __init__(self, project_db_path: str):
        self.conn = sqlite3.connect(project_db_path)
        self._init_tables()

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                commit_hash TEXT NOT NULL,
                commit_message TEXT,
                commit_author TEXT,
                commit_timestamp TEXT NOT NULL,
                parent_commit TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS snapshot_symbols (
                snapshot_id TEXT NOT NULL,
                symbol_hash TEXT NOT NULL,       -- hash(name, kind, file, scope, location)
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                file_path TEXT NOT NULL,
                scope TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                start_col INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                end_col INTEGER NOT NULL,
                signature TEXT,                  -- JSON: params + return type
                doc_comment TEXT,
                PRIMARY KEY (snapshot_id, symbol_hash)
            );
            CREATE TABLE IF NOT EXISTS snapshot_edges (
                snapshot_id TEXT NOT NULL,
                edge_type TEXT NOT NULL,          -- 'call' / 'dependency' / 'community'
                source TEXT NOT NULL,             -- source symbol/file identifier
                target TEXT NOT NULL,             -- target symbol/file identifier
                metadata TEXT                     -- JSON extra info
            );
            CREATE INDEX IF NOT EXISTS idx_snapshots_project
                ON snapshots(project_id, commit_timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_snapshot_symbols_file
                ON snapshot_symbols(snapshot_id, file_path);
        """)

    def save_snapshot(self, snapshot: ProjectSnapshot):
        """持久化完整快照"""
        self.conn.execute(
            "INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?)",
            (snapshot.snapshot_id, snapshot.project_id, snapshot.commit_hash,
             snapshot.commit_message, snapshot.commit_author,
             snapshot.commit_timestamp.isoformat(), snapshot.parent_commit,
             snapshot.created_at.isoformat())
        )
        for file_table in snapshot.file_tables.values():
            for sym in file_table.symbols:
                sym_hash = self._hash_symbol(sym)
                self.conn.execute(
                    "INSERT OR REPLACE INTO snapshot_symbols VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (snapshot.snapshot_id, sym_hash, sym.name, sym.kind.value,
                     sym.location.file_path, sym.scope,
                     sym.location.start_line, sym.location.start_col,
                     sym.location.end_line, sym.location.end_col,
                     json.dumps({"kind": sym.kind.value}), sym.doc_comment)
                )
        self.conn.commit()

    def _hash_symbol(self, sym: "Symbol") -> str:
        key = f"{sym.name}|{sym.kind.value}|{sym.location.file_path}|{sym.scope}|{sym.location.start_line}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def get_snapshot(self, commit_hash: str) -> Optional[ProjectSnapshot]:
        """按 commit hash 取回快照"""
        ...

    def get_snapshot_chain(self, limit: int = 20) -> list[dict]:
        """获取最近 N 个版本的快照链"""
        ...
```

### 7.3 变更检测引擎

**`backend-core/change_tracker/diff_engine.py`**:

```python
class DiffEngine:
    """比较两个 ProjectSnapshot, 生成 ChangeReport"""

    def __init__(self, resolver: "HybridResolver"):
        self.resolver = resolver  # 用于影响分析

    def diff(self, from_snap: ProjectSnapshot, to_snap: ProjectSnapshot) -> ChangeReport:
        """核心 diff 逻辑: 逐个维度比较"""
        file_changes = self._diff_files(from_snap, to_snap)
        symbol_changes = self._diff_symbols(from_snap, to_snap)
        dependency_changes = self._diff_dependencies(from_snap, to_snap)
        call_chain_changes = self._diff_call_chains(from_snap, to_snap)
        architecture_changes = self._diff_communities(from_snap, to_snap)

        # 影响链分析 (需要 HybridResolver)
        for sc in symbol_changes:
            if sc.kind == ChangeKind.MODIFIED or sc.kind == ChangeKind.REMOVED:
                sc.downstream_impact = self._find_downstream(sc, from_snap, to_snap)
                sc.test_files_affected = self._find_affected_tests(sc, to_snap)

        summary = self._build_summary(file_changes, symbol_changes, dependency_changes)

        return ChangeReport(
            report_id=str(uuid.uuid4()),
            from_commit=from_snap.commit_hash,
            to_commit=to_snap.commit_hash,
            from_snapshot_id=from_snap.snapshot_id,
            to_snapshot_id=to_snap.snapshot_id,
            summary=summary,
            file_changes=file_changes,
            symbol_changes=symbol_changes,
            dependency_changes=dependency_changes,
            call_chain_changes=call_chain_changes,
            architecture_changes=architecture_changes,
        )

    def _diff_symbols(self, from_snap, to_snap) -> list[SymbolChange]:
        """符号级 diff: 
        - 遍历 to_snap 中每个文件的新符号 vs from_snap 同一文件的符号
        - 用 hash 判断 added/removed/modified
        - 对于 modified, 进一步比较 signature/doc 子字段
        - 检测 rename (相同 scope 内名称变化 + 签名相似)
        """
        ...

    def _diff_files(self, from_snap, to_snap) -> list[FileChange]:
        """文件级 diff: 新增/删除/修改 (带行数统计)"""
        ...

    def _find_downstream(self, sc: SymbolChange, from_snap, to_snap) -> list[str]:
        """递归向下游遍历调用链, 找出所有受影响的符号"""
        ...

    def _build_summary(self, ...) -> ChangeSummary:
        """聚合统计, 计算风险评分"""
        risk = self._compute_risk_score(...)
        return ChangeSummary(
            ...
            risk_score=risk,
            risk_level=self._classify_risk(risk),
            key_insight=""  # 留给 LLM 填充
        )
```

### 7.4 Git 集成

**`backend-core/change_tracker/git_adapter.py`**:

```python
class GitAdapter:
    """封装 Git 操作: commit 历史、diff 统计、变更文件列表"""

    def __init__(self, project_root: str):
        self.root = project_root

    def get_commits(self, max_count: int = 50) -> list[dict]:
        """获取最近 N 个 commit 元数据"""
        ...

    def get_changed_files(self, from_commit: str, to_commit: str) -> list[str]:
        """两个 commit 之间变更的文件列表"""
        ...

    def get_current_commit(self) -> str:
        """当前 HEAD commit hash"""
        ...

    def get_diff_stats(self, from_commit: str, to_commit: str) -> dict:
        """文本 diff 统计: lines_added, lines_removed per file"""
        ...
```

### 7.5 变更触发机制

分析管线中的集成点:

```
git hooks / poll / user click
        │
        ▼
  当前 commit 是否已有快照?
        │
   ┌────┴────┐
   │ NO      │ YES
   ▼         ▼
  全量分析   增量分析 (仅变更文件)
  生成快照   生成快照 + diff 上一个快照 → ChangeReport
            │
            ▼
         推送到前端 + MCP 缓存
```

在 `analyst_runner.py` 末尾增加 `_maybe_update_change_tracker()`:

```python
async def _maybe_update_change_tracker(project_root, analysis_result):
    git = GitAdapter(project_root)
    current_commit = git.get_current_commit()
    store = SnapshotStore(db_path)

    existing = store.get_snapshot(current_commit)
    if existing:
        return  # 该 commit 已有快照

    # 构建快照
    snapshot = build_snapshot_from_analysis(analysis_result, current_commit, git)
    store.save_snapshot(snapshot)

    # 找到父 commit 快照做 diff
    parent_commit = git.get_parent_commit(current_commit)
    parent_snapshot = store.get_snapshot(parent_commit)
    if parent_snapshot:
        diff_engine = DiffEngine(hybrid_resolver)
        change_report = diff_engine.diff(parent_snapshot, snapshot)
        store.save_change_report(change_report)

        # 推送到前端 (ZeroMQ PUB)
        zmq_server.publish("change", "change.report", change_report)
```

### 7.6 变更可视化组件 (前端)

**新增组件** (在 Phase 4 基础上扩充):

| 组件 | 功能 | 视觉呈现 |
|------|------|----------|
| `ChangeTimeline.vue` | 沿时间轴展示历次分析快照, 每个节点显示符号/文件变更摘要 | 横向时间轴 + 色块 (绿=新增/红=删除/黄=修改) |
| `ChangeImpactGraph.vue` | D3 力导向图, 将受影响的节点高亮, 新节点绿色、删除节点红色、修改节点黄色 | D3ForceGraph 的 diff 着色模式 |
| `DiffCallHierarchy.vue` | 两个 commit 的调用链并排对比, 差异高亮 | 并排树形视图 + 行级 diff |
| `ChangeDashboard.vue` | 变更仪表盘: 风险评分、文件/符号统计、下游影响范围概览 | 卡片 + 数字 + 进度条 |
| `ChangeRiskBadge.vue` | 风险等级徽章 (low/medium/high/critical) 带颜色和 tooltip | 徽章组件 |
| `CommitSelector.vue` | 下拉选择器: 从 Git 历史中选基线和目标 commit 做 diff | 下拉菜单 + commit 预览 |

**新增 Store**:

| Store | 职责 |
|-------|------|
| `change-store.ts` | 管理当前 diff 状态: 选中 commit 对、ChangeReport 缓存、视图模式 |

### 7.7 MCP 变更相关 Tool (扩展 Phase 5)

在 `tools.py` 中追加:

```python
GET_CHANGES = ToolDefinition(
    name="get_changes",
    description="Get a complete change report between two commits: files changed, symbols added/removed/modified, dependency changes, architectural impact, and risk assessment.",
    inputSchema={
        "type": "object",
        "properties": {
            "from_commit": {"type": "string", "description": "Base commit hash. Use 'HEAD~1' for previous commit."},
            "to_commit": {"type": "string", "description": "Target commit hash. Defaults to HEAD.", "default": "HEAD"},
            "scope": {"type": "string", "enum": ["summary", "files", "symbols", "dependencies", "full"],
                      "default": "summary", "description": "Level of detail to return."}
        },
        "required": ["from_commit"]
    }
)

GET_VERSION_HISTORY = ToolDefinition(
    name="get_version_history",
    description="List recent commits with their analysis snapshot availability. Shows which versions have been analyzed.",
    inputSchema={
        "type": "object",
        "properties": {
            "max_count": {"type": "integer", "default": 20, "description": "Number of recent commits to list."},
            "only_analyzed": {"type": "boolean", "default": False, "description": "Only show commits with analysis snapshots."}
        }
    }
)

EVALUATE_CHANGE = ToolDefinition(
    name="evaluate_change",
    description="AI-assisted semantic evaluation of a code change. What was refactored? Is it a breaking change? What's the risk? Uses LLM to analyze the change report and produce a human-readable evaluation.",
    inputSchema={
        "type": "object",
        "properties": {
            "from_commit": {"type": "string", "description": "Base commit hash."},
            "to_commit": {"type": "string", "description": "Target commit hash.", "default": "HEAD"},
            "focus": {"type": "string", "enum": ["overview", "breaking", "refactoring", "security"],
                      "default": "overview", "description": "Evaluation focus area."}
        },
        "required": ["from_commit"]
    }
)

TRACK_SYMBOL_HISTORY = ToolDefinition(
    name="track_symbol_history",
    description="Track how a specific symbol has evolved across versions: when it was created, modified, its signature changes over time.",
    inputSchema={
        "type": "object",
        "properties": {
            "symbol_name": {"type": "string", "description": "Full qualified name of the symbol."},
            "file_path": {"type": "string", "description": "File containing the symbol."},
            "max_versions": {"type": "integer", "default": 10}
        },
        "required": ["symbol_name", "file_path"]
    }
)

# 追加到 CORE_TOOLS
CORE_TOOLS.extend([GET_CHANGES, GET_VERSION_HISTORY, EVALUATE_CHANGE, TRACK_SYMBOL_HISTORY])
```

### 7.8 MCP 变更相关 Skill (扩展 Phase 6)

在 `skills.py` 中追加:

```python
"assess_merge_impact": {
    "description": "全面评估一次合并/PR的代码影响: 变更摘要+符号级变更+下游影响+风险评估+测试建议",
    "steps": [
        {"tool": "get_changes", "from_input": ["from_commit", "to_commit"],
         "override": {"scope": "full"}},
        {"tool": "evaluate_change", "from_input": ["from_commit", "to_commit"],
         "override": {"focus": "overview"}},
    ],
    "inputSchema": {
        "type": "object",
        "properties": {
            "from_commit": {"type": "string"},
            "to_commit": {"type": "string", "default": "HEAD"}
        },
        "required": ["from_commit"]
    }
},

"review_refactoring": {
    "description": "分析最近一次重构的质量: 哪些符号移动了? 公共API是否破坏? 依赖是否简化?",
    "steps": [
        {"tool": "get_changes", "from_input": ["from_commit", "to_commit"],
         "override": {"scope": "symbols"}},
        {"tool": "evaluate_change", "from_input": ["from_commit", "to_commit"],
         "override": {"focus": "refactoring"}},
    ],
    "inputSchema": { /* 同上 */ }
},
```

### 7.9 Agent 变更感知协作流程

```
User: "最新一次 PR 合并后的影响范围是什么?"

Agent 内部:
  1. tools/call get_version_history → 获取最近 commit 列表
  2. tools/call assess_merge_impact { from_commit: "abc1234" }
     → 内部执行 get_changes + evaluate_change
  3. 收到聚合结果:
     {
       "summary": {
         "total_files_changed": 7,
         "symbols_added": 3, "symbols_modified": 5,
         "downstream_files_affected": ["api.py", "handlers.py"],
         "test_files_impacted": ["test_api.py"],
         "risk_score": 0.45, "risk_level": "medium",
         "breaking_changes": [],
         "key_insight": "本次变更是纯内部重构, 提取了公共工具函数, 对外API无破坏性变更"
       },
       "evaluation": {
         "refactoring_type": "extract_method",
         "is_breaking": false,
         "recommendation": "建议更新 test_api.py 中的 mock 逻辑以匹配新函数签名"
       }
     }
  4. Agent: "PR 修改了7个文件, 提取了3个工具函数, 修改了5个已有函数签名。
     无破坏性变更, 风险等级为中。建议更新 test_api.py 的 mock 逻辑..."
```

**工时**: 数据模型 0.5天, SnapshotStore 1天, DiffEngine 1.5天, Git 集成 0.5天, 触发机制 0.5天, MCP变更Tool/Skill 1天。总计 **5天**。

**第七阶段产出**: 完整的变更分析管线: Git 版本跟踪 → 快照存储 → 自动 Diff → 影响评估 → 可视化。MCP 扩展 11 个原子 Tool + 7 个复合 Skill。

---

## 时间线总览

```
Week 1           Week 2           Week 3           Week 4           Week 5           Week 6           Week 7
├──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┤
│Ph0│Ph1        │ Phase 2                           │ Phase 3              │ Phase 4
│1天│P0修复     │ Tree-sitter Query + Symbol 模型   │ Stack Graphs 集成    │ 前端债务清理
│测 │后端清理   │ + SimpleBinder                    │ HybridResolver       │ Store/组件拆分
│试 │           │                                    │                      │ Composables
│框 │ 3天        │ 6天                                │ 3.5天                │ 7.5天
│架 │           │                                    │                      │
│   │           │ 里程碑A: Query链路                 │ 里程碑B: 混合解析器  │ 里程碑C: B→A
│   │里程碑0   │ TypeScript prototype              │ 定义跳转可用         │ 架构评分A
├───┴───────────┴────────────────────────────────────┴──────────────────────┼──────────────────┤
│                                                                          │ Phase 5
│                                                                          │ MCP Server
│                                                                          │ 11 Tools (ZMQ)
│                                                                          │
│                                                                          │ 5天
│                                                                          │
│                                                                          │ 里程碑D: MCP
│                                                                          │ Agent可发现
├──────────────────────────────────────────────────────────────────────────┴──────────────────┤
│ Phase 6                                       │ Phase 7                                     │
│ Skills + 复合Tool + 编排引擎                  │ 变更感知: 快照存储 + Diff引擎 + 可视化       │
│                                               │ + MCP变更Tool/Skill                         │
│ 4天                                            │ 5天                                         │
│                                               │                                             │
│ 里程碑E: Skills完整                            │ 里程碑F: 变更感知完整                      │
│                                               │ Git→快照→Diff→评估→可视化 链路贯通          │
└───────────────────────────────────────────────┴─────────────────────────────────────────────┘
```

**总计: 35 个工作日 | 7 周 (含 Phase 0 测试框架)**

```
Phase 0 ──► Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5 ──► Phase 6 ──► Phase 7
(测试     (P0修复   (Query   (Stack    (前端     (MCP      (Skills   (变更感知
 框架)    后端清理)  引擎     Graphs    债务      Server    编排)     全链路)
                     Symbol  Hybrid    清理)     独立进程)
                     Binder  Resolver)

所有 Phase 严格顺序执行 (单开发者)。
Phase 2 准入: npm run type-check + npm test + pytest 通过 (Phase 0 建立的基线)。
```

- Phase 5 依赖 Phase 3 (HybridResolver via ZMQ)
- Phase 6 依赖 Phase 5 (MCP Server + ToolDispatcher)
- Phase 7 依赖 Phase 2+3 (Symbol模型 + DiffEngine 需要 HybridResolver) + Phase 5 (MCP变更Tool/Skill reuses MCPServer)

---

## 新增目录与文件清单

### 变更分析模块 (Phase 7 新增)

```
backend-core/
  change_tracker/
    __init__.py
    change_model.py          # ProjectSnapshot / ChangeReport / SymbolChange / ChangeSummary 数据模型
    snapshot_store.py        # SQLite 快照存储 (snapshots + snapshot_symbols + snapshot_edges 表)
    diff_engine.py           # DiffEngine: 比较两个快照, 生成 ChangeReport (文件/符号/依赖/调用链四维)
    git_adapter.py           # Git 操作: commit历史 / changed_files / diff_stats
    impact_analyzer.py       # 下游影响分析 (递归调用链遍历 + 测试文件匹配)

src/
  stores/
    change-store.ts          # 变更分析状态: 选中commit对, ChangeReport缓存, 视图模式
  components/
    change/                  # 新增变更可视化组件目录
      ChangeTimeline.vue     # 版本时间轴 (Git历史 + 快照状态)
      ChangeImpactGraph.vue  # 变更影响 D3 力导向图 (diff着色: 绿/红/黄)
      DiffCallHierarchy.vue  # 调用链并排diff (两个commit对比)
      ChangeDashboard.vue    # 变更仪表盘 (风险评分 + 统计卡片)
      ChangeRiskBadge.vue    # 风险等级徽章 (low/medium/high/critical)
      CommitSelector.vue     # Git commit 选择器 (from/to 双列表)
      SymbolHistoryPanel.vue # 符号演化历史 (时间线+diff)
```

### MCP Server 模块 (Phase 5-6 新增) + 变更Tool扩展 (Phase 7 追加)

```
backend-core/
  mcp_server/
    __init__.py
    __main__.py              # python -m topocode.mcp_server 入口
    server.py                # MCPServer: JSON-RPC 2.0 over stdio
    tools.py                 # 11 Tool定义: 7核心 + 4变更 (get_changes/evaluate_change/get_version_history/track_symbol_history)
    dispatcher.py            # ToolDispatcher: 请求 → Handler 调度
    skills.py                # 7 Skill定义: 5核心 + 2变更 (assess_merge_impact/review_refactoring)
    skill_executor.py        # SkillExecutor: 步骤编排 + 结果聚合
    result_compressor.py     # 结果压缩 (按文件分组/摘要/截断)
    path_validator.py        # 文件路径安全校验
```

### 前端管理 (Phase 4-7 新增)

```
src/components/settings/
  MCPSettings.vue            # MCP Server 启停控制 + 状态监控
src/stores/
  mcp-store.ts               # MCP Server 生命周期状态管理
electron/
  mcp-manager.ts             # 管理 MCP Server 子进程 (spawn/stop/restart)
```

---

## 里程碑验收标准

### 里程碑 0: 测试基线 (Week 1 Day 1)
- [ ] `npm run type-check` 无报错 (vue-tsc 崩溃已修复)
- [ ] `npm run lint` 无错误
- [ ] `npm test` 可运行, ≥10 条测试用例通过 (utils/ 覆盖率 ≥90%)
- [ ] `pytest backend-core/tests/` 可运行, ≥5 条测试用例通过

### 里程碑 1: P0 清零 (Week 1 Day 4)
- [ ] `usePlantUmlRender.ts` IPC 路径修复, Electron 渲染正常
- [ ] `types/index.ts` / `types/ipc.ts` 无字段名冲突
- [ ] 死代码回调数组已删除
- [ ] `backend/` 旧目录已删除

### 里程碑 A: Query 链路 (Week 2 Day 5)
- [ ] TypeScript `.scm` Query 文件通过 `tree-sitter query` 命令验证
- [ ] `QueryLoader` 可正确加载并捕获符号/引用
- [ ] `Symbol` + `Reference` 模型替代旧的手写 DFS 输出
- [ ] `SimpleBinder` 可正确解析 ≥80% 的 TypeScript 文件内引用

### 里程碑 B: 混合解析器 (Week 3 Day 2)
- [ ] `StackGraphsService` 可启动子进程并索引项目
- [ ] `HybridResolver` 自动路由快速/精确路径
- [ ] 前端"转到定义"功能可跳转到跨文件定义

### 里程碑 C: 架构升级 (Week 4 Day 5)
- [ ] 所有 P0/P1 问题已修复 (v2 报告)
- [ ] 组件 >400 行数量从 26 → ≤15
- [ ] `any` 类型从 392 → ≤200
- [ ] 综合架构评分 B(66) → A(≥80)

### 里程碑 D: MCP 可用 (Week 5 Day 4)
- [ ] `tools/list` 返回 7 个核心 Tool
- [ ] Continue/Cline 可通过 stdio 配置发现 TopoCode MCP Server
- [ ] `get_definition` 可正确返回跨文件定位
- [ ] `get_references` 可返回正确引用列表 (含文件分组)
- [ ] 文件路径遍历攻击被拦截

### 里程碑 E: Skills 完整 (Week 6 Day 4)
- [ ] 7 个复合 Skill 全部可用 (含 assess_merge_impact + review_refactoring)
- [ ] `get_impact_analysis` 可一键返回完整影响报告
- [ ] 结果压缩策略生效 (500+ 引用自动分组摘要)
- [ ] Agent 端到端测试: "这个函数改动影响哪些地方?" → 2-3 次 Tool Call 返回完整答案

### 里程碑 F: 变更感知完整 (Week 7 Day 5)
- [ ] Git 集成: `get_commits`, `get_changed_files`, `get_diff_stats` 可用
- [ ] 分析完成后自动生成快照并存入 `snapshots` 表
- [ ] Diff 后自动生成 ChangeReport (文件/符号/依赖/调用链四维)
- [ ] 前端 `ChangeTimeline` + `ChangeImpactGraph` 可视化组件可交互
- [ ] MCP: `get_changes` / `evaluate_change` Tool 返回正确变更报告
- [ ] Agent 端到端: "最新PR的影响?" → assess_merge_impact → 完整影响+风险评估
- [ ] `track_symbol_history`: 跟踪符号在多个版本中的演化路径

---

## 风险与缓解

| 风险 | 可能性 | 缓解措施 |
|------|--------|----------|
| `stack-graphs` CLI 在目标语言上覆盖率低 | 中 | 先用 AI 辅助生成 `.tsg` 规则, 渐进覆盖 |
| Tree-sitter Query 语法差异导致迁移工作量大 | 中 | 先在 TypeScript 验证, 再 AI 批量生成 |
| 大组件拆分会引入回归 Bug | 低 | 拆分前后视觉回归测试, 保留 wrapper 兼容 |
| Community 分析管线改造影响线上功能 | 低 | 新旧代码通过 feature flag 切换 |
| MCP 协议变更导致与 Agent 不兼容 | 低 | stdio JSON-RPC 是标准, MCP 规范稳定; 可参考 `mcp` Python SDK 对齐 |
| Agent 调用频率过高导致后端过载 | 中 | LRU 缓存 + 结果压缩 + 单 Agent 最大并发限制 |
| 外部 Agent 对项目路径无感知 | 中 | MCP Server 启动时通过 `--project-root` 参数注入, 同时支持 `set_project` Tool 动态切换 |
| Skill 执行耗时过长 (Agent 等待超时) | 中 | Skill 超时 10s, 超时返回部分结果 + `partial: true` 标记 |
| 快照存储膨胀 (大项目每 commit 存全量快照) | 中 | 仅存储符号摘要 (非完整AST), 压缩率 >90%; 对合并 commit 按日/周粒度去重; 设置快照保留上限 (100个) |
| Git 历史过大导致 diff 遍历慢 | 低 | 限制单次 diff 最多对比 20 个 commit 间隔; 增量 diff 缓存 |
| 变更分析中有已装/未装分析结果的不一致 | 低 | get_version_history 的 `only_analyzed=true` 过滤; 对未分析版本提示"请先分析该版本" |

---

## 完整性审查

### 7.1 跨阶段依赖一致性检查

| 前置 → 后置 | 依赖项 | 状态 |
|-------------|--------|------|
| Phase 2 → Phase 3 | `Symbol` 模型被 `HybridResolver` 使用 | ✅ 一致 |
| Phase 2 → Phase 7 | `Symbol` / `FileSymbolTable` 被 `ProjectSnapshot` 复用 | ✅ 一致 (Phase 7 直接 import Phase 2 的 `symbol_model.py`) |
| Phase 3 → Phase 5 | `HybridResolver` 被 `ToolDispatcher` 使用 | ✅ 一致 |
| Phase 3 → Phase 7 | `HybridResolver` 被 `DiffEngine._find_downstream()` 使用 | ✅ 一致 |
| Phase 5 → Phase 6 | `ToolDispatcher` + `CORE_TOOLS` 被 `SkillExecutor` 使用 | ✅ 一致 |
| Phase 5 → Phase 7 | MCP Tool `get_changes` 等复用 `MCPServer` 的 `tools/call` 流程 | ✅ 一致 |
| Phase 2 → Phase 4 | Query 引擎替代后, 前端 `FileStatsPanel` 等不受影响 (通过 IPC 隔离) | ✅ 一致 (后端变更对前端透明) |

### 7.2 数据模型一致性检查

| 检查项 | 发现 | 状态 |
|--------|------|------|
| `Symbol` 模型是否在所有阶段一致? | Phase 2 定义 `symbol_model.py`, Phase 7 `SnapshotStore` 序列化它, Phase 5 `ToolDispatcher` 以 JSON 格式返回——**需要确保附加字段 (signature/doc_comment) 在序列化时不丢失** | ⚠️ 需确认: `Symbol` dataclass 序列化为 JSON 时应包含 `signature` 字段 (当前定义中无 signature, 需补充) |
| `FileSymbolTable` 是否支持版本化? | Phase 2 的 `FileSymbolTable` 不包含版本信息——Phase 7 `ProjectSnapshot` 在外层增加 `commit_hash` 进行版本锚定, 不修改 `FileSymbolTable` 本身 | ✅ 一致 |
| `ChangeReport` 中引用的 `SourceLocation` 是否与 Phase 2 一致? | Phase 7 `SymbolChange` 引用 `SourceLocation` 来自 Phase 2 模型—类型一致 | ✅ 一致 |
| MCP `get_changes` 返回的 JSON 格式与前端 `ChangeDashboard` 期望格式是否一致? | Phase 7 工具返回 `ChangeReport`, 前端组件期望 `ChangeDashboardData`——**需要定义共享的 TypeScript 接口** | ⚠️ 需确认: 建议在 `types/ipc.ts` 中定义 `ChangeReportDTO` |
| Snapshot 的 `symbol_hash` 是否跨越不同树-sitter 版本稳定? | `_hash_symbol` 用 `(name, kind, file, scope, line)` 五元组——AST 结构变化不影响 hash, 但 **Tree-sitter 版本升级可能改变 line 号** | ⚠️ 需确认: 对同一 commit 用不同 Tree-sitter 版本分析的快照不应混合对比 |

### 7.3 工时估算一致性检查

| 检查项 | 发现 | 状态 |
|--------|------|------|
| Phase 2 估算 6 天但包含 3 个子任务 | 3天(Query) + 2天(Symbol模型) + 1天(Binder) = 6天 | ✅ 一致 |
| Phase 5 估算 4 天但 Tool 数量从 7→11 后工时未变 | 新增 4 个变更 Tool 增加 ~1 天工作量, 当前 4 天偏紧 | ⚠️ 建议: Phase 5 调整为 **5 天**, 或部分变更 Tool 写到 Phase 7 中 |
| Phase 7 估算 5 天 | 数据模型0.5 + SnapshotStore1 + DiffEngine1.5 + Git0.5 + 触发0.5 + MCP变更Tool1 = 5天 | ✅ 一致 |
| Phase 4 7.5天 vs 4.1(2天)+4.2(1.5天)+4.3(3天)+4.4(1天)=7.5天 | 总计 7.5 天, 标为 5-7天 | ⚠️ 建议: 统一为 **7.5 天** |

### 7.4 概念/术语一致性检查

| 检查项 | 发现 |
|--------|------|
| `Tool` 定义的 inputSchema 格式 | Phase 5 用 `"type": "object"` 顶层, Phase 7 新增 Tool 同样格式—一致 ✅ |
| `Skill` 的 `steps` 结构中 `from_input` / `from_context` 语义 | Phase 6 定义, Phase 7 新增 Skill 同样格式—一致 ✅ |
| 前端组件命名 | `ChangeTimeline` vs `DiffCallHierarchy` vs `ChangeImpactGraph`—均以功能名词命名, 但 `ImpactGraph`/`Dashboard`/`Timeline` 风格混用 | ⚠️ 建议: 统一为 `Change*` 前缀 |

### 7.5 已明确的设计决策 (8项确认)

---

#### 决策 1: Stack Graphs 集成策略

**结论: 系统工具, 用户按需安装。**

`stack-graphs` 不是 Python 包, 不在 `requirements.txt` 中, 也不是所有平台预装。按以下策略处理:

| 层面 | 决策 |
|------|------|
| 分发方式 | **用户自行安装** (类似安装 Git/Docker), 项目中不捆绑分发 |
| 检测机制 | Phase 3 启动时 `shutil.which('stack-graphs')` 检测 PATH |
| 降级行为 | CLI 不存在 → `HybridResolver` 仅使用 `SimpleBinder`, 精确路径自动跳过 |
| 用户提示 | 前端 `StatusBar` 显示"Stack Graphs 未安装 → 跨文件引用精度受限", 提供安装引导链接 |
| 安装文档 | `docs/usage-guide.md` 增加 Stack Graphs 安装章节 (各平台) |

**代码实现**:
```python
import shutil

class StackGraphsService:
    def __init__(self, project_root: str, language: str):
        self.available = shutil.which('stack-graphs') is not None
        if not self.available:
            logger.info("stack-graphs CLI not found in PATH; precise resolution disabled")

    async def definition(self, file, line, col) -> dict | None:
        if not self.available:
            return None  # 安静降级
        ...
```

---

#### 决策 2: MCP Server 架构

**结论: 选项(2) — 独立进程, 通过 ZeroMQ 连接到主后端。**

原计划"初期方案A (直接库调用)"改为**方案B (ZeroMQ 消息)**。理由:
1. MCP Server 必须通过 **stdio** 与 Agent 通信 — 如果 FastAPI 进程已占用 stdin/stdout (uvicorn 日志输出), 无法再复用 stdio 作 MCP 协议通道。
2. 与现有 ZMQ 基础设施一致, 复用电子的 `zmq-router.ts` 已实现的 `zmqRouter.call()` 方法。
3. MCP Server 可独立重启、升级, 不影响主后端稳定性。

**架构**:
```
Agent stdio ──► MCP Server (独立 Python 进程)
                     │
                     │  ZMQ DEALER  (tcp://127.0.0.1:5671)
                     ▼
              FastAPI/ZMQ 主后端 (HybridResolver + SnapshotStore + ...)
```

**启动方式 (Electron)**:
```typescript
// mcp-manager.ts
spawn('python', ['-m', 'topocode.mcp_server', 
    '--project-root', projectRoot,
    '--zmq-dealer-port', '5671'], 
    { stdio: ['pipe', 'pipe', 'pipe'] })
// stdin/stdout 对接 Agent 配置
```

**Agent 配置**:
```json
{
  "mcpServers": {
    "topocode": {
      "command": "python",
      "args": ["-m", "topocode.mcp_server", "--zmq-dealer-port", "5671", "--project-root", "${workspaceFolder}"]
    }
  }
}
```

---

#### 决策 3: 快照触发策略

**结论: 仅全量分析触发 Snapshot 持久化。局部分析不写快照。**

| 分析类型 | 触发方式 | 行为 |
|----------|----------|------|
| 全量分析 (用户显式触发) | `analysis.runTask` 完成后 | 生成 `ProjectSnapshot` → 写入 DB → 自动 diff 上一个快照 → 生成 `ChangeReport` → 推送前端 |
| 局部分析 (单文件/目录) | `analysis.runTask` 完成后 | **不写快照表**。仅在前端生成 "实时 diff" (相对于最近一次全量快照) 供临时预览, 关闭页面丢弃 |
| 首次分析 (项目导入) | 导入完成后 | 生成初始快照 (无父快照, 不 diff) |
| 用户强制快照 | 前端按钮 | 触发一次全量分析 + 快照 |

**数据流**:
```
全量分析完成
  ├─ 构建 ProjectSnapshot
  ├─ snapshot_store.save(snapshot)
  ├─ parent = snapshot_store.get(parent_commit)
  └─ if parent:
       change_report = diff_engine.diff(parent, snapshot)
       ├─ snapshot_store.save_change_report(report)
       └─ zmq.publish("change", "report", report)  → 推送前端

局部分析完成
  └─ # 不操作快照表
     # 前端可调用 get_changes(from=last_full_snapshot) 获取实时 diff
```

---

#### 决策 4: 快照存储方案

**结论: 选项(1)+(2)+(3) 组合 — 20版本上限 + 文件hash去重 + 独立 `snapshots.db`。**

| 参数 | 值 |
|------|------|
| 存储位置 | `{project_db_dir}/snapshots.db` (独立文件, 非 project DB) |
| 版本上限 | **最近 20 个 commit 的快照** (超过自动清理) |
| 去重策略 | 文件级 hash 去重: Git blob SHA 未变的文件, 符号表指针指向最近一个包含该文件版本的快照 |
| 清理策略 | FIFO: 超过 20 个快照时, 删除最旧的快照 (若其含有的文件版本被后续快照引用, 则保留该文件记录但标记快照为已删除) |

**存储估算**: 中等 TypeScript 项目 (~500 文件, ~3000 符号), 每个快照压缩后约 ~500KB。20 个版本 ≈ **10MB**。去重后实际 ≈ **2-3MB**。

**表结构 (最终)**:
```sql
-- snapshots.db
CREATE TABLE snapshots (
    snapshot_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    commit_hash TEXT NOT NULL,
    commit_message TEXT,
    commit_author TEXT,
    commit_timestamp TEXT NOT NULL,
    parent_commit TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE file_versions (
    file_hash TEXT PRIMARY KEY,         -- Git blob SHA
    file_path TEXT NOT NULL,
    snapshot_id TEXT NOT NULL           -- 第一次出现的快照 (用于去重链)
);

CREATE TABLE snapshot_symbols (
    snapshot_id TEXT NOT NULL,
    file_hash TEXT NOT NULL,            -- 关联 file_versions
    symbol_hash TEXT NOT NULL,          -- hash(name+kind+scope)
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    scope TEXT NOT NULL,
    location_json TEXT NOT NULL,        -- JSON: {start_line, start_col, end_line, end_col}
    signature TEXT,
    doc_comment TEXT,
    PRIMARY KEY (snapshot_id, file_hash, symbol_hash)
);

CREATE TABLE change_reports (
    report_id TEXT PRIMARY KEY,
    from_snapshot_id TEXT NOT NULL,
    to_snapshot_id TEXT NOT NULL,
    report_json TEXT NOT NULL,          -- 压缩后的 ChangeReport JSON
    created_at TEXT NOT NULL
);
```

---

#### 决策 5: Tree-sitter Query 与 grammars 自带 .scm 的关系

**结论: 全新编写 `definitions.scm` 和 `references.scm`, 参考 grammars 的节点类型定义。**

| 文件类型 | 来源 | 用途 | 与我们 Query 的关系 |
|----------|------|------|---------------------|
| `highlights.scm` | 随 grammars 分发 (如 `tree-sitter-typescript`) | 编辑器语法高亮 | **无关** — 标记的是颜色 token, 不是语义结构 |
| `tags.scm` | 随 grammars 分发 | ctags 风格的符号索引 (简化版) | **可参考** — 但 tags.scm 通常只捕获顶层符号名, 缺少作用域/参数/引用信息 |
| `locals.scm` | 随 grammars 分发 | 局部变量作用域定义 | **部分相关** — 可借鉴其作用域规则, 但我们 Query 需捕获更多上下文 |
| `definitions.scm` | **我们编写** (新) | 捕获函数/类/变量/接口的完整定义 (含签名/参数/文档) | ← 本阶段核心产出 |
| `references.scm` | **我们编写** (新) | 捕获所有引用点 (调用/成员访问/标识符) | ← 本阶段核心产出 |
| `imports.scm` | **我们编写** (新) | 捕获 import/include/require 语句 | ← 本阶段核心产出 |

**编写策略**:
1. **节点类型命名**: 使用 grammars 中已定义的 AST 节点类型名称 (如 `function_declaration`, `call_expression`, `import_statement`)。这些名称来自 `tree-sitter-{lang}/src/node-types.json`——我们的 QueryLoader 应加载此文件以验证节点类型有效性。
2. **捕获标签命名**: 我们自定义标签前缀 (`@func.name`, `@call.callee`, `@ref.name` 等), 与 grammars 自带的高亮标签 (`@function`, `@variable`) 独立。
3. **AI 辅助生成**: 用 grammars 的 `node-types.json` 作为 prompt context, 让 LLM 生成 Query。人工审查边界 case。

**目录结构**:
```
plugins/parsers/parsers/queries/
  typescript/
    definitions.scm    ← 新编写 (基于 typescript/node-types.json)
    references.scm     ← 新编写
    imports.scm        ← 新编写
  python/
    definitions.scm    ← AI 生成 + 人工审查
    ...
```

---

#### 决策 6: 测试基础设施

**结论: 在 Phase 1 之前插入 Phase 0 — 测试框架搭建, 且作为 Phase 2+ 的准入条件。**

**理由**: `vitest.config.ts` 存在但 `tests/` 为空, Python 侧无正式测试目录, `vue-tsc` 当前崩溃——在 0% 测试覆盖下进行 Phase 2/3/4 大规模重构风险不可接受。

**Phase 0 内容**:

| # | 任务 | 工时 | 验收标准 |
|---|------|------|----------|
| T1 | 修复 `vue-tsc` 崩溃 (Node 版本兼容) | 0.5h | `npm run type-check` 无报错 |
| T2 | 搭建前端单元测试: `src/__tests__/` 目录 + vitest 基础配置 | 1h | `npm test` 可运行 (即使 0 条测试) |
| T3 | 为 `utils/` 5 个纯函数文件写首批测试 (time/fileColors/statusBadge) | 1h | 覆盖率 ≥90% for utils/ |
| T4 | 为 `composables/` 中纯逻辑部分写测试 (useChatSession) | 1h | 核心路径覆盖 |
| T5 | 搭建 Python 测试: `backend-core/tests/` 目录 + `pytest` 配置 | 1h | `pytest` 可运行 |
| T6 | 为 `backend-core/config.py` + `change_model.py` + `symbol_model.py` 写数据模型测试 | 1h | 序列化/反序列化一致性验证 |
| T7 | CI 集成: `.github/workflows/test.yml` (仅前端, 后端 skip 若无 Python 环境) | 0.5h | PR 自动跑 lint + type-check + test |

**Phase 0 总计: 1 天 (6h)**

**Phase 2/3/4 准入条件**:
- [ ] `npm run type-check` 通过
- [ ] `npm run lint` 通过
- [ ] `npm test` 通过 (≥ 10 条测试用例)
- [ ] `pytest backend-core/tests/` 通过 (≥ 5 条测试用例)

---

#### 决策 7: Phase 4 并行策略

**结论: 假定单开发者, 严格按 Phase 顺序执行。Phase 4 在 Phase 3 完成后开始。**

**理由**:
- 用户未提及团队规模, 默认单开发者。
- Phase 4 的大组件拆分 (SubDocViewer 960行) 与 Phase 2/3 的 Python 后端改造是**完全不同的代码域**, 同一人切换成本高。
- 按顺序执行确保每个 Phase 完成后有稳定的基线, 降低回滚成本。

**调整后的时间线 (顺序执行)**:
```
Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7
 1天      3天      6天      3.5天    7.5天     5天      4天       5天

总计: 35 天 ≈ 7 周
```

---

#### 决策 8: 变更可视化组件

**结论: 确认 D3ForceGraph diffMode prop 方案。**

**实现**:

`D3ForceGraph.vue` 新增 props:

```typescript
interface DiffModeProps {
  enabled: boolean
  addedNodes: string[]      // 新增符号节点ID (绿色 #4caf50)
  removedNodes: string[]    // 删除符号节点ID (红色 #f44336)
  modifiedNodes: string[]   // 修改符号节点ID (黄色 #ff9800)
}

// 使用示例:
<D3ForceGraph 
  :graph-data="changeReport.graph"
  :diff-mode="{ 
    enabled: true, 
    addedNodes: changeReport.symbol_changes.filter(s => s.kind === 'added').map(n => n.symbol_name),
    removedNodes: [...], 
    modifiedNodes: [...] 
  }"
/>
```

**组件关系**:
```
D3ForceGraph.vue (通用, 已有)
  ├─ 新增 diffMode prop → 节点着色逻辑
  │
  └─ ChangeImpactGraph.vue (新增, 轻量包装)
       ├─ 图例: 🟢Added 🟡Modified 🔴Removed
       ├─ 过滤器: 按文件/按符号类型/按变更类型
       ├─ 详情面板: 点击节点 → 右侧弹出 SymbolChange 详情
       └─ 内部: <D3ForceGraph :diff-mode="{...}" />
```

---

### 7.6 各 Phase 最终产出汇总 (调整后)

| Phase | 核心产出 | 工时 | 累积工时 |
|-------|----------|------|----------|
| Phase 0 | 测试框架 (vitest + pytest) + CI + 工具函数纯测试 + 准入基线 | 1天 | 1天 |
| Phase 1 | P0/P1 清零, 后端目录清理 | 3天 | 4天 |
| Phase 2 | `.scm` Query引擎 + `Symbol`/`Reference`/`FileSymbolTable` + SimpleBinder | 6天 | 10天 |
| Phase 3 | `StackGraphsService` (可选降级) + `HybridResolver` + 融合图 | 3.5天 | 13.5天 |
| Phase 4 | Store拆分 + Composable提取 + 大组件拆分 + 类型修复 | 7.5天 | 21天 |
| Phase 5 | MCP Server (11 Tool, ZMQ独立进程) + Electron `mcp-manager.ts` | 5天 | 26天 |
| Phase 6 | SkillExecutor + 7 Skill + 结果压缩 (Token Budget) | 4天 | 30天 |
| Phase 7 | SnapshotStore + DiffEngine + Git集成 + 变更可视化 + 变更MCP Tool/Skill | 5天 | **35天** |

---

## 八、8 项设计决策速查表

| # | 决策项 | 结论 | 优先级 |
|---|--------|------|--------|
| 1 | Stack Graphs 集成 | **系统工具, 用户按需安装**。`shutil.which` 检测, 不存在时 SimpleBinder 降级 | Phase 3 实施 |
| 2 | MCP Server 架构 | **独立进程 + ZeroMQ** (`--zmq-dealer-port`)。MCP Server 通过 ZMQ DEALER 连主后端, stdio 面向 Agent | Phase 5 实施 |
| 3 | 快照触发 | **仅全量分析** 触发 Snapshot 持久化。局部分析生成实时 diff 不持久化 | Phase 7 实施 |
| 4 | 快照存储 | **20版本上限 + 文件hash去重 + 独立 `snapshots.db`** | Phase 7 实施 |
| 5 | Tree-sitter Query | **全新编写** definitions/references/imports.scm, 参考 grammars 的 `node-types.json` 节点类型。与自带 highlights/tags 无关 | Phase 2 实施 |
| 6 | 测试基础设施 | **Phase 0 前置**。vitest + pytest 基线, 10+ 前端 + 5+ 后端测试用例。Phase 2+ 准入条件 | Phase 0 实施 (立即) |
| 7 | 并行策略 | **严格顺序**。单开发者, Phase 0→1→2→...→7 依次执行 | 所有 Phase |
| 8 | 变更可视化 | **D3ForceGraph `diffMode` prop + `ChangeImpactGraph` 轻量包装**。通用组件增加 diff 着色能力, 变更组件提供图例/过滤/详情面板 | Phase 7 实施 |
