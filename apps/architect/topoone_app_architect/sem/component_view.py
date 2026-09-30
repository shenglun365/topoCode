"""组件级聚合视图（批3）：资产入口挂在组件条目上的语义聚合（需求 4 / 1-A / N3）。

- 组件级=architect 侧虚拟节点（资产树组件条目直接用 KB 组件目录结构）；
- 内容=按组件圈定逻辑级+实现级资产，LLM 归并整理为 4 面（需求 1-B 裁决）：
  capability(能力) / interface_facet(接口面) / control_logic(控制逻辑) /
  data_ownership(数据持有)——语义表达为主不贴代码，可下钻成员；
- 缓存（需求 4.1）：arch_component_views 项目库表持久（LLM 产物费钱），
  可手动清除重生成；成员/代码变更 → 辐射标 stale（批2-2 影响辐射的消费方）。
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from ..store.base import _dumps, _target_db
from .logic_extract import _norm

logger = logging.getLogger(__name__)

FACETS = ("capability", "interface_facet", "control_logic", "data_ownership")

_PROMPT = """你是资深软件架构分析师。以下是组件「{comp}」圈定的语义资产(实现级骨架 + 逻辑链)。
请归并整理为组件的语义表达(4 个切面)，以语义描述为主、不贴代码：

1. capability: 组件对外提供的功能单元(做什么)；
2. interface_facet: 组件边界契约汇总(怎么被调用/依赖什么)；
3. control_logic: 核心决策与控制路径(怎么做主)；
4. data_ownership: 组件拥有/管理的数据实体归纳(管什么)。

只依据给出的资产事实归纳，不臆造；每个切面 entries 数组，每条 {name, summary}；
relatedAssets 引用支撑该条目的资产符号名(用于下钻)。

输出 JSON(不要多余文本)：
{{"capability":{{"summary":"...","entries":[{{"name":"...","summary":"...","relatedAssets":["符号名"]}}]}},
  "interface_facet":{{...}},"control_logic":{{...}},"data_ownership":{{...}}}}

