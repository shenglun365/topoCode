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
from typing import Any, Callable, Dict, List, Optional

from . import store

logger = logging.getLogger(__name__)

# ── Skills 注册表(architect 专属) ──────────────────────────────────────

_ARCH_SKILLS: List[Dict[str, Any]] = []


def register_architect_skill(name: str, description: str = "",
                             steps: int = 1, category: str = "requirement-analysis") -> Callable:
    """类/函数装饰器：注册 architect 专属技能元数据(与主后端 skill_registry 同形)。"""
    def decorator(fn):
        _ARCH_SKILLS.append({
            "name": name, "description": description, "steps": steps, "category": category,
        })
        return fn
    return decorator


def architect_skills() -> List[Dict[str, Any]]:
    seen: set = set()
    out = []
    for s in _ARCH_SKILLS:
        if s["name"] not in seen:
            seen.add(s["name"])
            out.append(s)
    return out


# ── Tools 注册表(architect 专属: 知识库检索 / 项目上下文) ──────────────

_ARCH_TOOLS: Dict[str, Dict[str, Any]] = {}


def register_architect_tool(name: str, description: str = "") -> Callable:
    def decorator(fn):
        _ARCH_TOOLS[name] = {"name": name, "description": description, "handler": fn}
        return fn
    return decorator


def architect_tools() -> List[Dict[str, str]]:
    return [{"name": t["name"], "description": t["description"]} for t in _ARCH_TOOLS.values()]


# ── 自由对话工具协议: 模型文本工具块 → 解析/执行 ──────────────────────
# 标准形: [TOOL_CALL]{"tool":"x","arguments":{...}}[/TOOL_CALL]
# 模型变体(均容忍)：```json 围栏、丢前导 '['、闭合标签写成 [/TOOL_CALL> 等。
# ⚠️ 未闭合块(部分模型省略 [/TOOL_CALL]，裸开标签后直接跟 JSON)：必须支持——
# 否则整轮 0 解析、[TOOL_CALL] 裸文本透传到对话且工具不执行(生产实测回归)。
# 策略：闭合标签存在时以其定界；缺失时按「下一开标签/文末」切段 + 花括号
# 配对(字符串/转义感知)抽取 JSON，保证连续多个未闭合块逐块解析。
# ⚠️ lookbehind (?<![/\w])：排除闭合标签 [/TOOL_CALL] 内部的 "TOOL_CALL]" 子串被
# 二次认作开标签(曾导致 seg_end 被切短、闭合定界失效、strip 残留闭合标签)。
_TOOL_CALL_OPEN = re.compile(r'(?:```(?:json)?\s*)?\[?\s*(?<![/\w])TOOL_CALL\]',
                             re.DOTALL)
_TOOL_CALL_CLOSE = re.compile(r'\[/TOOL_CALL[>\]]+\]?\s*(?:```)?')
_TOOL_CALL_BLOCK = re.compile(
    r'(?:```(?:json)?\s*)?\[?\s*TOOL_CALL\](.*?)\[/TOOL_CALL[>\]]+\]?\s*(?:```)?',
    re.DOTALL)
_FENCE = re.compile(r'^\s*```(?:json)?\s*|\s*```\s*$')


def _clean_block(raw: str) -> str:
    raw = _FENCE.sub("", raw or "").strip()
    if raw.startswith("{"):
        return raw
    first = raw.find("{")
    last = raw.rfind("}")
    return raw[first:last + 1] if first >= 0 and last > first else raw


def _json_object_spans(text: str) -> List[tuple]:
    """花括号配对(字符串/转义感知)返回顶层 {…} 的 (start, end_exclusive) 段列表。"""
    spans: List[tuple] = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text or ""):
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    spans.append((start, i + 1))
                    start = -1
    return spans


