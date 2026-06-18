# TopoCode Agent 架构规范

## 一、核心架构

### 三层次架构

```
┌──────────────────────────────────────────────────────────────┐
│  Workflow Layer                                              │
│  决定"做什么"                                                 │
│  - AgentWorkflow (plan → execute → finalize)                  │
│  - AgenticWorkflow (ReAct loop → observe → act)               │
├──────────────────────────────────────────────────────────────┤
│  Tool Calling Layer (tool_calling/)                           │
│  决定"怎么调用 LLM"                                           │
│  - agentic_chat() — 唯一入口                                   │
│  - ToolCallingStrategy — 策略抽象                              │
│    ├─ NativeStrategy (原生 function calling)                   │
│    └─ TextFallbackStrategy ([TOOL_CALL:] 文本)                 │
├──────────────────────────────────────────────────────────────┤
│  Provider Layer (providers/)                                  │
│  负责"与 LLM API 通信"                                        │
│  - chat_stream() / chat_sync() — 纯 API 通信                  │
│  - 不感知 tool calling 策略                                    │
│  - 不感知 workflow 逻辑                                       │
└──────────────────────────────────────────────────────────────┘
```

### 层级职责

| 层 | 职责 | 不负责 |
|----|------|--------|
| Workflow | 编排步骤/ReAct 循环、调用工具 | LLM 通信、tool calling 策略 |
| ToolCalling | 策略选择、请求构造、响应解析 | 工作流编排、Provider 通信 |
| Provider | HTTP 通信、错误处理、token 统计 | 策略选择、工作流逻辑 |

### 数据流

```
_run_agentic()
  │
  ├─ create_strategy(multi_db, model_id)
  │  └─ 根据 Provider.supports_tools 自动选择策略
  │
  └─ agentic_chat(messages, tools, strategy)
       │
       ├─ strategy.build_request(messages, tools)
       │  └─ Native: tools → payload["tools"]
       │     Text: 注入 [TOOL_CALL:] 到 system prompt
       │
       ├─ provider.chat_sync(request)
       │  └─ HTTP POST → raw dict
       │
       └─ strategy.parse_response(raw)
          └─ Native: 解析 tool_calls[]
             Text: 解析 [TOOL_CALL:] 标记
```

---

## 二、ToolCallingStrategy 规范

### 基类

```python
class ToolCallingStrategy(ABC):
    @abstractmethod
    async def chat(self, messages, tools, multi_db, model_id, ...) -> AgentChatResponse
    @classmethod
    def name(cls) -> str
```

### 两种内置策略

| 策略 | NativeToolCallingStrategy | TextFallbackToolCallingStrategy |
|------|-------------------------|-------------------------------|
| 适用模型 | OpenAI / Qwen3 / DeepSeek | Ollama 旧版 / 不支持 tools 的模型 |
| Provider 要求 | `supports_tools=True` | 无 |
| 工具注入 | API 层 `tools` payload | system prompt 文本 |
| 工具解析 | API 返回 `tool_calls` | 正则解析 `[TOOL_CALL:]` |
| 输出格式 | 自动 JSON (`content`) | 纯文本 + 标记 |

### 新增策略

只需要三步：

1. 继承 `ToolCallingStrategy`
2. 实现 `chat()` 方法（返回统一的 `AgentChatResponse`）
3. 在 `create_strategy()` 工厂函数中添加选择逻辑

示例：
```python
class AnthropicToolCallingStrategy(ToolCallingStrategy):
    @classmethod
    def name(cls) -> str:
        return "anthropic"

    async def chat(self, messages, tools, multi_db, model_id, ...) -> AgentChatResponse:
        # 实现 Anthropic 格式的 tool calling
        ...
```

### 统一数据结构

```python
@dataclass
class ToolCall:
    name: str          # 工具名
    arguments: dict    # 参数 dict
    id: str            # 调用 ID

@dataclass
class AgentChatResponse:
    content: str             # 文本输出（无工具调用时）
    tool_calls: list[ToolCall]  # 工具调用列表
    tokens_used: int         # 本次消耗 token 数
    finish_reason: str       # "stop" | "tool_calls" | "error"
```

---

## 三、Provider 规范

### 能力声明

每个 Provider 声明自身能力：

```python
class BaseLLMProvider(ABC):
    supports_tools: bool = False  # 是否支持原生 function calling
```

当前实现：

| Provider | supports_tools |
|----------|---------------|
| `OpenAICompatProvider` | `True` |
| `OllamaProvider` | `True` |

### chat_sync 接口

```python
def chat_sync(self, model_config, messages, mode, tools, output_schema) -> dict
```

返回 dict 必须包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `content` | str | 模型输出文本 |
| `usage` | dict | `{prompt_tokens, completion_tokens, total_tokens}` |
| `tool_calls` | list[dict] | 工具调用（OpenAI 格式 `{id, type, function: {name, arguments}}`） |
| `finish_reason` | str | `"stop"` 或 `"tool_calls"` |

### 新增 Provider

1. 继承 `BaseLLMProvider`
2. 声明 `supports_tools`
3. 实现 `chat_stream()` 和 `chat_sync()`
4. 在 `providers/__init__.py` 中 `register_all()` 注册
5. Provider 不感知 tool calling 策略，只做 API 格式转换

---

## 四、Workflow 规范

### 两种工作流基类

