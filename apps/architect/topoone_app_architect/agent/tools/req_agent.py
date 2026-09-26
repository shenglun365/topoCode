"""需求分析 agent —— architect 自持的 harness / skills / tools。

三层结构(architect 进程内自持，不依赖主后端 provider 注册)：
  - skills : 需求分析专属技能元数据(经 @register_architect_skill 注册，供 harness 编排与 MCP 记录)。
  - tools  : 知识库检索工具(经 KB `/zmq/architecture.model` 拉真实架构资产 + kb_gateway/MCP)。
  - harness: req_harness.clarify / collect —— 组装 prompt → `llm.sync`(KbGateway 转发主后端
             ai chat 能力)→ 结构化产出(澄清问题 / RequirementAnalysis)。

LLM 复用通道：`KbGateway.call('llm.sync', ...)` → 主后端 /zmq/llm.sync(新增)。
模型优先级：architect 侧 `arch_collab_config.llm.modelId`(配置优先)，无则透传空串由主后端
默认模型(is_default)兜底。写日志/用量审计由主后端完成，architect 零状态。

降级语义：任何 KB/LLM 不可达、LLM 未配置、结构化解析失败 → 返回空结构/None，由路由回退
现有 heuristic(requirements.py 既有逻辑)，保持前端 turn 协议不变。
"""
import inspect
import json
import logging
import os
import re
import typing
from typing import Any, Callable, Dict, List, Optional

from ... import store

from ...agent.cognition.prompt import TOOL_FEED_PREFIX as _TOOL_FEED_PREFIX
logger = logging.getLogger(__name__)

from ...agent.planning.req_spec import (  # noqa: F401,E402
    _SPEC_FIELD_ALIASES,
    _norm_scope_list,
    _repair_json_like,
    _spec_snapshot,
    _sync_analysis_cache,
    apply_spec_payload,
    extract_proposal_fence,
    extract_spec_payload,
    is_spec_payload,
    parse_scope_files,
    repair_spec_payload_format,
    strip_proposal_fence,
)
from ...agent.planning.task_plan import (  # noqa: F401,E402
    extract_task_fence, strip_task_fence)
from ...agent.collab.cards import (  # noqa: F401,E402
    extract_choices_fence, strip_choices_fence,
    extract_choices_json_fence, resolve_choices_payload)

from ...agent.tools.protocol import (  # noqa: F401,E402
    _FENCE,
    _TOOL_CALL_BLOCK,
    _TOOL_CALL_CLOSE,
    _TOOL_CALL_OPEN,
    _clean_block,
    _json_object_spans,
    _parse_tool_payload,
    _tool_call_regions,
    extract_tool_calls,
    strip_tool_blocks,
    tool_parse_audit,
)
from ...agent.tools.registry import (  # noqa: F401,E402
    _ARCHIVED_DENY_TOOLS,
    _ARCH_SKILLS,
    _ARCH_TOOLS,
    _RETIRED_TOOLS,
    architect_skills,
    architect_tools,
    register_architect_skill,
    register_architect_tool,
)

# ── Skills/Tools 注册表与工具协议: 实现迁至 agent.tools(P1) ──







# ── 工具审计结构预留(WS6-E): 完整 record schema 定义, 存储/UI 不在本期 ──
# schema: {ts, tool, argsDigest, ok, resultDigest, conversationId, reqId,
#          projectId, modelId, stage(工具推导: design/implement/evaluate/accept), latencyMs}
# 未来落库: arch_tool_audit 表 / 复用 arch_mcp_calls; WS7 提炼器以此为原料源之一。
def record_tool_audit(name: str, arguments: Dict[str, Any], ok: bool,
                      result_summary: str = "", latency_ms: float = 0.0,
                      project: str = "") -> Dict[str, Any]:
    """工具调用审计记录(结构接口预留)。当前仅 debug 日志, 不落存储。"""
    try:
        from ... import ctx as _actx
        conv_id = _actx.get_conv() or ""
        req_id = _actx.get_req() or ""
    except Exception:
        conv_id = req_id = ""
    rec = {
        "ts": _now_ms(), "tool": name,
        "argsDigest": _digest(arguments), "ok": bool(ok),
        "resultDigest": _digest(result_summary),
        "conversationId": conv_id, "reqId": req_id,
        "projectId": (project or ""), "modelId": get_model_preference(),
        "latencyMs": round(latency_ms, 1),
    }
    logger.debug("[tool-audit] %s", json.dumps(rec, ensure_ascii=False)[:400])
    try:
        from ...store.base import _insert_into, _db
        _insert_into(_db(), "arch_tool_audit", {
            "ts": rec["ts"], "tool": name,
            "argsDigest": rec["argsDigest"], "ok": rec["ok"],
            "resultDigest": rec["resultDigest"],
            "conversationId": conv_id, "reqId": req_id,
            "projectId": rec["projectId"], "modelId": rec["modelId"],
            "latencyMs": rec["latencyMs"]})
    except Exception as e:  # noqa: BLE001 — 审计不碍业务
        logger.debug("[tool-audit] persist skipped: %s", e)
    return rec


def _digest(v: Any, limit: int = 120) -> str:
    s = json.dumps(v, ensure_ascii=False, default=str) if not isinstance(v, str) else v
    s = " ".join((s or "").split())
    return s[:limit]


def _now_ms() -> int:
    import time as _t
    return int(_t.time() * 1000)


def _unwrap_hint(hint):
    """Optional[X] → X；其余原样。"""
    if typing.get_origin(hint) is typing.Union:
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return hint


