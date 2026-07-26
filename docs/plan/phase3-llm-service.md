# Phase 3: LLM 服务层详细设计

> 文件名: `docs/plan/phase3-llm-service.md`
> 目标包: `topoone/llm/`
> 位置: `next/backend/topoone/llm/`
> 依赖: Phase 1 `core/` + Phase 2 `tools/`
> 代码量: 迁移约 1700 行 + 适应约 200 行

---

## 1. 包结构总览

```
topoone/llm/
├── __init__.py                # LLMService 导出
├── service.py                 # LLMService (核心: 会话 + 流式聊天 + 同步聊天)
├── types.py                   # ChatRequest, ChatResponse, ToolCall 等消息类型
├── usage.py                   # 用量限制检查 + 记录
├── call_log.py                # 调用日志记录
│
├── providers/                 # LLM 提供商 (从旧 providers/ 迁移, 无变化)
│   ├── __init__.py            # ProviderRegistry
│   ├── base.py                # BaseLLMProvider
│   ├── ollama.py              # OllamaProvider
│   └── openai_compat.py       # OpenAICompatProvider + 8 个子类
│
├── session/                   # 会话管理 (从旧 llm_service.py 提取)
│   ├── __init__.py
│   ├── store.py               # SessionStore (list/create/delete/messages)
│   └── analysis.py            # AnalysisSessionStore
│
├── context/                   # 上下文装配 (从旧 context/ 迁移, 无变化)
│   ├── __init__.py
│   ├── assembly.py            # ContextAssembler + CollectContext
│   ├── ingredient.py          # ContextIngredient ABC
│   ├── registry.py            # 工厂 + 单例
│   ├── recipes/               # 5 个配方
│   │   └── __init__.py
│   └── ingredients/           # 12 个配料 (1-80 行每个)
│       ├── __init__.py
│       ├── community_info.py
│       ├── file_list.py
│       ├── directory_tree.py
│       ├── exported_symbols.py
│       ├── file_centrality.py
│       ├── edge_relations.py
│       ├── parent_chain.py
│       ├── import_external.py
│       ├── tech_stack.py
│       ├── test_coverage.py
│       ├── entry_points.py
│       └── file_metadata.py
│
├── prompt_manager.py          # 提示词模板管理 (从旧迁移, 无变化)
└── instruction_manager.py     # 用户指令注入 (从旧迁移, 无变化)
```

---

## 2. 逐文件规格

### 2.1 `llm/__init__.py`

```python
"""LLM 服务层"""
from .service import LLMService
from .types import ChatRequest, ChatResponse, ToolCall, ChatMode
from .providers import get_provider, list_providers, register_all_providers
```

---

### 2.2 `llm/types.py`

**新建**: 统一的聊天消息类型（替代散布的 dict 类型）

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

class ChatMode(str, Enum):
    CHAT = "chat"
    TOOLS = "tools"
    STRUCTURED = "structured"

@dataclass
class ChatMessage:
    role: str                           # system | user | assistant | tool
    content: str
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None

@dataclass
class ChatRequest:
    """流式聊天请求"""
    session_id: str
    model_id: str
    messages: list[ChatMessage]
    mode: ChatMode = ChatMode.CHAT
    tools: list[dict] | None = None     # OpenAI tool schema
    output_schema: dict | None = None   # JSON Schema
    template_id: str | None = None
    max_tokens: int | None = None
    extra_meta: dict = field(default_factory=dict)

@dataclass
class ChatChunk:
    """流式块"""
    request_id: str
    content: str
    done: bool = False
    tool_calls: list[dict] | None = None
    usage: dict | None = None
    error: str | None = None

@dataclass
class ChatResponse:
    """同步聊天响应"""
    content: str
    tool_calls: list[dict] | None = None
    usage: dict | None = None
    finish_reason: str = ""
    error: str | None = None

@dataclass
class ToolCall:
    name: str
    arguments: dict
    id: str | None = None