def _parse_tool_payload(raw: str) -> Optional[Dict[str, Any]]:
    """块内容 → {tool, arguments}；非法 JSON/缺 tool 字段返回 None。

    先整体直解(_clean_block 快路径)；失败再按花括号配对逐段兜底
    (块内含前后杂文/多对象时仍可解析)。
    """
    data: Any = None
    try:
        data = json.loads(_clean_block(raw))
    except Exception:
        data = None
    if not (isinstance(data, dict) and isinstance(data.get("tool"), str)):
        for s, e in _json_object_spans(raw or ""):
            try:
                cand = json.loads(raw[s:e])
            except Exception:
                continue
            if isinstance(cand, dict) and isinstance(cand.get("tool"), str):
                data = cand
                break
    if not isinstance(data, dict) or not isinstance(data.get("tool"), str):
        return None
    args = data.get("arguments")
    if not isinstance(args, dict):
        args = {}
    return {"tool": data["tool"], "arguments": args}


def _tool_call_regions(text: str) -> List[tuple]:
    """定位全部工具块区域 [(start, end_exclusive, content)]。

    闭合块 = 开标签..闭合标签尾；未闭合块 = 开标签..首个配对 JSON 尾。
    无合法 JSON 的裸 "TOOL_CALL]" 提及不当块处理(避免误删正文)。
    """
    regions: List[tuple] = []
    opens = list(_TOOL_CALL_OPEN.finditer(text or ""))
    for idx, m in enumerate(opens):
        seg_end = opens[idx + 1].start() if idx + 1 < len(opens) else len(text)
        close = _TOOL_CALL_CLOSE.search(text, m.end(), seg_end)
        if close:
            regions.append((m.start(), close.end(), text[m.end():close.start()]))
            continue
        spans = _json_object_spans(text[m.end():seg_end])
        if spans:
            s, e = spans[0]
            regions.append((m.start(), m.end() + e, text[m.end():m.end() + e]))
    return regions


def extract_tool_calls(text: str) -> List[Dict[str, Any]]:
    """从模型输出中解析工具调用块(闭合/未闭合均支持)。返回 [{tool, arguments}]；异常/缺失字段自动跳过。"""
    calls: List[Dict[str, Any]] = []
    if not text:
        return calls
    for _s, _e, content in _tool_call_regions(text):
        payload = _parse_tool_payload(content)
        if payload:
            calls.append(payload)
    return calls


def strip_tool_blocks(text: str) -> str:
    """移除全部工具调用块(含未闭合块)，返回纯文本。"""
    if not text:
        return ""
    regions = _tool_call_regions(text)
    if not regions:
        return text.strip()
    out: List[str] = []
    pos = 0
    for start, end, _content in regions:
        out.append(text[pos:start])
        pos = end
    out.append(text[pos:])
    return "".join(out).strip()


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
    return rec


def _digest(v: Any, limit: int = 120) -> str:
    s = json.dumps(v, ensure_ascii=False, default=str) if not isinstance(v, str) else v
    s = " ".join((s or "").split())
    return s[:limit]


def _now_ms() -> int:
    import time as _t
    return int(_t.time() * 1000)


def run_arch_tool(name: str, arguments: Dict[str, Any],
                  root: Optional[str], project: Optional[str]) -> Dict[str, Any]:
    """执行 architect 注册工具；缺失/异常返回 {error}。root/project 按签名自动注入。

    执行环带审计 hook(WS6-E 结构预留)。
    """
    entry = _ARCH_TOOLS.get(name)
    if not entry:
        return {"error": f"未知工具: {name}"}
    fn = entry["handler"]
    kwargs = dict(arguments or {})
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
        return result if isinstance(result, dict) else {"result": result}
    except Exception as e:
        logger.exception("[req_agent] tool %s failed", name)
        record_tool_audit(name, arguments, False, str(e),
                          latency_ms=_now_ms() - t0, project=project or "")
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


def _kb_gateway():
    try:
        from . import ctx
        g = ctx.kb()
        if g is not None:
            return g
    except Exception:
        pass
    from .kb_gateway import get_gateway
    return get_gateway()


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
                         scopes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    from . import semantic_assets as S
    try:
        return S.search(root, project, text, kind, limit, offset,
                        scopes=scopes, level=level)
    except Exception as e:
        logger.warning("[req_agent] asset.semantic.search failed: %s", e)
        return []


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

