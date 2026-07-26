# Phase 4: Agent 工作流 + 知识库详细设计

> 文件名: `docs/plan/phase4-agent-knowledge.md`
> 目标包: `topoone/agent/` + `topoone/knowledge/`
> 位置: `next/backend/topoone/{agent,knowledge}/`
> 依赖: Phase 1 `core/` + Phase 2 `tools/` + Phase 3 `llm/`
> 代码量: 迁移约 4500 行 + 新建约 300 行

---

## 目录

1. [包结构总览](#1-包结构总览)
2. [逐文件规格: agent/](#2-逐文件规格-agent)
3. [逐文件规格: knowledge/](#3-逐文件规格-knowledge)
4. [与旧代码的映射关系](#4-与旧代码的映射关系)
5. [模块依赖关系图](#5-模块依赖关系图)
6. [测试规划](#6-测试规划)
7. [验证清单](#7-验证清单)

---

## 1. 包结构总览

```
topoone/agent/                       # 代理系统
├── __init__.py                      # AgentRuntime, RouterHarness, SubAgent 导出
├── runtime.py                       # AgentRuntime (plan→execute→observe 循环)
├── memory.py                        # AgentMemory (滑动窗口上下文管理)
├── sandbox.py                       # AgentSandbox + PathSandbox + RateLimiter + BudgetTracker
├── router.py                        # RouterHarness + RouteEntry + create_default_router
├── queue.py                         # AgentTaskManager + 全局队列
├── sub_agent.py                     # SubAgent (并行文件摘要)
├── skills/                          # 技能编排 (Phase 2 已建)
│   ├── __init__.py
│   ├── registry.py                  # @register_skill
│   └── builtin.py                   # 内建技能
├── toolkits/                        # Agent 工具适配层
│   ├── __init__.py
│   └── adapters.py                  # tools/builtin → AgentTool 包装
├── tool_calling/                    # 工具调用策略
│   ├── __init__.py                  # ToolCall, AgentChatResponse
│   ├── chat.py                      # agentic_chat() 入口
│   ├── strategy.py                  # NativeToolCallingStrategy + TextFallbackStrategy
│   └── fallback_extractors.py       # 文本格式工具调用解析
└── workflows/                       # 工作流定义
    ├── __init__.py
    ├── base.py                      # AgentWorkflow ABC + AgenticWorkflow ABC
    ├── overview.py                  # 架构概览生成
    ├── component_analyst.py         # 组件分析 (顺序)
    ├── agentic_component_analyst.py # 组件分析 (Agent 驱动)
    ├── pre_summary.py               # 文件预摘要
    └── pipeline.py                  # 流水线编排

topoone/knowledge/                   # 知识库
├── __init__.py
├── service.py                       # 知识文档 CRUD
├── graph.py                         # 知识图谱
├── dimensions.py                    # 维度系统 (lifecycle/techStack/abstraction/purpose)
└── config/                          # 内建维度标签
    └── tags.json
```

---

## 2. 逐文件规格: `agent/`

### 2.1 `agent/__init__.py`

```python
"""代理系统"""
from .runtime import AgentRuntime, AgentProgress, AgentStatus
from .memory import AgentMemory
from .sandbox import AgentSandbox
from .router import RouterHarness, RouteEntry, create_default_router
from .queue import AgentTaskManager, get_global_queue
from .sub_agent import SubAgent
```

---

### 2.2 `agent/runtime.py`

**源文件**: `backend-core/agent_workflow/runtime.py` (1206 行)
**变更**: 移除 `llm_adapter` 直接依赖(改为接收 `llm_chat_fn` 参数), 使用 Phase 2 `tools/` 的 ToolDef/ToolResult 替代旧 AgentTool/ToolResult

**类**: `AgentRuntime`

```python
class AgentRuntime:
    """代理运行时 - plan→execute→observe 循环"""

    def __init__(self, tools: ToolRegistry, sandbox: AgentSandbox,
                 memory: AgentMemory | None = None,
                 on_progress: ProgressCallback | None = None,
                 multi_db=None):
        """
        tools:      Phase 2 ToolRegistry (非旧 ToolRegistry)
        sandbox:    AgentSandbox
        memory:     AgentMemory (可选)
        on_progress: 进度回调
        multi_db:   MultiDBManager (用于保存日志)
        """

    # ─── 运行 ───

    async def run(self, workflow: AgentWorkflow, context: dict) -> WorkflowResult:
        """执行工作流 (自动判断 sequential / agentic)"""

    def cancel(self):
        """取消运行"""

    # ─── Sequential 路径 ───

    async def _run_sequential(self, workflow: AgentWorkflow, context: dict) -> WorkflowResult:
        """
        1. workflow.plan() → [AgentStep]
        2. 遍历每一步:
           - 从 tools/registry 获取工具
           - ToolExecutor.execute(step.tool, step.args, ctx)
           - 更新进度
        3. workflow.finalize(results) → WorkflowResult
        """

    # ─── Agentic 路径 ───

    async def _run_agentic(self, workflow: AgenticWorkflow, context: dict) -> WorkflowResult:
        """
        对每个 component:
        1. 构建 system prompt (含 context ingredient)
        2. agentic_chat(messages, tools_schema)
        3. 解析工具调用 → ToolExecutor.execute
        4. 循环直到完成
        5. workflow.finalize({"component_results": [...]})
        """

    # ─── 进度 ───

    @property
    def status(self) -> AgentStatus: ...
    @property
    def progress(self) -> AgentProgress: ...

    def _report(self, **kwargs):
        """更新进度并调用 on_progress 回调"""

class AgentStatus(Enum):
    IDLE, PLANNING, RUNNING, COMPLETED, PARTIAL, FAILED, CANCELLED

@dataclass
class AgentProgress:
    status: AgentStatus
    steps: list[StepProgress] = field(default_factory=list)
    step_current: int = 0
    step_total: int = 0
    message: str = ""
    weighted_progress: float = 0.0
    total_files: int = 0
    total_comps: int = 0
    done_files: int = 0
    done_comps: int = 0
```

**核心变更**:
- `self._tools` 从旧 `ToolRegistry` 改为 Phase 2 `topoone.tools.registry.ToolRegistry`
- `run()` 内部使用 `ToolExecutor` 执行工具, 而非直接调用 `AgentTool.execute()`
- `llm_adapter` 依赖移除: `_run_agentic` 接收 `llm_chat_fn` 作为 context 参数
- 进度回调类型与 Phase 1 `transport/event.py` 兼容

**依赖**: Phase 2 `tools/registry.py`, `tools/executor.py`; Phase 3 `llm/service.py`(通过参数传入); `agent/memory.py`, `agent/sandbox.py`, `agent/workflows/base.py`

---

### 2.3 `agent/memory.py`

**源文件**: `backend-core/agent_workflow/memory.py` (67 行)
**变更**: 无修改, 直接迁移

**类**: `AgentMemory`

```python
class AgentMemory:
    """代理记忆 - 滑动窗口上下文管理"""

    def __init__(self, max_context_chars: int = 40000): ...
    def put(self, key: str, value: Any): ...
    def get(self, key: str) -> Any: ...
    def get_all(self) -> dict[str, Any]: ...
    def format_context(self) -> str: ...
    def clear(self): ...
```

**依赖**: 无

---

### 2.4 `agent/sandbox.py`

**源文件**: `backend-core/agent_workflow/sandbox.py` (212 行)
**变更**: 无修改, 直接迁移

**类**: `AgentSandbox`, `PathSandbox`, `ContentGuard`, `RateLimiter`, `BudgetTracker`

```python
class PathSandbox:
    def __init__(self, project_root: str): ...
    def allow_read(self, path: str) -> bool: ...
    def allow_write(self, path: str) -> bool: ...
    def validate_read(self, path: str) -> str: ...
    def validate_write(self, path: str) -> str: ...

class ContentGuard:
    """内容安全守卫 - 屏蔽 shell 命令、危险代码"""
    @classmethod
    def sanitize(cls, text: str) -> str: ...
    @classmethod
    def is_safe(cls, text: str) -> bool: ...

class RateLimiter:
    """速率限制 - 并发 + 间隔 + 每秒请求数"""

class BudgetTracker:
    """预算追踪 - token 数 + 超时"""

class AgentSandbox:
    """代理沙箱 - 组合 PathSandbox + ContentGuard + RateLimiter + BudgetTracker"""
```

**依赖**: 无

---

### 2.5 `agent/router.py`

**源文件**: `backend-core/agent_workflow/router.py` (340 行)
**变更**: `create_default_router` 使用 Phase 2 的 `tools/builtin` 构建工具注册表, 依赖 `mcp/registry.py` 注入第三方工具

**类**: `RouterHarness`

```python
class RouterHarness:
    """路由编排器 - action → workflow 路由"""

    def __init__(self, project_root: str = "", max_concurrency: int = 3, multi_db=None):
        self._routes: dict[str, RouteEntry] = {}
        self._mcp_registry: MCPServerRegistry | None = None  # Phase 2 MCP

    def set_mcp_registry(self, mcp_registry: "MCPServerRegistry"):
        """注入 MCP Server 注册表 (用于注入第三方工具)"""

    def register(self, action: str, entry: RouteEntry): ...

    def dispatch(self, action: str, task_id: str, context: dict,
                 on_complete=None) -> str:
        """分发任务到 AgentTaskManager"""
        # 1. 查找 RouteEntry
        # 2. RouteEntry.tool_builder() → ToolRegistry
        # 3. 若有 MCP 注册表, 注入第三方工具
        # 4. AgentTaskManager.enqueue()

    def cancel(self, agent_id: str) -> bool: ...
    def get_progress(self, agent_id: str) -> dict | None: ...

    @property
    def routes(self) -> list[str]: ...

@dataclass
class RouteEntry:
    workflow_class: type
    tool_builder: callable     # (context) → ToolRegistry
    description: str = ""
    sandbox_builder: callable | None = None
    context_transformer: callable | None = None

def create_default_router(project_root, project_db, multi_db, task_id, ...) -> RouterHarness:
    """
    创建默认路由:
    - overview   → OverviewWorkflow
    - analyze_components → AgenticComponentAnalystWorkflow
    - presummary_files  → PreSummaryWorkflow
    - pipeline   → PipelineWorkflow
    """
```

**依赖**: Phase 2 `tools/registry.py`, `mcp/registry.py`; Phase 3 `llm/service.py`; `agent/workflows/*`, `agent/queue.py`

---

### 2.6 `agent/queue.py`

**源文件**: `backend-core/agent_workflow/agent_queue.py` (373 行)
**变更**: `enqueue` 内部使用 Phase 2 `tools/registry.ToolRegistry` 替代旧 `agent_workflow.tools.ToolRegistry`

**类**: `AgentTaskManager`

```python
class AgentTaskManager:
    """Agent 任务队列管理器"""

    def __init__(self, max_concurrency=3, ...): ...
    def enqueue(self, task_id, workflow, context, tools, sandbox,
                on_complete=None, multi_db=None) -> str: ...
    def get_progress(self, agent_id: str) -> dict | None: ...
    def cancel(self, agent_id: str) -> bool: ...
    def set_persist_path(self, path: str): ...

def get_global_queue(max_concurrency=3) -> AgentTaskManager: ...
```

**依赖**: `agent/runtime.py`, `agent/sandbox.py`, `agent/workflows/base.py`

---

### 2.7 `agent/sub_agent.py`

**源文件**: `backend-core/agent_workflow/sub_agent.py` (491 行)
**变更**: 使用 Phase 3 `topoone/llm/service.LLMService` 替代旧 `backend-core/llm_service.LLMService`

**类**: `SubAgent`

```python
class SubAgent:
    """子代理 - 并行文件摘要"""

    def __init__(self, multi_db, project_root="", model_id="",
                 project_db=None, task_id="", cancel_event=None): ...

    async def summarize_files(self, files, task_id, project_id, file_cache,
                              focus="", max_concurrent=1, force_refresh=False,
                              language="") -> SubAgentResult: ...
        """并行文件摘要: 读取 → 构建结构 → LLM 摘要"""

@dataclass
class SubAgentResult:
    files_processed: int
    cache_hits: int
    cache_misses: int
    summaries: list
    tokens_used: int
    tokens_saved: int
    failed: int = 0
```

**依赖**: Phase 3 `llm/service.py`; Phase 1 `core/db/manager.py`, `core/config/state.py`

---

### 2.8 `agent/toolkits/adapters.py`

**新建**: 将 Phase 2 `tools/builtin/*` 的工具包装为旧 `AgentTool` 接口(保持与旧 workflows 兼容)

```python
class AgentToolAdapter(AgentTool):
    """包装 ToolDef + handler 为 AgentTool ABC"""

    def __init__(self, tool_def: ToolDef, handler: callable):
        self.name = tool_def.name
        self.description = tool_def.description
        self._handler = handler
        self._tool_def = tool_def

    async def execute(self, **kwargs) -> ToolResult:
        ctx = {...}  # 从 AgentRuntime 传入的上下文
        return await self._handler(kwargs, ctx)

    def to_openai_schema(self) -> dict:
        return self._tool_def.to_openai_schema()

def wrap_registry(registry: ToolRegistry, context: dict) -> ToolRegistry:
    """包裹 tools/registry 中的所有工具为 AgentTool 兼容"""
    adapted = ToolRegistry()
    for tool in registry.list():
        handler = get_handler(tool.name)
        adapter = AgentToolAdapter(tool, handler)
        adapted.register(adapter)
    return adapted
```

**依赖**: Phase 2 `tools/`, `agent/workflows/base.py`

---

### 2.9 `agent/tool_calling/` — 工具调用策略

**源文件**: `backend-core/agent_workflow/tool_calling/` (全部)
**变更**: 使用 Phase 3 `llm/service.py` 替代旧 `llm_service.LLMService`

```python
# tool_calling/__init__.py
@dataclass
class ToolCall:
    name: str
    arguments: dict
    id: str | None = None

@dataclass
class AgentChatResponse:
    content: str
    tool_calls: list[ToolCall] | None = None
    usage: dict | None = None

# tool_calling/chat.py
async def agentic_chat(messages, tools=None, multi_db=None, model_id="",
                       strategy=None, temperature=0.3, max_tokens=None) -> AgentChatResponse:
    """统一入口 → strategy.chat()"""

# tool_calling/strategy.py
class ToolCallingStrategy(ABC):
    async def chat(self, messages, tools, multi_db, model_id, temperature, max_tokens) -> AgentChatResponse: ...

class NativeToolCallingStrategy(ToolCallingStrategy):
    """原生 function calling"""

class TextFallbackToolCallingStrategy(ToolCallingStrategy):
    """文本回退 (XML / [TOOL_CALL:] markers)"""

def create_strategy(multi_db=None, model_id="", preferred="") -> ToolCallingStrategy: ...

# tool_calling/fallback_extractors.py
def parse_qwen_xml(text: str) -> list[ToolCall]: ...
def parse_tool_call_marker(text: str) -> list[ToolCall]: ...
def extract_fallback_tool_calls(text: str) -> list[ToolCall]: ...
def extract_fallback_content(text: str) -> str: ...
def clean_model_content(text: str) -> str: ...
```

**依赖**: Phase 3 `llm/service.py` (LLMService)

---

### 2.10 `agent/workflows/` — 工作流定义

**源文件**: `backend-core/agent_workflow/workflows/` (全部)
**变更**: 无修改, 直接迁移

**类层次**:
```
AgentWorkflow (ABC)        — base.py
  ├── _plan() → [AgentStep]     (抽象)
  ├── _finalize(results) → WorkflowResult  (抽象)
  └── agent_config → dict

AgenticWorkflow (ABC)      — base.py  (extends AgentWorkflow)
  ├── _build_system_prompt(context) → str  (抽象)
  └── _build_fallback(context) → str       (抽象, 降级用)

OverviewWorkflow           — overview.py
  ├── plan() → [Generate Overview]
  └── finalize() → 保存架构概览文档

ComponentAnalystWorkflow   — component_analyst.py
  └── (batch 模式: 定义步骤, 执行分析)

AgenticComponentAnalystWorkflow — agentic_component_analyst.py
  └── (ReAct 模式: 多轮工具调用)

PreSummaryWorkflow         — pre_summary.py
  └── (批量文件摘要)

PipelineWorkflow           — pipeline.py
  └── (编排: 项目摘要 → 预摘要 → 组件分析 → 架构概览)
```

**依赖**: `agent/sandbox.py`, `agent/toolkits/adapters.py`, Phase 3 `llm/context/`

---

## 3. 逐文件规格: `knowledge/`

### 3.1 `knowledge/__init__.py`

```python
"""知识库服务"""
from .service import KnowledgeService
from .graph import KnowledgeGraph
from .dimensions import KnowledgeDimensions
```

---

### 3.2 `knowledge/service.py`

**源文件**: `backend-core/core_service.py` 中 `register_knowledge_methods` 部分 (约 300 行)
**变更**: 从 core_service.py 提取为独立服务

**类**: `KnowledgeService`

```python
class KnowledgeService:
    """知识文档 CRUD + 检索"""

    def __init__(self, multi_db: MultiDBManager):
        self.multi_db = multi_db

    # ─── CRUD ───

    def list_docs(self, project_id: str = None, category: str = None,
                  page: int = 1, page_size: int = 20) -> dict: ...
    def create_doc(self, title: str, content: str, project_id: str = None,
                   metadata: dict = None) -> dict: ...
    def get_doc(self, doc_id: str) -> dict | None: ...
    def update_doc(self, doc_id: str, **kwargs) -> dict: ...
    def delete_doc(self, doc_id: str) -> dict: ...

    # ─── 检索 ───

    def search(self, query: str, project_id: str = None,
               dimensions: dict = None) -> list[dict]: ...
        """全文搜索 + 维度过滤"""

    def get_graph(self, project_id: str = None) -> dict: ...
        """获取知识图谱 (doc 间关联)"""

    def get_dimensions(self) -> dict: ...
        """获取维度定义 + 标签"""

    def register(self, server: "ZMQServer"):
        """注册 knowledge.* RPC"""
```

**依赖**: `topoone/core/db/manager.py` (MultiDBManager)

---

### 3.3 `knowledge/graph.py`

**新建**: 知识图谱关联

```python
class KnowledgeGraph:
    """知识图谱 - 文档间关联"""

    def __init__(self, multi_db): ...

    def get_graph(self, project_id=None) -> dict:
        """获取全部节点+边"""
        # 节点: 知识文档
        # 边: 引用关系 (doc → doc)

    def add_link(self, source_id: str, target_id: str, rel_type: str = "reference"): ...
    def remove_link(self, source_id: str, target_id: str): ...
```

**依赖**: `core/db/manager.py`

---

### 3.4 `knowledge/dimensions.py`

**源文件**: 前端 `src/utils/mock.ts` 中的 `knowledgeDimensions` 常量 + 后端配置
**变更**: 从 mock 数据变为后端配置

```python
class KnowledgeDimensions:
    """知识库维度系统"""

    DEFAULT_DIMENSIONS = {
        "lifecycle": ["design", "development", "review", "deprecated"],
        "techStack": ["python", "javascript", "java", "go", "rust", "cpp"],
        "abstraction": ["architecture", "design-pattern", "implementation", "configuration"],
        "purpose": ["reference", "tutorial", "api-doc", "best-practice"],
    }

    def __init__(self, multi_db): ...
    def get_dimensions(self) -> dict: ...
    def update_tags(self, dimension: str, tags: list[str]): ...
    def add_tag(self, dimension: str, tag: str): ...
    def remove_tag(self, dimension: str, tag: str): ...
```

**依赖**: `core/db/manager.py` (可选, 降级使用默认常量)

---

## 4. 与旧代码的映射关系

### agent/ — 迁移映射

| 目标文件 | 源文件 | 行数 | 变更 |
|----------|--------|------|------|
| `agent/runtime.py` | `agent_workflow/runtime.py` | ~1100 | ToolRegistry → Phase 2 tools/ |
| `agent/memory.py` | `agent_workflow/memory.py` | ~67 | 直接迁移 |
| `agent/sandbox.py` | `agent_workflow/sandbox.py` | ~212 | 直接迁移 |
| `agent/router.py` | `agent_workflow/router.py` | ~340 | +MCP 注入 |
| `agent/queue.py` | `agent_workflow/agent_queue.py` | ~373 | ToolRegistry 适配 |
| `agent/sub_agent.py` | `agent_workflow/sub_agent.py` | ~491 | LLMService 路径 |
| `agent/toolkits/adapters.py` | 新建 | ~80 | 包装 Phase 2 tools |
| `agent/tool_calling/__init__.py` | `agent_workflow/tool_calling/__init__.py` | ~41 | 直接迁移 |
| `agent/tool_calling/chat.py` | `agent_workflow/tool_calling/chat.py` | ~44 | 直接迁移 |
| `agent/tool_calling/strategy.py` | `agent_workflow/tool_calling/strategy.py` | ~373 | LLMService 路径 |
| `agent/tool_calling/fallback_extractors.py` | `.../fallback_extractors.py` | ~153 | 直接迁移 |
| `agent/workflows/base.py` | `agent_workflow/workflows/base.py` | ~78 | 直接迁移 |
| `agent/workflows/overview.py` | `agent_workflow/workflows/overview.py` | ~500 | 直接迁移 |
| `agent/workflows/component_analyst.py` | `.../component_analyst.py` | ~300 | 直接迁移 |
| `agent/workflows/agentic_component_analyst.py` | `.../agentic_component_analyst.py` | ~400 | 直接迁移 |
| `agent/workflows/pre_summary.py` | `.../pre_summary.py` | ~300 | 直接迁移 |
| `agent/workflows/pipeline.py` | `.../pipeline.py` | ~400 | 直接迁移 |

### knowledge/ — 迁移映射

| 目标文件 | 源文件 | 行数 | 变更 |
|----------|--------|------|------|
| `knowledge/service.py` | `core_service.py:register_knowledge_methods` | ~300 | 提取独立 |
| `knowledge/graph.py` | 新建 | ~60 | 知识图谱 |
| `knowledge/dimensions.py` | 新建(参考前端 mock.ts) | ~60 | 维度系统 |

**总计**: 迁移 ~4500 行, 新建 ~200 行

---

## 5. 模块依赖关系图

```
agent/                              knowledge/
  │                                    │
  ├── memory.py  ← 无依赖               ├── service.py → core/db
  ├── sandbox.py ← 无依赖               ├── graph.py → core/db
  │                                    └── dimensions.py → core/db
  ├── toolkits/adapters.py → tools/
  │
  ├── tool_calling/ → Phase 3 llm/service.py
  │
  ├── workflows/ → agent/sandbox, toolkits, Phase 3 llm/context
  │
  ├── sub_agent.py → llm/service.py, core/db
  │
  ├── runtime.py → tools/, memory, sandbox, workflows
  │
  ├── queue.py → runtime, sandbox, workflows, tools/
  │
  └── router.py → queue, workflows, tools/, Phase 2 mcp/ (可选)
```

---

## 6. 测试规划

```
tests/
├── agent/
│   ├── test_runtime.py           # AgentRuntime 顺序 + agentic 模式
│   ├── test_memory.py            # 滑动窗口
│   ├── test_sandbox.py           # 路径 + 内容 + 速率 + 预算
│   ├── test_router.py            # dispatch → queue → complete
│   ├── test_queue.py             # enqueue / cancel / progress
│   ├── test_sub_agent.py         # 文件摘要
│   ├── test_tool_calling.py      # agentic_chat + 策略选择
│   ├── test_fallback_extractors.py # XML / marker 解析
│   └── workflows/
│       ├── test_overview.py
│       ├── test_component_analyst.py
│       └── test_pipeline.py
│
├── knowledge/
│   ├── test_service.py           # CRUD + 搜索
│   ├── test_graph.py             # 知识图谱
│   └── test_dimensions.py        # 维度系统
```

### 关键测试

```python
async def test_sequential_workflow():
    """顺序工作流: plan → execute steps → finalize"""
    runtime = AgentRuntime(tools, sandbox)
    result = await runtime.run(workflow, context)
    assert result.success

async def test_agentic_chat_mock():
    """agentic chat with mock provider"""
    response = await agentic_chat(
        messages=[{"role": "user", "content": "hello"}],
        multi_db=mock_db,
        model_id="test-model",
    )
    assert isinstance(response.content, str)

def test_knowledge_crud():
    """知识文档 CRUD"""
    svc = KnowledgeService(multi_db)
    doc = svc.create_doc(title="Test", content="# Hello")
    assert doc["id"] is not None
    fetched = svc.get_doc(doc["id"])
    assert fetched["title"] == "Test"
    svc.delete_doc(doc["id"])
```

---

## 7. 验证清单

```bash
# 1. 包导入
python -c "
from topoone.agent import AgentRuntime, RouterHarness, SubAgent
from topoone.agent.memory import AgentMemory
from topoone.agent.sandbox import AgentSandbox
from topoone.agent.workflows import OverviewWorkflow
from topoone.agent.tool_calling import agentic_chat
print('agent OK')
from topoone.knowledge import KnowledgeService, KnowledgeGraph
print('knowledge OK')
"

# 2. RouterHarness 注册
python -c "
from topoone.agent import RouterHarness, create_default_router
router = create_default_router('/tmp', None, None, 'test-task')
print(f'Routes: {router.routes}')
assert len(router.routes) > 0
"

# 3. 全部测试
cd next/backend && python -m pytest tests/agent/ tests/knowledge/ -v
```

**Phase 4 完成标志**:
1. AgentRuntime 可运行顺序/agentic 工作流
2. RouterHarness 4 条路由注册正常
3. AgentTaskManager 队列管理 + 取消正常
4. SubAgent 文件摘要工作正常
5. 知识库 CRUD + 搜索 + 图 + 维度完整
6. 工具调用策略 (native + text fallback) 正常
7. 全部 pytest 测试通过