```

---

### 2.3 `llm/service.py`

**源文件**: `backend-core/llm_service.py` (1256 行)
**变更**: 拆分出 session/usage/call_log 子模块, 用回调替代 ZMQ 直连

**类**: `LLMService`

```python
class LLMService:
    """LLM 聊天服务 - 会话管理 + 流式聊天 + 同步聊天 + 工具调用"""

    def __init__(self, multi_db, publish_callback=None):
        """
        multi_db: MultiDBManager
        publish_callback: Optional Callable(topic, event_type, data)
                         用于发布 LLM 流式事件（由上层注入）
        """

    # ─── 流式聊天 ───

    async def streaming_chat(self, request: ChatRequest) -> str:
        """
        发起流式聊天:
        1. 检查用量限制
        2. 解析 model config
        3. 启动 _execute_streaming 异步任务
        4. 返回 request_id
        """

    def abort_chat(self, request_id: str):
        """取消进行中的流式请求"""

    async def _execute_streaming(self, request_id, request, model):
        """
        内部流式执行循环:
        1. 工具调用循环 (最多 5 轮)
        2. HTTP streaming via provider
        3. 通过 publish_callback 发送 ChatChunk
        4. 结构化输出验证(若需要) + 重试
        5. 保存消息到 session store
        6. 记录调用日志
        """

    # ─── 同步聊天 ───

    async def sync_chat(
        self,
        messages: list[ChatMessage],
        model_id: str,
        max_tokens: int | None = None,
    ) -> str:
        """非流式同步聊天（供 Agent Runtime 使用）"""

    def sync_chat_sync(
        self,
        messages: list[dict],
        model_id: str,
        max_tokens: int | None = None,
    ) -> str:
        """同步包装（在 executor 线程中运行）"""

    # ─── 会话管理 (委托给 SessionStore) ───

    def list_sessions(self, module_type=None, project_id=None, status="active") -> list[dict]: ...
    def create_session(self, module_type, title, project_id=None, metadata=None) -> dict: ...
    def delete_session(self, session_id: str) -> dict: ...
    def get_messages(self, session_id, limit=100, offset=0) -> list[dict]: ...
    def add_message(self, session_id, role, content, token_count=None, metadata=None) -> dict: ...
    def delete_message(self, message_id: str) -> dict: ...

    # ─── 注册到 ZMQServer ───

    def register(self, server: "ZMQServer"):
        """注册 session.* llm.* analysisSession.* promptTemplate.* RPC"""
```

**依赖**:
- `topoone/core/db/manager.py` (MultiDBManager)
- `topoone/core/db/connection.py` (SQLiteContext)
- `topoone/llm/providers/` (get_provider)
- `topoone/llm/session/store.py` (SessionStore)
- `topoone/llm/usage.py` (UsageTracker)
- `topoone/llm/call_log.py` (CallLogger)
- `topoone/llm/prompt_manager.py` (PromptManager)
- `topoone/llm/instruction_manager.py` (InstructionManager)
- 第三方: `requests`

---

### 2.4 `llm/providers/` — LLM 提供商

从 `backend-core/providers/` 直接迁移, **无变更**:

```
topoone/llm/providers/
├── __init__.py         # register_provider, get_provider, list_providers, register_all
├── base.py             # BaseLLMProvider ABC (chat_stream, chat_sync)
├── ollama.py           # OllamaProvider (supports_tools=True)
└── openai_compat.py    # OpenAICompatProvider + 8 子类
```

**类继承关系**:
```
BaseLLMProvider (ABC)
  ├── OllamaProvider              # Ollama API (原生)
  ├── OpenAICompatProvider        # OpenAI API (兼容)
  │     ├── LmStudioProvider
  │     ├── DeepSeekProvider
  │     ├── MiniMaxCNProvider
  │     ├── MiniMaxGlobalProvider
  │     ├── OpenRouterProvider
  │     ├── CustomLocalProvider
  │     └── CustomCloudProvider
  └── CustomLocalProvider         # 自定义本地