@register_architect_tool(
    "req.propose",
    "形成需求提案：在资产地图对话中，当讨论收敛为明确的改进/新增需求时调用，"
    "把 需求+方案+评估 三段结构化产出为提案（进入需求方案的规划组，等待用户确认后续流程）。"
    "参数：title(一句话需求)、requirementMd(需求描述：背景/目标/范围)、designMd(方案要点：技术路径/涉及组件与文件，"
    "可引用对话中讨论的资产)、assessmentMd(评估：收益/风险/工作量估计 estMin 分钟)、priority(P0/P1/P2)。",
)
def tool_req_propose(title: str = "", requirementMd: str = "", designMd: str = "",
                     assessmentMd: str = "", priority: str = "P1",
                     estMin: int = 0, root: Optional[str] = None,
                     project: Optional[str] = None) -> Dict[str, Any]:
    from . import ctx, store as _store
    title = (title or "").strip()
    if not title:
        return {"ok": False, "error": "缺少需求标题"}
    now = __import__("topoone_app_architect.arch_routes.common", fromlist=["_ts"])._ts()
    req = {
        "id": _store.next_id("RQ"), "kind": "user-story", "tier": "raw",
        "location": "proposal", "title": title,
        "priority": priority if priority in ("P0", "P1", "P2") else "P1",
        "status": "raw",
        "desc": requirementMd or "", "acceptance": [], "traceTo": [],
        "updatedAt": now,
        # 方案/评估并入 desc（Markdown 三段）+ analysis 摘要（供池准入）
        "sourceType": "asset-chat",
    }
    try:
        conv_id = ctx.get_conv()
    except Exception:
        conv_id = ""
    if conv_id:
        req["sourceConversationId"] = conv_id
    sections = []
    if requirementMd:
        sections.append(f"## 需求\n\n{requirementMd}")
    if designMd:
        sections.append(f"## 方案\n\n{designMd}")
    if assessmentMd:
        sections.append(f"## 评估\n\n{assessmentMd}")
    req["desc"] = "\n\n".join(sections) if sections else (requirementMd or title)
    req["analysis"] = {
        "functionalScope": [], "entityBoundary": [],
        "assessmentSummary": (assessmentMd or "")[:500],
        "assetScope": [], "estMin": int(estMin or 0),
        "implementationPath": (designMd or "")[:500],
        "changes": [], "steps": [],
        "designMd": designMd or "",
    }
    _store.RequirementsStore.create(req)
    return {"ok": True, "requirementId": req["id"], "title": title,
            "hint": "提案已创建（规划组）；用户确认后在需求方案会话中继续"}


