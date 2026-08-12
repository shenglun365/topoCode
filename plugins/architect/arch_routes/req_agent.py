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
# [TOOL_CALL]{"tool":"x","arguments":{...}}[/TOOL_CALL]
# (模型可能再套 ```json 围栏，解析时剥离；闭合标签容忍 [ / > 及 >] 写法)
_TOOL_CALL_BLOCK = re.compile(r'\[TOOL_CALL\](.*?)\[/TOOL_CALL[>\]]+\]?', re.DOTALL)
_FENCE = re.compile(r'^\s*```(?:json)?\s*|\s*```\s*$')


def _clean_block(raw: str) -> str:
    raw = _FENCE.sub("", raw or "").strip()
    if raw.startswith("{"):
        return raw
    first = raw.find("{")
    last = raw.rfind("}")
    return raw[first:last + 1] if first >= 0 and last > first else raw


def extract_tool_calls(text: str) -> List[Dict[str, Any]]:
    """从模型输出中解析工具调用块。返回 [{tool, arguments}]；异常/缺失字段自动跳过。"""
    calls: List[Dict[str, Any]] = []
    if not text:
        return calls
    for m in _TOOL_CALL_BLOCK.finditer(text):
        try:
            data = json.loads(_clean_block(m.group(1)))
        except Exception:
            continue
        if not isinstance(data, dict) or not isinstance(data.get("tool"), str):
            continue
        args = data.get("arguments") or {}
        if not isinstance(args, dict):
            continue
        calls.append({"tool": data["tool"], "arguments": args})
    return calls


def strip_tool_blocks(text: str) -> str:
    """移除全部工具调用块，返回纯文本。"""
    return _TOOL_CALL_BLOCK.sub("", text or "").strip()


def run_arch_tool(name: str, arguments: Dict[str, Any],
                  root: Optional[str], project: Optional[str]) -> Dict[str, Any]:
    """执行 architect 注册工具；缺失/异常返回 {error}。root/project 按签名自动注入。"""
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
    try:
        result = fn(**kwargs)
        return result if isinstance(result, dict) else {"result": result}
    except Exception as e:
        logger.exception("[req_agent] tool %s failed", name)
        return {"error": f"{name} 执行失败: {e}"}


def tool_result_text(name: str, result: Any, limit: int = 3000) -> str:
    """工具结果 → 文本(截断，供下一轮 LLM 上下文)。"""
    if isinstance(result, dict) and "error" in result:
        return str(result.get("error"))
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


# ── 语义数据资产工具 ─────────────────────────────────────────────

@register_architect_tool(
    "asset.semantic.search",
    "检索当前项目已提取的语义数据资产(数据结构/处理流程/控制逻辑)，按关键词命中。返回资产(含 AST 锚点)。",
)
def tool_semantic_search(root: Optional[str], project: Optional[str],
                         text: str = "", kind: str = "") -> List[Dict[str, Any]]:
    from . import semantic_assets as S
    try:
        return S.search(root, project, text, kind)
    except Exception as e:
        logger.warning("[req_agent] asset.semantic.search failed: %s", e)
        return []