```

---

### 2.5 `llm/session/store.py`

**源文件**: 从 `backend-core/llm_service.py` 提取 session CRUD 方法

**类**: `SessionStore`

```python
class SessionStore:
    """LLM 会话持久化管理 - llm_sessions + llm_messages 表 CRUD"""

    def __init__(self, multi_db): ...

    def list(self, module_type=None, project_id=None, status="active") -> list[dict]: ...
    def create(self, module_type, title, project_id=None, metadata=None) -> dict: ...
    def delete(self, session_id: str): ...
    def get_messages(self, session_id, limit=100, offset=0) -> list[dict]: ...
    def add_message(self, session_id, role, content, token_count=None, metadata=None) -> dict: ...
    def delete_message(self, message_id: str): ...
    def update_metadata(self, session_id, metadata: dict): ...
    def clear_all_sessions(self): ...
```

**依赖**: `topoone/core/db/manager.py` (MultiDBManager)

---

### 2.6 `llm/session/analysis.py`

**源文件**: 从 `backend-core/llm_service.py` 提取 analysis session 方法

**类**: `AnalysisSessionStore`

```python
class AnalysisSessionStore:
    """分析会话管理 - analysis_sessions 表 CRUD"""

    ANALYSIS_SESSION_PREFIXES = ("comm-", "pipeline-", "ai-")

    def __init__(self, multi_db): ...

    def list(self, project_id=None) -> list[dict]: ...
    def create(self, project_id, session_type, metadata=None) -> dict: ...
    def delete(self, session_id: str): ...
```

**依赖**: `topoone/core/db/manager.py` (MultiDBManager)

---

### 2.7 `llm/usage.py`

**源文件**: 从 `backend-core/llm_service.py` 提取用量限制 + 记录方法

**类**: `UsageTracker`

```python
class UsageTracker:
    """LLM 用量追踪 - model_daily_usage 表"""

    def __init__(self, multi_db): ...

    def check_limits(self, model_id: str):
        """检查 daily 用量限制 (max_requests_per_day, max_tokens_per_day)"""

    def record_usage(self, model_id: str, token_data: dict):
        """记录用量 (UPSERT model_daily_usage)"""

    def get_usage_stats(self, model_id=None, start_date=None, end_date=None) -> list[dict]: ...
```

**依赖**: `topoone/core/db/manager.py` (MultiDBManager)

---

### 2.8 `llm/call_log.py`

**源文件**: 从 `backend-core/llm_service.py` 提取调用日志方法

**类**: `CallLogger`

```python
class CallLogger:
    """LLM 调用日志 - llm_call_logs + report_interaction_log 表"""

    def __init__(self, multi_db): ...

    def save_call_log(self, session_id, messages, content, model, request_id, **kwargs):
        """保存调用日志到 llm_call_logs"""

    def save_interaction_log(self, session_id, request_id, model, mode, status, latency_ms, meta):
        """保存交互日志到 report_interaction_log"""
```

**依赖**: `topoone/core/db/manager.py` (MultiDBManager)

---

### 2.9 `llm/prompt_manager.py`

**源文件**: `backend-core/prompt_manager.py` (467 行)
**变更**: 无修改, 直接迁移

**类**: `PromptManager`

```python
class PromptManager:
    """提示词模板管理 - llm_prompt_templates 表 CRUD + 变量渲染"""

    def __init__(self, multi_db): ...
    def list_templates(self, mode, module_type, category, locale) -> list[dict]: ...
    def get_template(self, template_id, locale) -> dict | None: ...
    def create_template(self, name, mode, module_type, category, locale, **content) -> dict: ...
    def update_template(self, template_id, **kwargs) -> dict: ...
    def delete_template(self, template_id) -> dict: ...
    def render(self, template_id, variables, locale) -> dict: ...
    def restore_defaults(self, locale=None): ...
    def get_language_instruction(self, locale="") -> str: ...
```

**依赖**: `topoone/core/db/manager.py` (MultiDBManager), 第三方: `json`

---

### 2.10 `llm/instruction_manager.py`

**源文件**: `backend-core/instruction_manager.py` (163 行)
**变更**: 无修改, 直接迁移

**类**: `InstructionManager`

```python
class InstructionManager:
    """用户自定义指令注入 - 在 chat 时注入到消息列表"""

    DEFAULT_INSTRUCTIONS = [...]

    def __init__(self, store=None): ...

    def inject(self, messages: list[dict], project_id="", scope="all") -> list[dict]:
        """按优先级注入指令到消息列表"""
        # prepend: 添加到 system 前
        # append: 添加到 system 后
        # replace: 替换 system

    def add_instruction(self, text, scope="all", priority="append"): ...
    def clear_runtime_instructions(self): ...