@register_architect_tool(
    "req.finalize",
    "定稿：把 plan 结论固化为结构化需求分析并转入待执行。当需求讨论收敛、可明确范围/影响/实现路径时调用"
    "(调用后本会话需求状态→待执行，左栏会话移入「待执行」组)。"
    "参数：title、description、functionalScope[str]、entityBoundary[str]、"
    "assetScope[{assetId,assetType,role,source}]、estMin(int 分钟)、implementationPath(str)、assessmentSummary(str)。",
)
def tool_req_finalize(title: str = "", description: str = "",
                      functionalScope: Optional[List[str]] = None,
                      entityBoundary: Optional[List[str]] = None,
                      assetScope: Optional[List[Dict[str, Any]]] = None,
                      estMin: Optional[int] = None,
                      implementationPath: str = "",
                      assessmentSummary: str = "",
                      root: Optional[str] = None, project: Optional[str] = None) -> Dict[str, Any]:
    from . import ctx
    req_id = ctx.get_req()
    if not req_id:
        return {"ok": False, "error": "当前会话未绑定需求，无法定稿"}
    row = store.RequirementsStore.get(req_id)
    if not row:
        return {"ok": False, "error": f"需求 {req_id} 不存在"}
    try:
        est = int(estMin or 0)
    except (TypeError, ValueError):
        est = 0
    # ── WS5-B 定稿门禁: 涉及资产保鲜检查(过期→拦截, 先刷新再定稿) ──
    scoped_ids = [str(x.get("assetId") or "").strip()
                  for x in (assetScope or [])
                  if isinstance(x, dict) and str(x.get("assetId") or "").strip()]
    if scoped_ids:
        try:
            from .sem.engine import _lazy_reconcile
            _lazy_reconcile(root, project)
        except Exception:
            pass
        stale: List[str] = []
        for aid in dict.fromkeys(scoped_ids):
            # 只拦「存在且过期」: assetScope 可含 KB 组件 id(comm-…)等非语义资产, 不误伤
            a = store.SemanticAssetsStore.get(aid)
            if a and (a.get("status") == "stale" or a.get("needsUpdate")):
                stale.append(f"{aid} {a.get('name', '')}")
        if stale:
            return {
                "ok": False, "blocked": "stale_assets", "staleAssets": stale[:20],
                "error": "定稿门禁: 涉及资产已过期(源码变更后未刷新), "
                         "请先对下列资产逐个 asset.semantic.refresh, 全部新鲜后重新定稿: "
                         + "; ".join(stale[:8]),
            }
    analysis = {
        "functionalScope": functionalScope or [],
        "entityBoundary": entityBoundary or [],
        "assessmentSummary": assessmentSummary or "",
        "assetScope": assetScope or [],
        "estMin": est,
        "implementationPath": implementationPath or "",
        "changes": [],
        "steps": [],
    }
    store.RequirementsStore.update(req_id, {
        "title": (title or "").strip() or row.get("title") or req_id,
        "analysis": analysis,
        "status": "analyzed",
        "location": "pool",
    })
    return {
        "ok": True, "reqId": req_id, "status": "analyzed", "location": "pool",
        "lifecycle": "ready", "summary": "已定稿，需求转入待执行(可指派 subagent 执行)。",
    }


# ── 需求指派工具(定稿后 → subagent 执行，经 agent-bus broker 交接) ─────

@register_architect_tool(
    "execution.assign",
    "指派：把本会话需求指派给 subagent 执行(定稿/待执行后可用)。"
    "target=runner 指派内部执行任务(需 execId，缺省取需求已绑定执行任务；"
    "broker 将触发 /exec/{execId}/run)；target=mcp 指派外部 MCP 工具(需 tool，"
    "可选 params)。成功后需求状态→执行中，左栏会话移入「执行中」组。"
    "参数：target(\"runner\"|\"mcp\")、execId?(runner)、tool?(mcp)、params?{…}(mcp)。",
)
def tool_execution_assign(target: str = "", execId: str = "",
                          tool: str = "",
                          params: Optional[Dict[str, Any]] = None,
                          root: Optional[str] = None, project: Optional[str] = None) -> Dict[str, Any]:
    from . import ctx
    from .execution import assign_requirement
    req_id = ctx.get_req()
    if not req_id:
        return {"ok": False, "error": "当前会话未绑定需求，无法指派"}
    row, e = assign_requirement(req_id, target, exec_id=execId, tool=tool, params=params)
    if not row:
        return {"ok": False, "error": e[1]}
    return {
        "ok": True, "reqId": req_id, "status": row.get("status"),
        "assignedTo": row.get("assignedTo"), "lifecycle": "executing",
        "summary": f"已指派给 {row.get('assignedTo')}，需求进入执行中(broker 已发布交接)。",
    }


# ── 澄清提问工具(plan agent → 用户，经 broker 总线，「需要你输入」可见) ──

