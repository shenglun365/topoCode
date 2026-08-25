"""I5 — architect 后端接入 tAgent SE 大脑（薄接线基础层）。

architect 是独立进程，仅经 KbGateway(HTTP) 触达主后端 LLM/KB。本模块提供：

- `KbGatewayLLMClient`：tAgent `LLMClient` 协议实现，走 `llm.sync`(mode=chat)。
  主后端 llm.sync 的 chat 模式不跑工具循环、忽略 tools 参数 → 返回纯文本，
  故 `supports_tools=False`，tAgent 自动选 TextFallback 策略（文本 [TOOL_CALL]，
  与 architect 现网 req_agent 的工具协议同源）；工具在 architect 进程本地执行。
- `ArchitectToolAdapter`：把 architect 既有领域工具（同步 `fn(root, project, **args)`）
  适配为 tAgent `AgentTool`（带参数 schema），注入 ArchitectSEAgent 的工具注册表。
- `build_architect_se(...)`：组装 `ArchitectSEAgent`（SE 大脑：analyze/design/plan/
  execute/rejudge/verify），文件探查工具读 project_root 磁盘，领域工具注入。

SE 大脑负责"需求→分析→设计→任务树(含 depends_on)→执行→stale 重判→验证"，
architect 既有领域工具（KB 资产/语义检索/依赖图/项目上下文）作为其探查能力。
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable, Optional

from topocode_agent.core.llm.protocol import ChatResponse, StreamEvent, ToolCall
from topocode_agent.core.tool.base import AgentTool, ToolResult
from topocode_agent.profiles.architect_se import ArchitectSEAgent

logger = logging.getLogger(__name__)

# llm 调用超时（秒）——与 req_agent._LLM_CALL_TIMEOUT 同量级
_LLM_TIMEOUT = 180.0

# tAgent TextFallback 工具调用标记正则为 `(\w+)`，不含点号；architect 领域工具
# 惯用点号命名（kb.asset.search）→ 注册进 SE 大脑时净化为下划线安全名，
# handler 绑定不受影响（LLM 按 system prompt 里的安全名调用）。
_RE_UNSAFE_NAME = re.compile(r"[^\w]")


def sanitize_tool_name(name: str) -> str:
    return _RE_UNSAFE_NAME.sub("_", name).strip("_") or "tool"


# ── LLMClient over KbGateway ──────────────────────────────────────

class KbGatewayLLMClient:
    """tAgent LLMClient → 主后端 llm.sync（经 KbGateway HTTP）。

    - `supports_tools=False`：主后端 llm.sync 的 chat 模式不返回原生 tool_calls，
      tAgent 据此选 TextFallback（文本 [TOOL_CALL]）策略，与 architect 现网一致。
    - `chat` 走非流式（SE 的 analyze/design/plan 均非流式）；`chat_stream` 以
      单次 delta+done 包装（协议完整性，SE 不依赖流式）。
    """

    def __init__(self, gateway: Any, model_id: str = "", session_id: str = "arch-se"):
        self._gw = gateway
        self._model_id = model_id
        self._session_id = session_id

    @property
    def supports_tools(self) -> bool:
        return False

    def _resolve_model(self, model: str) -> str:
        return model or self._model_id

    async def chat(
        self,
        messages: list[dict],
        *,
        tools: Optional[list[dict]] = None,
        model: str = "",
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        extra: Optional[dict] = None,
    ) -> ChatResponse:
        mod = self._resolve_model(model)

        def _call() -> Optional[dict]:
            return self._gw.call(
                "llm.sync", timeout=_LLM_TIMEOUT,
                modelId=mod if mod else None,
                mode="chat",
                messages=list(messages),
                maxTokens=max_tokens,
            )

        res = await asyncio.to_thread(_call)
        if not isinstance(res, dict):
            # 主后端不可达/降级 → 空响应（tAgent 侧按空内容处理，走兜底/失败判定）
            logger.warning("[KbGatewayLLM] llm.sync 不可用/非 dict: %r", res)
            return ChatResponse(content="", finish_reason="error")
        content = res.get("content") or ""
        usage = res.get("usage") or {}
        return ChatResponse(
            content=content,
            usage=usage if isinstance(usage, dict) else {},
            model=mod,
            finish_reason="stop",
        )

    async def chat_stream(
        self,
        messages: list[dict],
        *,
        tools: Optional[list[dict]] = None,
        model: str = "",
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        extra: Optional[dict] = None,
    ):
        """非流式包装：单次 delta + done（SE 大脑不依赖流式，仅协议完整）。"""
        resp = await self.chat(
            messages, tools=tools, model=model,
            temperature=temperature, max_tokens=max_tokens, extra=extra)
        yield StreamEvent(type="delta", content=resp.content)
        yield StreamEvent(type="done", content="", tool_calls=None,
                          usage=resp.usage or None, finish_reason=resp.finish_reason)


# ── 领域工具适配 ──────────────────────────────────────────────────

class ArchitectToolAdapter(AgentTool):
    """把 architect 既有领域工具适配为 tAgent AgentTool。

    fn 签名：`fn(root, project, **args) -> dict|list|str`（同步，可能触 KB/本地模型）。
    parameters：`{arg: {"type": ..., "description": ...}}`，用于生成 LLM 可见的
    function schema（architect 原工具未声明参数 schema，由宿主在此补）。
    """

    llm_visible = True
    version = "1.0"
    author = "architect"
    category = "architect"

    def __init__(self, name: str, description: str,
                 fn: Callable[..., Any],
                 parameters: Optional[dict] = None,
                 root: Optional[str] = None,
                 project: Optional[str] = None):
        # 净化为 tAgent 安全名（点号→下划线）；handler 绑定与原始名无关
        self.name = sanitize_tool_name(name)
        self.description = description
        self._fn = fn
        self._params = parameters or {}
        self._root = root
        self._project = project

    def to_openai_schema(self) -> Optional[dict]:
        if not self.llm_visible:
            return None
        props = {
            k: {"type": v.get("type", "string"),
                "description": v.get("description", "")}
            for k, v in self._params.items()
        }
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": [k for k, v in self._params.items()
                                 if v.get("required")],
                },
            },
        }

    async def execute(self, **kwargs) -> ToolResult:
        try:
            result = await asyncio.to_thread(
                self._fn, self._root, self._project, **kwargs)
            return ToolResult.ok(result)
        except Exception as e:  # noqa: BLE001
            logger.warning("[ArchitectTool] %s failed: %s", self.name, e)
            return ToolResult.fail(str(e))


# ── SE 组装 ───────────────────────────────────────────────────────

def adapt_domain_tool(tool: dict, root: Optional[str], project: Optional[str],
                      parameters: Optional[dict] = None) -> ArchitectToolAdapter:
    """`{name, description, handler}` → ArchitectToolAdapter。"""
    return ArchitectToolAdapter(
        name=tool["name"],
        description=tool.get("description", ""),
        fn=tool["handler"],
        parameters=parameters,
        root=root, project=project,
    )


def build_architect_se(
    gateway: Any,
    root: Optional[str] = None,
    project: Optional[str] = None,
    model_id: str = "",
    *,
    domain_tools: Optional[list[dict]] = None,
    tool_parameters: Optional[dict] = None,
    project_root: str = "",
    max_turns: int = 8,
    pool=None,
    scheduler=None,
    on_submit: Optional[Callable] = None,
    on_event: Optional[Callable] = None,
) -> ArchitectSEAgent:
    """组装 tAgent SE 大脑（architect 后端用）。

    Args:
      gateway: KbGateway 实例（或 duck-typed `.call(method, **params)`）。
      root/project: architect 项目上下文（透传给领域工具）。
      model_id: SE 模型（空则主后端默认）。
      domain_tools: architect 领域工具 `[{name, description, handler}]`
                    （来自 req_agent.architect_tools 注册表 + handler）。
      tool_parameters: `{tool_name: {arg: {type, description, required}}}`
                       为领域工具补参数 schema（缺省则该工具无参数说明）。
      project_root: 源码根目录（SE 文件探查工具读盘用）。
      pool/scheduler/on_submit: 任务树执行去向（进程内 / 跨进程 runner）。
      on_event: SE 事件回调 `(src, AgentEvent)`。
    """
    llm = KbGatewayLLMClient(gateway, model_id=model_id)
    se = ArchitectSEAgent(
        llm=llm,
        provider=None,  # 文件探查走磁盘（project_root）；KB 探查走注入的领域工具
        project_root=project_root or (root or ""),
        model=model_id,
        max_turns=max_turns,
        pool=pool,
        scheduler=scheduler,
        on_event=on_event,
        on_submit=on_submit,
    )
    # 注入 architect 领域工具（KB 资产/语义检索/依赖图/项目上下文）
    for tool in domain_tools or []:
        name = tool["name"]
        se.tools.register(adapt_domain_tool(
            tool, root, project,
            parameters=(tool_parameters or {}).get(name)))
    return se