语义资产：
{assets}"""


def _load(pid: str, component_id: str, rev: str = "workspace") -> Optional[dict]:
    db = _target_db("arch_component_views", pid)
    rows = db.fetchall(
        "SELECT * FROM arch_component_views WHERE project_id=? AND component_id=? AND rev=? "
        "ORDER BY generated_at DESC LIMIT 1", (pid, component_id, rev or "workspace"))
    if not rows:
        return None
    r = rows[0]
    try:
        facets = json.loads(r["facets"] or "{}")
        members = json.loads(r["members"] or "[]")
    except Exception:
        facets, members = {}, []
    return {"id": r["id"], "componentId": r["component_id"], "rev": r["rev"],
            "facets": facets, "members": members, "status": r["status"],
            "modelId": r["model_id"], "generatedAt": r["generated_at"]}


def save_view(pid: str, component_id: str, rev: str, facets: dict,
              members: List[str], model_id: str = "") -> dict:
    now = int(time.time() * 1000)
    db = _target_db("arch_component_views", pid)
    vid = f"cv-{component_id}-{now}"
    db.execute(
        "INSERT INTO arch_component_views (id, project_id, component_id, rev, facets, "
        "members, status, model_id, created_at, generated_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (vid, pid, component_id, rev or "workspace", _dumps(facets),
         _dumps(members), "active", model_id, now, now, now))
    db.commit()
    return _load(pid, component_id, rev) or {"id": vid}


def clear_view(pid: str, component_id: str, rev: str = "workspace") -> int:
    db = _target_db("arch_component_views", pid)
    cur = db.execute(
        "DELETE FROM arch_component_views WHERE project_id=? AND component_id=? AND rev=?",
        (pid, component_id, rev or "workspace"))
    db.commit()
    return cur.rowcount or 0


def mark_stale_for_assets(pid: str, asset_ids: List[str]) -> int:
    """影响辐射(批2-2 上层打脏)：成员资产变更 → 视图标 stale。

    members 为生成时快照(JSON id 列表)——SQLite 无 JSON contains，逐行 Python 判。
    """
    db = _target_db("arch_component_views", pid)
    rows = db.fetchall("SELECT id, members FROM arch_component_views "
                       "WHERE project_id=? AND status='active'", (pid,))
    want = set(asset_ids)
    hit = 0
    now = int(time.time() * 1000)
    for r in rows:
        try:
            members = set(json.loads(r["members"] or "[]"))
        except Exception:
            continue
        if members & want:
            db.execute("UPDATE arch_component_views SET status='stale', updated_at=? WHERE id=?",
                       (now, r["id"]))
            hit += 1
    db.commit()
    return hit


def get_component_view(root: str, project: Optional[str], component_id: str,
                       rev: str = "workspace") -> dict:
    """视图读取：缓存 active 直返；stale 带 stale 标记；无缓存带 regenerate 提示。"""
    from .paths import project_id_for, resolve_root
    rid = (resolve_root(root, project) or "").strip()
    pid = project_id_for(rid, project) if rid else ""
    view = _load(pid, component_id, rev) if pid else None
    if not view:
        return {"componentId": component_id, "rev": rev, "status": "missing",
                "facets": None, "regenerate": True}
    out = dict(view)
    out["regenerate"] = view.get("status") != "active"
    return out


def _job_gen_component_view(ctx) -> dict:
    from . import job_runner
    from .paths import project_id_for, resolve_root
    from ..agent.cognition.llm import llm_sync
    sc = ctx.scope or {}
    rid = (resolve_root(sc.get("root") or "", sc.get("project")) or "").strip()
    if not rid:
        return {"error": "项目 root 解析失败"}
    pid = project_id_for(rid, sc.get("project"))
    rev = sc.get("rev") or "workspace"
    keys = list(sc.get("keys") or [])
    if not keys:
        return {"error": "缺少组件 id"}
    from .catalog import component_catalog
    cat = component_catalog(rid, sc.get("project"))
    by_id = cat.get("byId") or {}
    from ..store import SemanticAssetsStore
    saved_total = 0
    for cid in keys:
        if ctx.cancelled():
            return {"saved": saved_total, "summary": f"已取消({saved_total}/{len(keys)})"}
        comp = by_id.get(cid) or {}
        owns = {_norm(f) for f in (comp.get("owns") or [])}
        assets = [a for a in SemanticAssetsStore.search(
            pid, limit=2000, rev=rev if rev != "workspace" else "")
            if a.get("status") == "active" and (
                _norm(((a.get("astRefs") or [{}])[0].get("file")) or "") in owns
                or cid in ((a.get("meta") or {}).get("scopes") or [])
                or (a.get("scopeKey") or "") == cid)]
        if not assets:
            logger.warning("[comp-view] 组件 %s 无资产，跳过", cid)
            continue
        ctx.progress(total=len(keys), done=saved_total, current=comp.get("name") or cid)
        brief_lines: List[str] = []
        sym_of_id: Dict[str, str] = {}
        for a in assets[:60]:
            refs = a.get("astRefs") or []
            sym = (refs[0] or {}).get("symbol") or a.get("name") or ""
            if a.get("id"):
                sym_of_id[a["id"]] = sym
            d = a.get("detail") or {}
            ios = d.get("iospec") or {}
            io_txt = ""
            if ios:
                io_txt = (f" 输入:{[e.get('name') for e in (ios.get('inputs') or [])[:4]]}"
                          f" 输出:{[e.get('name') for e in (ios.get('outputs') or [])[:4]]}")
            brief_lines.append(f"- [{a.get('kind')}] {a.get('name')}: {(a.get('desc') or '')[:100]}{io_txt}")
        prompt = _PROMPT.replace("{comp}", comp.get("name") or cid).replace(
            "{assets}", "\n".join(brief_lines))
        res = llm_sync([{"role": "user", "content": prompt}],
                       mode="chat", model_id=sc.get("modelId") or None, max_tokens=4000)
        content = ((res or {}).get("content") or "").strip()
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            logger.warning("[comp-view] %s LLM 未返回 JSON", cid)
            continue
        try:
            facets = json.loads(m.group(0))
        except Exception:
            logger.warning("[comp-view] %s JSON 解析失败", cid)
            continue
        facets = {k: facets[k] for k in FACETS if k in facets}
        members = [aid for aid, sym in sym_of_id.items()]
        save_view(pid, cid, rev, facets, members, sc.get("modelId") or "")
        saved_total += 1
        ctx.progress(total=len(keys), done=saved_total)
    return {"saved": saved_total, "summary": f"组件视图 {saved_total}/{len(keys)}"}


from . import job_runner as _job_runner  # noqa: E402
_job_runner.register("gen_component_view", _job_gen_component_view)  # noqa: E305


def start_gen_component_view(root: str, project: Optional[str], keys: List[str],
                             *, rev: str = "workspace",
                             model_id: Optional[str] = None) -> dict:
    from .paths import project_id_for, resolve_root
    from . import job_runner
    rid = (resolve_root(root, project) or "").strip()
    if not rid:
        return {"started": False, "reason": "invalid_root"}
    return job_runner.start_job(
        project_id_for(rid, project), "gen_component_view",
        scope={"type": "component", "keys": keys, "rev": rev, "root": rid,
               "project": project, "modelId": model_id},
        llm=True)


def clear_component_view(root: str, project: Optional[str], component_id: str,
                         rev: str = "workspace") -> dict:
    from .paths import project_id_for, resolve_root
    rid = (resolve_root(root, project) or "").strip()
    pid = project_id_for(rid, project) if rid else ""
    if not pid:
        return {"cleared": 0}
    return {"cleared": clear_view(pid, component_id, rev)}