```

**依赖**: 无

---

### 2.11 `llm/context/` — 上下文装配系统

**源文件**: `backend-core/context/assembly.py`, `ingredient.py`, `registry.py`, `recipes/`, `ingredients/`
**变更**: 无修改, 整体迁移

**类**: `ContextAssembler`

```python
class ContextAssembler:
    """上下文装配器 - 按配方组合 LLM 上下文"""

    def register(self, ing: ContextIngredient): ...
    def assemble(self, recipe: list[str], ctx: CollectContext) -> str: ...

@dataclass
class CollectContext:
    """上下文收集器 - 装配时注入的数据"""
    db: Any                           # project_db
    task_id: str
    project_root: str
    comm_id: str = ""
    file_paths: set = field(default_factory=set)
    fp_map: dict = field(default_factory=dict)
    edge_list: list = field(default_factory=list)
    all_fp_map: dict = field(default_factory=dict)
    existing_results: dict = field(default_factory=dict)
    file_path: str = ""

class ContextIngredient(ABC):
    """配料抽象基类"""
    name: str = ""
    def collect(self, ctx: CollectContext) -> Any: ...
    def format(self, data: Any) -> str: ...
```

**5 个配方**:

| 配方名 | 使用的配料 |
|--------|-----------|
| `RECIPE_COMPONENT_ANALYSIS` | community_info, file_list, directory_tree, exported_symbols, file_centrality, edge_relations, parent_chain, import_external |
| `RECIPE_COMPONENT_ANALYSIS_AGENTIC` | community_info, directory_tree, exported_symbols, edge_relations |
| `RECIPE_ARCH_COMMUNITY` | community_info, file_list, directory_tree, exported_symbols, file_centrality, edge_relations |
| `RECIPE_ARCH_OVERVIEW` | community_info, edge_relations |
| `RECIPE_FILE_SUMMARY` | file_metadata |

**12 个配料**: community_info, file_list, directory_tree, exported_symbols, file_centrality, edge_relations, parent_chain, import_external, tech_stack, test_coverage, entry_points, file_metadata

**依赖**: `topoone/core/db/connection.py` (SQLiteContext, 各 ingredient collect 方法需要)

---

## 3. 与旧代码的映射关系

| 目标文件 | 源文件 | 行数 | 变更类型 |
|----------|--------|------|----------|
| `llm/types.py` | 新建 | ~100 | 从散布的 dict 类型集中定义 |
| `llm/service.py` | `llm_service.py:41-931` | ~700 | 拆分出 session/usage/call_log |
| `llm/session/store.py` | `llm_service.py` 提取 | ~200 | 从 LLMService 提取 |
| `llm/session/analysis.py` | `llm_service.py` 提取 | ~80 | 从 LLMService 提取 |
| `llm/usage.py` | `llm_service.py` 提取 | ~80 | 从 LLMService 提取 |
| `llm/call_log.py` | `llm_service.py` 提取 | ~100 | 从 LLMService 提取 |
| `llm/providers/` | `providers/` | ~540 | 直接迁移 |
| `llm/prompt_manager.py` | `prompt_manager.py` | ~467 | 直接迁移 |
| `llm/instruction_manager.py` | `instruction_manager.py` | ~163 | 直接迁移 |
| `llm/context/` | `context/` | ~400 | 直接迁移 |

**总计**: 迁移 ~1900 行, 新建 ~100 行

---

## 4. 模块依赖关系图

```
llm/types.py                      ← 无依赖
  │
llm/providers/                    → types.py, 第三方 requests
  │
llm/prompt_manager.py             → core/db/manager.py
llm/instruction_manager.py        ← 无依赖
  │
llm/session/store.py              → core/db/manager.py, types.py
llm/session/analysis.py           → core/db/manager.py
llm/usage.py                      → core/db/manager.py
llm/call_log.py                   → core/db/manager.py
  │
llm/context/                      → core/db/connection.py (ingredients)
  │