@register_architect_tool(
    "interaction.clarify",
    "澄清提问：执行中发现信息不足/存在歧义/需要用户决策时，向用户提问"
    "(经 broker 总线发布；工作台「需要你输入」会提示用户回答，"
    "用户回答会作为新消息注入本会话，你在下一回合可见)。"
    "参数：message(问题文本，简洁明确，一次只问一个关键问题)。",
)
def tool_interaction_clarify(message: str = "",
                             root: Optional[str] = None, project: Optional[str] = None) -> Dict[str, Any]:
    from . import ctx
    from .bus_client import get_bus
    req_id = ctx.get_req()
    if not req_id:
        return {"ok": False, "error": "当前会话未绑定需求，无法提问"}
    message = (message or "").strip()
    if not message:
        return {"ok": False, "error": "缺少提问内容(message)"}
    pub = get_bus().publish("plan", "user", "interaction.clarify",
                            {"reqId": req_id, "message": message})
    if pub is None:
        return {"ok": False, "error": "agent-bus broker 不可达，无法发布提问"}
    return {
        "ok": True, "reqId": req_id, "messageId": pub.get("id"),
        "summary": "已向用户提问(工作台「需要你输入」可见)；继续当前回合的其它工作，"
                   "用户回答会在下一回合注入本会话。",
    }


# ── LLM 通道: 复用主后端 ai chat ─────────────────────────────────────

_MODEL_KEY = "llm.modelId"
_MAX_TOKENS_KEY = "llm.maxTokens"

# LLM 同步调用超时(秒)：本地大模型结构化提取/工具循环耗时可能远超 KB 默认 10s，
# 与 model_configs.timeout 对齐(默认 300s)，可用 LLM_SYNC_TIMEOUT 覆盖。
_LLM_CALL_TIMEOUT = float(os.environ.get("LLM_SYNC_TIMEOUT", "300"))


def get_model_preference() -> str:
    """architect 侧模型偏好(空 = 由主后端默认 is_default 兜底)。"""
    from . import store
    return store.CollabConfigStore.get(_MODEL_KEY, "")


def set_model_preference(model_id: str) -> None:
    from . import store
    store.CollabConfigStore.set(_MODEL_KEY, model_id)


def get_max_tokens_preference() -> Optional[int]:
    """architect 侧 max_tokens 偏好(空 = 主后端按 model_configs.max_tokens)。"""
    from . import store
    raw = store.CollabConfigStore.get(_MAX_TOKENS_KEY, "")
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return None
    return val if val > 0 else None


def set_max_tokens_preference(value: Optional[int]) -> None:
    """设置 max_tokens 偏好；None/<=0 视为清除(回退主后端模型配置)。"""
    from . import store
    store.CollabConfigStore.set(
        _MAX_TOKENS_KEY,
        str(int(value)) if value and int(value) > 0 else "",
    )


