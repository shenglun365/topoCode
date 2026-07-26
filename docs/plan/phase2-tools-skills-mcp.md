# Phase 2: 工具/Skills/MCP 管理层详细设计

> 文件名: `docs/plan/phase2-tools-skills-mcp.md`
> 目标包: `topoone/tools/` + `topoone/mcp/` + `topoone/agent/skills/`
> 位置: `next/backend/topoone/{tools,mcp,agent/skills}/`
> 依赖: Phase 1 `core/`（数据存取层）
> 代码量: 约 2000 行（新写） + 迁移约 1500 行

---

## 目录

1. [设计目标与原则](#1-设计目标与原则)
2. [包结构总览](#2-包结构总览)
3. [逐文件规格: tools/](#3-逐文件规格-tools)
4. [逐文件规格: mcp/](#4-逐文件规格-mcp)
5. [逐文件规格: agent/skills/](#5-逐文件规格-agentskills)
6. [与旧代码的映射关系](#6-与旧代码的映射关系)
7. [模块依赖关系图](#7-模块依赖关系图)
8. [MCP 协议规格](#8-mcp-协议规格)
9. [测试规划](#9-测试规划)
10. [验证清单](#10-验证清单)

---

## 1. 设计目标与原则

### 目标

1. **统一工具注册表**: Agent 系统和 Coding Agent 共用一套工具定义，消除现有 `tools.py` + `toolkits/` + `tool_calling/` 三处定义的混乱
2. **MCP Server**: 将内建工具暴露为标准 MCP 协议，使第三方 LLM 应用可发现和调用
3. **MCP Client**: 发现并调用第三方 MCP Server，扩展系统能力
4. **技能编排**: 工具的组合与编排层，连接工具注册表和工作流系统

### 原则

| 原则 | 说明 |
|------|------|
| **Tools 零 Agent 依赖** | `topoone/tools/` 不依赖 `topoone/agent/` 或 `topoone/llm/` |
| **MCP 零业务依赖** | `topoone/mcp/` 只依赖 stdio/TCP + 标准 MCP 协议，不依赖任何业务模块 |
| **Skills 薄层** | `agent/skills/` 只做注册 + 编排，不含工作流执行逻辑 |
| **Schema 驱动** | 所有工具、参数、结果通过 pydantic/dataclass schema 定义 |

---

## 2. 包结构总览

```
topoone/
├── tools/                           # 统一工具管理（零 Agent 依赖）
│   ├── __init__.py                  # 导出 ToolRegistry 单例
│   ├── schema.py                    # ToolDef, ToolParam, ToolResult 标准 schema
│   ├── registry.py                  # 全局工具注册表
│   ├── executor.py                  # 工具执行器（参数校验、超时、沙箱）
│   └── builtin/                     # 内建工具集合
│       ├── __init__.py
│       ├── file_tools.py            # read_file, search_content, summarize_file
│       ├── symbol_tools.py          # get_symbol_detail, search_symbols, get_symbol_code
│       ├── graph_tools.py           # get_community_subgraph, get_call_chain, get_ast_node
│       ├── edge_tools.py            # get_edge_detail
│       └── knowledge_tools.py       # search_knowledge, get_document（预留）
│
├── mcp/                             # MCP Server + Client（零业务依赖）
│   ├── __init__.py
│   ├── schema.py                    # MCP JSON-RPC 消息类型
│   ├── server.py                    # MCP Server: 将 tools/ 注册的工具暴露
│   ├── client.py                    # MCP Client: 连接第三方 MCP Server
│   ├── transport.py                 # stdio / TCP transport 抽象
│   └── registry.py                  # 第三方 MCP Server 配置管理
│
└── agent/
    ├── ...                          # Phase 4
    └── skills/                      # 技能编排（薄层）
        ├── __init__.py
        ├── schema.py                # SkillDef, SkillStep
        ├── registry.py              # @register_skill 装饰器 + DB 同步
        └── builtin.py               # 内建技能定义（从 agent_workflow 迁移）
```

---

## 3. 逐文件规格: `tools/`

### 3.1 `tools/__init__.py`

```python
"""统一工具管理 - 零 Agent/LLM 依赖"""
from .schema import ToolDef, ToolParam, ToolResult, ToolStatus
from .registry import ToolRegistry
from .executor import ToolExecutor
```

---

### 3.2 `tools/schema.py`

**新建**: 工具定义的标准 schema

```python
from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum

class ToolParamType(Enum):
    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"

@dataclass
class ToolParam:
    """工具参数定义"""
    name: str
    type: ToolParamType
    description: str = ""
    required: bool = False
    default: Any = None
    enum: list[str] | None = None     # 可选枚举值

@dataclass
class ToolDef:
    """工具定义 - 纯数据描述"""
    name: str
    description: str
    parameters: list[ToolParam]
    category: str = "general"         # io / query / graph / knowledge
    llm_visible: bool = True          # 是否对 LLM 可见
    version: str = "1.0"
    
    def to_openai_schema(self) -> dict:
        """转为 OpenAI function calling schema"""
    
    def to_mcp_schema(self) -> dict:
        """转为 MCP 工具 schema"""

@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    data: Any = None
    error: str | None = None
    tokens_used: int = 0
    metadata: dict = field(default_factory=dict)
    
    @classmethod
    def ok(cls, data=None, tokens_used=0, **metadata) -> "ToolResult": ...
    @classmethod
    def fail(cls, error: str, **metadata) -> "ToolResult": ...

class ToolStatus(Enum):
    READY = "ready"
    RUNNING = "running"
    ERROR = "error"
    DISABLED = "disabled"
```

**设计决策**:
- 使用纯 `ToolDef` 数据类（非抽象基类），与 AgentSystem 解耦
- `to_openai_schema` 和 `to_mcp_schema` 两种序列化方法
- 从 `agent_workflow/tools.py` 的 `AgentTool` + `ToolResult` 演化而来，但去除 ABC 继承和 agent 特有字段（`cancel_event`, `author` 等）

---

### 3.3 `tools/registry.py`

**源文件**: `backend-core/agent_workflow/tools.py:74-116`（ToolRegistry）
**变更**: 重写为全局单例，支持模块级标注

```python
class ToolRegistry:
    """全局工具注册表 - 线程安全"""
    
    def __init__(self):
        self._tools: dict[str, ToolDef] = {}
    
    def register(self, tool: ToolDef) -> None:
        """注册工具（重名覆盖）"""
    
    def register_builtins(self) -> int:
        """注册所有内建工具（从 builtin/ 加载），返回注册数量"""
    
    def unregister(self, name: str) -> None:
        """注销工具"""
    
    def get(self, name: str) -> ToolDef | None:
        """按名称获取工具定义"""
    
    def list(self, category: str | None = None) -> list[ToolDef]:
        """列出工具（可按分类过滤）"""
    
    def to_openai_tools(self, names: list[str] | None = None) -> list[dict]:
        """转为 OpenAI 工具列表 schema"""
    
    def to_mcp_tools(self) -> list[dict]:
        """转为 MCP 工具列表"""
    
    def __contains__(self, name: str) -> bool: ...
    def __len__(self) -> int: ...

# 模块级单例
_registry: ToolRegistry | None = None

def get_registry() -> ToolRegistry:
    """获取全局注册表单例"""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
```

**设计决策**:
- 模块级单例 + `get_registry()` 工厂（与 `state_store.get_store()` 一致的惯用模式）
- `register_builtins()` 自动扫描 `tools/builtin/` 目录注册
- 支持 `to_openai_tools`（Agent 调用）和 `to_mcp_tools`（MCP Server 调用）

**依赖**: `tools/schema.py`

---

### 3.4 `tools/executor.py`

**新建**: 工具执行器

```python
class ToolExecutor:
    """工具执行器 - 参数校验 + 执行 + 超时控制"""
    
    def __init__(self, registry: ToolRegistry | None = None):
        self._registry = registry or get_registry()
    
    def validate(self, name: str, kwargs: dict) -> tuple[bool, str]:
        """校验参数是否符合 ToolDef.parameters 定义"""
    
    async def execute(
        self,
        name: str,
        kwargs: dict,
        context: dict | None = None,    # 执行上下文（project_db, task_id 等）
        timeout: int = 30,
    ) -> ToolResult:
        """
        查找工具名 → 获取对应 handler → 校验参数 → 执行 → 返回结果
        超时自动取消
        """
    
    def execute_sync(self, name, kwargs, context=None, timeout=30) -> ToolResult:
        """同步包装 execute()"""
```

**设计决策**:
- `execute` 根据工具名查找对应的 handler 函数（从 `builtin/*.py` 导入）
- `validate` 做参数类型检查（required 字段缺失、类型不匹配）
- `timeout` 通过 `asyncio.wait_for` 实现

**依赖**: `tools/schema.py`, `tools/registry.py`

---

### 3.5 `tools/builtin/` — 内建工具

#### 3.5.1 `tools/builtin/__init__.py`

```python
"""内建工具集合 - 自动注册到 ToolRegistry"""

from . import file_tools, symbol_tools, graph_tools, edge_tools, knowledge_tools

BUILTIN_MODULES = [file_tools, symbol_tools, graph_tools, edge_tools, knowledge_tools]

def register_all(registry):
    for mod in BUILTIN_MODULES:
        if hasattr(mod, "register"):
            mod.register(registry)
```

---

#### 3.5.2 `tools/builtin/file_tools.py`

**源文件**: `backend-core/agent_workflow/toolkits/file_tools.py` (291 行)
**变更**: 从 AgentTool ABC 改为纯函数 + ToolDef 定义

```python
"""文件操作工具 - read_file, search_content, summarize_file"""

TOOL_READ_FILE = ToolDef(
    name="read_file",
    description="Read full content of specified file (auto-truncates beyond 10000 chars)",
    category="io",
    parameters=[
        ToolParam(name="path", type=ToolParamType.STRING, description="File path", required=True),
    ],
)

TOOL_SEARCH_CONTENT = ToolDef(
    name="search_content",
    description="Search for keywords or regex in files, returns matching lines with line numbers (max 50)",
    category="io",
    parameters=[
        ToolParam(name="pattern", type=ToolParamType.STRING, description="Search pattern", required=True),
        ToolParam(name="path", type=ToolParamType.STRING, description="Optional file path filter"),
    ],
)

TOOL_SUMMARIZE_FILE = ToolDef(
    name="summarize_file",
    description="Read one or more files and generate functional summaries (≤10 files)",
    category="io",
    parameters=[
        ToolParam(name="path", type=ToolParamType.ARRAY, description="File path(s)", required=True),
        ToolParam(name="focus", type=ToolParamType.STRING, description="Analysis focus"),
        ToolParam(name="language", type=ToolParamType.STRING, description="Output language"),
    ],
)

async def handle_read_file(kwargs: dict, ctx: dict) -> ToolResult:
    """执行 read_file"""

async def handle_search_content(kwargs: dict, ctx: dict) -> ToolResult:
    """执行 search_content"""

async def handle_summarize_file(kwargs: dict, ctx: dict) -> ToolResult:
    """执行 summarize_file"""

HANDLERS = {
    "read_file": handle_read_file,
    "search_content": handle_search_content,
    "summarize_file": handle_summarize_file,
}

def register(registry):
    """注册所有文件工具到 registry"""
    for tool_def in [TOOL_READ_FILE, TOOL_SEARCH_CONTENT, TOOL_SUMMARIZE_FILE]:
        registry.register(tool_def)
```

**设计决策**:
- 从类（AgentTool ABC）改为 `ToolDef` 常量 + async handler 函数
- handler 接收 `(kwargs, ctx)`，`ctx` 包含 `project_db`, `project_root`, `path_sandbox` 等运行时依赖
- `HANDLERS` 字典供 `ToolExecutor` 查找

**依赖**: `tools/schema.py`, Phase 1 `core/db/`（project_db）, `core/project/scanner.py`

---

#### 3.5.3 `tools/builtin/symbol_tools.py`

**源文件**: `backend-core/agent_workflow/toolkits/symbol_tools.py` (280 行)
**变更**: 同 file_tools，从 ABC 到 ToolDef + handler

```python
TOOL_GET_SYMBOL_DETAIL = ToolDef(
    name="get_symbol_detail",
    description="Get detailed symbol info: type, signature, code snippet, file path",
    category="query",
    parameters=[ToolParam(name="symbol_id", type=ToolParamType.STRING, required=True)],
)

TOOL_SEARCH_SYMBOLS = ToolDef(
    name="search_symbols",
    description="Search code symbols by name (functions, classes, methods, etc.)",
    category="query",
    parameters=[
        ToolParam(name="pattern", type=ToolParamType.STRING, required=True),
        ToolParam(name="kind", type=ToolParamType.STRING, description="Symbol type filter"),
        ToolParam(name="limit", type=ToolParamType.INTEGER, default=20),
    ],
)

TOOL_GET_SYMBOL_CODE = ToolDef(
    name="get_symbol_code",
    description="Get full source code snippet for a symbol (3 lookup methods)",
    category="query",
    parameters=[
        ToolParam(name="symbol_id", type=ToolParamType.STRING),
        ToolParam(name="file_path", type=ToolParamType.STRING),
        ToolParam(name="name", type=ToolParamType.STRING),
        ToolParam(name="line", type=ToolParamType.INTEGER),
    ],
)

async def handle_get_symbol_detail(kwargs, ctx) -> ToolResult: ...
async def handle_search_symbols(kwargs, ctx) -> ToolResult: ...
async def handle_get_symbol_code(kwargs, ctx) -> ToolResult: ...

def register(registry): ...
```

**依赖**: `tools/schema.py`, Phase 1 `core/store/analysis_store.py`（graph_node 查询）

---

#### 3.5.4 `tools/builtin/graph_tools.py`

**源文件**: `backend-core/agent_workflow/toolkits/graph_tools.py` (272 行)
**变更**: 同上

```python
TOOL_GET_SUBGRAPH = ToolDef(name="get_community_subgraph", ...)
TOOL_GET_CALL_CHAIN = ToolDef(name="get_call_chain", ...)
TOOL_GET_AST_NODE = ToolDef(name="get_ast_node", ...)
```

**依赖**: `tools/schema.py`, Phase 1 `core/analysis/community.py`, `core/store/analysis_store.py`

---

#### 3.5.5 `tools/builtin/edge_tools.py`

**源文件**: `backend-core/agent_workflow/toolkits/edge_tools.py` (79 行)
**变更**: 同上

```python
TOOL_GET_EDGE_DETAIL = ToolDef(name="get_edge_detail", ...)
```

---

#### 3.5.6 `tools/builtin/knowledge_tools.py`

**新建**: 知识库工具（预留 Phase 4 实现 handler）

```python
"""知识库工具 - search_knowledge, get_document"""

TOOL_SEARCH_KNOWLEDGE = ToolDef(
    name="search_knowledge",
    description="Search knowledge base documents by keyword",
    category="knowledge",
    parameters=[ToolParam(name="query", type=ToolParamType.STRING, required=True)],
)

TOOL_GET_DOCUMENT = ToolDef(
    name="get_document",
    description="Get full content of a knowledge document",
    category="knowledge",
    parameters=[ToolParam(name="doc_id", type=ToolParamType.STRING, required=True)],
)

# handlers 在 Phase 4 实现
async def handle_search_knowledge(kwargs, ctx) -> ToolResult:
    return ToolResult.fail("Not implemented yet")

async def handle_get_document(kwargs, ctx) -> ToolResult:
    return ToolResult.fail("Not implemented yet")

def register(registry): ...
```

---

## 4. 逐文件规格: `mcp/`

### 4.1 `mcp/__init__.py`

```python
"""MCP Server + Client（零业务依赖）"""
from .schema import (
    MCPRequest, MCPResponse, MCPError,
    ToolListRequest, ToolListResponse,
    ToolCallRequest, ToolCallResponse,
)
from .server import MCPServer
from .client import MCPClient
from .registry import MCPServerRegistry
```

---

### 4.2 `mcp/schema.py`

**新建**: MCP JSON-RPC 消息类型

```python
from dataclasses import dataclass, field
from typing import Any
from enum import Enum
import json

class MCPMethod(str, Enum):
    TOOLS_LIST = "tools/list"
    TOOLS_CALL = "tools/call"
    RESOURCES_LIST = "resources/list"
    RESOURCES_READ = "resources/read"
    PROMPTS_LIST = "prompts/list"
    PROMPTS_GET = "prompts/get"
    INITIALIZE = "initialize"

@dataclass
class MCPRequest:
    """MCP JSON-RPC 请求"""
    jsonrpc: str = "2.0"
    id: str | int = ""
    method: str = ""
    params: dict = field(default_factory=dict)
    
    def to_bytes(self) -> bytes: ...
    
    @classmethod
    def from_bytes(cls, data: bytes) -> "MCPRequest": ...

@dataclass
class MCPResponse:
    """MCP JSON-RPC 响应"""
    jsonrpc: str = "2.0"
    id: str | int = ""
    result: dict | None = None
    error: dict | None = None
    
    def to_bytes(self) -> bytes: ...
    @classmethod
    def from_bytes(cls, data: bytes) -> "MCPResponse": ...

# 便捷构造函数
def make_tools_list_request() -> MCPRequest: ...
def make_tools_list_response(tools: list[dict]) -> MCPResponse: ...
def make_tool_call_request(name: str, arguments: dict) -> MCPRequest: ...
def make_tool_call_response(result: Any) -> MCPResponse: ...
def make_error_response(id: str, code: int, message: str) -> MCPResponse: ...
```

**设计决策**:
- 严格遵循 [MCP 协议规范](https://spec.modelcontextprotocol.io/)
- JSON-RPC 2.0 标准消息格式
- `to_bytes`/`from_bytes` 支持 stdio transport 的 `\n` 分隔

---

### 4.3 `mcp/transport.py`

**新建**: Transport 抽象 + stdio/TCP 实现

```python
from abc import ABC, abstractmethod
import asyncio

class MCPTransport(ABC):
    """MCP 传输层抽象"""
    
    @abstractmethod
    async def send(self, data: bytes): ...
    
    @abstractmethod
    async def recv(self) -> bytes: ...
    
    @abstractmethod
    async def close(self): ...

class StdioTransport(MCPTransport):
    """stdio 传输（子进程 stdin/stdout）"""
    
    def __init__(self, process: asyncio.subprocess.Process): ...
    async def send(self, data: bytes): ...
    async def recv(self) -> bytes: ...
    async def close(self): ...

class TCPTransport(MCPTransport):
    """TCP 传输（asyncio socket）"""
    
    def __init__(self, host: str, port: int): ...
    async def connect(self): ...
    async def send(self, data: bytes): ...
    async def recv(self) -> bytes: ...
    async def close(self): ...
```

---

### 4.4 `mcp/server.py`

**新建**: MCP Server — 将内建工具暴露为 MCP 协议

```python
import asyncio
import json
from ..tools.registry import get_registry

class MCPServer:
    """MCP Server - 通过 stdio/TCP 暴露工具"""
    
    def __init__(self, registry=None, transport=None):
        self._registry = registry or get_registry()
        self._transport = transport
        self._running = False
    
    @classmethod
    async def create_stdio(cls, registry=None) -> "MCPServer":
        """创建 stdio 模式的 MCP Server"""
        transport = StdioTransport(...)
        return cls(registry, transport)
    
    @classmethod
    async def create_tcp(cls, host: str, port: int, registry=None) -> "MCPServer":
        """创建 TCP 模式的 MCP Server"""
        transport = TCPTransport(host, port)
        return cls(registry, transport)
    
    async def serve(self):
        """主循环: 接收请求 → 路由 → 响应"""
        self._running = True
        while self._running:
            req_bytes = await self._transport.recv()
            response = await self._handle(req_bytes)
            await self._transport.send(response)
    
    async def _handle(self, req_bytes: bytes) -> bytes:
        """路由请求到对应处理器"""
        request = MCPRequest.from_bytes(req_bytes)
        
        if request.method == MCPMethod.TOOLS_LIST:
            return self._handle_tools_list(request)
        elif request.method == MCPMethod.TOOLS_CALL:
            return await self._handle_tool_call(request)
        elif request.method == MCPMethod.INITIALIZE:
            return self._handle_initialize(request)
        else:
            return make_error_response(request.id, -32601, "Method not found")
    
    def _handle_tools_list(self, request) -> bytes:
        """tools/list: 从注册表获取所有 LLM 可见工具"""
        tools = self._registry.list()
        mcp_tools = [t.to_mcp_schema() for t in tools if t.llm_visible]
        return make_tools_list_response(mcp_tools).to_bytes()
    
    async def _handle_tool_call(self, request) -> bytes:
        """tools/call: 执行工具并返回结果"""
        name = request.params.get("name", "")
        arguments = request.params.get("arguments", {})
        
        executor = ToolExecutor(self._registry)
        result = await executor.execute(name, arguments)
        
        return MCPResponse(
            id=request.id,
            result={"content": [{"type": "text", "text": json.dumps(result.data)}]}
        ).to_bytes()
    
    def _handle_initialize(self, request) -> bytes:
        """initialize: 返回 Server 信息"""
        return MCPResponse(
            id=request.id,
            result={
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "topoone", "version": "0.1.0"},
            }
        ).to_bytes()
    
    def stop(self):
        self._running = False
```

**设计决策**:
- Server 通过 `registry` 获取内建工具列表
- 不直接依赖 `tools/builtin/` 中的 handler 实现——委托给 `ToolExecutor`
- `tools/list` 返回所有 `llm_visible=True` 的工具
- `tools/call` 的参数和执行通过 `ToolExecutor` 完成

**依赖**: `tools/registry.py`, `tools/executor.py`, `mcp/schema.py`, `mcp/transport.py`

---

### 4.5 `mcp/client.py`

**新建**: MCP Client — 连接第三方 MCP Server

```python
class MCPClient:
    """MCP Client - 发现并调用第三方工具"""
    
    def __init__(self, transport: MCPTransport):
        self._transport = transport
        self._tools: list[dict] = []
        self._connected = False
    
    @classmethod
    async def connect_stdio(cls, command: str, args: list[str]) -> "MCPClient": ...
    
    @classmethod
    async def connect_tcp(cls, host: str, port: int) -> "MCPClient": ...
    
    async def initialize(self) -> dict:
        """发送 initialize 请求, 获取 server 信息"""
    
    async def list_tools(self) -> list[dict]:
        """获取远程工具列表"""
    
    async def call_tool(self, name: str, arguments: dict) -> Any:
        """调用远程工具"""
    
    @property
    def tools(self) -> list[dict]:
        """已缓存的远程工具列表"""
    
    async def close(self):
        """关闭连接"""
```

**设计决策**:
- 每个第三方 MCP Server 对应一个 `MCPClient` 实例
- `connect_stdio` 用于启动本地子进程（如 `topocode serve`）
- `connect_tcp` 用于连接远程 MCP Server
- `list_tools()` 结果缓存，供 Agent Runtime 和 Coding Agent 使用

**依赖**: `mcp/schema.py`, `mcp/transport.py`

---

### 4.6 `mcp/registry.py`

**新建**: 第三方 MCP Server 配置管理

```python
from dataclasses import dataclass
from typing import Optional
import json

@dataclass
class MCPServerConfig:
    """第三方 MCP Server 配置"""
    name: str
    transport: str               # "stdio" | "tcp"
    command: str = ""            # stdio 模式: 启动命令
    args: list[str] = field(default_factory=list)  # stdio 模式: 命令参数
    host: str = "127.0.0.1"     # TCP 模式: 主机
    port: int = 0                # TCP 模式: 端口
    enabled: bool = True
    
    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> "MCPServerConfig": ...

class MCPServerRegistry:
    """第三方 MCP Server 注册表（持久化到 DB）"""
    
    def __init__(self, multi_db=None):
        self._servers: dict[str, MCPClient] = {}   # name -> client
        self._configs: dict[str, MCPServerConfig] = {}
    
    def load_from_db(self, multi_db): ...
        """从 app_config 表加载 MCP Server 配置"""
    
    def save_to_db(self, multi_db): ...
    
    def add(self, config: MCPServerConfig) -> str:
        """添加配置（返回 server name）"""
    
    def remove(self, name: str): ...
    
    async def connect_all(self) -> dict[str, bool]:
        """连接所有启用的 Server, 返回 {name: success}"""
    
    async def connect_one(self, name: str) -> bool:
        """连接指定 Server"""
    
    def disconnect_all(self): ...
    
    def get_client(self, name: str) -> MCPClient | None: ...
    
    def list_all_tools(self) -> list[dict]:
        """汇总所有已连接 Server 的工具列表（名称加 namespace 前缀）"""
    
    @property
    def configs(self) -> list[MCPServerConfig]: ...
```

**设计决策**:
- 配置持久化到 `app_config` 表（key=`mcp_servers`, value=JSON）
- `list_all_tools()` 为工具名添加 `{server_name}:` 前缀以避免命名冲突
- 在 `topoone/agent/` 的 RouterHarness 中使用，将远程工具注入 Agent Runtime

**依赖**: `mcp/client.py`, Phase 1 `core/db/manager.py`（MultiDBManager，可选）

---

## 5. 逐文件规格: `agent/skills/`

### 5.1 `agent/skills/__init__.py`

```python
"""技能编排层 - 连接工具注册表和工作流系统"""
from .schema import SkillDef, SkillStep
from .registry import register_skill, get_registered_skills, sync_skills_to_db
from .builtin import register_builtin_skills
```

---

### 5.2 `agent/skills/schema.py`

**新建**: 技能定义

```python
from dataclasses import dataclass, field

@dataclass
class SkillStep:
    """技能单步定义"""
    name: str
    description: str
    tool: str                          # 对应的工具名
    params_template: dict | None = None  # 参数模板

@dataclass
class SkillDef:
    """技能定义 - 一组工具的组合编排"""
    name: str
    description: str
    steps: list[SkillStep]
    category: str = "general"
    version: str = "1.0"
```

---

### 5.3 `agent/skills/registry.py`

**源文件**: `backend-core/agent_workflow/skill_registry.py` (93 行)
**变更**: 兼容旧装饰器接口，但底层使用 `SkillDef`

```python
"""技能注册表"""

_registry: list[SkillDef] = []

def register_skill(
    name: str,
    description: str = "",
    steps: int = 1,
    category: str = "general",
) -> callable:
    """
    装饰器: 将函数标记为技能
    兼容旧 @register_skill 接口
    
    用法:
        @register_skill(name="skill_read_file", description="Read source file", steps=1)
        def my_handler(ctx): ...
    """
    def decorator(func):
        skill = SkillDef(
            name=name,
            description=description,
            steps=[SkillStep(name=f"step_{i}", description="", tool="") for i in range(steps)],
            category=category,
        )
        _registry.append(skill)
        return func
    return decorator

def get_registered_skills() -> list[SkillDef]:
    """获取已注册技能（去重）"""

def sync_skills_to_db(multi_db, locale: str | None = None):
    """同步技能到 skill_configs 表"""
```

**依赖**: `agent/skills/schema.py`, Phase 1 `core/db/manager.py`（MultiDBManager）

---

### 5.4 `agent/skills/builtin.py`

**新建**: 内建技能定义（从旧 `agent_workflow/skill_registry.py` 的注册迁移）

```python
from .registry import register_skill

@register_skill(name="skill_read_source_file", description="Read source code file content", steps=1, category="io")
def skill_read_file(ctx): ...   # 占位, 实际由 workflow 调用

@register_skill(name="skill_search_symbols", description="Search code symbols by name pattern", steps=1, category="query")
def skill_search_symbols(ctx): ...

@register_skill(name="skill_generate_arch_overview", description="Generate architecture overview document", steps=3, category="analysis")
def skill_generate_overview(ctx): ...

@register_skill(name="skill_analyze_community", description="Analyze architecture community details", steps=4, category="analysis")
def skill_analyze_community(ctx): ...

@register_skill(name="skill_explore_graph", description="Explore community subgraph structure", steps=1, category="graph")
def skill_explore_graph(ctx): ...

@register_skill(name="skill_analyze_relations", description="Analyze edge relations between symbols", steps=1, category="graph")
def skill_analyze_relations(ctx): ...

def register_builtin_skills():
    """确保所有装饰器触发注册（import side effect）"""
    pass
```

**设计决策**:
- 使用装饰器的 import side effect 注册（与旧版兼容）
- handler 函数保持占位——实际由 AgentWorkflow 通过工作流执行

**依赖**: `agent/skills/registry.py`

---

## 6. 与旧代码的映射关系

### tools/ — 迁移映射

| 目标文件 | 源文件 | 行数 | 变更 |
|----------|--------|------|------|
| `tools/schema.py` | 新建 | ~100 | 从 AgentTool + ToolResult 提取 |
| `tools/registry.py` | `agent_workflow/tools.py:74-116` | ~80 | 重写为单例，增加 to_mcp 方法 |
| `tools/executor.py` | 新建 | ~120 | 新写（替代旧 AgentRuntime 中的执行逻辑） |
| `tools/builtin/file_tools.py` | `agent_workflow/toolkits/file_tools.py` | ~250 | ABC → ToolDef + handler |
| `tools/builtin/symbol_tools.py` | `agent_workflow/toolkits/symbol_tools.py` | ~250 | ABC → ToolDef + handler |
| `tools/builtin/graph_tools.py` | `agent_workflow/toolkits/graph_tools.py` | ~240 | ABC → ToolDef + handler |
| `tools/builtin/edge_tools.py` | `agent_workflow/toolkits/edge_tools.py` | ~60 | ABC → ToolDef + handler |
| `tools/builtin/knowledge_tools.py` | 新建 | ~40 | 预留 stub |

### mcp/ — 新建

| 目标文件 | 源文件 | 行数 | 说明 |
|----------|--------|------|------|
| `mcp/schema.py` | 新建 | ~80 | MCP JSON-RPC 消息类型 |
| `mcp/transport.py` | 新建 | ~120 | stdio/TCP transport |
| `mcp/server.py` | 新建 | ~150 | 暴露 tools/ 注册表 |
| `mcp/client.py` | 新建 | ~120 | 连接第三方 MCP |
| `mcp/registry.py` | 新建 | ~100 | 配置管理 |

### agent/skills/ — 迁移映射

| 目标文件 | 源文件 | 行数 | 变更 |
|----------|--------|------|------|
| `agent/skills/schema.py` | 新建 | ~40 | SkillDef 定义 |
| `agent/skills/registry.py` | `agent_workflow/skill_registry.py` | ~90 | 底层换 SkillDef，接口兼容 |
| `agent/skills/builtin.py` | `agent_workflow/skill_registry.py` 中的装饰器 | ~40 | 提取集中定义 |

**总计**: 新建 ~800 行, 迁移 ~900 行

---

## 7. 模块依赖关系图

```
tools/schema.py            ← 无依赖
tools/registry.py          → schema.py
tools/executor.py          → schema.py, registry.py
  │
tools/builtin/*.py         → schema.py, core/* (数据源)
  │
mcp/schema.py              ← 无依赖
mcp/transport.py           ← 无依赖
mcp/server.py              → schema.py, transport.py, tools/registry.py, tools/executor.py
mcp/client.py              → schema.py, transport.py
mcp/registry.py            → client.py, core/db/manager.py (可选)
  │
agent/skills/schema.py     ← 无依赖
agent/skills/registry.py   → schema.py, core/db/manager.py
agent/skills/builtin.py    → registry.py (装饰器 side effect)
```

**跨包依赖**:
- `mcp/server.py` 依赖 `tools/`
- `agent/skills/registry.py` 依赖 Phase 1 `core/db/manager.py`
- `tools/builtin/*.py` 依赖 Phase 1 `core/store/*`、`core/analysis/*`

---

## 8. MCP 协议规格

### 8.1 支持的 MCP 方法

| 方法 | 功能 | 本阶段状态 |
|------|------|-----------|
| `initialize` | 握手 + 能力声明 | 完整实现 |
| `tools/list` | 列出可用工具 | 完整实现 |
| `tools/call` | 调用指定工具 | 完整实现 |
| `resources/list` | 列出资源 | 预留 |
| `resources/read` | 读取资源 | 预留 |
| `prompts/list` | 列出提示模板 | 预留 |
| `prompts/get` | 获取提示模板 | 预留 |

### 8.2 通信模式

```
# Client → Server (请求)
{"jsonrpc":"2.0","id":"1","method":"tools/list","params":{}}

# Server → Client (响应)
{"jsonrpc":"2.0","id":"1","result":{"tools":[
  {"name":"read_file","description":"...","inputSchema":{...}},
  {"name":"search_symbols","description":"...","inputSchema":{...}},
  ...
]}}

# Client → Server (调用)
{"jsonrpc":"2.0","id":"2","method":"tools/call","params":{
  "name":"read_file","arguments":{"path":"src/main.py"}
}}

# Server → Client (结果)
{"jsonrpc":"2.0","id":"2","result":{
  "content":[{"type":"text","text":"file contents..."}]}
}}
```

### 8.3 使用场景

| 场景 | Server 模式 | Client 模式 |
|------|------------|-------------|
| Agent 内联调用 | — | 直接 local 调用 ToolRegistry（不走 MCP） |
| 暴露给第三方 LLM | `topocode serve` 启动 stdio MCP | 第三方工具如 Claude/Cursor 连接 |
| 接入第三方工具 | — | 连接外部 MCP Server（数据库、浏览器等） |
| 分布式 Agent Worker | TCP MCP Server 监听 | Worker 进程连接获取工具 |

### 8.4 与现有 installer 的集成

现有 `plugins/installer/targets/*.py` 已经为各 coding agent 输出包含 `topocode serve` 的 `mcp.json`:

```json
{
  "mcpServers": {
    "topoone": {
      "command": "topocode",
      "args": ["serve"]
    }
  }
}
```

Phase 2 完成后，`topocode serve` 将启动 `MCPServer`（stdio 模式）, 提供 `tools/list` 和 `tools/call` 端点。

---

## 9. 测试规划

### 测试目录

```
next/backend/tests/
├── tools/
│   ├── test_schema.py         # ToolDef, ToolParam, ToolResult 序列化
│   ├── test_registry.py       # ToolRegistry CRUD + 单例
│   ├── test_executor.py       # 参数校验 + 执行 + 超时
│   └── builtin/
│       ├── test_file_tools.py
│       ├── test_symbol_tools.py
│       ├── test_graph_tools.py
│       └── test_edge_tools.py
├── mcp/
│   ├── test_schema.py         # MCPRequest/Response 序列化
│   ├── test_transport.py      # stdio/TCP 通信
│   ├── test_server.py         # tools/list + tools/call
│   └── test_client.py         # 连接/列表/调用
└── agent/
    └── skills/
        ├── test_schema.py
        └── test_registry.py   # @register_skill + sync_skills_to_db
```

### 关键测试用例

```python
# tools/registry_test.py
def test_register_and_list():
    reg = ToolRegistry()
    reg.register(TOOL_READ_FILE)
    reg.register(TOOL_SEARCH_SYMBOLS)
    tools = reg.list()
    assert len(tools) == 2
    assert reg.get("read_file") is not None

def test_to_openai_tools():
    reg = ToolRegistry()
    reg.register_builtins()
    schemas = reg.to_openai_tools()
    assert all("function" in s for s in schemas)

def test_to_mcp_tools():
    reg = ToolRegistry()
    reg.register_builtins()
    tools = reg.to_mcp_tools()
    assert all("inputSchema" in t for t in tools)

# mcp/server_test.py
async def test_tools_list():
    reg = ToolRegistry()
    reg.register(TOOL_READ_FILE)
    server = MCPServer(reg)
    req = make_tools_list_request()
    resp = await server._handle(req.to_bytes())
    data = json.loads(resp)
    assert len(data["result"]["tools"]) == 1

async def test_tool_call():
    reg = ToolRegistry()
    reg.register(TOOL_READ_FILE)
    server = MCPServer(reg)
    req = make_tool_call_request("read_file", {"path": "test.txt"})
    resp = await server._handle(req.to_bytes())
    data = json.loads(resp)
    assert "result" in data
```

---

## 10. 验证清单

```bash
# 1. 包导入
python -c "
from topoone.tools import ToolRegistry, ToolExecutor
from topoone.tools.schema import ToolDef, ToolParam, ToolResult
from topoone.tools.builtin import register_all
print('tools OK')
from topoone.mcp import MCPServer, MCPClient
print('mcp OK')
from topoone.agent.skills import register_skill, get_registered_skills
print('skills OK')
"

# 2. 工具注册 + 内建工具
python -c "
from topoone.tools import get_registry
reg = get_registry()
from topoone.tools.builtin import register_all
register_all(reg)
tools = reg.list()
print(f'{len(tools)} builtin tools registered')
for t in tools:
    print(f'  {t.name} ({t.category})')
"

# 3. MCP Server 响应
python -c "
import asyncio
from topoone.tools import get_registry
from topoone.tools.builtin import register_all
from topoone.mcp import MCPServer
reg = get_registry()
register_all(reg)

async def test():
    server = MCPServer(reg)
    # 测试 tools/list
    import json
    req = json.dumps({'jsonrpc':'2.0','id':'1','method':'tools/list','params':{}}).encode()
    resp = await server._handle(req)
    data = json.loads(resp)
    assert len(data['result']['tools']) > 0
    print(f'MCP Server OK: {len(data[\"result\"][\"tools\"])} tools')
asyncio.run(test())
"

# 4. 全部测试
cd next/backend && python -m pytest tests/tools/ tests/mcp/ tests/agent/skills/ -v
```

**Phase 2 完成标志**:
1. 全部 10 个内建工具注册到 ToolRegistry
2. 每个工具可以通过 ToolExecutor 执行
3. MCP Server 可启动并响应 `tools/list` 响应
4. MCP Client 可连接第三方 Server（通过 mock 验证）
5. 技能注册兼容旧 `@register_skill` 装饰器
6. 全部 pytest 测试通过
7. 与旧 `agent_workflow/` 零冲突
