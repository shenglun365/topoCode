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
import inspect
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
    in_thread：True（默认）→ 工具在 worker 线程执行（KB 类工具，无线程亲和）；
    False → 在事件循环线程同步执行（asset.* 提取工具依赖 asset_tools 的
    thread-local 提取上下文/facts，必须与 set_extraction_context 同线程）。
    """

    llm_visible = True
    version = "1.0"
    author = "architect"
    category = "architect"

    def __init__(self, name: str, description: str,
                 fn: Callable[..., Any],
                 parameters: Optional[dict] = None,
                 root: Optional[str] = None,
                 project: Optional[str] = None,
                 in_thread: bool = True):
        # 净化为 tAgent 安全名（点号→下划线）；handler 绑定与原始名无关
        self.name = sanitize_tool_name(name)
        self.description = description
        self._fn = fn
        self._params = parameters or {}
        self._root = root
        self._project = project
        self._in_thread = in_thread

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

    def _invoke(self, kwargs: dict) -> Any:
        """按 req_agent.run_arch_tool 约定调用：root/project 按签名注入，其余关键字透传。"""
        params = inspect.signature(self._fn).parameters
        kw = dict(kwargs)
        if "root" in params and "root" not in kw:
            kw["root"] = self._root
        if "project" in params and "project" not in kw:
            kw["project"] = self._project
        return self._fn(**kw)

    async def execute(self, **kwargs) -> ToolResult:
        try:
            if self._in_thread:
                result = await asyncio.to_thread(self._invoke, kwargs)
            else:
                result = self._invoke(kwargs)  # 同线程同步执行（thread-local 亲和）
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


# 只读探查工具参数 schema（供 LLM 生成 [TOOL_CALL] 参数；root/project 由适配器注入）
TOOL_PARAMS = {
    "project.ctx": {},
    "kb.asset.search": {
        "text": {"type": "string", "description": "检索关键词", "required": True},
        "preferred": {"type": "array", "description": "首选资产 id 列表"},
    },
    "kb.baseline": {},
    "kb.graph": {
        "comp_ids": {"type": "array", "description": "组件 id 列表", "required": True},
    },
    "kb.code_mappings": {
        "asset_ids": {"type": "array", "description": "资产 id 列表", "required": True},
    },
    "asset.semantic.search": {
        "text": {"type": "string", "description": "语义检索关键词"},
        "kind": {"type": "string",
                 "description": "类别 structure/behavior/rule/contract"},
    },
}


def architect_domain_tools(root, project, tool_names=None):
    """从 req_agent 注册表取领域工具 `[{name, description, handler}]`（惰性导入，避免环）。"""
    from . import req_agent
    names = list(tool_names) if tool_names else list(TOOL_PARAMS.keys())
    out = []
    for name in names:
        entry = req_agent._ARCH_TOOLS.get(name)
        if entry:
            out.append({"name": name, "description": entry.get("description", ""),
                        "handler": entry["handler"]})
    return out


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


# ── SE 任务树生成（替换 execution._build_task_tree 的机械拆分）────────

_STATUS_MAP = {
    "running": "in-progress", "done": "done", "failed": "blocked",
    "blocked": "blocked", "stale": "pending", "skipped": "pending",
}


def _req_text(reqs) -> str:
    parts = [f"【{r.get('title', '')}】{r.get('desc', '')}" for r in reqs]
    return "\n\n".join(p for p in parts if p.strip(" 【】")) or "（无需求文本）"


def _analysis_text(reqs) -> str:
    parts = []
    for r in reqs:
        a = r.get("analysis") or {}
        bits = []
        if a.get("assessmentSummary"):
            bits.append(str(a["assessmentSummary"]))
        if a.get("functionalScope"):
            bits.append("功能范围: " + ", ".join(map(str, a["functionalScope"])))
        if a.get("implementationPath"):
            bits.append("实现路径: " + str(a["implementationPath"]))
        if bits:
            parts.append(f"[{r.get('title', '')}]\n" + "\n".join(bits))
    return "\n\n".join(parts) or "（无分析结论）"


def _design_text(reqs) -> str:
    import json as _json
    parts = []
    for r in reqs:
        d = r.get("design")
        if isinstance(d, dict):
            d = d.get("content") or d.get("doc") or d.get("markdown") \
                or _json.dumps(d, ensure_ascii=False)
        if d:
            parts.append(f"[{r.get('title', '')}]\n{d}")
    return "\n\n".join(parts)


def _node_fe(n) -> dict:
    return {
        "id": n.id, "title": n.title, "kind": n.kind,
        "status": _STATUS_MAP.get(n.status, "pending"),
        "estMin": n.est_min, "context": list(n.context), "files": list(n.files),
        "dependsOn": list(n.depends_on),
        "children": [_node_fe(c) for c in n.children],
    }


def _tree_to_frontend(tree) -> dict:
    """CodingTaskTree → 前端 TaskNode 形状（est_min→estMin，状态映射，保留 dependsOn）。"""
    roots = tree.roots
    if len(roots) == 1:
        return _node_fe(roots[0])
    total = sum(r.est_min for r in roots)
    return {"id": "tp-se", "title": "任务方案", "kind": "epic", "status": "pending",
            "estMin": total, "context": [], "files": [], "dependsOn": [],
            "children": [_node_fe(r) for r in roots]}


def _reid_tree(node: dict, prefix: str = "se") -> dict:
    """重映射为唯一 id（LLM 生成的 id 可能重复/不稳定），同步 dependsOn 引用。"""
    old_to_new: dict = {}
    counter = [0]

    def _assign(n):
        old = n["id"]
        counter[0] += 1
        new = f"{prefix}-{counter[0]:04d}"
        # 重复旧 id：仅首个映射生效（后续同 id 节点复用首映射，保持依赖一致）
        old_to_new.setdefault(old, new)
        n["id"] = old_to_new[old]
        for c in n.get("children") or []:
            _assign(c)

    def _fix_deps(n):
        n["dependsOn"] = [old_to_new.get(d, d) for d in n.get("dependsOn") or []]
        for c in n.get("children") or []:
            _fix_deps(c)

    _assign(node)
    _fix_deps(node)
    return node


async def build_task_tree_se(reqs, root=None, project=None, model_id: str = "",
                             gateway: Any = None):
    """SE 大脑生成任务树（显式 depends_on）→ 前端 TaskNode 形状。

    复用需求已产出的 analysis/design 文本作为 SE 输入；plan 阶段 SE 仍跑 agentic
    循环（可用注入的 KB/代码探查工具核实）。失败返回 (None, problems)。
    """
    from .kb_gateway import get_gateway
    gw = gateway or get_gateway()
    se = build_architect_se(
        gw, root=root, project=project, model_id=model_id,
        domain_tools=architect_domain_tools(root, project),
        tool_parameters=TOOL_PARAMS,
        project_root=root or "",
    )
    result = await se.plan(_req_text(reqs), _analysis_text(reqs), _design_text(reqs))
    if result.tree is None:
        return None, list(result.problems or [])
    return _reid_tree(_tree_to_frontend(result.tree)), []


# ── 任务树提交 runner（A1：SE.execute → on_submit → runner）──────

# 前端 TaskNode 状态 → CodingTaskNode 状态（_tree_to_frontend/_STATUS_MAP 的逆映射）
_FE_STATUS_REVERSE = {
    "in-progress": "running", "done": "done", "blocked": "blocked",
    "pending": "pending", "ready": "ready",
}


def frontend_tree_to_coding(node: dict):
    """前端 TaskNode 形状(camelCase) → CodingTaskTree(snake_case, {roots:[...]}).

    `_tree_to_frontend` 的逆操作：把 DB 里用户确认的树还原为 runner 需要的
    `CodingTaskTree`（经 `CodingTaskTree.from_dict` 校验结构）。
    """
    from topocode_agent.orchestration import CodingTaskTree

    def _conv(n: dict) -> dict:
        return {
            "id": n["id"],
            "title": n.get("title", ""),
            "kind": n.get("kind", "task"),
            "status": _FE_STATUS_REVERSE.get(n.get("status", "pending"), "pending"),
            "depends_on": list(n.get("dependsOn") or []),
            "context": list(n.get("context") or []),
            "files": list(n.get("files") or []),
            "est_min": n.get("estMin", 0),
            "source_hash": n.get("sourceHash", ""),
            "children": [_conv(c) for c in n.get("children") or []],
        }
    return CodingTaskTree.from_dict({"roots": [_conv(node)]})


def make_runner_on_submit(runner=None):
    """构建 `on_submit(tree: CodingTaskTree, context: dict) -> tree_id` 回调。

    经 RunnerGateway 把树提交给 runner(:3458)。on_submit 是**同步**回调
    （`se.execute` 同步调用）→ 内部为阻塞 HTTP POST，调用方应以
    `asyncio.to_thread` 包裹 `se.execute` 以免阻塞事件循环。
    runner 不可达返回 None（`se.execute` 透传，调用方据此报 502）。
    """
    from .runner_gateway import get_runner
    r = runner or get_runner()

    def _submit(tree, context):
        return r.submit_tree(tree.to_dict(), context or {})
    return _submit


def make_se_context(reqs, root: str, project: Optional[str],
                    task: Optional[dict] = None) -> dict:
    """提交 runner 的树级 context（str/list 值进 coding prompt L1 简报）。"""
    ctx = {
        "requirement": _req_text(reqs),
        "project": project or "",
        "root": root or "",
    }
    if task:
        if task.get("taskBranch"):
            ctx["branch"] = task["taskBranch"]
        if task.get("baseCommit"):
            ctx["baseCommit"] = task["baseCommit"]
    return ctx


# ── 哈希失效重判（A3：blocked_stale → se.rejudge → 再确认 → PUT+rejudge+run）──

def stale_node_ids(runner_tree_dict: dict) -> list:
    """从 runner 树(snake_case)提取 stale 节点 id 列表。"""
    out: list = []

    def _walk(n: dict) -> None:
        if n.get("status") == "stale":
            out.append(n["id"])
        for c in n.get("children") or []:
            _walk(c)
    for r in runner_tree_dict.get("roots") or []:
        _walk(r)
    return out


def seed_runner_tree(se, tree_id: str, runner_tree_dict: dict):
    """跨进程重判：把 runner 侧当前树注入 SE，使 `se.rejudge` 能读到 old_tree。

    跨进程(on_submit)执行时 SE 本地 `_trees` 不含该树(树在 runner)，
    rejudge 依赖 `self._trees.get(tree_id)` 构建失效清单/原树上下文。
    """
    from topocode_agent.orchestration import CodingTaskTree
    se._trees[tree_id] = CodingTaskTree.from_dict(runner_tree_dict)
    return se._trees[tree_id]