| 基类 | 执行模式 | plan() | 工具调用 |
|------|---------|--------|---------|
| `AgentWorkflow` | 固定步骤顺序执行 | 返回预定义 `list[AgentStep]` | `tool.execute(**step.args)` |
| `AgenticWorkflow` | ReAct 循环（逐组件） | 返回空列表（由 ReAct 接管） | `agentic_chat()` → 策略层 → execute |

### I/O Schema（显式声明）

每个 Workflow 声明期望的输入字段和产出的输出结构：

```python
class AgenticWorkflow(AgentWorkflow):
    input_schema: dict = {}
    output_schema: dict = {}
```

Router 或在 dispatch 前校验 context 字段是否满足 `input_schema` 的要求。

### AgenticWorkflow 抽象方法

```python
class AgenticWorkflow(AgentWorkflow):
    max_turns: int = 5
    max_turn_timeout: int = 180

    @abstractmethod
    def get_system_prompt(self, context: dict) -> str
    @abstractmethod
    def finalize(self, results: dict) -> WorkflowResult

    def get_tool_filter(self, context) -> list[str] | None
    def get_task_description(self, context) -> str
```

### 新增 AgenticWorkflow

1. 继承 `AgenticWorkflow`
2. 实现 `get_system_prompt()` 和 `finalize()`
3. 可选重写 `get_tool_filter()` 限制 LLM 可见的工具
4. 在 `router.py` 中注册新路由
5. Workflow 不感知 Provider 通信和策略细节

### Agentic 结果保存

Agentic 工作流的结果通过 `context["_save_fn"]` 保存到 DB：

```python
context["_save_fn"] = _save_fn   # 由 task_manager.py 在 agentic 模式下注入
```

在 `_run_agentic` 完成后：
1. 尝试将 LLM 输出解析为 JSON → 逐组件保存 `analyzed_name` + `functional_summary`
2. JSON 解析失败时回退 → 将 LLM 文本整体作为 `functional_summary` 保存到每个组件
3. 最终写入 `component_analysis` 和 `community_llm_results` 表

---

## 五、工具规范

### AgentTool 属性

```python
class AgentTool(ABC):
    name: str           # 工具名（唯一标识）
    description: str    # 描述（LLM 可见）
    category: str       # "io" | "query" | "graph" | "analysis"
    llm_visible: bool   # 是否对 LLM 的 tool calling 可见
```

### OpenAI Schema

```python
def to_openai_schema(self) -> dict | None:
    # llm_visible=False 时返回 None
    # llm_visible=True 时必须返回完整 OpenAI function schema
    return {
        "type": "function",
        "function": {
            "name": ...,
            "description": ...,
            "parameters": {"type": "object", "properties": {...}},
        },
    }
```

### ToolRegistry 方法

```python
class ToolRegistry:
    def to_openai_tools(self, filter_names=None) -> list[dict]
    # 返回所有 llm_visible=True 且名在 filter_names 中的工具的 OpenAI schema
```

### 新增工具

1. 继承 `AgentTool`
2. 设 `llm_visible = True`（如需 LLM 可见）
3. 实现 `to_openai_schema()`（返回完整参数 Schema）
4. 实现 `execute()`
5. 在 `tool_factory.py` 中注册

---

## 六、`_run_agentic` 执行流程

```
# 逐组件处理（每个组件独立 ReAct 循环）
for c_idx, comp in enumerate(components):
    1. 构建 system prompt（含组件信息 + 项目摘要 + 父组件概要）
    2. 构建 user 消息（组件 context：文件列表、符号、边关系）
    3. 内层 ReAct 循环 for turn in range(max_turns):
         a. agentic_chat(msg, tools, strategy)
         b. if response.tool_calls:
              for tc in tool_calls[:3]:
                result = tool.execute(**tc.arguments)
                messages.append(assistant + tool_results)
           else:
              output = response.content
              break
    4. save_result(comp, output) — 立即写入 DB
    5. 继续下一个组件

finalize({component_results: [...]})
```

### 关键约束

| 约束 | 值 |
|------|-----|
| 每组件最大轮次 | `workflow.max_turns`（默认 6） |
| 每轮超时 | `workflow.max_turn_timeout`（默认 180s） |
| 每轮最多工具调用 | 3 个 |
| 工具调用范围 | 项目内所有文件（`PathSandbox` 限制） |
| 结果保存 | 每组件分析完成后立即写入 `component_analysis` + `community_llm_results` |
| 每轮最多工具调用 | 3 个 |
| LLM 速率限制 | `sandbox.llm_rate`（默认 3 并发） |
| Token 预算 | `sandbox.budget` |
| 策略选择 | `create_strategy()` 自动 | 

---

## 七、运行时规范

### AgentRuntime.run() 分发逻辑

```python
async def run(self, workflow, context):
    if isinstance(workflow, AgenticWorkflow):
        return await self._run_agentic(workflow, context)
    return await self._run_sequential(workflow, context)
```

### `_run_sequential` 修改原则

- 不引入 `agentic_chat`
- 不引入 `ToolCallingStrategy`
- 保持现有的 `tool.execute(**step.args)` 模式
- 工具内部如需 LLM 调用，使用 `create_llm_chat_fn()`（纯文本）

### 非功能约束

| 约束 | 值 |
|------|-----|
| 取消支持 | `runtime.cancel()` → `_cancelled = True` |
| 预算检查 | 每次循环检测 `budget.exhausted()` |
| 进度报告 | `self._report()` 每轮/每步 |
| 日志前缀 | `[AgentRuntime]` |