def llm_sync(messages: List[Dict[str, str]],
             mode: str = "chat",
             tools: Optional[List[str]] = None,
             output_schema: Optional[Dict[str, Any]] = None,
             max_tokens: Optional[int] = None,
             model_id: Optional[str] = None,
             on_error: Optional[Callable[[str], None]] = None) -> Optional[Dict[str, Any]]:
    """经 KbGateway 调主后端 llm.sync。不可达/异常返回 None(调用方降级)。

    model_id: 本次对话的模型偏好(对话侧单独选择)，优先于全局 `llm.modelId`；
    空串则回退全局偏好，再由主后端 is_default 兜底。
    on_error: 可选回调，捕获失败原因文本(KbError 详情/异常信息)，供调用方
    识别上下文超限等可重试错误(如逐行解读的二分降级)；不改变 None 返回语义。
    """
    gateway = _kb_gateway()
    try:
        body: Dict[str, Any] = {
            "modelId": model_id if model_id is not None else get_model_preference(),
            "mode": mode,
            "messages": messages,
            "maxTokens": max_tokens,
        }
        if tools:
            body["tools"] = tools
        if output_schema:
            body["outputSchema"] = output_schema
        res = gateway.call("llm.sync", timeout=_LLM_CALL_TIMEOUT, **body)
        if not isinstance(res, dict):
            logger.warning("[req_agent] llm.sync 返回非 dict(%s): %r",
                           type(res).__name__,
                           str(res)[:200] if res is not None else None)
            if on_error:
                try:
                    on_error(f"llm.sync 返回非 dict: {type(res).__name__}")
                except Exception:
                    pass
            return None
        if mode == "structured" and output_schema and res.get("output") is None:
            logger.warning("[req_agent] llm.sync structured 输出为空: "
                           "content_len=%d structuredError=%r",
                           len(res.get("content") or ""),
                           str(res.get("structuredError"))[:200])
        return res
    except Exception as e:
        logger.warning("[req_agent] llm.sync failed: %s", e, exc_info=True)
        if on_error:
            try:
                on_error(str(e))
            except Exception:
                pass
        return None


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
    "- asset.semantic.search：检索已提取的语义数据资产(数据结构/处理流程/控制逻辑，比组件更细、锚定 AST 节点；支持 kind/level 过滤)\n"
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
    "- req.finalize：定稿(把 plan 结论固化为结构化需求分析并转入待执行)\n"
    "- execution.assign：指派(把定稿/待执行需求指派给 subagent 执行：runner=内部执行任务，mcp=外部 MCP 工具；成功后需求进入执行中)\n"
    "- interaction.clarify：澄清提问(信息不足/存在歧义/需要用户决策时向用户提问；用户回答会在下一回合注入本会话)\n"
    "- ctx.search：跨会话检索历史上下文(单元/消息/备案文档)——回答涉及历史讨论/已有结论时先检索，避免重复讨论\n"
    "- ctx.get：读取指定会话的上下文包(摘要+关键单元+备案文档清单)\n"
    "- ctx.summarize：生成/刷新会话摘要\n"
    "- probe.run：方案草图(probe)——调 coding agent 在代码快照上产出改动思路与伪 diff，供用户预览确认后再正式执行\n\n"
    "- coding.task.plan：实现方案(plan 模式,只读)——装配任务上下文(会话结论+需求+规约+资产影响面)交 coding agent 隔离分析，"
    "产出结构化方案(文件→行区间→意图+置信度)。「给需求拿方案」或先评估再执行时用\n"
    "- coding.task.execute：正式执行(主工作区+分支协议)——会话绑定需求后创建/交接执行任务运行。「给需求拿结果」「按方案执行」时用\n"
    "- capability.evaluate：图文评估——target=plan 评估会话最新方案(变更足迹×语义资产影响面+关系子图图)；"
    "target=execution 评估执行结果(实际 diff 足迹 + 与方案的偏差集)。报告内资产卡可点击联动资产地图。方案确认前/执行完成后调用\n"
    "- capability.mine：能力提炼——扫描会话(消息+方案/回执单元)提炼 规约/流程/技巧/skill 提案入待审队列, "
    "设计者采纳后生效(规约入规约库/skill 文档注入能力文档)。会话出现可复用模式时主动提议\n\n"
    "工具调用协议(重要)：当需要检索知识库/项目数据才能回答(例如确认真实资产、基线、依赖链路)时，"
    "先且仅先输出一个工具调用块，格式为：\n"
    '[TOOL_CALL]{"tool":"<=工具名>","arguments":{参数}}[/TOOL_CALL]\n'
    "硬性规则(执行类指令)：凡用户要求『提取/抽取语义资产』或给出组件ID(comm-…)要求提取/刷新/保存时，"
    "你的第一条回复必须是对应的 asset.semantic.* 工具调用块；工具结果是同步返回的真实执行结果。"
    "严禁在不调用工具的情况下输出『提取报告/结果摘要/新鲜度检查/产出条数』等编造结论——"
    "你没有调用工具就没有任何执行结果，如实说明需要调用工具即可。\n"
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
    '- asset.semantic.extract: {"scope": {"type": "comm|files|symbols|project", "key": "组件ID(comm-…，先 kb.asset.search 取 id；未命中返回 error+候选清单须如实告知)", "files": [], "symbols": []}, "kinds": ["entity","contract","state","rule","process","decision"]}\n'
    '- asset.semantic.detail: {"asset_id": "sa-xxx"}\n'
    '- asset.semantic.mappings: {"asset_ids": ["sa-xxx"]}\n'
    "- asset.semantic.reconcile: {}\n"
    '- asset.semantic.refresh: {"asset_id": "sa-xxx"}\n'
    '- code.read_symbols: {"file": "相对路径", "symbol"?: "符号名", "startLine"?: 行, "endLine"?: 行}\n'
    '- asset.semantic.save: {"assets": [{"name": "…", "kind": "entity|contract|state|rule|process|decision", '
    '"level"?: "implementation", "desc"?: "…", "detail"?: {…}, '
    '"astRefs": [{"file": "…", "symbol": "…", "startLine": n, "endLine": n}]}]}\n'
    '- asset.semantic.update: {"assetId": "sa-xxx", "patch": {"name"?: "新名", "desc"?: "新描述"}}\n'
    '- asset.semantic.merge: {"intoId": "sa-xxx", "targetIds": ["sa-yyy"], "targetName"?: "合并后名称"}\n'
    '- asset.semantic.split: {"assetId": "sa-xxx", "parts": [{"name": "…", "anchorKeys": ["file:symbol"], "desc"?: "…"}]}\n'
    '- convention.propose: {"ruleText": "服务以 XxxService 结尾", "scenarios": ["naming"], "appliesKinds"?: ["process"]}\n'
    '- contract.propose: {"items": [{"kind": "…", "level"?: "implementation", "target": {"file"?: "…", "symbol"?: "…"}, '
    '"behavior"?: {"steps": [{"order": 1, "semantic": "…"}], "branches": [{"condition": "…", "semantic": "…"}]}, '
    '"zAxis"?: [{"category": "…", "text": "…"}], "acceptance"?: {"mode"?: "auto", "criteria"?: "…"}, '
    '"origin": {"quote": "设计者原话(必填)"}, "reqId"?: "…"}]}\n'
    '- mcp.call: {"tool": "<mcp工具名>", "params": {…}}\n'
    '- req.finalize: {"title": "…", "description": "…", "functionalScope": ["…"], '
    '"entityBoundary": ["…"], "assetScope": [{"assetId":"…","assetType":"component","role":"core",'
    '"source":"auto"}], "estMin": 90, "implementationPath": "…", "assessmentSummary": "…"}\n'
    '- execution.assign: {"target": "runner", "execId": "ex-xxx(缺省取需求已绑定任务)"} '
    '或 {"target": "mcp", "tool": "<mcp工具名>", "params": {…}}\n'
    '- req.finalize 门禁: assetScope 涉及资产若过期(stale/needsUpdate)会被拦截——'
    '先 asset.semantic.refresh 刷新再定稿\n'
    '- interaction.clarify: {"message": "<问题文本>"}\n'
    '- coding.task.plan: {"instruction": "要做什么(一句话)", "files"?: "相关文件,逗号分隔", "executorId"?: "opencode|cline|…", "timeoutS"?: 900}\n'
    '- coding.task.execute: {"adapter"?: "opencode(缺省)"}——需先 req.finalize 绑定需求\n'
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
                       skill_scenarios: Optional[List[str]] = None) -> str:
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
        f"{_CAPABILITY_DOC}{ir_doc}{extra}{mcp_extra}{skill_extra}"
    )


def llm_chat_start(messages: List[Dict[str, str]],
                   model_id: Optional[str] = None,
                   session_id: str = "arch-req-chat",
                   max_tokens: Optional[int] = None) -> Optional[str]:
    """发起流式对话(llm.chat)。成功返回 requestId；不可达/未配置/异常返回 None(调用方降级)。

    与 llm_sync 同通道(经 KbGateway 转发主后端)，但返回 requestId 而非完整内容：
    调用方随后经 ZMQ SUB 订阅 `llm.*`(按 requestId 过滤) 消费逐字 chunk。
    """
    gateway = _kb_gateway()
    try:
        body: Dict[str, Any] = {
            "sessionId": session_id,
            "modelId": model_id if model_id is not None else get_model_preference(),
            "mode": "chat",
            "messages": messages,
            "max_tokens": max_tokens,
        }
        res = gateway.call("llm.chat", timeout=_LLM_CALL_TIMEOUT, **body)
        if not isinstance(res, dict) or not res.get("requestId"):
            return None
        return res.get("requestId")
    except Exception as e:
        logger.warning("[req_agent] llm.chat failed: %s", e)
        return None


# ── Skills 定义 ────────────────────────────────────────────────────────

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