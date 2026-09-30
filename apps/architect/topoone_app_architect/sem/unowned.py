"""未归属组件文件清单 + 跨组件符号关联（语义资产「其它」域补全）。

文件全集 = 符号库 nodes 的 DISTINCT file_path（与提取同口径、镜像根相对、
只含有符号的文件——file/import 节点排除，与 _query_nodes 一致）；
owns = 组件目录 build_component_catalog（KB 唯一 id + owns）；
未归属 = 全集 − owns（双向后缀对齐兜底：符号库与组件 owns 的路径基准
理论上同为镜像根相对，但历史数据/手工目录可能混入 workDir 相对路径）。

跨组件关联 = 未归属文件内符号 与 已归属组件文件内符号 之间的
calls/imports/... 边（符号库 codegraph/native 合并视图），按组件聚合。
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple

from .paths import _norm_path, project_id_for, resolve_root

logger = logging.getLogger(__name__)

_UNOWNED_CAP = 500          # 未归属文件清单上限（超大仓库防雪崩）
_CROSS_FILE_CAP = 200       # 跨关联查询一次最多处理的文件数
_SAMPLES_PER_FILE = 3       # 每文件返回的关联样本边数
# 可提取符号类别(与 engine._ASSET_EXPECTED_ANCHOR_KIND 的锚点白名单对齐)：
# 仅含 file/import/variable/macro 的文件(如 #include 聚合头)实现层管线结构性无产出。
_EXTRACTABLE_KINDS = {"class", "struct", "enum", "interface", "component",
                      "func", "function", "method", "route", "field"}


def _owns_hit(owns_all: Set[str], f: str) -> bool:
    """文件是否被任一组件 owns 覆盖：精确优先，双向后缀对齐兜底。"""
    if f in owns_all:
        return True
    return any(o and (f.endswith("/" + o) or o.endswith("/" + f)) for o in owns_all)


def _catalog_maps(root: str, project: Optional[str]
                  ) -> Tuple[Dict[str, str], Set[str], Dict[str, str]]:
    """组件目录 → (cid→名称表, owns 全集, 文件→cid 归属表)。
    失败返回空（全部视为未归属）。归属表构建时精确入索引，查询侧再做后缀兜底。"""
    try:
        from ..common import build_component_catalog
        catalog = build_component_catalog(root, project) or {}
        names: Dict[str, str] = {}
        owns_all: Set[str] = set()
        file_owner: Dict[str, str] = {}
        for c in catalog.get("components") or []:
            cid = c.get("id")
            if not cid:
                continue
            names[cid] = (c.get("name") or "").strip() or cid
            for f in (c.get("owns") or []):
                nf = _norm_path(f)
                if not nf:
                    continue
                owns_all.add(nf)
                file_owner.setdefault(nf, cid)
        return names, owns_all, file_owner
    except Exception as e:
        logger.warning("[unowned] 组件目录获取失败(全部视为未归属): %s", e)
        return {}, set(), {}


def _symbol_files(conn) -> List[str]:
    """符号库全集文件（原始 file_path 值，供回查 WHERE file_path=?）。"""
    rows = conn.execute(
        "SELECT DISTINCT file_path FROM nodes WHERE kind NOT IN ('file','import')"
    ).fetchall()
    out = []
    for (p,) in rows:
        if p and _norm_path(p):
            out.append(p)
    return sorted(out, key=lambda p: _norm_path(p))


def unowned_files(root: Optional[str], project: Optional[str],
                  limit: int = _UNOWNED_CAP) -> dict:
    """未归属组件的文件清单（含每文件已提取资产数）。

    返回 {files:[{path, assetCount}], unownedCount, ownedCount,
          totalFiles, symbolSource, truncated}。
    """
    rid = (resolve_root(root, project) or "").strip()
    if not rid:
        return {"error": "项目根未解析，无法枚举文件"}
    pid = project_id_for(root, project)
    _, owns_all, _ = _catalog_maps(rid, project)

    from .symbols import open_symbol_conn, close_symbol_conn
    conn, src = open_symbol_conn(rid, project)
    if conn is None:
        return {"error": f"符号库不可用(source={src})：请先建立代码图谱索引",
            "reason": "no_symbol_source"}
    try:
        all_files = _symbol_files(conn)
        # 每文件可提取符号预判：无 class/func 等可锚定符号 → 结构性无产出
        # (config 聚合头实测反复提取 0 产出)，清单标注 + 批量跳过。
        kinds_by_file: Dict[str, set] = {}
        for fp, k in conn.execute(
                "SELECT file_path, kind FROM nodes WHERE kind NOT IN ('file','import')"):
            kinds_by_file.setdefault(_norm_path(fp or ""), set()).add((k or "").lower())
    finally:
        close_symbol_conn(conn)

    unowned = [f for f in all_files if not _owns_hit(owns_all, _norm_path(f))]

    # 每文件已提取资产数（首锚点文件索引；「其它」域资产的直接可视化证据）。
    # activeCount 单独统计：只剩 stale 资产的文件 = 需重提(重提按 canonicalKey
    # 命中旧行并复活为 active)——批量作业的 pending 判定用它。
    anchor_cnt: Counter = Counter()
    active_cnt: Counter = Counter()
    try:
        from .. import store
        for a in (store.SemanticAssetsStore.all_status(pid, limit=20000) or []):
            if (a.get("status") or "active") == "deleted":
                continue
            f = _norm_path(((a.get("astRefs") or [{}])[0].get("file")) or "")
            if not f:
                continue
            anchor_cnt[f] += 1
            if (a.get("status") or "active") == "active":
                active_cnt[f] += 1
    except Exception as e:
        logger.warning("[unowned] 资产锚点计数失败: %s", e)

    cap = max(1, min(int(limit or _UNOWNED_CAP), _UNOWNED_CAP))
    files = [{"path": f,
              "assetCount": anchor_cnt.get(_norm_path(f), 0),
              "activeCount": active_cnt.get(_norm_path(f), 0),
              "extractable": bool(kinds_by_file.get(_norm_path(f), set()) & _EXTRACTABLE_KINDS)}
             for f in unowned[:cap]]
    return {"files": files, "unownedCount": len(unowned),
            "ownedCount": len(all_files) - len(unowned),
            "totalFiles": len(all_files), "symbolSource": src,
            "truncated": len(unowned) > cap}


def _file_links(conn, raw_file: str, owns_all: Set[str], names: Dict[str, str],
                file_owner: Dict[str, str], owner_lookup) -> Optional[dict]:
    """单文件 ↔ 已归属组件文件的跨文件符号边聚合。

    file_owner: file(norm) → cid 缓存(含未命中 ""); owner_lookup(norm_file)→cid
    为带后缀兜底的归属查询。返回 {file, crossCount, byComponent, samples}
    或 None(零跨文件关联)。
    """
    mine = conn.execute(
        "SELECT id, name FROM nodes WHERE file_path = ? AND kind NOT IN ('import')",
        (raw_file,)).fetchall()
    if not mine:
        return None
    my_ids = {r[0] for r in mine}
    my_names = {r[0]: r[1] for r in mine}

    from .codegraph import _query_edges
    edges = [e for e in _query_edges(conn, list(my_ids))
             if (e.get("source") in my_ids) != (e.get("target") in my_ids)]
    if not edges:
        return None

    other_ids = list({e["target"] if e["source"] in my_ids else e["source"]
                      for e in edges})
    ph = ",".join("?" * len(other_ids))
    others: Dict[str, Tuple[str, str]] = {}
    try:
        for r in conn.execute(
                f"SELECT id, name, file_path FROM nodes WHERE id IN ({ph})",
                tuple(other_ids)).fetchall():
            others[r[0]] = (r[1] or "", _norm_path(r[2] or ""))
    except Exception as e:
        logger.warning("[unowned] 对端节点查询失败: %s", e)

    by_comp: Counter = Counter()
    comp_kinds: Dict[str, set] = {}
    samples: List[dict] = []
    for e in edges:
        out_dir = e["source"] in my_ids
        oid = e["target"] if out_dir else e["source"]
        oname, ofile = others.get(oid, ("", ""))
        if not ofile:
            continue
        cid = file_owner.get(ofile)
        if cid is None:
            cid = owner_lookup(ofile)
            file_owner[ofile] = cid or ""
        if not cid:
            continue      # 对端也未归属：不算跨组件关联
        by_comp[cid] += 1
        comp_kinds.setdefault(cid, set()).add(e.get("kind") or "")
        if len(samples) < _SAMPLES_PER_FILE * 8:
            samples.append({
                "node": my_names.get(e["source"] if out_dir else e["target"], ""),
                "target": oname,
                "targetFile": ofile,
                "component": names.get(cid, cid),
                "kind": e.get("kind") or "",
                "dir": "out" if out_dir else "in",
            })
    if not by_comp:
        return None
    samples = samples[:_SAMPLES_PER_FILE]
    return {"file": _norm_path(raw_file), "crossCount": sum(by_comp.values()),
            "byComponent": sorted(
                [{"component": names.get(cid, cid), "count": n,
                  "kinds": sorted(comp_kinds.get(cid) or [])}
                 for cid, n in by_comp.items()],
                key=lambda x: -x["count"]),
            "samples": samples}


def _make_owner_lookup(file_owner: Dict[str, str]):
    """文件(norm) → 组件 id：精确命中优先，双向后缀对齐兜底（基准不一致防护）。"""
    def lookup(f: str) -> str:
        if not f:
            return ""
        if f in file_owner:
            return file_owner[f]
        for o, cid in file_owner.items():
            if o and (f.endswith("/" + o) or o.endswith("/" + f)):
                return cid
        return ""
    return lookup


def unowned_cross_links(root: Optional[str], project: Optional[str],
                        file: Optional[str] = None,
                        limit: int = _CROSS_FILE_CAP) -> dict:
    """未归属文件 ↔ 已归属组件的跨组件符号关联（按组件聚合 + 样本边）。

    file 缺省 → 全部未归属文件（cap limit）。返回 {links:[...], totalCross, files}。
    """
    rid = (resolve_root(root, project) or "").strip()
    if not rid:
        return {"error": "项目根未解析"}
    names, owns_all, fo = _catalog_maps(rid, project)
    owner_lookup = _make_owner_lookup(fo)

    from .symbols import open_symbol_conn, close_symbol_conn
    conn, src = open_symbol_conn(rid, project)
    if conn is None:
        return {"error": f"符号库不可用(source={src})：请先建立代码图谱索引",
            "reason": "no_symbol_source"}
    try:
        if file:
            targets = [file.strip()]
        else:
            targets = [f for f in _symbol_files(conn)
                       if not _owns_hit(owns_all, _norm_path(f))][:max(1, int(limit or _CROSS_FILE_CAP))]
        file_owner: Dict[str, str] = {}
        links: List[dict] = []
        for f in targets:
            try:
                lk = _file_links(conn, f, owns_all, names, file_owner, owner_lookup)
            except Exception as e:
                logger.warning("[unowned] 跨关联聚合失败 %s: %s", f, e)
                lk = None
            if lk:
                links.append(lk)
        return {"links": links, "totalCross": sum(l["crossCount"] for l in links),
                "files": len(targets), "symbolSource": src}
    finally:
        close_symbol_conn(conn)


# ── 循环批量提取(后端作业)：页面关闭不影响，前端轮询进度 ──
# 单飞：每项目同时至多一个作业。作业线程内逐批「取当前未提取前 N → extract_scope」，
# 每批后重算清单(assetCount>0 自然退出待提取集)——中断/续传/幂等语义与前端旧循环一致。

_JOB_MAX_BATCHES = 80                # 循环保险丝(500 cap / 批 10 → 理论 ≤50 批)


def _pending_unowned(rid: str, project: Optional[str]) -> List[str]:
    """当前待提取的未归属文件：零资产/仅剩 stale(重提可复活)，
    且排除无独立符号的结构性无产出文件(config 聚合头等)。"""
    res = unowned_files(rid, project, limit=_UNOWNED_CAP)
    if res.get("error"):
        return []
    return [f["path"] for f in (res.get("files") or [])
            if not f.get("activeCount") and f.get("extractable", True)]


def _extract_job_loop(ctx) -> dict:
    """批 1-4 收编：进度走 job 行，取消走 cancelRequested 协作标记。"""
    from .structural_extract import extract_structural
    rid = (ctx.scope or {}).get("root") or ""
    project = (ctx.scope or {}).get("project") or ""
    batch = max(1, int((ctx.scope or {}).get("batch") or 10))
    level = (ctx.scope or {}).get("level") or "implementation"
    tried: set = set()          # 本作业已尝试文件：产出为 0 的文件 assetCount 恒 0，
                                # 不记录会每批重进待提取集 → 死循环(实测 44 批回归)
    done = saved = batches = 0
    errors: list = []
    for _ in range(_JOB_MAX_BATCHES):
        if ctx.cancelled():
            return {"saved": saved, "errors": errors, "summary": f"已取消({done})"}
        pending = [f for f in _pending_unowned(rid, project) if f not in tried]
        if not pending:
            break
        files = pending[:batch]
        tried.update(files)
        ctx.progress(done=done, saved=saved, batch=batches, current=files[0])
        try:
            # 批6：批量提取走结构化(无 LLM)；语义增强用户按需触发
            res = extract_structural(rid, project, files, rev="workspace")
            if (res or {}).get("parseFailures") == len(files):
                errors = (errors or [])[-4:] + [
                    {"files": files, "error": "解析失败(符号库/KB 不可达?)"}]
                break   # 整批全失败 → 停住如实上报
            if isinstance(res, dict) and res.get("error"):
                errors = (errors or [])[-4:] + [
                    {"files": files, "error": str(res.get("error"))[:200]}]
                break           # 范围/符号库类错误：继续批大概率同样失败，停住如实上报
            saved += (res.get("saved") or 0)
        except Exception as e:  # noqa: BLE001 — 作业线程必须吞异常保状态一致
            logger.warning("[unowned] 批量提取作业异常: %s", e, exc_info=True)
            errors = (errors or [])[-4:] + [
                {"files": files, "error": str(e)[:200]}]
            break
        done += len(files)
        batches += 1
        ctx.progress(done=done, saved=saved, batch=batches)
    return {"saved": saved, "errors": errors, "summary": f"完成({done} 文件/{batches} 批)"}


from . import job_runner as _job_runner
_job_runner.register("extract_unowned", _extract_job_loop)


def unowned_extract_start(root: Optional[str], project: Optional[str],
                          batch: int = 10, level: str = "implementation") -> dict:
    """启动循环批量提取作业(已有作业在跑则返回其进度)。立即返回，不等待完成。

    响应附清单三分盘点 unowned = 待提取(total) + 已有资产(withAssets) +
    无独立符号(noSymbols)——供前端解释「49 个未归属为何只有 38 个待提取」。
    """
    rid = (resolve_root(root, project) or "").strip()
    if not rid:
        return {"started": False, "reason": "invalid_root"}
    pid = project_id_for(root, project)
    files = (unowned_files(rid, project, limit=_UNOWNED_CAP).get("files") or [])
    pending = [f["path"] for f in files
               if not f.get("activeCount") and f.get("extractable", True)]
    breakdown = {"unowned": len(files),
                 "withAssets": sum(1 for f in files if f.get("activeCount")),
                 "noSymbols": sum(1 for f in files if f.get("extractable") is False)}
    # 互斥：「校验并提取」快照作业在跑时不启动(同项目同时至多一个提取循环)
    try:
        from .sync_extract import sync_extract_status
        if (sync_extract_status(root, project) or {}).get("running"):
            return {"started": False, "reason": "sync_running"}
    except Exception:
        pass
    if not pending:
        return {"started": False, "reason": "nothing_to_extract", "total": 0,
                **breakdown}
    from . import job_runner
    r = job_runner.start_job(
        pid, "extract_unowned",
        scope={"type": "project", "root": rid, "project": project,
               "batch": max(1, batch), "level": level},
        llm=False)   # 结构化提取无 LLM(批6) → 并行档
    if r.get("started"):
        logger.info("[unowned] 批量提取作业启动: pid=%s total=%d batch=%d level=%s",
                    pid, len(pending), batch, level)
        return {"started": True, "total": len(pending),
                "jobId": (r.get("job") or {}).get("id") or "", **breakdown}
    if r.get("reason") == "already_running":
        return {"started": False, "reason": "already_running",
                "progress": unowned_extract_status(root, project)}
    return {"started": False, "reason": r.get("reason") or "unknown"}


def unowned_extract_status(root: Optional[str], project: Optional[str]) -> dict:
    """作业进度(批 1-4：读 job 行映射旧响应形状，FE 兼容)。"""
    rid = (resolve_root(root, project) or "").strip()
    if not rid:
        return {"running": False}
    pid = project_id_for(root, project)
    from . import job_runner
    job = job_runner.active_job(pid, "extract_unowned")
    if not job:
        return {"running": False}
    p = job.get("progress") or {}
    result = job.get("result") or {}
    return {
        "running": job.get("state") == "running",
        "total": p.get("total") or 0, "done": p.get("done") or 0,
        "saved": p.get("saved") or 0, "batches": p.get("batch") or 0,
        "errors": result.get("errors") or [],
        "stopped": job.get("state") == "cancelled",
        "startedAt": job.get("startedAt") or 0,
        "finishedAt": job.get("finishedAt") or 0,
        "level": (job.get("scope") or {}).get("level") or "implementation",
        "batch": (job.get("scope") or {}).get("batch") or 10,
        "current": p.get("current") or "",
        "jobId": job.get("id") or "", "jobState": job.get("state") or "",
    }


def unowned_extract_stop(root: Optional[str], project: Optional[str]) -> dict:
    """请求停止作业(协作式取消；已落库资产保留)。"""
    rid = (resolve_root(root, project) or "").strip()
    if not rid:
        return {"stopped": False}
    pid = project_id_for(root, project)
    from . import job_runner
    job = job_runner.active_job(pid, "extract_unowned")
    if not job:
        return {"stopped": False}
    r = job_runner.cancel_job(pid, job["id"])
    return {"stopped": bool(r.get("cancelled"))}
