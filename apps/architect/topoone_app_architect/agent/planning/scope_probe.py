"""范围探针(环节十三) — KB+任务历史+文件树 grounding → 边界文件建议。

目标: allowedScope 不再靠需求文本盲猜。grounding 数据全部已有:
- tree:    仓库文件清单(boundary.list_repo_files, git 事实)
- history: 同项目其他需求的边界(scope 先验——历史任务实际动过的文件经
           里程碑回写已沉淀在各需求边界里)
- kb:      架构资产检索命中(kb.asset.search)

产出: 单次 LLM 调用(structured), 每个建议文件必须标注来源引用
(tree|history|kb|inference)。LLM 不可用 → ok=False, 调用方回落既有行为
(探针失败不阻断执行)。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("arch.planning.scope_probe")

_VALID_SOURCES = ("tree", "history", "kb", "inference")
_TREE_LIMIT = 400          # 文件清单注入上限(防上下文膨胀)
_MAX_PROPOSED = 20         # 建议文件数上限


def gather_grounding(root: str, project: Optional[str], req_text: str,
                     exclude_rid: str = "") -> Dict[str, Any]:
    """三源 grounding 数据(确定性, 无 LLM)。"""
    from ..governance.boundary import list_repo_files
    tree = list_repo_files(root or "")
    # history: 同项目其他需求的边界(scope 先验)——需求存项目库, all() 天然项目隔离
    history: List[str] = []
    try:
        from ...arch_routes import store
        for r in store.RequirementsStore.all():
            if r.get("id") == exclude_rid:
                continue
            snap = (store.RequirementsStore.spec_active(r.get("id") or "")
                    or {}).get("snapshot") or {}
            scope = [str(x) for x in (snap.get("allowedScope") or [])]
            if not scope:
                scope = [str(x) for x in ((r.get("analysis") or {})
                                          .get("allowedScope") or [])]
            if scope:
                history.append(f"{r.get('id')}({r.get('title')}): "
                               + ", ".join(scope[:8]))
    except Exception as e:  # noqa: BLE001
        logger.debug("[scope-probe] history: %s", e)
    # kb: 架构资产检索命中(名称/描述, 组件级线索)
    kb: List[str] = []
    try:
        from ...arch_routes.req_agent import tool_kb_asset_search
        for a in tool_kb_asset_search(root, project, req_text)[:6]:
            kb.append(f"{a.get('id')} {a.get('name')}: {str(a.get('desc') or '')[:80]}")
    except Exception as e:  # noqa: BLE001
        logger.debug("[scope-probe] kb: %s", e)
    return {"tree": tree, "history": history, "kb": kb}


def probe_scope(root: str, project: Optional[str], req_text: str,
                rid: str = "", tier: str = "T1") -> Dict[str, Any]:
    """范围探针: grounding + 单次 LLM → {ok, files: [{path, source}], note}。

    files 已归一(去 ./、去尾 /、去重、截断); 来源引用非法 → inference。
    R3.1 链3收编(D7-①): 经 CallTurn——T2 附逐文件 source 标注示例脚手架/
    按挡重试; 兜底(R2.3 启发式)由调用方接线。tier 缺省 T1(基线行为不变)。
    """
    if not (req_text or "").strip():
        return {"ok": False, "error": "需求文本为空"}
    g = gather_grounding(root, project, req_text, exclude_rid=rid)
    schema = {
        "type": "object",
        "properties": {
            "files": {"type": "array", "items": {
                "type": "object",
                "properties": {"path": {"type": "string"},
                               "source": {"type": "string"}},
                "required": ["path"]}},
            "note": {"type": "string"},
        },
        "required": ["files"],
    }
    sys_prompt = (
        "你是范围探针。依据需求文本与三源参考(仓库文件树/同项目历史需求边界/架构资产),"
        "提出本需求**预期修改范围**的文件清单(文件或目录前缀)。规则:\n"
        "1. 每个文件标注 source 引用: tree=文件树中真实存在; history=历史需求边界出现过;"
        "kb=资产线索推导; inference=你自己的推断(尽量少用);\n"
        f"2. 最多 {_MAX_PROPOSED} 项; 只提与需求实质相关的文件, 不要穷举;\n"
        "3. 目录前缀(如 src/http/)优于逐文件罗列; 新建文件按预期路径提出;\n"
        "4. 只输出结构化结果, 不要解释。")
    user_parts = [f"需求文本:\n{req_text[:6000]}"]
    if g["tree"]:
        user_parts.append("仓库文件树:\n" + "\n".join(g["tree"][:_TREE_LIMIT]))
    if g["history"]:
        user_parts.append("同项目历史需求边界:\n" + "\n".join(g["history"][:20]))
    if g["kb"]:
        user_parts.append("架构资产命中:\n" + "\n".join(g["kb"]))
    # R3.1 链3收编(D7-①): 经 CallTurn(分目的脚手架/按挡重试; llm 不可用计失败)
    from ...agent.compensation.ctx import Purpose
    from ...agent.turns import call as _call_turn
    from ...arch_routes.agent_roles import load_light_tasks_cfg
    from ..governance.light_tasks import resolve_light_task_model
    r = _call_turn.call(
        Purpose.PROBE,
        [{"role": "system", "content": sys_prompt},
         {"role": "user", "content": "\n\n".join(user_parts)}],
        tier=tier, schema=schema, max_tokens=1024,
        model_id=resolve_light_task_model("probe", load_light_tasks_cfg())
        or None,
        validate=lambda p: (isinstance((p or {}).get("files"), list)
                            and bool(p["files"]), "files 非列表或为空"),
        fallback=lambda: None)
    payload = r.get("output") if r.get("ok") else None
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        return {"ok": False, "error": "探针输出无效"}
    files: List[Dict[str, str]] = []
    seen = set()
    for item in payload["files"][:_MAX_PROPOSED]:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        while path.startswith("./"):
            path = path[2:]
        path = path.rstrip("/")
        if not path or path in seen or path.startswith("/"):
            continue
        seen.add(path)
        src = str(item.get("source") or "inference").strip().lower()
        files.append({"path": path,
                      "source": src if src in _VALID_SOURCES else "inference"})
    return {"ok": bool(files), "files": files,
            "note": str(payload.get("note") or "")[:200]}


# ── R2.3: 探针失败 → 确定性启发式兜底(零 LLM; 开关 r2_3_probe_fallback) ──

_PATH_TOKEN = re.compile(r"[`\"']?([\w./-]+\.[A-Za-z]{1,8}|[\w-]+/[\w./-]+)[`\"']?")


def heuristic_scope_fallback(root: str, req_text: str,
                             exclude_rid: str = "") -> Dict[str, Any]:
    """探针失败兜底(R2.3): 文件树前缀匹配 + 历史需求边界先验(确定性, 零 LLM)。

    产出与 probe_scope 同形: {ok, files: [{path, source}], note, degraded: True}。
    来源: tree=需求文本中的路径 token 命中文件树(前缀匹配);
          history=同项目其他需求边界条目(取目录前缀, 最多 5 项)。
    精度有限——调用方须在卡片/指令中明示降级来源(设计 §3.3 ScopeGroundProvider)。
    """
    from ..governance.boundary import list_repo_files
    files: List[Dict[str, str]] = []
    seen: set = set()

    def _add(path: str, source: str) -> None:
        path = path.rstrip("/")
        if path and path not in seen and not path.startswith("/"):
            seen.add(path)
            files.append({"path": path, "source": source})

    tree = list_repo_files(root or "")
    tree_set = set(tree)
    # ① 需求文本中的路径 token → 文件树前缀匹配
    for tok in _PATH_TOKEN.findall(req_text or "")[:40]:
        tok = tok.lstrip("./")
        if tok in tree_set:
            _add(tok, "tree")
            continue
        hits = [f for f in tree if f.startswith(tok.rstrip("/"))
                and len(files) < _MAX_PROPOSED]
        if hits:
            _add(tok.rstrip("/"), "tree" if tok in tree_set else "tree")
    # ② 历史需求边界先验(同项目, 目录前缀级)
    try:
        from ...arch_routes import store
        for r in store.RequirementsStore.all():
            if len(files) >= _MAX_PROPOSED:
                break
            if r.get("id") == exclude_rid:
                continue
            snap = (store.RequirementsStore.spec_active(r.get("id") or "")
                    or {}).get("snapshot") or {}
            scope = [str(x) for x in (snap.get("allowedScope") or [])][:2]
            for s in scope:
                if len(files) >= _MAX_PROPOSED:
                    break
                _add(s.rstrip("/") if "/" in s else s.rsplit("/", 1)[0]
                     if "." in s else s, "history")
    except Exception as e:  # noqa: BLE001
        logger.debug("[scope-probe] fallback history: %s", e)
    return {"ok": bool(files), "files": files[:_MAX_PROPOSED],
            "note": "探针不可用——文件树/历史边界启发式兜底(精度有限)",
            "degraded": True}
