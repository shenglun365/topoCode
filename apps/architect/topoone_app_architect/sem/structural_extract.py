"""结构化提取器（批2-3）：两段式提取的第一段——无 LLM 资产骨架。

以 KB parseFileAst（symbols + implDetails）为源，机械映射为实现级语义资产骨架：
- function/method            → process（steps=归属该函数的 statements 序；trigger=signature）
- interface/class/type_alias → entity（fields=constants 表中归属行的 name/value）
- property/variable 等       → 附着于所属 entity 的 fields，不独立建行（噪声控制）
- contract/state/rule/decision 语义类别 → 结构化层不判，留 LLM 语义增强(第二段)修正

落库复用 _save_assets（canonicalKey 含 rev → 跨视角多行；upsert/复活/stale 逻辑继承）。
需求对应：2-G「同步提取不调 LLM」+ 3-B「实现级提供结构化前置数据」。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .change_detector import detect_file_changes
from .structural_parse import parse_file, parse_rev_file, symbol_index

logger = logging.getLogger(__name__)

# 符号 kind → 资产 kind 映射（结构化层可判定的两类）
_ENTITY_KINDS = ("interface", "class", "struct", "enum", "component")
_PROCESS_KINDS = ("func", "method")
# 每文件资产骨架上限（防超大文件雪崩；超出部分下次增强/人工）
_PER_FILE_CAP = 60


def _norm(p: str) -> str:
    return (p or "").strip().replace("\\", "/").lstrip("./")


def build_file_skeleton(rel: str, parsed: dict) -> List[dict]:
    """单文件解析结果 → 实现级资产骨架清单。"""
    syms = symbol_index(parsed)
    impl = (parsed or {}).get("implDetails") or {}
    statements = impl.get("statements") or []
    constants = impl.get("constants") or []
    entities: List[dict] = []
    processes: List[dict] = []
    for s in syms:
        if s["startLine"] <= 0:
            continue
        kind = s["kind"]
        anchor = {"file": rel, "symbol": s["qualifiedName"] or s["name"],
                  "kind": kind, "startLine": s["startLine"], "endLine": s["endLine"]}
        if kind in _ENTITY_KINDS:
            fields = [{"name": c.get("name") or "", "type": (c.get("value") or "").rstrip(";")}
                      for c in constants
                      if (c.get("line") or 0) and s["startLine"] <= (c.get("line") or 0) <= s["endLine"]][:24]
            entities.append({
                "name": s["name"] or s["qualifiedName"], "kind": "entity",
                "level": "implementation",
                "desc": (s["docstring"] or "").strip()[:300],
                "astRefs": [anchor],
                "detail": {"kind": "type", "fields": fields,
                           "signature": s["signature"] or s["qualifiedName"]},
            })
        elif kind in _PROCESS_KINDS:
            qn = s["qualifiedName"] or s["name"]
            # enclosing 为短名(解析器口径)——qualifiedName/短名双匹配
            own_stmts = [x for x in statements
                         if (x.get("enclosing") or "") in (qn, s["name"])][:16]
            steps = [{"order": i + 1,
                      "semantic": f"{st.get('type') or 'stmt'}: {(st.get('condition') or '').strip()[:120]}",
                      "astRefs": [{"file": rel, "symbol": qn,
                                   "kind": kind,
                                   "startLine": st.get("startLine") or s["startLine"],
                                   "endLine": st.get("endLine") or s["endLine"]}]}
                     for i, st in enumerate(own_stmts)]
            processes.append({
                "name": s["name"] or s["qualifiedName"], "kind": "process",
                "level": "implementation",
                "desc": (s["docstring"] or "").strip()[:300],
                "astRefs": [anchor],
                "detail": {"kind": "call_chain",
                           "steps": steps,
                           "trigger": s["signature"] or ""},
            })
    out = entities + processes
    return out[:_PER_FILE_CAP]


def extract_structural(root: str, project: Optional[str], files: List[str],
                       *, rev: str = "workspace") -> Dict[str, Any]:
    """结构化提取（无 LLM）：文件清单 → 骨架 → _save_assets 落库（rev 视角）。

    rev='baseline:<v>'/'head:<sha>' 时走 parse_rev_file（git show 临时文件通道）。
    返回 {saved, files, parseFailures, error?}。
    """
    from .engine import _save_assets
    from .paths import resolve_root
    rid = (resolve_root(root, project) or "").strip()
    if not rid:
        return {"error": "项目 root 解析失败", "saved": 0, "files": 0, "parseFailures": 0}
    historical = bool(rev) and rev != "workspace" and not rev.startswith("baseline:")
    saved_total = 0
    parse_fail = 0
    done = 0
    for rel in files:
        rel = _norm(rel)
        if not rel:
            continue
        parsed = (parse_rev_file(rid, rel, rev) if historical
                  else parse_file(rid, rel))
        done += 1
        if not parsed:
            parse_fail += 1
            continue
        skeletons = build_file_skeleton(rel, parsed)
        if not skeletons:
            continue
        try:
            ctx = {"root": rid, "project": project, "source": "structural",
                   "rev": rev, "files": [rel], "srcHash": rev, "table": {}}
            saved = _save_assets(_pid_of(rid, project), "files", rel,
                                 skeletons, ctx)
            saved_total += len(saved or [])
        except Exception as e:  # noqa: BLE001 — 单文件失败不拖累整批
            logger.warning("[structural] save %s failed: %s", rel, e)
    return {"saved": saved_total, "files": done, "parseFailures": parse_fail,
            "summary": f"结构化提取 {saved_total} 骨架 / {done} 文件"}


def _pid_of(root: str, project: Optional[str]) -> str:
    from .paths import project_id_for
    return project_id_for(root, project)


def plan_structural(root: str, project: Optional[str],
                    *, base: str = "HEAD") -> Dict[str, Any]:
    """变化量计划（需求 2.2/2-G）：文件级变化 ∩ 可解析 → 待提取清单。"""
    ch = detect_file_changes(root, base)
    todo = sorted(set(ch["added"]) | set(ch["modified"]))
    return {"added": len(ch["added"]), "modified": len(ch["modified"]),
            "deleted": len(ch["deleted"]), "files": todo[:2000],
            "truncated": len(todo) > 2000}


# ── 统一任务系统接入（批2-4）：结构化提取作业（全量/单组件/多组件档位） ──

def _job_extract_impl(ctx) -> dict:
    """extract_impl 作业执行体：scope.type=project(全量) | component(单/多组件)。

    scope: {type, keys(组件id[]), files(显式清单,优先), rev, base}
    组件档位 → 组件目录 owns 展开文件清单；项目档位 → 变化量计划(2.2 口径)
    或全量符号文件（rev=baseline 时 KB catalog 全量）。
    """
    from . import job_runner
    from .paths import project_id_for, resolve_root
    sc = ctx.scope or {}
    rid = (resolve_root(sc.get("root") or "", sc.get("project")) or "").strip()
    if not rid:
        return {"error": "项目 root 解析失败"}
    rev = sc.get("rev") or "workspace"
    files: List[str] = list(sc.get("files") or [])
    if not files:
        keys = list(sc.get("keys") or [])
        if keys:
            from .catalog import component_catalog
            cat = component_catalog(rid, sc.get("project"))
            by_id = cat.get("byId") or {}
            seen: set = set()
            for k in keys:
                for f in ((by_id.get(k) or {}).get("owns") or []):
                    nf = _norm(f)
                    if nf:
                        seen.add(nf)
            files = sorted(seen)
        elif (sc.get("scopeType") or "") == "project":
            plan = plan_structural(rid, sc.get("project"), base=sc.get("base") or "HEAD")
            files = plan.get("files") or []
    if not files:
        return {"saved": 0, "summary": "无可提取文件"}
    ctx.progress(total=len(files), done=0, saved=0)
    saved_total = parse_fail = done = 0
    for rel in files:
        rel = _norm(rel)
        if not rel:
            continue
        if ctx.cancelled():
            return {"saved": saved_total, "parseFailures": parse_fail,
                    "summary": f"已取消({done}/{len(files)})"}
        parsed = (parse_rev_file(rid, rel, rev) if (rev != "workspace" and not rev.startswith("baseline:"))
                  else parse_file(rid, rel))
        done += 1
        if not parsed:
            parse_fail += 1
            ctx.progress(total=len(files), done=done, saved=saved_total, current=rel)
            continue
        skeletons = build_file_skeleton(rel, parsed)
        if skeletons:
            try:
                from .engine import _save_assets
                sctx = {"root": rid, "project": sc.get("project"),
                        "source": "structural", "rev": rev,
                        "files": [rel], "srcHash": rev, "table": {}}
                saved_total += len(_save_assets(
                    project_id_for(rid, sc.get("project")), "files", rel,
                    skeletons, sctx) or [])
            except Exception as e:  # noqa: BLE001
                logger.warning("[structural] job save %s: %s", rel, e)
        ctx.progress(total=len(files), done=done, saved=saved_total, current=rel)
    return {"saved": saved_total, "parseFailures": parse_fail,
            "summary": f"结构化提取 {saved_total} 骨架 / {done} 文件"}


from . import job_runner as _job_runner
_job_runner.register("extract_impl", _job_extract_impl)


def start_extract_impl(root: str, project: Optional[str], *,
                       rev: str = "workspace", keys: Optional[List[str]] = None,
                       files: Optional[List[str]] = None,
                       base: str = "HEAD") -> dict:
    """提交结构化提取作业（需求 2-B 档位：全量=无 keys / 单·多组件=keys / 显式 files）。"""
    from .paths import project_id_for, resolve_root
    from . import job_runner
    rid = (resolve_root(root, project) or "").strip()
    if not rid:
        return {"started": False, "reason": "invalid_root"}
    return job_runner.start_job(
        project_id_for(rid, project), "extract_impl",
        scope={"type": "component" if keys else "project", "keys": keys or [],
               "files": files or [], "rev": rev, "root": rid,
               "project": project, "base": base},
        llm=False)