@register_architect_tool(
    "asset.semantic.extract",
    "从最新代码结构提取语义数据资产(类别: structure/behavior/rule/contract，粒度: high/medium/low)并落库，"
    "供对话确认与需求/设计引用。"
    "参数 scope={type: files|symbols|comm|project, key?, files?, symbols?}，kinds=[structure|behavior|rule|contract]。",
)
def tool_semantic_extract(root: Optional[str], project: Optional[str],
                          scope: Dict[str, Any] = None,
                          kinds: Optional[List[str]] = None) -> Dict[str, Any]:
    from . import semantic_assets as S
    scope = scope or {}
    try:
        return S.extract_scope(root, project,
                               scope.get("type") or "project",
                               scope.get("key") or "",
                               scope.get("files") or [],
                               scope.get("symbols") or [],
                               kinds=kinds)
    except Exception as e:
        logger.warning("[req_agent] asset.semantic.extract failed: %s", e)
        return {"assets": [], "count": 0, "degraded": True, "error": str(e)}


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
             model_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """经 KbGateway 调主后端 llm.sync。不可达/异常返回 None(调用方降级)。

    model_id: 本次对话的模型偏好(对话侧单独选择)，优先于全局 `llm.modelId`；
    空串则回退全局偏好，再由主后端 is_default 兜底。
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
            return None
        if mode == "structured" and output_schema and res.get("output") is None:
            logger.warning("[req_agent] llm.sync structured 输出为空: "
                           "content_len=%d structuredError=%r",
                           len(res.get("content") or ""),
                           str(res.get("structuredError"))[:200])
        return res
    except Exception as e:
        logger.warning("[req_agent] llm.sync failed: %s", e, exc_info=True)
        return None


def run_tools_loop(msgs: List[Dict[str, str]], *,
                   root: Optional[str] = None, project: Optional[str] = None,
                   model_id: Optional[str] = None,
                   mode: str = "chat",
                   output_schema: Optional[Dict[str, Any]] = None,
                   max_tokens: Optional[int] = None,
                   max_rounds: int = 4) -> Dict[str, Any]:
    """统一工具调用循环(同步通道)：解析模型输出的 `[TOOL_CALL]` 块 → 逐个执行 →
    回喂结果 → 再次询问，直至得到不含工具块的最终内容。供 harness(clarify/collect)
    与 WS 降级通道共用，杜绝「裸 [TOOL_CALL] 中断」。

    返回 {'content': str, 'output': Any|None}；content 已剥离所有工具块。
    """
    work = list(msgs or [])
    for _round in range(max_rounds + 1):
        res = llm_sync(work, mode=mode, output_schema=output_schema,
                       max_tokens=max_tokens, model_id=model_id)
        content = (res or {}).get("content", "") if res else ""
        if not content:
            return {"content": "", "output": None}
        calls = extract_tool_calls(content)
        if not calls:
            return {
                "content": strip_tool_blocks(content),
                "output": (res or {}).get("output") if res else None,
            }
        results: List[Dict[str, str]] = []
        for c in calls:
            name = c.get("tool", "")
            args = c.get("arguments", {})
            result = run_arch_tool(name, args, root, project)
            results.append({"name": name, "text": tool_result_text(name, result)})
        if not results:
            return {"content": strip_tool_blocks(content), "output": None}
        tool_feed = "\n".join(f"[{r['name']}] {r['text']}" for r in results)
        work.append({"role": "assistant", "content": strip_tool_blocks(content) or "(调用知识库检索)"})
        work.append({"role": "user", "content": f"以下是知识库工具返回结果，请基于结果直接回答，不再输出工具调用块：\n{tool_feed}"})
    return {"content": "", "output": None}


# ── 自由对话(流式)通道 ────────────────────────────────────────────────

_CAPABILITY_DOC = (
    "你可以使用以下能力(skills/tools)：\n"
    "- kb.asset.search：全文检索知识库架构资产(组件/ER/实体/流程)，按关键词命中并按相关度排序\n"
    "- kb.code_mappings：查询资产对应的代码映射(文件/行号)，锁定「改哪里」\n"
    "- kb.baseline：读取当前项目 KB 基线(git 表示：分支/提交/基线版本)\n"
    "- kb.graph：遍历组件依赖图(依赖/被调用)，判断需求改动的影响链路\n"
    "- project.ctx：读取项目上下文(项目名/分支/基线 id/降级状态)\n"
    "- asset.semantic.search：检索已提取的语义数据资产(数据结构/处理流程/控制逻辑，比组件更细、锚定 AST 节点)\n"
    "- asset.semantic.extract：从最新代码结构提取语义数据资产并落库，供对话确认与需求/设计引用\n"
    "- asset.semantic.detail：读取单个语义资产的完整描述/结构化细节/AST 锚点\n"
    "- asset.semantic.mappings：查询语义资产对应的代码映射(文件/行号)，锁定「改哪里」\n"
    "- asset.semantic.reconcile：校验资产新鲜度，标记因文件变更/新增文件影响而过期的资产(需更新后使用)\n"
    "- asset.semantic.refresh：更新过期资产(增量重提；失败软删并重新生成)\n\n"
    "工具调用协议(重要)：当需要检索知识库/项目数据才能回答(例如确认真实资产、基线、依赖链路)时，"
    "先且仅先输出一个工具调用块，格式为：\n"
    '[TOOL_CALL]{"tool":"<=工具名>","arguments":{参数}}[/TOOL_CALL]\n'
    "各工具的参数：\n"
    '- kb.asset.search: {"text": "检索关键词", "preferred": ["资产ID(可选)"]}\n'
    '- kb.code_mappings: {"asset_ids": ["资产ID"]}\n'
    "- kb.baseline: {}\n"
    '- kb.graph: {"comp_ids": ["组件ID"]}\n'
    "- project.ctx: {}\n"
    '- asset.semantic.search: {"text": "关键词", "kind": "structure|behavior|rule|contract(可选)"}\n'
    '- asset.semantic.extract: {"scope": {"type": "comm|files|symbols|project", "key": "组件ID", "files": [], "symbols": []}, "kinds": ["structure","behavior","rule","contract"]}\n'
    '- asset.semantic.detail: {"asset_id": "sa-xxx"}\n'
    '- asset.semantic.mappings: {"asset_ids": ["sa-xxx"]}\n'
    "- asset.semantic.reconcile: {}\n"
    '- asset.semantic.refresh: {"asset_id": "sa-xxx"}\n'
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
    "实现路径或改动影响时，可用 Mermaid 或 PlantUML 图直观表达。直接以代码围栏输出，前端会自动渲染成图：\n"
    "  ```mermaid\n  graph LR\n    A[订单实体] --> B[订单明细]\n  ```\n"
    "  ```plantuml\n  @startuml\n  class Order {\n    +id: Long\n    +amount: BigDecimal\n  }\n  @enduml\n  ```\n"
    "要求：图代码语法正确、节点精简、命名与代码资产一致；围栏语言标签只能用 mermaid 或 plantuml；"
    "图中不要包含 [TOOL_CALL] 块。"
)


def _diagram_skill_doc() -> str:
    """绘图增强(IR→代码)能力文档：从 reports 拉共享 IR schema(单一起源)。

    拉取失败时降级为最小说明(不阻塞对话)。
    """
    base = (
        "绘图增强(diagram.build)：当需要输出复杂/较大图表时，优先用结构化中间表示(IR)描述图，"
        "再调用 diagram.build 生成语法正确的代码，避免小模型直接写 mermaid/plantuml 源码出错。\n"
        "用法：输出一个工具调用块 "
        '[TOOL_CALL]{"tool":"diagram.build","arguments":{"ir":{lang, diagram_type, nodes, edges, ...}}}[/TOOL_CALL]，'
        "收到返回代码后，以 ```mermaid 或 ```plantuml 围栏输出；可再用 diagram.validate 校验。\n\n"
        "IR schema：\n"
    )
    try:
        from . import diagram as _diagram
        docs = _diagram.fetch_ir_docs()
        if docs:
            return base + docs
    except Exception as e:
        logger.warning("[req_agent] fetch ir-docs failed: %s", e)
    return base + (
        "mermaid: flowchart{nodes[{id,text,shape}], edges[{from,to,label}], direction} / "
        "sequence{participants[], messages[{from,to,label,arrow}]} / "
        "class{classes[{name,stereotype,members[]}], relations[]} / "
        "state{states[], transitions[]} / er{entities[], relations[]} / gantt / pie；"
        "plantuml: component{nodes[], edges[]} / sequence{participants[], messages[]}。\n"
        "lang 字段取 mermaid | plantuml。"
    )


def chat_system_prompt(root: Optional[str], project: Optional[str],
                       diagram_skill: bool = False) -> str:
    """自由对话系统提示：能力文档 + 当前项目/KB 上下文 + 范围限定(软拒绝)。

    diagram_skill=True 时注入绘图增强(IR→代码)文档与工具说明(对应前端 📐 开关)。
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
    extra = f"\n\n{_diagram_skill_doc()}" if diagram_skill else ""
    return (
        "你是 TopoCode 架构需求分析 agent(自由对话)。\n"
        f"当前项目：{ctx.get('name') or '(未绑定)'}，模式：{mode}。{kb}\n\n"
        f"{_CAPABILITY_DOC}{extra}"
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
    """clarify 回合: KB 资产检索 → LLM 生成澄清问题清单。返回 None 表示降级(mock/heuristic)。

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
                         mode="chat", max_tokens=1200, model_id=model_id)
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
                                                "structure", "behavior", "rule", "contract"]},
                        "level": {"enum": ["high", "medium", "low"]},
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
        max_tokens=1600, model_id=model_id)
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