def _coerce_args(fn: Callable, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """按 handler 签名注解收敛模型入参类型(小模型参数形状不稳的确定性兜底)。

    两条入参链([TOOL_CALL] / ```proposal 围栏)的 JSON 类型都原样到达这里；
    小模型常把 str 传成 dict/对象、把 list 传成 str。按注解归一：
    - str       ← list(逐项字符串化按行拼) / dict(json 串) / 标量(str())
    - List[str] ← str(splitlines 剥列表符) / dict([json 串]) / 标量([str()]) —— 复用 _md_lines
    - List[dict]← str(json 解析, 败则 [{'value': s}]) / dict([dict])
    - int       ← str(int(float)) 失败回退默认 / float 截断
    - bool      ← 'true'/'1' 等
    收敛事件记入 llm_dataset(arg_coerce)。返回新 kwargs，不改调用方原 dict。
    """
    try:
        hints = typing.get_type_hints(fn)
    except Exception:  # noqa: BLE001
        hints = {}
    if not kwargs:
        return kwargs
    out = dict(kwargs)
    coerced = []
    for key, val in kwargs.items():
        hint = _unwrap_hint(hints.get(key))
        if hint is None or val is None:
            continue
        origin = typing.get_origin(hint)
        if hint is list:  # 裸 list 注解按 List[str] 语义收敛
            origin = list
        try:
            if origin is None and hint is str:
                if isinstance(val, str):
                    continue
                if isinstance(val, (list, tuple)):
                    out[key] = "\n".join(_md_lines(list(val)))
                elif isinstance(val, dict):
                    out[key] = json.dumps(val, ensure_ascii=False)
                else:
                    out[key] = str(val)
                coerced.append((key, type(val).__name__, "str"))
            elif origin is list:
                item_t = (typing.get_args(hint) or (None,))[0]
                if item_t is dict or typing.get_origin(item_t) is dict:
                    if isinstance(val, str):
                        try:
                            parsed = json.loads(val)
                            out[key] = parsed if isinstance(parsed, list) else [{"value": val}]
                        except Exception:  # noqa: BLE001
                            out[key] = [{"value": val}]
                    elif isinstance(val, dict):
                        out[key] = [val]
                    continue
                if isinstance(val, str):
                    out[key] = _md_lines(val)
                elif isinstance(val, dict):
                    out[key] = [json.dumps(val, ensure_ascii=False)]
                elif isinstance(val, (int, float, bool)):
                    out[key] = [str(val)]
                elif isinstance(val, (list, tuple)):
                    continue
                else:
                    out[key] = _md_lines(val)
                coerced.append((key, type(val).__name__, "list"))
            elif hint is int:
                if isinstance(val, bool):
                    out[key] = int(val)
                    coerced.append((key, "bool", "int"))
                elif isinstance(val, str):
                    out[key] = int(float(val.strip()))
                    coerced.append((key, "str", "int"))
                elif isinstance(val, float):
                    out[key] = int(val)
                    coerced.append((key, "float", "int"))
            elif hint is bool and isinstance(val, str):
                out[key] = val.strip().lower() in ("true", "1", "yes", "on", "是")
                coerced.append((key, "str", "bool"))
        except (TypeError, ValueError):
            # int(float("abc")) 等不可救收敛 → 保持原值，让工具自身校验给模型可读错误
            continue
    if coerced:
        try:
            from ...agent.reflection import dataset as llm_dataset
            llm_dataset.record("arg_coerce", tool=getattr(fn, "__name__", "?"),
                               items=[{"param": k, "from": a, "to": b}
                                      for k, a, b in coerced])
        except Exception:  # noqa: BLE001
            pass
        logger.info("[arg-coerce] %s: %s", getattr(fn, "__name__", "?"),
                    ", ".join(f"{k}:{a}→{b}" for k, a, b in coerced))
    return out


# ── 分析挡位(会话级 analysisMode) → 挡位体系已迁 agent/governance/gears.py
#    (环节十二a, T0-T4 数据驱动); 旧二值工具门禁已随流程缓解层拆除——
#    挡位行为差异全部走提示词面(orchestrator 注入 architect_note)。
# 规约状态机工具: v2 默认退役(模型面不可见)——strict 挡恢复启用, quick 挡保持退役
_SPEC_TOOLS = {"req.propose", "req.amend"}


def run_arch_tool(name: str, arguments: Dict[str, Any],
                  root: Optional[str], project: Optional[str],
                  internal: bool = False) -> Dict[str, Any]:
    """执行 architect 注册工具；缺失/异常返回 {error}。root/project 按签名自动注入。

    入参先经 _coerce_args 按签名注解类型收敛(小模型 dict/list 形状兜底)；
    执行环带审计 hook(WS6-E 结构预留)。
    """
    entry = _ARCH_TOOLS.get(name)
    if not entry:
        if name in _RETIRED_TOOLS:
            return {"error": _RETIRED_TOOLS[name]}
        return {"error": f"未知工具: {name}"}
    # 退役工具只拦模型面调用; internal=True 为系统确定性路径放行。
    # 规约工具(req.propose/req.amend)不退役——需求卡按需出现, 挡位门禁已拆(cv-175)。
    if name in _RETIRED_TOOLS and not internal:
        if name not in _SPEC_TOOLS:
            return {"error": _RETIRED_TOOLS[name]}
    # PR1 归档只读: 归档会话上拒绝动作类工具(落库/定稿/指派); 检索/读取/提炼放行
    if name in _ARCHIVED_DENY_TOOLS:
        try:
            from ... import ctx as _ctx
            conv_id = _ctx.get_conv()
            if conv_id:
                from ... import store as _store
                conv = _store.ConversationsStore.get(conv_id)
                if conv and (conv.get("status") or "active") == "archived":
                    return {"error": f"会话已归档(只读)：{name} 不可执行。可读取/复制/提炼。"}
        except Exception:  # noqa: BLE001
            pass
    # cv-187: 未关联 KB(降级)项目 → kb.* 工具执行面拦截(与提示面裁剪同口径),
    # 杜绝静默空结果误导模型; internal=True 系统确定性路径放行。
    if name in KB_FACE_TOOLS and not internal:
        try:
            from ...arch_routes.project import kb_degraded as _kb_deg
            if _kb_deg(root, project):
                return {"error":
                        "当前项目未关联知识库(KB)，kb.* 工具不可用。"
                        "可改用本地能力: asset.semantic.search / map.overview / "
                        "map.assets / code.read_symbols；或在项目总览关联 KB 后重试。"}
        except Exception:  # noqa: BLE001
            pass
    fn = entry["handler"]
    kwargs = _coerce_args(fn, dict(arguments or {}))
    params = inspect.signature(fn).parameters
    if "root" in params and "root" not in kwargs:
        kwargs["root"] = root
    if "project" in params and "project" not in kwargs:
        kwargs["project"] = project
    t0 = _now_ms()
    try:
        result = fn(**kwargs)
    except TypeError as e:
        # cv-188: 模型乱传参数名(如 req.amend 传 title)——裸 TypeError 空转回合,
        # 给出支持的参数清单让模型一轮自纠。
        import re as _re
        m = _re.search(r"unexpected keyword argument '(\w+)'", str(e))
        supported = ", ".join(params) + "（root/project 自动注入, 无需传）"
        bad = f"参数 {m.group(1)} 不受支持" if m else f"参数形状错误({e})"
        record_tool_audit(name, arguments, False, str(e),
                          latency_ms=_now_ms() - t0, project=project or "")
        return {"error": f"{name} {bad}。支持的参数: {supported}"}
    try:
        ok = not (isinstance(result, dict) and result.get("error"))
        record_tool_audit(name, arguments, ok,
                          tool_result_text(name, result, limit=200),
                          latency_ms=_now_ms() - t0, project=project or "")
        try:
            from ...agent.reflection import dataset as _lds
            _lds.record("tool_call", tool=name, ok=ok, args=arguments,
                        result=tool_result_text(name, result, limit=1200),
                        latencyMs=_now_ms() - t0, project=project or "")
        except Exception:  # noqa: BLE001
            pass
        return result if isinstance(result, dict) else {"result": result}
    except Exception as e:
        logger.exception("[req_agent] tool %s failed", name)
        record_tool_audit(name, arguments, False, str(e),
                          latency_ms=_now_ms() - t0, project=project or "")
        try:
            from ...agent.reflection import dataset as _lds
            _lds.record("tool_call", tool=name, ok=False, args=arguments,
                        error=str(e), latencyMs=_now_ms() - t0,
                        project=project or "")
        except Exception:  # noqa: BLE001
            pass
        return {"error": f"{name} 执行失败: {e}"}


def tool_result_text(name: str, result: Any, limit: int = 3000) -> str:
    """工具结果 → 文本(截断，供下一轮 LLM 上下文)。"""
    if isinstance(result, dict) and "error" in result:
        return str(result.get("error"))
    # 纯 Markdown 产物(map.*/probe 等工具)直通，免 json 转义噪音(\n 换行符等)
    if isinstance(result, dict) and set(result.keys()) == {"markdown"}:
        md = str(result.get("markdown") or "")
        return md if len(md) <= limit else md[:limit] + "...(truncated)"
    s = json.dumps(result, ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[:limit] + "...(truncated)"


# ── 工具实现(M3 拆分): 按域迁 agent/tools/impl/*(注册随定义点, 行为等价) ──
# 保留名 re-export: 既有内部调用(scope_probe._kb_hits 等)与测试接缝不断;
# mcp 出向三件套留驻本文件(_kb_gateway 打桩接缝)。
from ...agent.tools.impl.kb import (_model, _model_assets, _model_code_mappings,
                                   _project_degraded, tool_kb_asset_search,
                                   tool_kb_baseline, tool_kb_code_mappings,
                                   tool_kb_graph, tool_project_ctx)
from ...agent.cognition.prompt import KB_FACE_TOOLS
from ...agent.tools.impl.map import (tool_map_assets, tool_map_component,
                                    tool_map_graph, tool_map_overview,
                                    tool_map_rules)
from ...agent.tools.impl.semantic import (tool_code_read_symbols,
                                         tool_semantic_detail,
                                         tool_semantic_extract,
                                         tool_semantic_mappings,
                                         tool_semantic_reconcile,
                                         tool_semantic_refresh,
                                         tool_semantic_search,
                                         tool_semantic_stats)
from ...agent.tools.impl.asset import (tool_asset_semantic_merge,
                                      tool_asset_semantic_save,
                                      tool_asset_semantic_split,
                                      tool_asset_semantic_update,
                                      tool_contract_propose,
                                      tool_convention_propose)
from ...agent.tools.impl.diagram import tool_diagram_build, tool_diagram_validate


# ── MCP 出向工具(经 MCP server 转发，供 plan agent 调用开放/外部 MCP 工具) ──

_MCP_TOOLS_CACHE: Dict[str, Any] = {"ts": 0.0, "tools": []}
_MCP_TOOLS_TTL = 60.0  # 秒：列工具带 TTL 缓存，避免每回合网络往返


def _mcp_tool_list() -> List[Dict[str, Any]]:
    """列 MCP 可用工具(GET /v1/tools，带 TTL 缓存)。不可达返回缓存/[]。"""
    import time
    now = time.time()
    if _MCP_TOOLS_CACHE["tools"] and now - _MCP_TOOLS_CACHE["ts"] <= _MCP_TOOLS_TTL:
        return _MCP_TOOLS_CACHE["tools"]
    from ...agent.governance.timeouts import get as _timeout_of
    tools = _kb_gateway().tools(timeout=_timeout_of("kb_mcp_tools")) or []
    if tools:
        _MCP_TOOLS_CACHE["ts"] = now
        _MCP_TOOLS_CACHE["tools"] = tools
    return tools


def _mcp_doc() -> str:
    """MCP 开放工具清单(动态)：注入系统提示，供 plan agent 经 mcp.call 调用。"""
    tools = _mcp_tool_list()
    if not tools:
        return ("MCP(mcp.call)：当前无可用 MCP 工具(MCP server 不可达或未注册工具)，"
                "如需外部工具请先在「外部调用」页配置。")
    lines = ["MCP 开放工具(经 mcp.call 调用，参数 {\"tool\":\"<名>\",\"params\":{…}})："]
    for t in tools[:20]:
        lines.append(f"- {t.get('name', '')}: {t.get('description', '')}")
    return "\n".join(lines)


@register_architect_tool(
    "mcp.call",
    "调用 MCP 开放工具(经 MCP server 转发，可调用外部/注册的工具)。"
    "参数 {\"tool\": \"<mcp工具名>\", \"params\": {…工具参数}}。返回 {ok, tool, call|error}。",
)
def tool_mcp_call(tool: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not tool:
        return {"ok": False, "error": "缺少 MCP 工具名(tool)"}
    from ...agent.governance.timeouts import get as _timeout_of
    result = _kb_gateway().query(tool, timeout=_timeout_of("kb_mcp_call"), **(params or {}))
    if result is None:
        return {"ok": False, "tool": tool, "error": "MCP 不可达或超时"}
    return result


# ── 需求分析工具(plan 结论 → 结构化分析) ────────────────

def _md_lines(text) -> List[str]:
    """Markdown 行/JSON 数组 → 数组(剥列表符/序号，去空行)。

    容忍模型把 allowedScopeMd 等字段传成 JSON 数组(自然行为)——逐项字符串化后
    同样剥前缀；非字符串标量(数字等)也直接字符串化。
    """
    import re as _re
    if isinstance(text, (list, tuple)):
        items: List[Any] = list(text)
    elif isinstance(text, str):
        items = text.splitlines()
    else:
        items = [str(text)] if text not in (None, "") else []
    out: List[str] = []
    for ln in items:
        t = _re.sub(r"^\s*(?:[-*+]|\d+[.)])\s*", "", str(ln)).strip()
        if t:
            out.append(t)
    return out


# ── 规约快照/边界解析(生命周期重构: 版本链语义) ──────────────────────

# ── 占位正文门禁(cv-224) ──────────────────────────────────────────────
# 模型遵从混乱时会把「先澄清后落卡」执行成落壳卡(requirementMd/designMd
# 为省略号等占位)——确定性拒绝并回喂错误文案, 走既有工具错误自纠环,
# 零 LLM 判分。
_PLACEHOLDER_BODY = {"...", "…", "。。。", "待补充", "待完善", "待定", "todo",
                     "tbd", "n/a", "na", "无", "-", "—"}


def _body_placeholder_error(text: str, label: str, min_len: int = 0) -> str:
    """字段若提供且为占位 → 错误文案(可回喂自纠); 未提供(空)→放行。

    只拦占位符不拦短正文——「修复登录按钮」是合法需求; 「薄」归 gap_matrix
    澄清流(缺口驱动), 硬门禁拦之会误伤(cv 实证: 夹具/真实短诉求均合法)。"""
    t = (text or "").strip()
    if not t:
        return ""
    core = t.rstrip("。.！!？?…").strip()
    if (not core) or core.lower() in _PLACEHOLDER_BODY:
        return (f"{label} 为占位内容——禁止用省略号/「待补充」等占位符落卡；"
                "请给出完整正文，或按澄清指引先向用户提问，不要提交占位卡片。")
    return ""


@register_architect_tool(
    "req.propose",
    "形成/更新需求规约：讨论收敛为明确需求，或设计者要求 生成方案/提炼方案/完善需求 时调用。"
    "用户要求 编写脚本/工具/程序/函数 时**必须先调用本工具**收敛需求"
    "(designMd=技术选型与结构设计)，由 /执行 链路生成代码——"
    "严禁在对话中直接输出成品代码替代需求收敛(代码属于执行产物，不落库无法走执行链路)。"
    "**边界(定位裁决 2026-09-26)**: 信息问询/状态进度/资产检索类回合**禁止调用本工具**"
    "——问什么答什么，不扩大化；仅当用户表达明确行动意图(要建/要改/要修)时才起草。"
    "会话已绑定未完结的需求时默认**更新该需求**(追加新 draft 版本，不新建)；"
    "需要在本会话开启全新需求时传 newRequirement=true。"
    "产出规约见 plan 场景技能文档：designMd 为核心(逻辑与实现细节；为空时执行缺方案依据)，"
    "约束四项(目标/允许范围/禁止改动/验收标准)可按对话留空，不编造。"
    "产出通道二选一：① 输出 [TOOL_CALL] 调用本工具；②(推荐，更可靠) 在回复末尾输出"
    " ```proposal 围栏，内容为本工具参数的 JSON——系统会自动解析落库并发方案卡。"
    "需求提案不用 contract.propose 替代(那是 🧾 期望固化)。"
    "参数：title、requirementMd(需求目标)、designMd(方案)、"
    "allowedScopeMd/forbiddenScopeMd(允许增删改/一定不能动的模块·文件·目录，每行一项，可空)、"
    "acceptanceMd(验收标准，每行一条)、assessmentMd(评估)、estMin(分钟)、priority、"
    "newRequirement(默认 false=更新绑定需求)。",
)


def tool_req_propose(title: str = "", requirementMd: str = "", designMd: str = "",
                     assessmentMd: str = "", priority: str = "P1",
                     estMin: int = 0,
                     allowedScopeMd: str = "", forbiddenScopeMd: str = "",
                     acceptanceMd: str = "", newRequirement: bool = False,
                     root: Optional[str] = None,
                     project: Optional[str] = None) -> Dict[str, Any]:
    from ... import ctx
    from ... import store as _store
    from ...common import _ts
    title = (title or "").strip()
    if not title:
        return {"ok": False, "error": "缺少需求标题"}
    body_err = _body_placeholder_error(requirementMd, "requirementMd") \
        or _body_placeholder_error(designMd, "designMd")
    if body_err:
        return {"ok": False, "error": body_err}
    conv_id = ""
    try:
        conv_id = ctx.get_conv()
    except Exception:
        pass
    allowed = _md_lines(allowedScopeMd)
    forbidden = _md_lines(forbiddenScopeMd)
    acceptance = _md_lines(acceptanceMd)
    # desc 单源契约: 只放需求目标纯文本——方案/边界/验收/评估各有结构化
    # 字段, 指令组装时按节渲染; 此前把全部字段拼进 desc 文本 blob →
    # 与组装层双渲染(双标题/重复分节, cv-181 实证)
    snapshot = _spec_snapshot(title, requirementMd, designMd, allowed,
                              forbidden, acceptance, [], assessmentMd, estMin)

    bound_rid = ""
    try:
        bound_rid = ctx.get_req()
    except Exception:
        pass
    if bound_rid and not newRequirement:
        row = _store.RequirementsStore.get(bound_rid)
        if row and (row.get("doneMark") or 0) != 1:
            entry = _store.RequirementsStore.spec_append(
                bound_rid, snapshot, actor="architect", conv_id=conv_id,
                reason="对话完善规约")
            _store.RequirementsStore.spec_confirm(bound_rid)   # 无草稿态: 更新即就绪
            _sync_analysis_cache(bound_rid, snapshot)
            try:
                log_conv_event(conv_id,
                               f"📝 **需求卡已更新**：`{bound_rid}` → v{entry['ver']}"
                               f"（ready，可直接 `/执行`）",
                               meta={"kind": "specReady", "requirementId": bound_rid,
                                     "ver": entry["ver"], "updated": True,
                                     "spec": _spec_card_payload(
                                         snapshot, str(row.get("priority") or ""))})
            except Exception:  # noqa: BLE001
                pass
            return {"ok": True, "requirementId": bound_rid, "ver": entry["ver"],
                    "updated": True, "title": title,
                    "hint": "需求卡已更新(ready)——点卡片「开始执行」启动, 或直接说\"执行\""}

    req = {
        "id": _store.next_id("RQ"), "kind": "user-story",
        "status": ST.REQ_READY, "title": title,
        "priority": priority if priority in ("P0", "P1", "P2") else "P1",
        "activeVer": 1,
        "specVersions": [{"ver": 1, "state": ST.SPEC_CONFIRMED, "snapshot": snapshot,
                          "source": {"convId": conv_id, "actor": "architect"},
                          "reason": "初始提案", "createdAt": _ts()}],
        "ownerConv": conv_id, "sourceType": "asset-chat",
        "projectId": project or "",
        "sourceConversationId": conv_id, "updatedAt": _ts(), "createdAt": _ts(),
    }
    _store.RequirementsStore.create(req)
    _sync_analysis_cache(req["id"], snapshot)
    # 需求跟踪台账: 需求落库即挂账(生成=done), 失败不阻断需求流
    try:
        from ...store.tracking import emit as _tr_emit
        from ...store.states import TRACK_DONE
        _tr_emit(category="需求",
                 title=str(req.get("title") or req["id"])[:200],
                 content=str(snapshot.get("desc") or "")[:2000],
                 action_type="分析", creator_role="architect",
                 state=TRACK_DONE, result=f"需求卡已创建({req['id']}，ready)",
                 result_state="ok",
                 ref_type="requirement", ref_id=req["id"],
                 conversation_id=conv_id,
                 project_id=str(req.get("projectId") or ""))
    except Exception:  # noqa: BLE001
        pass
    # 回写会话绑定(后端真相源): amend 契约/守卫修复/执行链路依赖 conv.reqId
    if conv_id:
        try:
            _store.ConversationsStore.update(conv_id, {"reqId": req["id"]})
        except Exception as e:  # noqa: BLE001
            logger.warning("[req.propose] conv.reqId 回写失败 conv=%s: %s", conv_id, e)
    # 方案缺失如实提示(不再门禁拦截——执行器自行判断, 信息进任务指令)
    no_design = not str(designMd or "").strip()
    receipt = (f"📝 **需求卡已创建**：`{req['id']}` {title}（ready——点「开始执行」启动，或直接说\"执行\"）")
    if no_design:
        receipt = (f"📝 **需求卡已创建**：`{req['id']}` {title}（ready；"
                   "⚠️ 未包含实现方案——建议直接在对话中说明要补充的方案)")
    try:
        log_conv_event(conv_id, receipt,
                       meta={"kind": "specReady", "requirementId": req["id"],
                             "ver": 1, "noDesign": no_design,
                             "spec": _spec_card_payload(snapshot, priority)})
    except Exception:  # noqa: BLE001
        pass
    hint = "需求卡已创建(ready)——点卡片「开始执行」启动, 或直接说\"执行\""
    if no_design:
        hint += "(⚠️ 方案缺失, 建议直接在对话中说明要补充的方案)"
    return {"ok": True, "requirementId": req["id"], "ver": 1, "updated": False,
            "title": title, "noDesign": no_design, "hint": hint}


@register_architect_tool(
    "req.amend",
    "需求修订(通用)：用户要求 补充需求/完善方案/调整规约 时调用——对会话绑定(或指定)"
    "需求追加新 draft 版本(append-only，历史版本保留可追溯)。"
    "参数均可选——只传需要调整的字段，未传字段沿用当前版本值。"
    "参数：reqId(可选)、designMd(调整后完整方案)、allowedScope[str]、forbiddenScope[str]、"
    "acceptance[str]、functionalScope[str]、requirementMd(需求目标)、"
    "assessmentSummary(str)、reasoning(修订理由, 版本留痕)。",
    params_doc='{"requirementMd": "修订后需求目标(全文, 可选)", '
               '"designMd": "修订后方案(可选)", "acceptance": ["验收条目"], '
               '"allowedScope": ["目录"], "forbiddenScope": ["目录"], '
               '"reasoning": "修订原因"} —— 只传要调整的字段; '
               '标题修订用 {"title": "新标题"}',
)
def tool_req_amend(reqId: str = "", designMd: str = "", requirementMd: str = "",
                   allowedScope: Optional[List[str]] = None,
                   forbiddenScope: Optional[List[str]] = None,
                   acceptance: Optional[List[str]] = None,
                   functionalScope: Optional[List[str]] = None,
                   assessmentSummary: str = "", reasoning: str = "",
                   root: Optional[str] = None,
                   project: Optional[str] = None,
                   **extra) -> Dict[str, Any]:
    # cv-188 别名折叠: 小模型对 amend 形状不稳(实测 title/items/patch/
    # amendmentMd 四种误传), 确定性收编而非裸 TypeError 空转回合。
    ignored: List[str] = []
    for alias in ("amendmentMd", "md", "desc", "content"):
        if extra.get(alias) and not requirementMd:
            requirementMd = str(extra.pop(alias))
        elif alias in extra:
            extra.pop(alias)
            ignored.append(alias)
    if isinstance(extra.get("title"), str) and extra.get("title").strip():
        extra["_title"] = extra.pop("title").strip()
    if isinstance(extra.get("items"), list) and not acceptance:
        acceptance = [str(x) for x in extra.pop("items")]
    elif "items" in extra:
        extra.pop("items")
        ignored.append("items")
    patch = extra.pop("patch", None)
    if isinstance(patch, dict):
        _known = {"title", "desc", "designMd", "assessmentSummary",
                  "acceptance", "allowedScope", "forbiddenScope", "functionalScope"}
        ignored.extend(k for k in patch if k not in _known)
        if isinstance(patch.get("title"), str) and patch["title"].strip():
            extra["_title"] = patch["title"].strip()
        if isinstance(patch.get("desc"), str) and patch["desc"].strip() and not requirementMd:
            requirementMd = patch["desc"]
        if isinstance(patch.get("designMd"), str) and patch["designMd"].strip() and not designMd:
            designMd = patch["designMd"]
        if (isinstance(patch.get("assessmentSummary"), str)
                and patch["assessmentSummary"].strip() and not assessmentSummary):
            assessmentSummary = patch["assessmentSummary"]
        if isinstance(patch.get("acceptance"), list) and acceptance is None:
            acceptance = patch["acceptance"]
        if isinstance(patch.get("allowedScope"), list) and allowedScope is None:
            allowedScope = patch["allowedScope"]
        if isinstance(patch.get("forbiddenScope"), list) and forbiddenScope is None:
            forbiddenScope = patch["forbiddenScope"]
        if isinstance(patch.get("functionalScope"), list) and functionalScope is None:
            functionalScope = patch["functionalScope"]
    extra.pop("title", None)
    for k in list(extra):
        if k != "_title":
            ignored.append(k)
    # 占位门禁前置于绑定解析(cv-225): 载荷问题(占位)比路由问题(未绑定)
    # 更具指导性——先拦占位, 避免模型在错误信号间挣扎。
    body_err = _body_placeholder_error(requirementMd, "requirementMd") \
        or _body_placeholder_error(designMd, "designMd")
    if body_err:
        return {"ok": False, "error": body_err}
    from ... import ctx
    req_id = (reqId or "").strip() or ctx.get_req()
    if not req_id:
        # 回退读会话绑定: req.propose 与 amend 同轮调用时 ctx.req 尚未回写(下一轮生效)
        try:
            cid = ctx.get_conv()
            if cid:
                c = store.ConversationsStore.get(cid) or {}
                req_id = (c.get("reqId") or "").strip()
        except Exception:  # noqa: BLE001
            pass
    if not req_id:
        return {"ok": False, "error":
                "当前会话未绑定需求，无需修订——若要创建新需求请调用 req.propose "
                "并给出完整需求内容；若处于澄清轮，请先按指引向用户提问。"}
    row = store.RequirementsStore.get(req_id)
    if not row:
        return {"ok": False, "error": f"需求 {req_id} 不存在"}
    if (row.get("doneMark") or 0) == 1:
        return {"ok": False, "error": f"{req_id} 已完结；补充需求请新建需求(req.propose newRequirement=true)"}
    active = store.RequirementsStore.spec_active(req_id) or {}
    snap = dict(active.get("snapshot") or {})
    changed = []
    if extra.get("_title"):
        snap["title"] = str(extra["_title"])[:200]
        changed.append("标题")
    if requirementMd:
        snap["desc"] = requirementMd
        changed.append("需求目标")
    if designMd:
        snap["designMd"] = designMd
        changed.append("方案")
    if allowedScope is not None:
        snap["allowedScope"] = _md_lines(allowedScope)[:40]
        changed.append("允许改动范围")
    if forbiddenScope is not None:
        snap["forbiddenScope"] = _md_lines(forbiddenScope)[:40]
        changed.append("禁止改动范围")
    if acceptance is not None:
        snap["acceptance"] = _md_lines(acceptance)[:40]
        changed.append("验收标准")
    if functionalScope is not None:
        snap["functionalScope"] = _md_lines(functionalScope)[:40]
        changed.append("需求目标清单")
    if assessmentSummary:
        snap["assessmentSummary"] = str(assessmentSummary)[:500]
        changed.append("评估摘要")
    if not changed:
        return {"ok": False, "error": "未提供任何修订字段(参数均可选, 至少传一项)"}
    conv_id = ""
    try:
        conv_id = ctx.get_conv()
    except Exception:
        pass
    entry = store.RequirementsStore.spec_append(
        req_id, snap, actor="architect", conv_id=conv_id,
        reason=str(reasoning or "")[:200])
    _sync_analysis_cache(req_id, snap)
    try:
        log_conv_event(conv_id,
                       f"✏️ **需求卡已修订**（{req_id} → v{entry['ver']} ready）：{'、'.join(changed)}"
                       + (f" —— {str(reasoning)[:120]}" if reasoning else ""),
                       meta={"kind": "specReady", "requirementId": req_id,
                             "ver": entry["ver"], "updated": True,
                             "spec": _spec_card_payload(snap)})
    except Exception:  # noqa: BLE001
        pass
    hint = "修订已就绪(ready)——点「开始执行」按新版本执行"
    if ignored:
        hint += f"；已忽略不支持的参数: {','.join(sorted(set(ignored)))}"
    return {"ok": True, "reqId": req_id, "ver": entry["ver"], "amended": changed,
            "hint": hint}


# ── 会话只读工具(PR-D: 归档会话可被 agent 读取/引用; 不在任何动作黑名单) ──

@register_architect_tool(
    "conv.read",
    "读取会话(含归档)用于回顾/提炼/引用到新会话: 返回标题/状态/角色/最近消息。"
    "归档会话只读——历史回顾、交接引用、提炼总结用本工具, 不能向其发送消息。"
    "参数：convId(会话 id)、limit?(消息条数, 默认 20)。",
)
def tool_conv_read(convId: str = "", limit: int = 20) -> Dict[str, Any]:
    from ... import store as _store
    cid = (convId or "").strip()
    if not cid:
        return {"error": "缺少 convId"}
    conv = _store.ConversationsStore.get(cid)
    if not conv:
        return {"error": f"会话不存在: {cid}"}
    msgs = _store.ConversationsStore.messages(cid, limit=max(1, min(int(limit or 20), 100)))
    return {
        "ok": True, "convId": cid,
        "title": conv.get("title") or "", "kind": conv.get("kind") or "",
        "lifecycle": conv.get("status") or "active",
        "roleId": conv.get("roleId") or "architect",
        "summary": (conv.get("summary") or "")[:400],
        "messages": [
            {"role": m.get("role"), "content": (m.get("content") or "")[:600]}
            for m in msgs[-int(limit or 20):]
        ],
        "summaryText": f"会话 {cid}「{conv.get('title') or ''}」({conv.get('status')})共 {len(msgs)} 条消息已读取",
    }


# ── 澄清提问工具(plan agent → 用户，经 broker 总线，「需要你输入」可见) ──

# ── LLM 通道: 实现迁至 agent.cognition.llm(P1), 此处 re-export 兼容存量引用 ──

from ...store import states as ST
from ...agent.cognition import prompt as _disc  # noqa: F401,E402
from ...agent.cognition.llm import (  # noqa: F401,E402
    _LLM_CALL_TIMEOUT,
    _MAX_TOKENS_KEY,
    _MODEL_KEY,
    _kb_gateway,
    get_max_tokens_preference,
    get_model_preference,
    llm_chat_start,
    llm_sync,
    set_max_tokens_preference,
    set_model_preference,
)


def log_conv_event(conv_id: str, text: str, meta: Optional[dict] = None) -> None:
    """委托 collab.cards.land(卡片落流唯一出口, cv-175 规范化)。"""
    from ...agent.collab import cards as _cards
    meta = dict(meta or {})
    _cards.land(conv_id, text, kind=meta.pop("kind", None),
                project_id="", **meta)


def _spec_card_payload(snap: dict, priority: str = "") -> dict:
    """spec 卡自包含规约载荷(cv-215): 卡片携带**本版**规约全文——历史版本卡
    即历史快照(渲染不依赖台账当前版), 前端 specCard 优先读卡内载荷。
    字段=台账 _spec_snapshot 全量投影(截断口径一致), 快照不缩略。"""
    s = snap or {}
    return {
        "title": str(s.get("title") or ""),
        "priority": str(priority or ""),
        "desc": str(s.get("desc") or ""),
        "design": str(s.get("designMd") or ""),
        "allowedScope": list(s.get("allowedScope") or []),
        "forbiddenScope": list(s.get("forbiddenScope") or []),
        "acceptance": list(s.get("acceptance") or []),
        "functionalScope": list(s.get("functionalScope") or []),
        "assessmentSummary": str(s.get("assessmentSummary") or ""),
        "estMin": int(s.get("estMin") or 0),
    }

def execute_tool_with_repair(name: str, args: dict, root: Optional[str],
                             project: Optional[str],
                             model_id: str = "") -> Dict[str, Any]:
    """M4 补偿组件: 工具执行 + 机械性错误隔离修复(独立循环, 不污染主上下文)。

    修复范围 v1: 「未知工具」(名称幻觉)——每调用限 1 次预算; 修复失败/语义类
    错误(资产不存在等)原样返回(错误如实可见, cv-175 纪律)。可扩展修复种类见
    agent/reflection/repair_tasks.py 注册表。
    """
    result = run_arch_tool(name, args, root, project)
    if not (isinstance(result, dict) and result.get("error")):
        return result
    err = str(result.get("error") or "")
    if not err.startswith("未知工具"):
        return result
    try:
        from ...agent.reflection.repair_tasks import run_tool_call_repair
        fixed = run_tool_call_repair(name, args if isinstance(args, dict) else {},
                                     err, list(_ARCH_TOOLS), model_id=model_id)
    except Exception:  # noqa: BLE001 — 修复通道故障不影响既有错误返回
        return result
    if not fixed:
        return result
    repaired = run_arch_tool(fixed["tool"], fixed["arguments"], root, project)
    if isinstance(repaired, dict) and repaired.get("error"):
        logger.info("[tool-repair] 修复后仍失败 tool=%s→%s: %s",
                    name, fixed["tool"], str(repaired.get("error"))[:120])
    return repaired


def record_tool_parse_audit(content: str, calls: list, surface: str = "chat") -> None:
    """M4-C 失败样例回流: 有工具块但有效调用缺失/部分损坏 → 沉淀探针样本。

    落 llm_dataset(kind=tool_parse_fail, events.jsonl); 采集绝不影响业务。
    样本仅供探针判分用例库(编排增量轨道, tech-debt-ledger)与人工导出, 不自动改行为。
    """
    try:
        audit = tool_parse_audit(content or "")
        if not audit["regions"] or audit["valid"] >= audit["regions"]:
            return
        from ...agent.reflection.dataset import record
        record("tool_parse_fail", surface=surface,
               regions=audit["regions"], valid=audit["valid"],
               sample=(content or "")[-500:])
    except Exception:  # noqa: BLE001
        pass


# ── M4-A 受限生成(structured 通道) ────────────────────────────────────

_STRUCTURED_MODELS_KEY = "llm.structuredModels"


def structured_model_enabled(model_id: str) -> bool:
    """模型 structured 支持位(双源: ①能力档案探针位 ②CollabConfig 手工清单)。

    档案位(model_profile.structured, 探针 structured 冒烟写入)为单源方向;
    旧手工清单 llm.structuredModels 保留为手工覆盖兼容。未配置且无档案 = 走
    文本协议(现行为, 零散落分支)。
    """
    mid = model_id or ""
    if not mid:
        return False
    try:
        from ...agent.cognition import model_profile as _mp
        prof = _mp.get_profile(mid)
        if isinstance(prof, dict) and prof.get("structured") is True:
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        raw = store.CollabConfigStore.get(_STRUCTURED_MODELS_KEY, "") or "[]"
        ids = json.loads(raw)
        return isinstance(ids, list) and mid in {str(x) for x in ids}
    except Exception:  # noqa: BLE001
        return False


# ── 工具调用规范化(cv-222) — 判别式=注册表成员资格, 非枚举模型行为 ──────
# 模型的「无工具」示意形态多样(none/null/no_tool/任意噪声名), 枚举必然不完备。
# 判别两层:
#   ① 协议声明值: 空/none/null = 不调用(空即无工具——TOOL_CALL_SCHEMA 声明的
#     协议语义, 集合仅此两项, 属协议定义而非模型行为枚举);
#   ② 注册表成员资格: 未注册名 → 空参=模型噪声(不派发, 不烧修复轮);
#     带参=真名称幻觉 → 保留派发(诚实报错 + repair_tool_call, cv-175 纪律)。
_NO_TOOL_NAMES = {"none", "null"}

_DUP_CALL_TEXT = ("本回合已调用过相同工具与相同参数(结果已在上方回喂)——"
                  "请基于已有结果直接作答，或向用户提出澄清问题。")


def _call_key(name: str, args) -> tuple:
    """回合内重复调用判别键: (tool, 规范化参数)——幂等抑制单源。"""
    try:
        return (name, json.dumps(args or {}, sort_keys=True,
                                 ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001
        return (name, repr(args))


def _normalize_tool_calls(calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in calls or []:
        if not isinstance(c, dict):
            continue
        name = str(c.get("tool") or "").strip()
        if not name or name.lower() in _NO_TOOL_NAMES:
            continue                              # 协议声明: 无工具 → 转终稿轮
        if name not in _ARCH_TOOLS and not (isinstance(c.get("arguments"), dict)
                                            and c["arguments"]):
            continue                              # 未注册+空参 = 噪声, 不派发
        out.append({"tool": name,
                    "arguments": c.get("arguments") if isinstance(c.get("arguments"), dict) else {}})
    return out


def structured_tool_round(msgs: list, model_id: str = "",
                          schema: Optional[dict] = None,
                          max_tokens: Optional[int] = None) -> Dict[str, Any]:
    """受限生成单轮(非流式): mode=structured → 主后端约束解码+校验重试。

    返回 {'calls': [{tool, arguments}], 'content': str, 'error': str|''}。
    calls 为空且无 error = 模型未调用工具(空 tool)——调用方转终稿轮。
    """
    from ...agent.tools.protocol import TOOL_CALL_SCHEMA
    res = llm_sync(msgs, mode="structured",
                   output_schema=schema or TOOL_CALL_SCHEMA,
                   max_tokens=max_tokens, model_id=model_id)
    res = res or {}
    err = str(res.get("structuredError") or "")
    out = res.get("output")
    calls: List[Dict[str, Any]] = []
    if isinstance(out, dict) and str(out.get("tool") or "").strip():
        args = out.get("arguments")
        calls = [{"tool": str(out["tool"]).strip(),
                  "arguments": args if isinstance(args, dict) else {}}]
    calls = _normalize_tool_calls(calls)
    return {"calls": calls, "content": str(res.get("content") or ""),
            "error": err}


def run_tools_loop(msgs: List[Dict[str, str]], *,
                   root: Optional[str] = None, project: Optional[str] = None,
                   model_id: Optional[str] = None,
                   mode: str = "chat",
                   output_schema: Optional[Dict[str, Any]] = None,
                   max_tokens: Optional[int] = None,
                   max_rounds: int = 4,
                   allowed: Optional[List[str]] = None,
                   tool_schema: Optional[Dict[str, Any]] = None,
                   on_error: Optional[Callable[[str], None]] = None,
                   on_progress: Optional[Callable[[str, Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """统一工具调用循环(同步通道)：解析模型输出的 `[TOOL_CALL]` 块 → 逐个执行 →
    回喂结果 → 再次询问，直至得到不含工具块的最终内容。供 harness(clarify/collect)
    与 WS 降级通道共用，杜绝「裸 [TOOL_CALL] 中断」。

    allowed: 工具白名单(如逐行解读等受限任务)；非 None 时白名单外的工具调用不执行，
    回喂拒绝提示让模型改用允许的工具或直接作答。默认 None=不限制(原行为)。
    on_error: 透传给 llm_sync 的失败原因回调(见其 docstring)。
    on_progress: 进度回调(event, detail)，event ∈ 'llm'(detail.round=本轮轮次) |
    'tool'(detail.tool/idx/total)；在同步线程内同步调用，WS 层负责 marshal 到事件循环，
    让降级通道也有实时进度(否则用户整段等待零反馈)。

    返回 {'content': str, 'output': Any|None}；content 已剥离所有工具块。
    LLM 失败导致无内容时额外带 'error'(最近一次失败原因文本，空串=不可达/超时)。
    """
    work = list(msgs or [])
    last_err = ""
    _proposed: set = set()   # cv-174: 本循环已落库的提案(去重守卫)
    _seen_calls: set = set()  # 回合内幂等重复抑制(cv-225: 同参 project.ctx 三连)

    def _err(msg: str) -> None:
        nonlocal last_err
        last_err = msg or last_err
        if on_error:
            try:
                on_error(msg)
            except Exception:
                pass

    def _prog(event: str, **detail: Any) -> None:
        if on_progress:
            try:
                on_progress(event, detail)
            except Exception:
                pass

    for _round in range(max_rounds + 1):
        _prog("llm", round=_round + 1)
        use_structured = tool_schema is not None \
            and structured_model_enabled(model_id or "")
        if use_structured:
            # M4-A 受限生成轮: 约束解码直达工具 JSON(非流式); 终稿轮转普通模式
            sres = structured_tool_round(work, model_id or "",
                                         schema=tool_schema,
                                         max_tokens=max_tokens)
            if sres["error"]:
                # 失败显式不静默: 一次性 nudge 后本循环降级文本协议
                from ...agent.reflection.dataset import record
                record("tool_parse_fail", surface="structured",
                       sample=sres["error"][:300])
                work.append({"role": "user", "content":
                             f"结构化工具调用未成功({sres['error'][:160]})。"
                             "请直接基于已有信息作答，或改用文本协议输出工具调用块。"})
                tool_schema = None
                continue
            calls = sres["calls"]
            if not calls:
                # 空 tool = 模型示意无更多工具 → 转终稿轮(普通文本模式)
                work.append({"role": "user", "content":
                             "请基于以上工具结果直接给出面向用户的最终回答"
                             "(不要工具调用)。"})
                tool_schema = None
                continue
            results: List[Dict[str, str]] = []
            for ci, c in enumerate(calls):
                name = c.get("tool", "")
                args = c.get("arguments", {})
                _prog("tool", tool=name, idx=ci + 1, total=len(calls))
                _ck = _call_key(name, args)
                if _ck in _seen_calls:
                    results.append({"name": name, "text": _DUP_CALL_TEXT})
                    continue
                _seen_calls.add(_ck)
                if allowed and name not in allowed:
                    results.append({"name": name,
                                    "text": f"工具 {name} 不在本任务允许列表(仅限: {'/'.join(allowed)})，"
                                            "请改用允许的工具，或直接基于已有信息作答。"})
                    continue
                if name == "req.propose" and "req.propose" in _proposed:
                    # cv-174(同步降级路径同样适用): 同回合重复提案不落库
                    results.append({"name": name,
                                    "text": "重复的 req.propose 已忽略——本次循环已创建规约(以首个为准)；如需修改请用 req.amend"})
                    continue
                if name == "req.propose":
                    _proposed.add(name)
                result = execute_tool_with_repair(name, args, root, project,
                                                model_id=model_id or "")
                results.append({"name": name, "text": tool_result_text(name, result)})
            if results:
                tool_feed = "\n".join(f"[{r['name']}] {r['text']}" for r in results)
                work.append({"role": "assistant", "content": "(已调用工具)"})
                work.append({"role": "user", "content": f"{_TOOL_FEED_PREFIX}{tool_feed}"})
            continue
        res = llm_sync(work, mode=mode, output_schema=output_schema,
                       max_tokens=max_tokens, model_id=model_id, on_error=_err)
        content = (res or {}).get("content", "") if res else ""
        if not content:
            return {"content": "", "output": None, "error": last_err}
        calls = _normalize_tool_calls(extract_tool_calls(content))
        record_tool_parse_audit(content, calls, surface="sync")
        if not calls:
            return {
                "content": strip_tool_blocks(content),
                "output": (res or {}).get("output") if res else None,
            }
        results: List[Dict[str, str]] = []
        for ci, c in enumerate(calls):
            name = c.get("tool", "")
            args = c.get("arguments", {})
            _prog("tool", tool=name, idx=ci + 1, total=len(calls))
            _ck = _call_key(name, args)
            if _ck in _seen_calls:
                results.append({"name": name, "text": _DUP_CALL_TEXT})
                continue
            _seen_calls.add(_ck)
            if allowed and name not in allowed:
                results.append({"name": name,
                                "text": f"工具 {name} 不在本任务允许列表(仅限: {'/'.join(allowed)})，"
                                        "请改用允许的工具，或直接基于已有信息作答。"})
                continue
            result = execute_tool_with_repair(name, args, root, project,
                                            model_id=model_id or "")
            results.append({"name": name, "text": tool_result_text(name, result)})
        if not results:
            return {"content": strip_tool_blocks(content), "output": None}
        tool_feed = "\n".join(f"[{r['name']}] {r['text']}" for r in results)
        work.append({"role": "assistant", "content": strip_tool_blocks(content) or "(调用知识库检索)"})
        work.append({"role": "user", "content": f"{_TOOL_FEED_PREFIX}{tool_feed}"})
    return {"content": "", "output": None, "error": last_err or "工具调用轮次耗尽"}


# ── 自由对话(流式)通道 ────────────────────────────────────────────────

_CAPABILITY_DOC = (
    "你可以使用以下能力(skills/tools)：\n"
    "- kb.asset.search：全文检索知识库架构资产(组件/ER/实体/流程)，按关键词命中并按相关度排序\n"
    "- kb.code_mappings：查询资产对应的代码映射(文件/行号)，锁定「改哪里」\n"
    "- kb.baseline：读取当前项目 KB 基线(git 表示：分支/提交/基线版本)\n"
    "- kb.graph：遍历组件依赖图(依赖/被调用)，判断需求改动的影响链路\n"
    "- project.ctx：读取项目上下文(项目名/分支/基线 id/降级状态)\n"
    "- map.overview：资产地图总览——组件目录(含图层级 L0/L1/文件数/依赖)+资产统计；穷举/统计/层级类提问先看\n"
    "- map.component：组件档案——单组件的层级/文件/依赖出入/组件内语义资产\n"
    "- map.assets：语义资产表列检索——kind/level 过滤+关键词，Markdown 表格浏览清单\n"
    "- map.rules：项目规约全集(架构+编码+命名规约+词汇表，编码/评估必须遵守)\n"
    "- map.graph：关系图(mermaid)——component 组件依赖图 / semantic 语义关系图\n"
    "- asset.semantic.search：检索已提取的语义数据资产(数据结构/处理流程/控制逻辑，比组件更细、锚定 AST 节点；支持 kind/level 过滤；includeGlobal=true 时合并主库全局层通用资产)\n"
    "- asset.semantic.stats：语义资产统计(总量/按类别/按粒度/状态)\n"
    "层级概念约定：组件带**图层级**(L0=底层原子社区，L1/L2=逐级聚合，见 map.overview 目录「层级」列)；"
    "语义资产带**抽象粒度** level(business/implementation/logic)。"
    "用户问「L0/L1 模块/组件」指组件图层级(用 map.*)，问资产「粒度/层次」指语义资产 level(用 asset.semantic.* 的 level 过滤)。\n"
    "- asset.semantic.extract：按指令从最新代码提取语义数据资产并落库(指令化唯一入口：comm 时 key=组件ID 为权威范围，确定执行)\n"
    "- asset.semantic.detail：读取单个语义资产的完整描述/结构化细节/AST 锚点\n"
    "- asset.semantic.mappings：查询语义资产对应的代码映射(文件/行号)，锁定「改哪里」\n"
    "- asset.semantic.reconcile：校验资产新鲜度，标记因文件变更/新增文件影响而过期的资产(需更新后使用)\n"
    "- asset.semantic.refresh：更新过期资产(增量重提；失败软删并重新生成)\n"
    "- code.read_symbols：读取项目源码片段(按文件/符号)，对话式提取前先看真实代码\n"
    "- asset.semantic.save：对话式提取落库(按规约产出资产 → 框架值域校验/名称继承/墓碑承接)\n"
    "- asset.semantic.update：认知层编辑既有资产(改名/描述；旧名自动入历史，overlay 留痕)\n"
    "- asset.semantic.merge：合并资产(intoId 吸收 targetIds 锚点；目标留痕 mergedInto)\n"
    "- asset.semantic.split：拆分资产(按 anchorKeys 锚点组拆出新资产；原资产留痕 splitInto)\n"
    "- convention.propose：把观察到的命名重复模式固化为命名规约提案(pending，待设计者确认/忽略)\n"
    "- contract.propose：把对话中讨论出的期望固化为契约条目草稿(待设计者逐条确认；kind/level 按框架值域校验)\n"
    "- mcp.call：调用 MCP 开放工具(外部/注册工具)，参数 {\"tool\":\"<名>\",\"params\":{…}}\n"
    "- req.propose：需求提案(新建或幂等更新)——**开发类需求**(要写代码/改代码/交付组件)时调用，"
    "创建需求卡即 ready(designMd=选型与结构)；分析/问答类请求不要产卡。"
    "用户要求 编写脚本/工具/程序 时**必须先调本工具**，由 /执行 链路产出代码——"
    "**严禁直接输出成品代码**(python/bash 等)替代需求收敛。"
    "参数 {\"title\", \"requirementMd\"?, \"designMd\"?, \"allowedScopeMd\"?, "
    "\"forbiddenScopeMd\"?, \"acceptanceMd\"?, \"assessmentMd\"?, \"priority\"?, "
    "\"estMin\"?, \"newRequirement\"?: true 强制新建}\n"
    "- req.amend：需求修订(通用)——用户对既有需求 补充/完善/调整 时调用，追加新 draft "
    "版本(append-only)。reqId 勿传(系统自动取会话绑定需求)。"
    "参数 {\"designMd\"?, \"requirementMd\"?, \"allowedScope\"[]?, \"forbiddenScope\"[]?, "
    "\"acceptance\"[]?, \"reasoning\"?(修订留痕)}\n"
    "- ctx.search：跨会话检索历史上下文(单元/消息/备案文档)——回答涉及历史讨论/已有结论时先检索，避免重复讨论\n"
    "- ctx.get：读取指定会话的上下文包(摘要+关键单元+备案文档清单)\n"
    "- ctx.summarize：生成/刷新会话摘要\n"
    "- probe.run：方案草图(probe)——调 coding agent 在代码快照上产出改动思路与伪 diff，供用户预览确认后再正式执行\n\n"
    "- capability.evaluate：图文评估——target=plan 评估会话最新方案(变更足迹×语义资产影响面+关系子图图)；"
    "target=execution 评估执行结果(实际 diff 足迹 + 与方案的偏差集)。报告内资产卡可点击联动资产地图。方案确认前/执行完成后调用\n"
    "- capability.mine：能力提炼——扫描会话(消息+方案/回执单元)提炼 规约/流程/技巧/skill 提案入待审队列, "
    "设计者采纳后生效(规约入规约库/skill 文档注入能力文档)。会话出现可复用模式时主动提议\n\n"
    # 工具调用纪律: 引用 cognition.prompt 单源常量(禁止手工复制——cv-177 漂移教训)
    + _disc.TOOL_PROTOCOL_HEAD
    + _disc.ANTI_FABRICATION
    + _disc.REQ_CARD_DISCIPLINE
    + _disc.DIRECT_CMD_SYMBOLS
    + "各工具的参数：\n"
    '- kb.asset.search: {"text": "检索关键词", "preferred": ["资产ID(可选)"]}\n'
    '- kb.code_mappings: {"asset_ids": ["资产ID"]}\n'
    "- kb.baseline: {}\n"
    '- kb.graph: {"comp_ids": ["组件ID"]}\n'
    "- project.ctx: {}\n"
    '- asset.semantic.search: {"text": "关键词", "kind": "entity|contract|state|rule|process|decision(可选)", "level": "business|implementation|logic(可选)", "limit": 20, "offset": 0, "scopes": ["comm-…(可选)"]}\n'
    '- map.overview: {}\n'
    '- map.component: {"name": "组件名或id"}\n'
    '- map.assets: {"query": "关键词", "kind": "类别(可选)", "level": "粒度(可选)", "limit": 30}\n'
    '- map.rules: {}\n'
    '- map.graph: {"kind": "component|semantic"}\n'
    '- asset.semantic.stats: {}\n'
    '- asset.semantic.extract: {"scope": {"type": "comm|files|symbols|project", "key"?, "files"?, "symbols"?}, "kinds"?}(工作流见 extract 技能)\n'
    '- asset.semantic.detail: {"asset_id": "sa-xxx"}\n'
    '- asset.semantic.mappings: {"asset_ids": ["sa-xxx"]}\n'
    "- asset.semantic.reconcile: {}\n"
    '- asset.semantic.refresh: {"asset_id": "sa-xxx"}\n'
    '- code.read_symbols: {"file": "相对路径", "symbol"?: "符号名", "startLine"?: 行, "endLine"?: 行}\n'
    '- asset.semantic.save: {"assets": [{"name", "kind", "level"?, "desc"?, "detail"?, "astRefs"[{file,symbol,startLine,endLine}]}]}\n'
    '- asset.semantic.update: {"assetId": "sa-xxx", "patch": {"name"?: "新名", "desc"?: "新描述"}}\n'
    '- asset.semantic.merge: {"intoId": "sa-xxx", "targetIds": ["sa-yyy"], "targetName"?: "合并后名称"}\n'
    '- asset.semantic.split: {"assetId": "sa-xxx", "parts": [{"name": "…", "anchorKeys": ["file:symbol"], "desc"?: "…"}]}\n'
    '- convention.propose: {"ruleText": "服务以 XxxService 结尾", "scenarios": ["naming"], "appliesKinds"?: ["process"]}\n'
    '- contract.propose: {"items": [{kind, level?, target{file?,symbol?}, behavior{steps,branches?}, zAxis?, acceptance?, origin{quote 必填}, reqId?}]}(构造纪律见 contract 技能, 🧾)\n'
    '- mcp.call: {"tool": "<mcp工具名>", "params": {…}}\n'
    '- req.propose: {"title": "标题", "requirementMd": "需求目标", '
    '"designMd": "方案", "priority": "P1", "acceptanceMd": "验收"}\n'
    '- req.amend: {"requirementMd": "修订后目标", "designMd": "修订后方案", '
    '"acceptance": [...], "reasoning": "原因"} 只传要调整的字段; 标题用 {"title": …}\n'
    '- capability.evaluate: {"target": "plan|execution", "execId"?: "ex-…(execution 时必填)}\n'
    '- capability.mine: {"conversation"?: "cv-…(缺省当前会话)}\n'
    "输出工具调用块后不要再写其它内容；收到工具结果后才继续回答。"
    "若无需检索即可直接回答，就不要调用工具。\n\n"
    "可处理范围：\n"
    "1. 需求分析/澄清/范围收敛、资产命中与影响评估；\n"
    "2. 产品设计、软件开发实现建议(非文档化的帮助性建议)；\n"
    "3. 新项目引导(从零建立开发环境/确立目标)、未关联 KB 的已有项目建立 KB 的引导(非强制)。\n"
    "越界处理(软拒绝)：对与需求分析无关的通用闲聊/外包式实现请求，礼貌说明能力范围并引导回"
    "需求分析语境，不深入执行，但允许用户继续提问。\n"
    "回复保持简洁、直接、可操作，可输出 Markdown。\n\n"
    "图表输出能力：当描述语义数据资产(数据结构/处理流程/控制逻辑)、依赖链路、"
    "实现路径或改动影响时，用图直观表达。**优先**输出 ```diagram 围栏，内容为 JSON 图结构(DiagramSchema)，"
    "前端会自动把它确定性地转成 Mermaid/PlantUML 并动画，避免直接写图语法出错：\n"
    "  ```diagram\n  {\"version\":1,\"type\":\"flowchart\",\"direction\":\"LR\","
    "\"nodes\":[{\"id\":\"a\",\"label\":\"订单实体\"},{\"id\":\"b\",\"label\":\"订单明细\"}],"
    "\"edges\":[{\"from\":\"a\",\"to\":\"b\",\"label\":\"1:N\"}]}\n  ```\n"
    "仅当图极简单(≤2节点)或 IR 无法表达时，才直接输出 ```mermaid / ```plantuml 代码围栏。"
    "要求：节点精简、命名与代码资产一致；图中不要包含 [TOOL_CALL] 块。"
)


def _ir_schema_doc() -> str:
    """绘图 IR(DiagramSchema) 结构参考：从 reports 拉共享 schema(单一起源)，失败降级最小说明。默认注入。

    前端据 IR 的 type 选择引擎并确定性地转成 Mermaid/PlantUML + 动画(见 ```diagram 围栏)。
    """
    base = (
        "绘图 IR 结构(DiagramSchema)：```diagram 围栏内为 JSON，type 取 "
        "flowchart|activity|sequence|state|class|er|usecase|component|architecture|gantt|pie；"
        "前端据 type 选择引擎并转成 Mermaid/PlantUML。\n"
    )
    try:
        from . import diagram as _diagram
        docs = _diagram.fetch_ir_docs()
        if docs:
            return base + docs
    except Exception as e:
        logger.warning("[req_agent] fetch ir-docs failed: %s", e)
    return base + (
        "flowchart/activity/usecase/component/architecture: nodes[{id,label,kind?}], edges[{from,to,label?,kind?}]；"
        "sequence: participants[{id,label,type?}], messages[{from,to,label,kind?}]；"
        "state: states[{id,label,initial?,final?}], transitions[{from,to,label?,guard?}]；"
        "class: classes[{id,name,members[{name,kind?,type?}]}], classRelations[{from,to,kind?}]；"
        "er: entities[{id,name,attrs[{name,type?,key?}]}], erRelations[{from,to,kind?}]。"
    )


def _diagram_skill_doc() -> str:
    """可选的后端预校验工具(diagram.build/validate)说明。diagram_skill=True(前端 📐 开关)时注入。"""
    return (
        "绘图预校验(可选，复杂/较大图)：可先输出工具调用块 "
        '[TOOL_CALL]{"tool":"diagram.build","arguments":{"ir":{…DiagramSchema…}}}[/TOOL_CALL] '
        "由后端预生成/校验语法(返回 {code,type} 或 {error})，据此修正后仍以 ```diagram 围栏输出；"
        "diagram.validate 可校验已有 mermaid/plantuml 代码。"
    )


def chat_system_prompt(root: Optional[str], project: Optional[str],
                       diagram_skill: bool = False,
                       skill_scenarios: Optional[List[str]] = None,
                       model_id: str = "",
                       tool_surface: str = "full",
                       kb_enabled: bool = True,
                       ctx_budget: float = 1.0,
                       gu_allowed=None, prompt_slim: Optional[bool] = None) -> str:
    """自由对话系统提示：经 prompt_registry 组装(块化/按模型档案分级/预算裁剪)。

    等价模式(默认)下与旧拼接(header/边界/CAPABILITY/IR/📐/MCP/skill)逐字节
    一致; prompt.overrides 可开单源模式(能力文档由工具注册表渲染)与分级预算。
    model_id 非空 → 查模型能力档案取 tier(缺省 t1 保守档)。
    R3.4: tool_surface/kb_enabled 工具面裁剪 + ctx_budget 预算系数(缺省不变)。
    批丁: gu_allowed(GU 路线工具限定)→能力文档本轮子集; prompt_slim(简挡)。
    """
    from ...agent.cognition import model_profile as _mp
    from ...agent.cognition import prompt as _pr
    # cv-189 注入层硬控制(入口强制): 未关联 KB → 无论调用方传什么, kb_enabled
    # 恒 False(能力文档无 kb.*/mcp.call; MCP 块/skill/路由段各自另有降级门)。
    try:
        from ...arch_routes.project import kb_degraded as _kd
        if _kd(root, project):
            kb_enabled = False
    except Exception:  # noqa: BLE001
        pass
    tier = _mp.tier_of(model_id or "")
    # 批丁: prompt_slim 缺省按挡推导(t2+ 简挡——省系统面说明段, 约束密度降载)
    if prompt_slim is None:
        prompt_slim = tier >= 2
    return _pr.render_system({
        "root": root, "project": project, "diagram_skill": diagram_skill,
        "skill_scenarios": skill_scenarios, "tier": tier, "model_id": model_id or "",
        "tool_surface": tool_surface, "kb_enabled": kb_enabled,
        "ctx_budget": ctx_budget, "gu_allowed": gu_allowed,
        "prompt_slim": prompt_slim})


def _posture_textLegacy() -> str:
    from ...agent.cognition.prompt import posture_text
    return posture_text()


def chat_system_prompt_legacy(root: Optional[str], project: Optional[str],
                              diagram_skill: bool = False,
                              skill_scenarios: Optional[List[str]] = None) -> str:
    """旧拼接实现(等价基线对照/回退用, 不再在生产链路上)。"""
    """自由对话系统提示：能力文档 + 当前项目/KB 上下文 + 范围限定(软拒绝)。

    绘图 IR(DiagramSchema) 参考默认注入(模型优先输出 ```diagram IR 围栏，前端转码)；
    diagram_skill=True 时额外注入后端预校验工具说明(对应前端 📐 开关)；
    skill_scenarios 非空时按场景注入语义资产 skill 文档（plan-C §4.1 按场景加载，禁全量）。
    """
    ctx = tool_project_ctx(root, project)
    mode = "greenfield(从零)" if not project else "existing(既有)"
    degraded = ctx.get("degraded", False)
    bound = ctx.get("bound", False)
    # cv-189 注入层硬控制: 未关联 KB → KB 叙述整句不注入(与单源 header 同门)
    kb = (
        "KB 已绑定，可检索资产/基线/依赖图。"
        if bound and not degraded
        else ""
    )
    ir_doc = f"\n\n{_ir_schema_doc()}"
    extra = f"\n\n{_diagram_skill_doc()}" if diagram_skill else ""
    try:
        from ...arch_routes.project import kb_degraded as _kd
        _mcp_on = not _kd(root, project)
    except Exception:  # noqa: BLE001
        _mcp_on = True
    mcp_extra = f"\n\n{_mcp_doc()}" if _mcp_on else ""
    skill_extra = ""
    if skill_scenarios:
        try:
            from .asset_skill import skill_docs
            skill_extra = skill_docs(root, project, skill_scenarios)
        except Exception as e:
            logger.warning("[req_agent] skill 文档注入失败: %s", e)
    return (
        "你是 TopoCode 架构需求分析 agent(自由对话)。\n"
        f"当前项目：{ctx.get('name') or '(未绑定)'}，模式：{mode}。{kb}\n\n"
        "## 职责边界(重要)\n"
        "用户明确表达的需求**一律受理**，不拒做、不引导用户另找工具——包括与当前项目"
        "关联较弱的通用编程/运维任务(脚本、工具、配置等)：照常收敛为需求规约"
        "(req.propose 带 title/requirementMd/**designMd**/acceptanceMd)，需求卡就绪后可 /执行。"
        "关联较弱时仅在方案中说明「独立于项目核心资产」并收敛 scope，**不得以此为由拒绝或推诿**。"
        "已创建需求(RQ 编号以系统回执为准)后继续跟进完善，不得再声明该任务不属于职责范围。\n\n"
        # GU-3 人格统一: posture 判据块与注册表同源(cognition.prompt)
        f"{_posture_textLegacy()}\n\n"
        f"{_CAPABILITY_DOC}{ir_doc}{extra}{mcp_extra}{skill_extra}"
    )


# ── Skills 定义 ────────────────────────────────────────────────────────

@register_architect_tool(
    "task.propose",
    "创建 coding subagent 实施任务卡(轻门禁: 用户确认后执行)。方案成熟/用户要求实施时调用。",
)
def tool_task_propose(title: str, instruction: str,
                      executorType: Optional[str] = None,
                      root: Optional[str] = None, project: Optional[str] = None,
                      safetyClass: Optional[str] = None,
                      workTags: Optional[List[str]] = None) -> Dict[str, Any]:
    """v2 混合触发: architect 整理任务(目标/方案要点/边界/验收) → 用户确认(P4 委托 planning.task_plan)。

    safetyClass: readonly=纯读/分析(豁免互斥, 强制就地) | mutating=会写代码/文件(默认)
      | high-stakes=高风险(部署/发布/数据迁移/破坏性操作——强制隔离+合并门禁)。
    workTags: 工作类型开放标签, 如 ["analysis","docs"] / ["deploy"]。"""
    from ...agent.planning.task_plan import propose_task_tool
    return propose_task_tool(title, instruction, executorType=executorType,
                             root=root, project=project,
                             safetyClass=safetyClass or "",
                             workTags=workTags)


# ── 会话知识单元工具面(LLM 可读写; 存储归一后落 arch_context_units) ────────

@register_architect_tool(
    "help.lookup",
    "检索产品使用指南/帮助手册主题(会话基本流/指令确认/需求卡澄清/任务计划/"
    "执行器配置/分析挡位/会话管理/失败重试/常见问题)。产品使用咨询时调用并"
    "基于返回内容回答; 文档内容可能滞后于当前版本，以系统实际行为为准。",
    brief="检索使用指南/帮助手册主题(产品怎么用类咨询先查这里)",
    params_doc='{"query": "主题关键词(如: 执行器/需求卡/计划/确认; 空=返回主题清单)"}',
)
def tool_help_lookup(query: str = "", topic: str = "") -> Dict[str, Any]:
    from ...agent.governance.flow_policy import load_flow_policy
    from ...agent.turns.help_docs import lookup_topics
    rows = ((load_flow_policy().get("goal") or {}).get("helpTopics")) or None
    res = lookup_topics(str(query or topic or ""), rows=rows)
    res["ok"] = True
    return res


@register_architect_tool(
    "asset.upsert",
    "沉淀/更新会话知识单元(artifact 类型: 结论、约定、待办、可复用片段等分析性知识)。"
    "任务回执与里程碑报告系统已自动沉淀(execution_report/analysis), "
    "本工具用于补充人工/分析性知识。",
)
def tool_asset_upsert(title: str, content: str,
                      unitId: Optional[str] = None,
                      conversationId: Optional[str] = None,
                      reqId: Optional[str] = None) -> Dict[str, Any]:
    from ... import ctx as _ctx
    from ...store import ContextUnitsStore
    conv_id = conversationId or _ctx.get_conv() or ""
    if not conv_id:
        return {"ok": False, "error": "no-conversation"}
    if unitId:
        row = ContextUnitsStore.update(unitId, {"title": title, "content": content})
        if not row:
            return {"ok": False, "error": "unit-not-found"}
        return {"ok": True, "unit": row}
    row = ContextUnitsStore.create({
        "conversationId": conv_id, "type": "artifact",
        "title": title, "content": content,
        "refs": {"reqId": reqId or ""}, "importance": 1})
    return {"ok": True, "unit": row}


@register_architect_tool(
    "asset.list",
    "列出会话沉淀的知识单元(回执/分析/产物/决策/摘要, 可按类型过滤/关键词检索)——先查后用, 避免重复沉淀。",
)
def tool_asset_list(type: Optional[str] = None, q: Optional[str] = None,
                    limit: int = 50,
                    conversationId: Optional[str] = None) -> Dict[str, Any]:
    from ... import ctx as _ctx
    from ...store import ContextUnitsStore
    conv_id = conversationId or _ctx.get_conv() or ""
    if not conv_id:
        return {"ok": False, "error": "no-conversation"}
    if q:
        rows = ContextUnitsStore.search(q, type_=type or None,
                                        conversation_id=conv_id,
                                        limit=max(1, min(int(limit), 200)))
    else:
        rows = ContextUnitsStore.all(conversation_id=conv_id, type_=type or None,
                                     limit=max(1, min(int(limit), 200)))
    return {"ok": True, "units": rows, "count": len(rows)}


@register_architect_tool(
    "asset.delete",
    "删除会话知识单元(误沉淀/过期知识清理)。",
)
def tool_asset_delete(unitId: str) -> Dict[str, Any]:
    from ...store import ContextUnitsStore
    removed = ContextUnitsStore.delete(unitId)
    return {"ok": bool(removed), "deleted": bool(removed)}


@register_architect_skill("req.clarify", "需求澄清：依据需求+KB 命中生成需用户确认的澄清问题清单", steps=2)
def _skill_clarify():
    pass


@register_architect_skill("req.collect", "需求收集收敛：依据作答+候选资产 合成需求分析(范围内资产/路径)", steps=3)
def _skill_collect():
    pass


@register_architect_skill("req.assess", "四维评估：必要性/原子性/可验收性/可行性", steps=1)
def _skill_assess():
    pass


@register_architect_skill("req.spec", "规约约束：接口契约/兼容性/边界条件的概要设计约束", steps=1)
def _skill_spec():
    pass


@register_architect_skill("req.plan", "实现路径：需求实现路径与执行步骤(供批次预估)", steps=2)
def _skill_plan():
    pass


# ── 需求 Harness(M3 拆分): 实现迁 agent/requirements/harness.py, re-export 接缝 ──
from ...agent.requirements.harness import (_SYSTEM_PROMPT, _build_assessment,
                                          _build_changes, _build_steps,
                                          _kb_hits, _merge_assets,
                                          req_harness_clarify,
                                          req_harness_collect)