llm/service.py                    → core/db/manager.py, types.py
                                    → providers/, session/, usage/, call_log/
                                    → prompt_manager.py, instruction_manager.py
                                    → context/ (可选)
```

**关键依赖**: 全部依赖 Phase 1 `core/db/manager.py` (MultiDBManager)

---

## 5. Phase 3 不移入的内容

| 功能 | 归属 | 说明 |
|------|------|------|
| Agent 工作流 | Phase 4 `topoone/agent/` | 使用 LLMService，但不属于 LLM 层 |
| ToolCallingStrategy | Phase 4 `topoone/agent/` | 工具调用策略使用 tools/ 注册表 |
| LLM Adapter | Phase 4 `topoone/agent/` | create_llm_chat_fn 包装 |
| `llm.chat` / `llm.abortChat` RPC | Phase 4 `topoone/agent/` | 由 Agent 层注册到 ZMQ |
| Settings RPC | Phase 4 `topoone/llm/` 或独立 | model_configs CRUD |

---

## 6. 测试规划

```
tests/
├── llm/
│   ├── test_types.py               # ChatRequest/ChatResponse 序列化
│   ├── test_session.py             # SessionStore CRUD
│   ├── test_usage.py               # UsageTracker
│   ├── test_call_log.py            # CallLogger
│   ├── test_providers.py           # Provider registry + mock
│   ├── test_prompt_manager.py      # 模板 CRUD + 渲染
│   ├── test_instruction_manager.py # 指令注入
│   └── test_service.py             # LLMService mock 测试
│
├── context/
│   ├── test_assembly.py            # ContextAssembler
│   ├── test_ingredients.py         # 12 个配料各自测试
│   └── test_registry.py            # get_assembler 单例
```

### 关键测试

```python
async def test_streaming_chat():
    """LLMService 流式聊天 (mock provider)"""
    service = LLMService(mock_multi_db, publish_callback=mock_callback)
    req_id = await service.streaming_chat(request)
    assert req_id is not None
    # 验证 publish_callback 被调用 (含 ChatChunk)
    assert mock_callback.called

async def test_sync_chat():
    """同步聊天"""
    service = LLMService(mock_multi_db)
    content = await service.sync_chat(messages, "test-model")
    assert isinstance(content, str)

async def test_session_crud():
    """会话 CRUD"""
    store = SessionStore(mock_multi_db)
    session = store.create("chat", "Test")
    assert session["id"] is not None
    sessions = store.list()
    assert len(sessions) > 0
    store.delete(session["id"])

def test_instruction_inject():
    """指令注入"""
    mgr = InstructionManager()
    msgs = [{"role": "system", "content": "You are a helpful assistant."}]
    injected = mgr.inject(msgs, scope="all")
    assert len(injected) > 1
```

---

## 7. 验证清单

```bash
# 1. 包导入
python -c "
from topoone.llm import LLMService
from topoone.llm.types import ChatRequest, ChatResponse, ChatMessage
from topoone.llm.providers import get_provider, list_providers
from topoone.llm.prompt_manager import PromptManager
from topoone.llm.context import get_assembler
print('All LLM imports OK')
"

# 2. Provider 注册
python -c "
from topoone.llm.providers import list_providers, register_all_providers
register_all_providers()
providers = list_providers()
print(f'{len(providers)} providers registered: {providers}')
"

# 3. 上下文装配
python -c "
from topoone.llm.context import get_assembler
from topoone.llm.context.recipes import RECIPE_ARCH_OVERVIEW
assembler = get_assembler()
print(f'Assembler ready, {len(RECIPE_ARCH_OVERVIEW)} ingredients in ARCH_OVERVIEW recipe')
"

# 4. 全部测试
cd next/backend && python -m pytest tests/llm/ tests/context/ -v
```

**Phase 3 完成标志**:
1. 全部 Python 导入通过
2. LLMService 可发起流式/同步聊天 (mock provider)
3. 8 个 provider 全部注册
4. 会话 CRUD + 用量追踪 + 调用日志完整
5. 上下文装配 12 个配料 + 5 个配方工作正常
6. 全部 pytest 测试通过
