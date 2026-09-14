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

from . import store

logger = logging.getLogger(__name__)

from ..agent.planning.req_spec import (  # noqa: F401,E402
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
)
from ..agent.planning.task_plan import extract_task_fence  # noqa: F401,E402

from ..agent.reflection.guards import (  # noqa: F401,E402
    _FABRIC_RULES,
    _INTENT_PATTERNS,
    announced_tool_intent,
    fabricated_claim,
    guard_notice,
    guard_suggestions,
)
from ..agent.reflection.repair import (  # noqa: F401,E402
    _GUARD_REPAIR_TOOLS,
    _REPAIRABLE_ERR,
    _is_repairable_error,
    _repair_param_table,
    repair_fabricated_claim,
    repair_tool_args,
)

from ..agent.tools.protocol import (  # noqa: F401,E402
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
)
from ..agent.tools.registry import (  # noqa: F401,E402
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
        from . import ctx as _actx
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
        from .store.base import _insert_into, _db
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
            from . import llm_dataset
            llm_dataset.record("arg_coerce", tool=getattr(fn, "__name__", "?"),
                               items=[{"param": k, "from": a, "to": b}
                                      for k, a, b in coerced])
        except Exception:  # noqa: BLE001
            pass
        logger.info("[arg-coerce] %s: %s", getattr(fn, "__name__", "?"),
                    ", ".join(f"{k}:{a}→{b}" for k, a, b in coerced))
    return out


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
    # v2: 退役工具只拦模型面调用; internal=True 为系统确定性路径(spec-apply/
    # 守卫代落)——放行(P2 随规约域物理删除)。
    if name in _RETIRED_TOOLS and not internal:
        return {"error": _RETIRED_TOOLS[name]}
    # PR1 归档只读: 归档会话上拒绝动作类工具(落库/定稿/指派); 检索/读取/提炼放行
    if name in _ARCHIVED_DENY_TOOLS:
        try:
            from . import ctx as _ctx
            conv_id = _ctx.get_conv()
            if conv_id:
                from . import store as _store
                conv = _store.ConversationsStore.get(conv_id)
                if conv and (conv.get("status") or "active") == "archived":
                    return {"error": f"会话已归档(只读)：{name} 不可执行。可读取/复制/提炼。"}
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
        ok = not (isinstance(result, dict) and result.get("error"))
        record_tool_audit(name, arguments, ok,
                          tool_result_text(name, result, limit=200),
                          latency_ms=_now_ms() - t0, project=project or "")
        try:
            from . import llm_dataset as _lds
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
            from . import llm_dataset as _lds
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


def _model(root: Optional[str], project: Optional[str]) -> Dict[str, Any]:
    from .common import build_architecture_model
    return build_architecture_model(root, project)


def _model_assets(root: Optional[str], project: Optional[str]) -> List[Dict[str, Any]]:
    return _model(root, project).get("components") or []


def _model_code_mappings(root: Optional[str], project: Optional[str]) -> List[Dict[str, Any]]:
    from .common import build_architecture_model
    model = build_architecture_model(root, project, include_code_mappings=True)
    real = model.get("codeMappings") or []
    if real:
        return real[:80]
    return [{
        "id": f"cm-{c.get('id')}", "targetType": "component", "targetId": c.get("id"),
        "targetName": c.get("name"), "file": f"{'/'.join((c.get('owns') or [])[:1]) or 'app/' + str(c.get('name'))}",
        "line": "L1", "level": "logical", "note": c.get("desc"),
    } for c in model.get("components") or []][:40]


def _project_degraded(root: Optional[str], project: Optional[str]) -> bool:
    try:
        from .project import kb_degraded as _d
        return _d(root, project)
    except Exception:
        return True


# ── Tools 实现 ─────────────────────────────────────────────────────────

@register_architect_tool(
    "kb.asset.search",
    "全文检索知识库架构资产(组件/ER/实体/流程)，按关键词命中并按相关度排序",
)
def tool_kb_asset_search(root: Optional[str], project: Optional[str],
                         text: str, preferred: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    if _project_degraded(root, project):
        return []
    assets = _model_assets(root, project)
    pre = set(preferred or [])
    if pre:
        hits = [a for a in assets if a.get("id") in pre]
        if hits:
            return hits[:6]
    lowered = (text or "").lower()
    tokens = [t for t in lowered.split() if len(t) >= 2]
    scored = []
    if tokens:
        for a in assets:
            hay = f"{a.get('id', '')} {a.get('name', '')} {a.get('desc', '')}".lower()
            score = sum(3 for tk in tokens if tk in hay.split())
            if score == 0:
                score = sum(1 for tk in tokens if tk in hay)
            if pre and a.get("id") in pre:
                score += 10
            if score > 0:
                scored.append((score, a))
        scored.sort(key=lambda x: x[0], reverse=True)
    # 无关键词命中(如「当前系统有哪些组件」等穷举型提问)时回退返回资产清单，
    # 避免 LLM 误判「未检索到任何架构资产」
    if not scored:
        return assets[:6]
    return [a for _, a in scored[:6]]


@register_architect_tool(
    "kb.code_mappings",
    "查询资产对应的代码映射(文件/行号)，锁定「改哪里」的精确位置",
)
def tool_kb_code_mappings(asset_ids: List[str],
                          root: Optional[str] = None, project: Optional[str] = None) -> List[Dict[str, Any]]:
    ids = set(asset_ids or [])
    return [m for m in _model_code_mappings(root, project) if m.get("targetId") in ids][:12]


@register_architect_tool(
    "kb.baseline",
    "读取当前项目 KB 基线信息(git 表示：分支/提交/基线版本)，用于需求影响范围判断",
)
def tool_kb_baseline(root: Optional[str], project: Optional[str]) -> Dict[str, Any]:
    if _project_degraded(root, project):
        return {}
    from .project import _resolve_project as _rp
    try:
        proj = _rp(root, project)
    except Exception:
        proj = None
    return {
        "name": (proj or {}).get("name", ""),
        "baselineId": (proj or {}).get("baselineId", ""),
        "branch": (proj or {}).get("branch", "main"),
    }


@register_architect_tool(
    "kb.graph",
    "遍历组件依赖图(依赖/被调用)，判断需求改动的影响链路(基于 KB 真实架构模型的组件 dependsOn 与跨社区边)",
)
def tool_kb_graph(root: Optional[str], project: Optional[str],
                  comp_ids: List[str]) -> List[Dict[str, Any]]:
    """返回组件级依赖链：基于 KB 真实架构模型(kb.asset.search 同源)计算
    每个组件的下游依赖(dependsOn)与上游被依赖方，并附文件/调用关系。

    returns [{componentId, name, kind, downstream:[name], upstream:[name], files:[...], relMd}]
    """
    if not comp_ids:
        return []
    if _project_degraded(root, project):
        raise ValueError("KB 能力不足：项目未绑定 KB 基线，无法读取依赖图。请在项目概览中关联知识库。")
    assets = _model_assets(root, project)
    by_id = {a.get("id"): a for a in assets}
    id_to_name = {a.get("id"): (a.get("name") or a.get("id")) for a in assets}
    # 上游映射：扫描全部组件的 dependsOn，收集指向每个 comp 的调用方
    upstream_map: Dict[str, List[str]] = {}
    for a in assets:
        for dep in (a.get("dependsOn") or []):
            upstream_map.setdefault(dep, []).append(a.get("id"))

    results: List[Dict[str, Any]] = []
    for cid in comp_ids:
        comp = by_id.get(cid)
        if not comp:
            results.append({
                "componentId": cid, "name": cid, "kind": "service",
                "downstream": [], "upstream": [], "files": [],
                "relMd": f"## 依赖分析\n\nKB 中未命中组件 {cid}，请核对组件 ID。",
            })
            continue
        downstream = [id_to_name.get(d, d) for d in (comp.get("dependsOn") or [])]
        upstream = [id_to_name.get(u, u) for u in (upstream_map.get(cid) or [])]
        name = comp.get("name") or cid
        lines = [f"## 组件 {name} 依赖链\n",
                 f"- **下游依赖**(本组件依赖)：{('、'.join(downstream)) if downstream else '无'}\n",
                 f"- **上游调用方**(依赖本组件)：{('、'.join(upstream)) if upstream else '无'}\n",
                 f"- **包含文件**：{(', '.join((comp.get('owns') or [])[:8])) or '—'}\n",
                 f"- **变更状态**：{comp.get('change') or 'same'}",
                 ""]
        results.append({
            "componentId": cid, "name": name, "kind": comp.get("kind") or "service",
            "downstream": downstream, "upstream": upstream,
            "files": (comp.get("owns") or [])[:8],
            "change": comp.get("change") or "same",
            "relMd": "\n".join(lines),
        })
    return results


@register_architect_tool(
    "project.ctx",
    "读取当前项目上下文(项目名/分支/基线 id/降级状态)，LLM 用于判断模式(greenfield/existing)",
)
def tool_project_ctx(root: Optional[str], project: Optional[str]) -> Dict[str, Any]:
    from .project import _resolve_project as _rp
    try:
        proj = _rp(root, project)
    except Exception:
        proj = None
    return {
        "root": root, "project": project,
        "bound": bool(proj),
        "degraded": _project_degraded(root, project),
        "name": (proj or {}).get("name", ""),
        "baselineId": (proj or {}).get("baselineId", ""),
    }


# ── 资产地图工具(map.*): 与对外 MCP 服务同源实现(Markdown 输出) ────────
# 穷举/层级/统计/规约类提问(「有哪些组件」「L0/L1 模块」「资产统计」「编码规约」)的
# 正确入口；kb.asset.search 是关键词检索(≤6 条命中)，不适合枚举型提问。

@register_architect_tool(
    "map.overview",
    "资产地图总览(Markdown)：组件目录(名称/图层级/文件数/依赖出入)+语义资产分类统计+基线视图。"
    "穷举/统计/层级类提问(如「有哪些组件」「L0/L1 模块」「资产总数」)先调此工具",
)
def tool_map_overview(root: Optional[str], project: Optional[str]) -> Dict[str, Any]:
    from .asset_map_tools import run_tool
    return {"markdown": run_tool("map.overview", {"project": project})}


@register_architect_tool(
    "map.component",
    "组件档案(Markdown)：单个组件的图层级/文件清单/依赖出入/组件内语义资产",
)
def tool_map_component(root: Optional[str], project: Optional[str],
                       name: str = "") -> Dict[str, Any]:
    from .asset_map_tools import run_tool
    if not (name or "").strip():
        return {"error": "缺少组件名(name)"}
    return {"markdown": run_tool("map.component", {"name": name.strip(), "project": project})}


@register_architect_tool(
    "map.assets",
    "语义资产表列检索(Markdown 表格)：kind/level 过滤+关键词，返回 名称/文件/状态 清单。"
    "需要浏览资产清单(而非前几条命中)时用",
)
def tool_map_assets(root: Optional[str], project: Optional[str], query: str = "",
                    kind: str = "", level: str = "", limit: int = 30) -> Dict[str, Any]:
    from .asset_map_tools import run_tool
    return {"markdown": run_tool("map.assets", {"query": query, "kind": kind,
                                                "level": level, "limit": limit,
                                                "project": project})}


@register_architect_tool(
    "map.rules",
    "项目规约全集(Markdown)：架构规约+编码规约+命名规约+词汇表，编码/方案评估必须遵守",
)
def tool_map_rules(root: Optional[str], project: Optional[str]) -> Dict[str, Any]:
    from .asset_map_tools import run_tool
    return {"markdown": run_tool("map.rules", {"project": project})}


@register_architect_tool(
    "map.graph",
    "关系图(mermaid)：kind=component 组件依赖图 / kind=semantic 语义关系图",
)
def tool_map_graph(root: Optional[str], project: Optional[str],
                   kind: str = "component") -> Dict[str, Any]:
    from .asset_map_tools import run_tool
    return {"markdown": run_tool("map.graph", {"kind": kind or "component",
                                               "project": project})}


@register_architect_tool(
    "asset.semantic.stats",
    "语义资产统计：总量/按六类(kind)/按粒度(level)/状态(active/stale/deleted/needsUpdate)。"
    "「有多少资产」「各类数量」等统计类提问用",
)
def tool_semantic_stats(root: Optional[str], project: Optional[str]) -> Dict[str, Any]:
    from .sem.engine import (SEMANTIC_KINDS, SEMANTIC_LEVELS, _lazy_reconcile,
                             project_id_for)
    from . import store
    try:
        _lazy_reconcile(root, project)
        pid = project_id_for(root, project)
        by_kind = {k: store.SemanticAssetsStore.count(pid, kind=k) for k in SEMANTIC_KINDS}
        by_level = {lv: store.SemanticAssetsStore.count(pid, level=lv) for lv in SEMANTIC_LEVELS}
        rows = store.SemanticAssetsStore.all_status(pid, limit=4000)
        status: Dict[str, int] = {"active": 0, "stale": 0, "deleted": 0, "needsUpdate": 0}
        for a in rows:
            status[a.get("status") or "active"] = status.get(a.get("status") or "active", 0) + 1
            if a.get("needsUpdate"):
                status["needsUpdate"] += 1
        return {"total": sum(by_kind.values()), "byKind": by_kind,
                "byLevel": by_level, "status": status}
    except Exception as e:
        logger.warning("[req_agent] asset.semantic.stats failed: %s", e)
        return {"error": str(e)}


# ── 语义数据资产工具 ─────────────────────────────────────────────

@register_architect_tool(
    "asset.semantic.search",
    "检索当前项目已提取的语义数据资产(六类 entity/contract/state/rule/process/decision)，"
    "支持 kind 类别 + level 粒度(business/implementation/logic) + scopes 组件范围过滤与关键词命中。"
    "返回资产(含 AST 锚点)。",
)
def tool_semantic_search(root: Optional[str], project: Optional[str],
                         text: str = "", kind: str = "", level: str = "",
                         limit: int = 20, offset: int = 0,
                         scopes: Optional[List[str]] = None,
                         includeGlobal: bool = False) -> List[Dict[str, Any]]:
    from . import semantic_assets as S
    try:
        rows = S.search(root, project, text, kind, limit, offset,
                        scopes=scopes, level=level)
    except Exception as e:
        logger.warning("[req_agent] asset.semantic.search failed: %s", e)
        rows = []
    # WS8-S4: includeGlobal 时合并主库全局桶(按需开关, R7 禁全量注入)
    if includeGlobal and text.strip():
        try:
            from .store.base import GLOBAL_PID, _db, _row_to_api
            like = f"%{text.strip()}%"
            grows = _db().fetchall(
                "SELECT * FROM arch_semantic_assets WHERE project_id = ? "
                "AND status = 'active' AND (name LIKE ? OR desc LIKE ?) LIMIT ?",
                (GLOBAL_PID, like, like, max(3, int(limit) // 4)))
            have = {r.get("id") for r in rows}
            for g in grows:
                d = _row_to_api(g)
                if d.get("id") in have:
                    continue
                d["scopeGlobal"] = True
                rows.append(d)
        except Exception as e:
            logger.debug("[req_agent] global layer merge skipped: %s", e)
    return rows


@register_architect_tool(
    "asset.semantic.extract",
    "按指令从最新代码提取语义数据资产(六类: entity/contract/state/rule/process/decision，实现层)并落库。"
    "指令化提取的唯一执行入口：规则定死类别+tAgent 定向+锚定代码段+语义解释。"
    "参数 scope={type: comm|files|symbols|project, key?, files?, symbols?}，"
    "comm 时 key 为**组件ID**(comm-…，权威范围)；kinds 可选[六类]。"
    "返回紧凑摘要 {count, byKind, degraded, source[, error, candidates, reason]}。",
)
def tool_semantic_extract(root: Optional[str], project: Optional[str],
                          scope: Dict[str, Any] = None,
                          kinds: Optional[List[str]] = None) -> Dict[str, Any]:
    from . import semantic_assets as S
    scope = scope or {}
    try:
        res = S.extract_scope(root, project,
                              scope.get("type") or "project",
                              scope.get("key") or "",
                              scope.get("files") or [],
                              scope.get("symbols") or [],
                              kinds=kinds)
    except Exception as e:
        logger.warning("[req_agent] asset.semantic.extract failed: %s", e)
        return {"count": 0, "degraded": True, "error": str(e)}
    # 紧凑摘要(供 agent 如实汇报；不回传全量资产对象，省对话上下文)
    from collections import Counter
    assets = res.get("assets") or []
    summary: Dict[str, Any] = {
        "count": res.get("count", len(assets)),
        "byKind": dict(Counter(a.get("kind") for a in assets)),
        "degraded": res.get("degraded", False),
        "source": res.get("source"),
    }
    if res.get("error"):
        summary["error"] = res["error"]
    if res.get("candidates"):
        summary["candidates"] = res["candidates"]
    if res.get("reason"):
        summary["reason"] = res["reason"]
    return summary


@register_architect_tool(
    "asset.semantic.detail",
    "读取单个语义数据资产的完整信息(描述/结构化细节/AST 锚点)，供需求/设计引用确认。",
)
def tool_semantic_detail(asset_id: str, root: Optional[str] = None,
                         project: Optional[str] = None) -> Optional[Dict[str, Any]]:
    from . import semantic_assets as S
    return S.detail(asset_id)


@register_architect_tool(
    "asset.semantic.mappings",
    "查询语义数据资产对应的代码映射(文件/行号/符号)，锁定「改哪里」的精确位置。",
)
def tool_semantic_mappings(asset_ids: List[str], root: Optional[str] = None,
                           project: Optional[str] = None) -> List[Dict[str, Any]]:
    from . import semantic_assets as S
    out = []
    for i in (asset_ids or []):
        out += S.mappings(i, root, project)
    return out[:12]


@register_architect_tool(
    "asset.semantic.reconcile",
    "校验语义数据资产新鲜度(git/文件哈希比对)：标记因文件变更或新增文件影响而过期的资产为「需更新后使用」。返回失效清单。",
)
def tool_semantic_reconcile(root: Optional[str], project: Optional[str]) -> Dict[str, Any]:
    from . import semantic_assets as S
    return S.reconcile_semantic(root, project, force=True)


@register_architect_tool(
    "asset.semantic.refresh",
    "更新单个过期(需更新)的语义数据资产：增量重提其所属范围；失败则软删并离线重新生成。返回新状态。",
)
def tool_semantic_refresh(asset_id: str, root: Optional[str] = None,
                          project: Optional[str] = None) -> Dict[str, Any]:
    from . import semantic_assets as S
    return S.handle_stale_asset(asset_id, root, project)


# ── 对话式提取工具（plan-C §4.1 skills+tools calling；M0 §8 工具清单） ──

@register_architect_tool(
    "code.read_symbols",
    "读取项目源码片段(按文件/符号/行号)，对话式提取前先看真实代码。"
    '参数 {"file": "相对路径", "symbol"?: "符号名", "startLine"?: 行, "endLine"?: 行}。',
)
def tool_code_read_symbols(root: Optional[str] = None, project: Optional[str] = None,
                           file: str = "", symbol: str = "",
                           startLine: int = 0, endLine: int = 0) -> Dict[str, Any]:
    import os
    from .semantic_assets import resolve_root, project_id_for
    from . import store as _store
    rpath = resolve_root(root, project)
    if not rpath or not file:
        return {"error": "缺少项目根或文件路径"}
    full = os.path.realpath(os.path.join(rpath, file))
    base = os.path.realpath(rpath)
    if not full.startswith(base + os.sep):
        return {"error": f"路径越界: {file}"}
    if not os.path.isfile(full):
        return {"error": f"文件不存在: {file}"}
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except Exception as e:
        return {"error": f"读取失败: {e}"}
    s, e = int(startLine or 0), int(endLine or 0)
    sym_info: Optional[Dict[str, Any]] = None
    if symbol and not (s and e):
        pid = project_id_for(root, project)
        cached = _store.AstCacheStore.get(pid, file.replace("\\", "/"))
        for n in (cached or {}).get("symbols") or []:
            if (n.get("name") or "") == symbol:
                s, e = int(n.get("startLine") or 0), int(n.get("endLine") or 0)
                sym_info = {"kind": n.get("kind") or "", "signature": n.get("signature") or ""}
                break
        if not (s and e):
            return {"error": f"符号未找到且未给行号: {symbol}",
                    "hint": "可改传 startLine/endLine 直接读行段"}
    if not s:
        s, e = 1, min(len(lines), 200)
    e = min(e or len(lines), len(lines))
    truncated = False
    if e - s + 1 > 240:
        e = s + 239
        truncated = True
    snippet = "\n".join(f"{i:4d}| {lines[i - 1]}" for i in range(s, e + 1))
    if len(snippet) > 12000:
        snippet = snippet[:12000] + "\n…(截断)"
        truncated = True
    return {"file": file, "symbol": symbol or None, "range": [s, e],
            "totalLines": len(lines), "truncated": truncated,
            "signature": (sym_info or {}).get("signature") or None,
            "code": snippet}


@register_architect_tool(
    "asset.semantic.save",
    "对话式提取落库：把按规约产出的语义资产写入项目(归一化管线：框架值域校验/名称继承/墓碑承接)。"
    "资产形态 {name, kind: entity|contract|state|rule|process|decision, level?, desc?, detail?, "
    "astRefs:[{file,symbol,startLine,endLine}]}。实现层资产必须带 astRefs 锚点；"
    "canonicalKey 命中既有资产时旧名优先，LLM 提议名以 proposedNames 返回供设计者定夺。",
)
def tool_asset_semantic_save(root: Optional[str] = None,
                             project: Optional[str] = None,
                             assets: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    from .semantic_assets import save_agent_assets
    return save_agent_assets(root, project, assets or [], executed_by="agent")


@register_architect_tool(
    "asset.semantic.update",
    "认知层编辑既有语义资产(仅改名/描述，overlay 审计)：patch={name? 新名(旧名自动入历史), desc? 新描述}。"
    "与 asset.semantic.save(新建)互补——已提取资产的措辞修正用本工具，勿重复 save。"
    "main-KB 关联项目会拒绝(应在主 KB 界面编辑)，错误信息含深链。",
)
def tool_asset_semantic_update(root: Optional[str] = None,
                               project: Optional[str] = None,
                               assetId: str = "",
                               patch: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from .semantic_assets import edit_asset_desc, rename_asset
    patch = patch or {}
    if not (assetId or "").strip():
        return {"error": "assetId 必填"}
    if not patch:
        return {"error": "patch 必填(至少含 name 或 desc)"}
    try:
        out: Dict[str, Any] = {}
        if (patch.get("name") or "").strip():
            out.update(rename_asset(assetId, patch["name"], author="agent"))
        if "desc" in patch:
            out.update(edit_asset_desc(assetId, patch.get("desc") or "", author="agent"))
        if not out:
            return {"error": "patch 无有效字段(仅支持 name/desc)"}
        return out
    except ValueError as e:
        return {"error": str(e)}


@register_architect_tool(
    "asset.semantic.merge",
    "合并语义资产：目标资产(intoId)吸收 targetIds 的锚点(并集)，目标行标记 mergedInto 留痕。"
    "用于设计者判定多个资产实为同一概念时。targetName 可选(合并后改名)。",
)
def tool_asset_semantic_merge(root: Optional[str] = None,
                              project: Optional[str] = None,
                              intoId: str = "",
                              targetIds: Optional[List[str]] = None,
                              targetName: str = "") -> Dict[str, Any]:
    from .semantic_assets import merge_assets
    try:
        return merge_assets((intoId or "").strip(), list(targetIds or []),
                            (targetName or "").strip(), author="agent")
    except ValueError as e:
        return {"error": str(e)}


@register_architect_tool(
    "asset.semantic.split",
    "拆分语义资产：按锚点组拆出新资产。parts=[{name, anchorKeys:[\"file:symbol\"], desc?}]，"
    "anchorKeys 必须取自原资产 astRefs 的 file:symbol；原资产标记 splitInto 留痕。",
)
def tool_asset_semantic_split(root: Optional[str] = None,
                              project: Optional[str] = None,
                              assetId: str = "",
                              parts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    from .semantic_assets import split_asset
    try:
        return split_asset((assetId or "").strip(), list(parts or []), author="agent")
    except ValueError as e:
        return {"error": str(e)}


@register_architect_tool(
    "convention.propose",
    "把对话中观察到的命名重复模式固化为命名规约『提案』(pending，待设计者确认，你无决定权)。"
    "当你多次看到设计者把资产改名为同一模式(如统一加 Service/Controller 后缀、"
    "过程用动宾结构)时调用。ruleText 要具体可判定(如『服务以 XxxService 结尾』)；"
    "scenarios 用适用场景(命名=naming/提取=extract/验收=accept/通用=general)。"
    "设计者在界面点『确认』才生效(active)，点『忽略』则删除——你只提议不生效。",
)
def tool_convention_propose(root: Optional[str] = None,
                            project: Optional[str] = None,
                            ruleText: str = "",
                            scenarios: Optional[List[str]] = None,
                            appliesKinds: Optional[List[str]] = None) -> Dict[str, Any]:
    from . import naming as _naming
    from .semantic_assets import project_id_for
    pid = project_id_for(root, project)
    try:
        row = _naming.propose_convention(
            pid, ruleText or "", scenarios=scenarios or None,
            applies_kinds=appliesKinds or None, author="agent")
        return {"id": row.get("id"), "ruleText": row.get("ruleText"),
                "scenarios": row.get("scenarios"), "status": row.get("status")}
    except ValueError as e:
        return {"error": str(e)}


@register_architect_tool(
    "contract.propose",
    "把对话中讨论出的期望固化为契约条目草稿(draft，待设计者逐条确认，你无判定权)。"
    "items: [{kind: entity|contract|state|rule|process|decision, level?: implementation, "
    "target: {file?, symbol?}, behavior?: {steps?: [{order, semantic, condition?}], "
    "branches?: [{condition, semantic}], fields?: [{name, semantic?}], relations?: [{target, type?}]}, "
    "zAxis?: [{category: observability|resilience|config|security, text, anchor?}], "
    "acceptance?: {mode?: auto|assisted|manual, criteria?, linkedTests?}, "
    "origin: {quote: 设计者原话引用(必填证据), messageId?}, reqId?}]。"
    "kind/level 必须在当前框架值域内；target 无 file 且无 symbol 会自动标为意图级。",
)
def tool_contract_propose(root: Optional[str] = None,
                          project: Optional[str] = None,
                          items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    from . import ctx as _ctx
    from . import contracts as _contracts
    from .semantic_assets import project_id_for
    pid = project_id_for(root, project)
    conv_id = _ctx.get_conv() or ""
    out: List[Dict[str, Any]] = []
    created = 0
    for it in items or []:
        if not isinstance(it, dict):
            out.append({"error": "item 必须是对象"})
            continue
        try:
            origin = it.get("origin")
            if not isinstance(origin, dict):
                origin = {}
            if not origin.get("convId"):
                origin = {**origin, "convId": conv_id}
            row = _contracts.create_item(pid, {**it, "origin": origin}, author="agent")
            created += 1
            out.append({"id": row.get("id"), "kind": row.get("kind"),
                        "intentOnly": bool(row.get("intentOnly")),
                        "status": row.get("status")})
        except ValueError as e:
            out.append({"error": str(e), "kind": it.get("kind")})
    return {"created": created, "items": out}


# ── 绘图增强工具（经薄代理转发 reports diagram_tools 服务，单一起源） ──

@register_architect_tool(
    "diagram.build",
    "从结构化中间表示(IR)生成语法正确的 Mermaid/PlantUML 图代码。"
    "LLM 只描述图的结构(节点/边/分组/方向)，由本工具生成精确代码，"
    "避免小参数模型直接输出 mermaid/plantuml 源码时的语法错误。",
)
def tool_diagram_build(ir: Dict[str, Any]) -> Dict[str, Any]:
    from . import diagram as _diagram
    return _diagram.call_build(ir)


@register_architect_tool(
    "diagram.validate",
    "校验 Mermaid/PlantUML 代码语法。返回 {valid, errors, warnings}。"
    "生成图后建议校验一次，语法有问题时修正 IR 重新调用 diagram.build。",
)
def tool_diagram_validate(code: str, lang: str = "mermaid") -> Dict[str, Any]:
    from . import diagram as _diagram
    return _diagram.call_validate(code, lang)


# ── MCP 出向工具(经 MCP server 转发，供 plan agent 调用开放/外部 MCP 工具) ──

_MCP_TOOLS_CACHE: Dict[str, Any] = {"ts": 0.0, "tools": []}
_MCP_TOOLS_TTL = 60.0  # 秒：列工具带 TTL 缓存，避免每回合网络往返


def _mcp_tool_list() -> List[Dict[str, Any]]:
    """列 MCP 可用工具(GET /v1/tools，带 TTL 缓存)。不可达返回缓存/[]。"""
    import time
    now = time.time()
    if _MCP_TOOLS_CACHE["tools"] and now - _MCP_TOOLS_CACHE["ts"] <= _MCP_TOOLS_TTL:
        return _MCP_TOOLS_CACHE["tools"]
    tools = _kb_gateway().tools(timeout=5) or []
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
    result = _kb_gateway().query(tool, timeout=30, **(params or {}))
    if result is None:
        return {"ok": False, "tool": tool, "error": "MCP 不可达或超时"}
    return result


# ── 需求定稿工具(plan 结论 → 结构化分析 + 转入待执行) ────────────────

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

@register_architect_tool(
    "req.propose",
    "形成/更新需求规约：讨论收敛为明确需求，或设计者要求 生成方案/提炼方案/完善需求 时调用。"
    "用户要求 编写脚本/工具/程序/函数 时**必须先调用本工具**收敛需求"
    "(designMd=技术选型与结构设计)，由 /执行 链路生成代码——"
    "严禁在对话中直接输出成品代码替代需求收敛(代码属于执行产物，不落库无法走执行链路)。"
    "会话已绑定未完结的需求时默认**更新该需求**(追加新 draft 版本，不新建)；"
    "需要在本会话开启全新需求时传 newRequirement=true。"
    "产出规约见 plan 场景技能文档：designMd 为核心(逻辑与实现细节；为空时用户将无法 /定稿——门禁要求方案非空)，"
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
    from . import ctx, store as _store
    from .common import _ts
    title = (title or "").strip()
    if not title:
        return {"ok": False, "error": "缺少需求标题"}
    conv_id = ""
    try:
        conv_id = ctx.get_conv()
    except Exception:
        pass
    allowed = _md_lines(allowedScopeMd)
    forbidden = _md_lines(forbiddenScopeMd)
    acceptance = _md_lines(acceptanceMd)
    sections = []
    if requirementMd:
        sections.append(f"## 需求目标\n\n{requirementMd}")
    if allowedScopeMd:
        sections.append(f"## 允许增删改范围\n\n{allowedScopeMd}")
    if forbiddenScopeMd:
        sections.append(f"## 禁止改动(一定不能动)\n\n{forbiddenScopeMd}")
    if designMd:
        sections.append(f"## 方案\n\n{designMd}")
    if acceptanceMd:
        sections.append(f"## 最终验收标准\n\n{acceptanceMd}")
    if assessmentMd:
        sections.append(f"## 评估\n\n{assessmentMd}")
    snapshot = _spec_snapshot(title, "\n\n".join(sections), designMd, allowed,
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
            _sync_analysis_cache(bound_rid, snapshot)
            try:
                log_conv_event(conv_id,
                               f"📝 **规约已更新**：`{bound_rid}` → v{entry['ver']}"
                               f"（draft；`/定稿` 确认后 `/执行`）")
            except Exception:  # noqa: BLE001
                pass
            return {"ok": True, "requirementId": bound_rid, "ver": entry["ver"],
                    "updated": True, "title": title,
                    "hint": "已更新既有需求规约(新 draft 版本)；`/定稿` 后 `/执行` 启动作业"}

    req = {
        "id": _store.next_id("RQ"), "kind": "user-story",
        "status": "draft", "title": title,
        "priority": priority if priority in ("P0", "P1", "P2") else "P1",
        "activeVer": 1,
        "specVersions": [{"ver": 1, "state": "draft", "snapshot": snapshot,
                          "source": {"convId": conv_id, "actor": "architect"},
                          "reason": "初始提案", "createdAt": _ts()}],
        "ownerConv": conv_id, "sourceType": "asset-chat",
        "projectId": project or "",
        "sourceConversationId": conv_id, "updatedAt": _ts(), "createdAt": _ts(),
    }
    _store.RequirementsStore.create(req)
    _sync_analysis_cache(req["id"], snapshot)
    # 回写会话绑定(后端真相源): amend 契约/守卫修复/执行链路依赖 conv.reqId
    if conv_id:
        try:
            _store.ConversationsStore.update(conv_id, {"reqId": req["id"]})
        except Exception as e:  # noqa: BLE001
            logger.warning("[req.propose] conv.reqId 回写失败 conv=%s: %s", conv_id, e)
    # 方案缺失标注: designMd 空时在回执与事件流如实提示(定稿门禁会拦, 提前引导 /调整)
    no_design = not str(designMd or "").strip()
    receipt = (f"📝 **需求规约已创建**：`{req['id']}` {title}（draft v1；"
               "`/定稿` 后 `/执行` 启动作业）")
    if no_design:
        receipt = (f"📝 **需求规约已创建**：`{req['id']}` {title}（draft v1；"
                   "**⚠️ 未包含实现方案(designMd 为空)**——`/定稿` 门禁会要求补全, "
                   "建议直接 `/调整` 描述方案要点)")
    try:
        log_conv_event(conv_id, receipt)
    except Exception:  # noqa: BLE001
        pass
    hint = "新需求规约已创建(draft v1)"
    if no_design:
        hint += "(⚠️ 方案缺失, 建议 /调整 补全后再 /定稿)"
    return {"ok": True, "requirementId": req["id"], "ver": 1, "updated": False,
            "title": title, "noDesign": no_design, "hint": hint}


@register_architect_tool(
    "req.finalize",
    "规约确认(交托门禁)：把当前 draft 版本确认为可执行(confirmed/ready)。"
    "通常由用户指令 `/定稿` 触发(系统直通, 模型仅在用户明确要求时代调)。"
    "门禁(结构完整性, 不评判语义)：designMd 非空; acceptance 若提供必须为数组且语法有效。"
    "缺失项不拦截, 仅在结果中如实提示。确认后旧 confirmed 版本自动废弃(superseded)。"
    "参数 reqId 勿传(系统自动取会话绑定需求)。",
)
def tool_req_finalize(reqId: str = "", root: Optional[str] = None,
                      project: Optional[str] = None) -> Dict[str, Any]:
    from . import ctx
    req_id = (reqId or "").strip() or ctx.get_req()
    if not req_id:
        return {"ok": False, "error": "当前会话未绑定需求，无法确认。请先在对话中形成需求(req.propose)"}
    row = store.RequirementsStore.get(req_id)
    if not row:
        return {"ok": False, "error": f"需求 {req_id} 不存在"}
    if (row.get("doneMark") or 0) == 1:
        return {"ok": False, "error": f"{req_id} 已完结(用户判定已完成)；继续执行请新建需求"}
    active = store.RequirementsStore.spec_active(req_id)
    if not active:
        return {"ok": False, "error": "无生效规约版本"}
    if active.get("state") == "confirmed":
        snap0 = active.get("snapshot") or {}
        has_d = bool(str(snap0.get("designMd") or "").strip())
        has_r = bool(str(snap0.get("desc") or row.get("desc") or "").strip())
        if not has_d and not has_r:
            return {"ok": False, "error": "规约确认门禁未过——当前已确认版本既无方案(designMd)"
                    "也无需求正文, 执行作业只会空转。请 `/调整` 补充内容落新版本后重新 `/定稿`。"}
        if not has_d:
            return {"ok": True, "reqId": req_id, "ver": active.get("ver"), "already": True,
                    "hint": "当前版本已确认(ready，将按需求正文执行)；建议 `/调整` 细化方案后重启作业。可直接 `/执行`"}
        return {"ok": True, "reqId": req_id, "ver": active.get("ver"), "already": True,
                "hint": "当前版本已确认(ready)，可直接 `/执行` 启动作业"}
    snap = active.get("snapshot") or {}
    # 结构门禁(放宽裁决): designMd 非空即可放行; 其余缺失只提示不拦截
    if not (snap.get("designMd") or "").strip():
        return {"ok": False, "error": "规约确认门禁未过——方案(designMd)为空(结构不完整)。"
                "请先完善方案(req.propose / req.amend)再 `/定稿`。"}
    warns = []
    if not (snap.get("acceptance") or []):
        warns.append("验收标准(acceptance)未定义")
    scope_files = parse_scope_files(snap.get("allowedScope") or [])
    if not scope_files:
        warns.append("允许改动范围未解析出文件/目录(并行互斥无法保护本需求)")
    warn_note = ("；⚠️ " + "；".join(warns)) if warns else ""
    res = store.RequirementsStore.spec_confirm(req_id)
    if not res.get("ok"):
        return res
    try:
        log_conv_event(ctx.get_conv(),
                       f"✅ **规约已确认**：`{req_id}` v{active.get('ver')}（ready，可执行）"
                       + warn_note)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "reqId": req_id, "ver": active.get("ver"), "status": "ready",
            "boundaryFiles": sorted(scope_files), "warns": warns,
            "hint": "规约已确认(ready)；发送 `/执行` 启动实施作业" + warn_note}


@register_architect_tool(
    "req.amend",
    "需求修订(通用)：用户要求 补充需求/完善方案/调整规约 时调用——对会话绑定(或指定)"
    "需求追加新 draft 版本(append-only，历史版本保留可追溯)。"
    "参数均可选——只传需要调整的字段，未传字段沿用当前版本值。"
    "参数：reqId(可选)、designMd(调整后完整方案)、allowedScope[str]、forbiddenScope[str]、"
    "acceptance[str]、functionalScope[str]、requirementMd(需求目标)、"
    "assessmentSummary(str)、reasoning(修订理由, 版本留痕)。",
)
def tool_req_amend(reqId: str = "", designMd: str = "", requirementMd: str = "",
                   allowedScope: Optional[List[str]] = None,
                   forbiddenScope: Optional[List[str]] = None,
                   acceptance: Optional[List[str]] = None,
                   functionalScope: Optional[List[str]] = None,
                   assessmentSummary: str = "", reasoning: str = "",
                   root: Optional[str] = None,
                   project: Optional[str] = None) -> Dict[str, Any]:
    from . import ctx
    req_id = (reqId or "").strip() or ctx.get_req()
    if not req_id:
        return {"ok": False, "error": "当前会话未绑定需求且未指定 reqId，无法修订"}
    row = store.RequirementsStore.get(req_id)
    if not row:
        return {"ok": False, "error": f"需求 {req_id} 不存在"}
    if (row.get("doneMark") or 0) == 1:
        return {"ok": False, "error": f"{req_id} 已完结；补充需求请新建需求(req.propose newRequirement=true)"}
    active = store.RequirementsStore.spec_active(req_id) or {}
    snap = dict(active.get("snapshot") or {})
    changed = []
    if requirementMd:
        snap["desc"] = f"## 需求目标\n\n{requirementMd}"
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
                       f"✏️ **规约已修订**（{req_id} → v{entry['ver']} draft）：{'、'.join(changed)}"
                       + (f" —— {str(reasoning)[:120]}" if reasoning else ""))
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "reqId": req_id, "ver": entry["ver"], "amended": changed,
            "hint": "修订已追加新 draft 版本；`/定稿` 后 `/执行` 按新版本执行"}


# ── 会话只读工具(PR-D: 归档会话可被 agent 读取/引用; 不在任何动作黑名单) ──

@register_architect_tool(
    "conv.read",
    "读取会话(含归档)用于回顾/提炼/引用到新会话: 返回标题/状态/角色/最近消息。"
    "归档会话只读——历史回顾、交接引用、提炼总结用本工具, 不能向其发送消息。"
    "参数：convId(会话 id)、limit?(消息条数, 默认 20)。",
)
def tool_conv_read(convId: str = "", limit: int = 20) -> Dict[str, Any]:
    from . import store as _store
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

from ..agent.cognition.llm import (  # noqa: F401,E402
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


def log_conv_event(conv_id: str, text: str) -> None:
    """统一时间线: 中间资产事件(提案/定稿/指派)以消息沉淀进来源会话。

    失败静默——事件回写不阻断工具主流程。
    """
    if not conv_id:
        return
    try:
        from .common import _ts
        store.ConversationsStore.append_message({
            "id": store.next_id("m"), "conversationId": conv_id,
            "role": "assistant", "time": _ts(),
            "content": text,
        })
    except Exception:  # noqa: BLE001
        pass




def run_tools_loop(msgs: List[Dict[str, str]], *,
                   root: Optional[str] = None, project: Optional[str] = None,
                   model_id: Optional[str] = None,
                   mode: str = "chat",
                   output_schema: Optional[Dict[str, Any]] = None,
                   max_tokens: Optional[int] = None,
                   max_rounds: int = 4,
                   allowed: Optional[List[str]] = None,
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
        res = llm_sync(work, mode=mode, output_schema=output_schema,
                       max_tokens=max_tokens, model_id=model_id, on_error=_err)
        content = (res or {}).get("content", "") if res else ""
        if not content:
            return {"content": "", "output": None, "error": last_err}
        calls = extract_tool_calls(content)
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
            if allowed and name not in allowed:
                results.append({"name": name,
                                "text": f"工具 {name} 不在本任务允许列表(仅限: {'/'.join(allowed)})，"
                                        "请改用允许的工具，或直接基于已有信息作答。"})
                continue
            result = run_arch_tool(name, args, root, project)
            if isinstance(result, dict) and result.get("error") \
                    and _is_repairable_error(str(result.get("error"))):
                _fixed = repair_tool_args(name, args, str(result.get("error")),
                                          model_id=model_id)
                if isinstance(_fixed, dict):
                    result = run_arch_tool(name, _fixed, root, project)
                    if not (isinstance(result, dict) and result.get("error")):
                        results.append({"name": name,
                                        "text": f"(参数已自动修复) {tool_result_text(name, result)}"})
                        continue
            results.append({"name": name, "text": tool_result_text(name, result)})
        if not results:
            return {"content": strip_tool_blocks(content), "output": None}
        tool_feed = "\n".join(f"[{r['name']}] {r['text']}" for r in results)
        work.append({"role": "assistant", "content": strip_tool_blocks(content) or "(调用知识库检索)"})
        work.append({"role": "user", "content": f"以下是知识库工具返回结果，请基于结果直接回答，不再输出工具调用块：\n{tool_feed}"})
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
    "- req.finalize：规约确认(交托门禁)——通常由用户指令 `/定稿` 系统直通，"
    "模型仅在用户明确要求时代调，把当前 draft 确认为 ready。reqId 勿传(系统自动取会话绑定需求)\n"
    "- req.propose：需求提案(新建或幂等更新)——对话产出完整需求/方案时调用，"
    "创建新需求或更新会话绑定需求的 draft 版本。"
    "用户要求 编写脚本/工具/程序 时**必须先调本工具**(designMd=选型与结构)，由 /执行 链路产出代码——"
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
    "工具调用协议(重要)：当需要检索知识库/项目数据才能回答(例如确认真实资产、基线、依赖链路)时，"
    "先且仅先输出一个工具调用块，格式为：\n"
    '[TOOL_CALL]{"tool":"<工具名>","arguments":{参数}}[/TOOL_CALL]\n'
    "硬性规则(防编造)：凡是会改数据或有真实执行结果的指令(提取/刷新/保存/定稿/委派执行等)，"
    "必须实际调用对应工具拿到同步返回的结果，再如实转述；"
    "严禁不调用工具就输出『已启动/报告/条数/检查结果』等编造结论。\n"
    "需求落库纪律(必须遵守)：\n"
    "1. 修改既有需求(用户确认后补充约束/调整方案/完善规约) → 必须用 [TOOL_CALL] 调 "
    "req.amend，严禁重新 req.propose 或输出裸 JSON 围栏当作工具调用；\n"
    "2. RQ 编号/数据 ID 一律由系统管理：工具调用不传 reqId(系统自动取会话绑定)，"
    "回复中的编号只来自工具返回，严禁自造编号(会被系统守卫拦截)；\n"
    "3. 确认(draft→ready)由用户指令 `/定稿` 发起(系统直通)；修订(req.amend)时不要顺带调用 req.finalize。\n"
    "会话指令符号(系统处理，与模型无关)：用户消息以 / 开头(/执行 /定稿 /继续 /diff /调整)时"
    "由系统直接执行确定性动作——模型不会收到这类消息，也不要在回复中代用户发出指令。\n"
    "各工具的参数：\n"
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
    '- req.finalize: {}——reqId 勿传(系统自动取会话绑定需求)；门禁=结构完整(designMd 非空)\n'
    '- req.propose / req.amend: 参数形状见上方能力清单(reqId 同样勿传)\n'
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
                       model_id: str = "") -> str:
    """自由对话系统提示：经 prompt_registry 组装(块化/按模型档案分级/预算裁剪)。

    等价模式(默认)下与旧拼接(header/边界/CAPABILITY/IR/📐/MCP/skill)逐字节
    一致; prompt.overrides 可开单源模式(能力文档由工具注册表渲染)与分级预算。
    model_id 非空 → 查模型能力档案取 tier(缺省 t1 保守档)。
    """
    from . import model_profile as _mp
    from . import prompt_registry as _pr
    tier = _mp.tier_of(model_id or "")
    return _pr.render_system({
        "root": root, "project": project, "diagram_skill": diagram_skill,
        "skill_scenarios": skill_scenarios, "tier": tier, "model_id": model_id or ""})


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
    kb = (
        "KB 已绑定，可检索资产/基线/依赖图。"
        if bound and not degraded
        else "KB 降级(无资产检索)，仅能基于需求描述给出规划建议，建议先关联知识库。"
    )
    ir_doc = f"\n\n{_ir_schema_doc()}"
    extra = f"\n\n{_diagram_skill_doc()}" if diagram_skill else ""
    mcp_extra = f"\n\n{_mcp_doc()}"
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
        "(req.propose 带 title/requirementMd/**designMd**/acceptanceMd)，后续同样可 /定稿 + /执行。"
        "关联较弱时仅在方案中说明「独立于项目核心资产」并收敛 scope，**不得以此为由拒绝或推诿**。"
        "已创建需求(RQ 编号以系统回执为准)后继续跟进完善，不得再声明该任务不属于职责范围。\n\n"
        f"{_CAPABILITY_DOC}{ir_doc}{extra}{mcp_extra}{skill_extra}"
    )


# ── Skills 定义 ────────────────────────────────────────────────────────

@register_architect_tool(
    "task.propose",
    "创建 coding subagent 实施任务卡(轻门禁: 用户确认后执行)。方案成熟/用户要求实施时调用。",
)
def tool_task_propose(title: str, instruction: str,
                      executorType: Optional[str] = None,
                      root: Optional[str] = None, project: Optional[str] = None) -> Dict[str, Any]:
    """v2 混合触发: architect 整理任务(目标/方案要点/边界/验收) → 用户确认(P4 委托 planning.task_plan)。"""
    from ..agent.planning.task_plan import propose_task_tool
    return propose_task_tool(title, instruction, executorType=executorType,
                             root=root, project=project)


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


# ── Harness: 需求澄清 / 需求收集 ─────────────────────────────────────

_SYSTEM_PROMPT = (
    "你是 TopoCode 架构需求分析 agent。你拥有知识库 skills/tools 能力：可检索知识库资产"
    "(kb.asset.search)、查代码映射(kb.code_mappings)、读基线(kb.baseline)、遍历依赖图(kb.graph)、"
    "检索/提取语义数据资产(asset.semantic.*，类别 structure/behavior/rule/contract × 粒度 high/medium/low，"
    "锚定 AST 节点)。"
    "你的产出必须直接可被表单消费，不得包含多余解释。"
)


def _names(hits: List[Dict[str, Any]]) -> List[str]:
    return [h.get("name") or h.get("id") for h in hits if h]


def _kb_hits(root: Optional[str], project: Optional[str],
             text: str, preferred: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """组件资产 + 语义数据资产合并命中(需求分析收敛的候选来源)。"""
    hits = tool_kb_asset_search(root, project, text, preferred)
    try:
        from . import semantic_assets as S
        sem = S.search(root, project, text) or []
        seen = {h.get("id") for h in hits}
        for a in sem:
            if a.get("id") and a.get("id") not in seen:
                hits.append(a)
    except Exception:
        pass
    return hits


def _hint(hits: List[Dict[str, Any]]) -> str:
    names = "、".join(_names(hits))
    if not names:
        return "知识库未命中明显资产，请依据需求描述给出建议资产。"
    return f"知识库命中候选：{names}。请优先据此收敛范围。"


def req_harness_clarify(req: Dict[str, Any], root: Optional[str] = None,
                        project: Optional[str] = None,
                        model_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """clarify 回合: KB 资产检索 → LLM 生成澄清问题清单。返回 None 表示未生成(调用方明确报 502，不回退伪造)。

    model_id: 本次对话选择的模型(可选)；空则回退全局 llm.modelId → 主后端默认。
    """
    title = req.get("title", "")
    desc = req.get("desc", "")
    mode = req.get("mode") or ("greenfield" if not project else "existing")
    preferred = req.get("preferredAssetIds") or []
    text = f"{title} {desc}"
    hits = _kb_hits(root, project, text, preferred)

    sys_prompt = _SYSTEM_PROMPT + (
        "\n\n当前阶段：需求澄清。请根据需求与知识库命中，返回 3-5 个需要用户确认的问题。"
        '只输出 JSON 数组: [{"key": str, "label": str, "type": "text", "hint": str}]。'
        "不要 Markdown 代码块。不要多余文字。"
    )
    user_prompt = (
        f"需求标题：{title}\n需求描述：{desc or '(未提供)'}\n模式：{mode}\n\n"
        f"{_hint(hits)}\n\n请生成澄清问题清单。"
    )
    res = run_tools_loop([{"role": "system", "content": sys_prompt},
                          {"role": "user", "content": user_prompt}],
                         root=root, project=project,
                         mode="chat", max_tokens=get_max_tokens_preference(), model_id=model_id)
    if not res:
        return None
    questions = _parse_json_array(res.get("content", ""))
    if not questions:
        return None
    return {"questions": questions, "hits": hits, "mode": mode, "degraded": False}


def _parse_json_array(text: str) -> List[Dict[str, Any]]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict)]


def req_harness_collect(ctx: Dict[str, Any], root: Optional[str] = None,
                        project: Optional[str] = None,
                        model_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """collect 回合: 上下文+答案 → LLM structured 产出 RequirementAnalysis。返回 None 降级。

    model_id: 本次对话选择的模型(可选)；空则回退全局 llm.modelId → 主后端默认。
    """
    base = ctx.get("base") or {}
    answers = {k: str(v) for k, v in (ctx.get("answers") or {}).items() if v and str(v).strip()}
    note = (ctx.get("note") or "").strip()
    title = base.get("title", "")
    desc = base.get("desc", "")
    mode = base.get("mode") or ("greenfield" if not project else "existing")
    preferred = base.get("preferredAssetIds") or []
    text = f"{title} {desc} {note} {' '.join(answers.values())}"
    hits = _kb_hits(root, project, text, preferred)
    manual = [{"assetId": a, "role": "core", "source": "manual"} for a in (preferred or [])]

    # 完整数据资产目录(组件/ER/实体/流程/数据流/语义资产)作为候选池，覆盖文本命中未及的范围。
    catalog_items: List[Dict[str, Any]] = []
    catalog_text = ""
    try:
        from .design import data_asset_catalog, _catalog_text
        catalog = data_asset_catalog(root, project)
        catalog_items = catalog.get("items") or []
        catalog_text = _catalog_text(catalog_items)
    except Exception:
        pass

    schema = {
        "type": "object",
        "required": ["functionalScope", "entityBoundary", "assetScope", "estMin",
                      "implementationPath", "assessmentSummary"],
        "properties": {
            "functionalScope": {"type": "array", "items": {"type": "string"}},
            "entityBoundary": {"type": "array", "items": {"type": "string"}},
            "assessmentSummary": {"type": "string"},
            "assetScope": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["assetId", "assetType", "role", "source"],
                    "properties": {
                        "assetId": {"type": "string"},
                        "assetType": {"enum": ["component", "er", "orm", "entity",
                                                "flow", "dataflow",
                                                "entity", "contract", "state", "rule", "process", "decision"]},
                        "level": {"enum": ["business", "logic", "implementation"]},
                        "role": {"enum": ["core", "related"]},
                        "source": {"enum": ["auto", "manual"]},
                        "file": {"type": "string"},
                        "businessReason": {"type": "string"},
                    },
                },
            },
            "estMin": {"type": "integer"},
            "implementationPath": {"type": "string"},
        },
    }

    sys_prompt = _SYSTEM_PROMPT + (
        "\n\n当前阶段：需求分析收敛。请依据作答/候选资产，只输出一个 JSON 对象(不要代码块)，字段："
        '{"functionalScope":[str], "entityBoundary":[str], "assetScope":[{assetId,assetType,role,'
        'source,file?,businessReason?}], "estMin":int(分钟), "implementationPath":str, "assessmentSummary":str}。'
        "assetScope 从下方完整数据资产目录与用户首选资产收敛，core 为直接改动、related 为联动，"
        "businessReason 简述业务理由。"
    )
    convo = "\n".join(
        f"{t.get('role')}: {t.get('content')}" for t in (ctx.get("turns") or [])[-8:]
        if isinstance(t, dict) and t.get("content")
    )
    answered_lines = "\n".join(f"• {k}: {v}" for k, v in answers.items())
    user_prompt = (
        f"需求：{title}\n描述：{desc or '(未提供)'}\n模式：{mode}\n"
        f"候选资产：{'、'.join(_names(hits)) or '—'}\n用户作答：\n{answered_lines or '(无)'}\n"
        f"备注：{note or '(无)'}\n对话摘录：{convo or '(无)'}"
    )
    if catalog_text:
        user_prompt += (
            f"\n\n完整数据资产目录({len(catalog_items)} 项)，assetScope 只从其中选择，不要臆造不存在的资产：\n"
            f"{catalog_text}"
        )
    res = run_tools_loop([
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ], root=root, project=project, mode="structured", output_schema=schema,
        max_tokens=get_max_tokens_preference(), model_id=model_id)
    if not res:
        return None
    output = res.get("output")
    if not output:
        return None

    report = {
        "functionalScope": output.get("functionalScope") or [],
        "entityBoundary": output.get("entityBoundary") or [],
        "feasibility": {"ok": True, "reason": "经知识库与 LLM 收敛，路径清晰",
                        "estMin": int(output.get("estMin") or 0)},
        "assetScope": _merge_assets(output.get("assetScope") or [], manual, hits, root, project),
        "assessment": _build_assessment(hits),
        "assessmentSummary": output.get("assessmentSummary")
            or f"需求「{title}」评估结论：可行。{_assessment_summary(hits)}",
        "implementationPath": output.get("implementationPath") or "",
        "changes": _build_changes(hits),
        "steps": _build_steps(hits, output.get("estMin") or 90),
    }
    return {"report": report, "hits": hits[:6], "degraded": False}


def _assessment_summary(hits: List[Dict[str, Any]]) -> str:
    if not hits:
        return "可行但需补充上下文。"
    return f"知识库命中 {len(hits)} 项资产，核心改动收敛。"


def _build_assessment(hits: List[Dict[str, Any]]):
    if hits:
        return {"necessity": {"grade": "high", "reason": f"命中 {len(hits)} 项资产"},
                "atomicity": {"independent": len(hits) <= 3,
                              "reason": "核心收敛" if len(hits) <= 3 else "跨资产较多"},
                "acceptability": {"ok": True, "reason": "可转化为功能用例验收"}}
    return {"necessity": {"grade": "medium", "reason": "命中不足"},
            "atomicity": {"independent": True, "reason": "领域建模建议"},
            "acceptability": {"ok": True, "reason": "可转换为功能用例验收"}}


def _merge_assets(llm_assets: List[Dict[str, Any]], manual: List[Dict[str, Any]],
                  hits: List[Dict[str, Any]],
                  root: Optional[str] = None, project: Optional[str] = None) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for m in manual:
        merged[m["assetId"]] = dict(m)
    for a in llm_assets:
        aid = a.get("assetId")
        if aid in merged:
            merged[aid].update({k: v for k, v in a.items() if k not in ("role", "source")})
        else:
            merged[aid] = dict(a)
    cm_by = {c.get("targetId"): c for c in _model_code_mappings(root, project)}
    for aid in list(merged.keys()):
        cm = cm_by.get(aid)
        if cm and not merged[aid].get("file"):
            merged[aid]["file"] = cm.get("file")
    return list(merged.values())


def _build_changes(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"resource": h.get("name") or h.get("id"), "kind": "modified",
             "before": f"当前 {h.get('name')} 基线实现", "after": "扩展以覆盖需求变更"}
            for h in hits[:4]]


def _build_steps(hits: List[Dict[str, Any]], est_min: int) -> List[Dict[str, Any]]:
    names = [h.get("name") or h.get("id") for h in hits[:3]]
    primary = "、".join(names) or "核心资产"
    # 语义资产 id(sa-*)并入步骤 context，供任务树携带并在 coding-agent 上下文展开锚点。
    sem_ids = [h.get("id") for h in hits if h.get("id") and str(h.get("id")).startswith("sa-")][:6]
    ctx1 = list(dict.fromkeys(names + sem_ids))
    return [
        {"id": "step-1", "title": "梳理现状与边界",
         "desc": f"检索知识库中 {primary} 的现状，锁定逻辑边界与不变量", "estMin": 30,
         "context": ctx1},
        {"id": "step-2", "title": "实现需求变更",
         "desc": f"按需求落地变更，覆盖 {primary} 的扩展点", "estMin": int(est_min),
         "context": ctx1},
        {"id": "step-3", "title": "测试与验收",
         "desc": "补充单测与集成用例，覆盖幂等/回滚/边界行为", "estMin": 60,
         "context": ["验收标准"] + sem_ids},
    ]