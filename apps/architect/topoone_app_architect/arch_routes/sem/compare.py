"""资产/组件变更对比 —— 任意 head 对 vs head/工作区（缓存态，零持久化）。

需求(plan-C 基线对比改造)：
- 基准统一取项目 baselineCommit(KB 基线版本 head)，不再依赖符号源同步 KV；
- 支持基线之后(含基线)的任意两个 head 互比，也支持 worktree(HEAD+未提交)作目标侧；
- 资产变化按「提取时锚点哈希(anchorHashes) × 两侧内容 md5」严格归属（不触发重提）：
    stable  = 锚点文件在两侧内容一致 → 资产不变；
    removed = 锚点文件在目标侧已删除 → 资产在目标侧消失；
    changed = 锚点文件被修改 → 资产属基准侧(side=base)或中间态(stale)，目标侧需重提；
    new     = 锚定新增文件且哈希匹配目标侧 → 目标侧新增资产；
    pending = 目标侧存在但无资产匹配其内容的文件 → 待提取(工作区目标可经 /extract 补齐后重比)；
- 变化关联为 **AST 符号级**：astRefs 的 [startLine,endLine] 即符号节点代码段，
  按 side 投影到对应侧坐标系后与该侧变更 hunk 求交——
  strong(强)=符号段内容变化；weak(弱)=仅同文件其他位置变更(可能受影响)；
  稳定资产不参与判定；文件级"同文件即标变"的噪声由此消除；
- 组件口径用 KB architecture.model 的 owns 归属；未归属任何组件的变更文件
  (典型为新增文件)归入「其他」桶(id=__other__，展示名由前端 i18n)，其资产与
  组件内资产的 relations 保留为跨域联系(证据式边，合理联动，不裁剪)；
- 结果只做进程内缓存(TTL 60s + LRU 32，键含 pid/base/target)——比对输入
  变化极快，不写库、不做任何持久化。
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import time
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from .. import store
from .paths import _norm_path, project_id_for, resolve_root
from . import symbols

logger = logging.getLogger(__name__)

CACHE_TTL = 60.0
CACHE_MAX = 32
_cmp_cache: "OrderedDict[tuple, Tuple[float, dict]]" = OrderedDict()

_CAP_FILES = 500      # 单类变更文件清单上限(响应内)
_CAP_ASSETS = 200     # 单桶资产清单上限
_CAP_LINKS = 100      # 跨域联系边上限
_CAP_SIDE_MD5 = 300   # 侧归属 md5 计算的变更文件数上限(超出退化为纯文件级推导)
_CAP_PENDING = 500    # 待提取文件清单上限(响应内; 与 count 保持一致, 提取闭环按钮按清单执行)

# 可提取=代码扩展(与 KB 扫描 walker._EXT_MAP 同口径): 文档/配置/无扩展名文件
# 永远提取不出语义资产, 混入 pending 会让「提取并重新对比」永远清不掉。
_CODE_EXTS = {
    ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs",
    ".py", ".pyw", ".java", ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hh", ".hxx",
    ".go", ".rs", ".cs", ".swift", ".rb", ".rake", ".kt", ".kts", ".php", ".inc",
    ".dart", ".scala", ".sc", ".lua", ".luau", ".m", ".mm", ".vue",
}


def _extractable(path: str) -> bool:
    dot = path.rfind(".")
    if dot <= path.rfind("/"):   # 无扩展名(或扩展名前是目录分隔) → 非代码
        return False
    return path[dot:].lower() in _CODE_EXTS
_BLOB_MAX = 8 * 1024 * 1024

OTHER = "__other__"


def _git(root: str, args: list, timeout: float = 20.0):
    return symbols._git(root, args, timeout=timeout)


def _git_ok(root: str, args: list) -> bool:
    """按退出码判定的 git 探测(cat-file -e / merge-base --is-ancestor 成功时无 stdout)。"""
    import subprocess
    try:
        p = subprocess.run(["git", "-C", root] + list(args),
                           capture_output=True, text=True, timeout=20)
        return p.returncode == 0
    except Exception:
        return False


def baseline_commit(root: Optional[str], project: Optional[str] = None) -> str:
    """基准 commit（对外口径与 baseline-diff 一致）。"""
    return symbols.resolve_base_commit(root, project)


def _commit_exists(root: str, sha: str) -> bool:
    return _git_ok(root, ["cat-file", "-e", f"{sha.strip()}^{{commit}}"])


def _blob_md5(root: str, ref: str, path: str) -> str:
    """ref:file 内容 md5(二进制读取，与工作区 _file_md5 同口径)。缺失/超限 → ''。"""
    try:
        p = subprocess.run(["git", "-C", root, "show", f"{ref}:{path}"],
                           capture_output=True, timeout=20)
        if p.returncode != 0 or not p.stdout or len(p.stdout) > _BLOB_MAX:
            return ""
        return hashlib.md5(p.stdout).hexdigest()[:16]
    except Exception:
        return ""


def _side_md5_maps(root: str, base: str, target: str,
                   files: Dict[str, List[str]]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """变更文件在基准/目标两侧的内容 md5（资产侧归属判定用；cap 内计算，缺失 ''）。

    base 侧：modified/deleted 取 `git show base:f`；added 在基准侧不存在 → ''。
    target 侧：added/modified 取 `git show target:f`；target='worktree' 时直接读
    磁盘文件(与提取时 anchorHashes 同源)；deleted 在目标侧不存在 → ''。
    """
    from .incremental import _file_md5
    base_md5: Dict[str, str] = {}
    tgt_md5: Dict[str, str] = {}
    budget = _CAP_SIDE_MD5
    for f in files.get("modified", []) + files.get("deleted", []):
        if budget <= 0:
            break
        budget -= 1
        base_md5[f] = _blob_md5(root, base, f)
    for f in files.get("added", []) + files.get("modified", []):
        if budget <= 0:
            break
        budget -= 1
        if target == "worktree":
            tgt_md5[f] = _file_md5(root, f)
        else:
            tgt_md5[f] = _blob_md5(root, target, f)
    return base_md5, tgt_md5


def _is_ancestor(root: str, base: str, tip: str) -> bool:
    """base 是否为 tip 的祖先(含相等)。git 失败视为不满足(宁可拒绝不误报)。"""
    return _git_ok(root, ["merge-base", "--is-ancestor", base, tip])


def _name_status(root: str, rng: list) -> Dict[str, List[str]]:
    """git diff --name-status → {added,modified,deleted}（R/C/T 记 modified，取新路径）。"""
    res: Dict[str, List[str]] = {"added": [], "modified": [], "deleted": []}
    out = _git(root, ["diff", "--name-status", *rng, "--"]) or ""
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) < 2:
            continue
        st, path = parts[0].strip(), parts[1].strip()
        if " -> " in path:
            path = path.split(" -> ")[-1].strip()
        if not path:
            continue
        if st.startswith("A"):
            res["added"].append(_norm_path(path))
        elif st.startswith("D"):
            res["deleted"].append(_norm_path(path))
        elif st[:1] in ("M", "R", "C", "T"):
            res["modified"].append(_norm_path(path))
    return res


def file_delta(root: str, base: str, target: str) -> Dict[str, List[str]]:
    """base → target 文件级变更（去重、工作区态优先）。

    target='worktree'：`git diff --name-status base`（工作区 vs 基准，含未提交）
    ∪ 未跟踪文件(porcelain `??` → added)。
    target=commit：两快照 diff（git diff base target）。
    """
    if target == "worktree":
        cat: Dict[str, str] = {}
        for src in (_name_status(root, [base]), symbols._git_porcelain_status(root)):
            for k in ("added", "modified", "deleted"):
                for p in src.get(k) or []:
                    cat[p] = k
        out: Dict[str, List[str]] = {"added": [], "modified": [], "deleted": []}
        for p, k in cat.items():
            out[k].append(p)
        return out
    return _name_status(root, [base, target])


def _component_maps(model: dict) -> Tuple[Dict[str, str], Dict[str, str]]:
    """KB 组件模型 → (id→展示名表, 文件→组件id 归属表)。归属取最深组件(父子重叠不重复计)。"""
    comps = model.get("components") or []
    by_id = {c.get("id"): c for c in comps if c.get("id")}
    names = {cid: ((c.get("name") or "").strip() or cid) for cid, c in by_id.items()}
    depth: Dict[str, int] = {}

    def _depth(cid: str, seen: Optional[set] = None) -> int:
        seen = seen if seen is not None else set()
        if cid in depth:
            return depth[cid]
        if cid in seen:
            return 0
        seen.add(cid)
        pid = (by_id.get(cid) or {}).get("parentId") or ""
        d = 0 if pid not in by_id else _depth(pid, seen) + 1
        depth[cid] = d
        return d

    owner: Dict[str, str] = {}
    for cid, c in by_id.items():
        for f in c.get("owns") or []:
            nf = _norm_path(f)
            if not nf:
                continue
            cur = owner.get(nf)
            if cur is None or _depth(cid) > _depth(cur):
                owner[nf] = cid
    return names, owner


def _owner_of(owner: Dict[str, str], p: str) -> str:
    """文件 → 组件 id：精确命中优先；未命中做双向后缀对齐——
    git diff 在工作目录(可为仓库子目录)执行产出 workDir 相对路径，
    而 KB owns 为镜像根相对路径，两侧基准不同，精确匹配会大面积漏归「其他」。"""
    if not p or not owner:
        return ""
    if p in owner:
        return owner[p]
    for o, cid in owner.items():
        if o and (p.endswith("/" + o) or o.endswith("/" + p)):
            return cid
    return ""


def _asset_brief(a: dict, files: List[str], comp: str) -> dict:
    return {"id": a.get("id") or "", "name": a.get("name") or "",
            "kind": a.get("kind") or "", "level": a.get("level") or "",
            "component": comp, "files": sorted(files)[:10]}


def _changed_hunks(root: str, base: str, target: str) -> Dict[str, Dict[str, List[List[int]]]]:
    """git diff -U0 解析变更 hunk → {file: {base: [[s,e]...], tgt: [[s,e]...]}}（闭区间，1-based）。

    用于符号级强/弱关联判定：变更行落在符号代码段行区间内 = 段内容真的变了(强)；
    仅同文件其他位置变更 = 弱关联(可能受影响)。
    target='worktree' → `git diff -U0 base`(工作区 vs 基准)；否则 `git diff -U0 base target`。
    解析 @@ -a[,b] +c[,d] @@ 两侧行区间(b/d=0 表示该侧无行，跳过)；
    `+++ /dev/null`(删除) 的 hunk 归属到 --- a/ 路径的 base 侧。
    """
    import re
    rng = [base] if target == "worktree" else [base, target]
    out: Dict[str, Dict[str, List[List[int]]]] = {}
    cur: Optional[str] = None
    cur_del: Optional[str] = None
    hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    for line in (_git(root, ["diff", "-U0", "--no-color", *rng, "--"]) or "").splitlines():
        if line.startswith("--- a/"):
            cur_del = _norm_path(line[6:].strip())
            continue
        if line.startswith("--- "):
            continue                       # --- /dev/null(新增文件)
        if line.startswith("+++ b/"):
            cur = _norm_path(line[6:].strip())
            out.setdefault(cur, {"base": [], "tgt": []})
            continue
        if line.startswith("+++ "):
            if cur_del:                    # +++ /dev/null(删除文件) → 归属被删路径
                cur = cur_del
                out.setdefault(cur, {"base": [], "tgt": []})
            continue
        m = hunk_re.match(line)
        if m and cur:
            bs, bn = int(m.group(1)), int(m.group(2) or 1)
            ts, tn = int(m.group(3)), int(m.group(4) or 1)
            h = out[cur]
            if bn > 0:
                h["base"].append([bs, bs + bn - 1])
            if tn > 0:
                h["tgt"].append([ts, ts + tn - 1])
    return out


def _span_hits(start: int, end: int, hunks: List[List[int]]) -> bool:
    """资产锚点行区间 [start,end] 与任一变更 hunk 相交。"""
    if not start or not hunks:
        return False
    end = end or start
    return any(start <= h[1] and end >= h[0] for h in hunks)


def compare_changes(root: Optional[str], project: Optional[str],
                    base: str = "", target: str = "worktree") -> dict:
    """资产/组件变更对比主入口。校验失败返回 {'error': msg}（路由转 400）。"""
    root = (resolve_root(root, project) or "").strip()
    if not root or not os.path.isdir(root):
        return {"error": "项目工作目录解析失败"}
    pid = project_id_for(root, project)
    base_commit = baseline_commit(root, project)
    base = (base or "").strip() or base_commit
    if not base:
        return {"error": "未对齐基线：项目无 baselineCommit，无法确定对比基准"}
    if not _commit_exists(root, base):
        return {"error": f"基准 commit 不存在: {base[:12]}"}
    target = (target or "worktree").strip() or "worktree"
    head = (_git(root, ["rev-parse", "HEAD"]) or "").strip()
    tip = head if target == "worktree" else target
    if target != "worktree" and not _commit_exists(root, target):
        return {"error": f"对比目标 commit 不存在: {target[:12]}"}
    # 基准须为目标侧的祖先(含相等)：保证「增量(可减量)」语义
    if tip and not _is_ancestor(root, base, tip):
        return {"error": "基准需为对比目标的祖先提交(含基线)；请选择基线之后的 head"}

    files = file_delta(root, base, target)
    counts = {k: len(set(v)) for k, v in files.items()}
    files = {k: sorted(set(v)) for k, v in files.items()}
    files_cap = {k: v[:_CAP_FILES] for k, v in files.items()}
    added, modified, deleted = set(files["added"]), set(files["modified"]), set(files["deleted"])
    changed_files = added | modified | deleted

    # ── 组件口径：KB owns 归属；未归属 → 「其他」(__other__) ──
    names: Dict[str, str] = {}
    owner: Dict[str, str] = {}
    try:
        from ..common import build_architecture_model
        model = build_architecture_model(root, project)
        names, owner = _component_maps(model if isinstance(model, dict) else {})
    except Exception as e:
        logger.warning("[compare] 组件模型获取失败(变更全部归入其他): %s", e)

    comp_delta: Dict[str, dict] = {}
    for k in ("added", "modified", "deleted"):
        for p in files[k]:
            cid = _owner_of(owner, p) or OTHER
            bucket = comp_delta.setdefault(cid, {"id": cid, "name": names.get(cid) or "",
                                                 "added": 0, "modified": 0, "deleted": 0})
            bucket[k] += 1
    components = [comp_delta[cid] for cid in
                  sorted(comp_delta, key=lambda c: (c == OTHER, comp_delta[c].get("name") or ""))]

    # ── 资产变化：锚点哈希 × 两侧内容 md5 的严格归属（不重提） ──
    # 资产提取时记录 anchorHashes(锚点文件 md5)。与基准/目标侧内容 md5 比对：
    #   匹配 base_md5 → 资产属基准侧；匹配 tgt_md5 → 属目标侧；都不匹配 → 中间态(stale)。
    # 目标侧新增/被改文件若无资产匹配 tgt_md5 → 目标侧资产缺失 → 待提取(工作区目标可补提)。
    base_md5, tgt_md5 = _side_md5_maps(root, base, target, files)
    # 符号级变化判定：astRefs 的 [startLine,endLine] 即符号节点代码段，
    # 按 side 归属投影到对应侧坐标系后与该侧变更 hunk 求交——
    # 段内命中 → 强关联(符号段内容真的变了)；段外同文件变更 → 弱关联(可能受影响)。
    hunks = _changed_hunks(root, base, target) if changed_files else {}
    rows = [a for a in (store.SemanticAssetsStore.all_status(pid, limit=4000) or [])
            if (a.get("status") or "active") != "deleted"]
    stable_n = 0
    changed: List[dict] = []          # 基准侧有、目标侧被修改
    new_at_target: List[dict] = []    # 目标侧新增(锚定 added 文件且哈希匹配目标侧)
    removed: List[dict] = []          # 目标侧删除(锚定文件目标侧不存在)
    changed_total = new_total = removed_total = 0
    changed_strong = changed_weak = 0
    other_delta_assets: List[dict] = []
    owned_ids: set = set()
    anchored: Dict[str, List[dict]] = {}   # file -> [ (asset, hash) ] 锚定索引(待提取判定用)
    for a in rows:
        ahashes = {_norm_path(k): (v or "") for k, v in (a.get("anchorHashes") or {}).items()}
        af = set(ahashes) & {_norm_path(r.get("file") or "") for r in (a.get("astRefs") or [])}
        af = {f for f in af if f}
        if not af:
            continue
        comp = _owner_of(owner, next(iter(af))) or OTHER
        hit_del = af & deleted
        hit_mod = af & modified
        hit_add = af & added
        in_delta = bool(hit_del or hit_mod or hit_add)
        if comp == OTHER:
            if in_delta:
                other_delta_assets.append(a)
        else:
            owned_ids.add(a.get("id"))
        for f in af:
            anchored.setdefault(f, []).append((a, ahashes.get(f) or ""))

        def _side(hits: set) -> str:
            bs = [base_md5.get(f) for f in hits if f in base_md5]
            ts = [tgt_md5.get(f) for f in hits if f in tgt_md5]
            if ts and all(ahashes.get(f) and ahashes.get(f) == tgt_md5.get(f) for f in hits if f in tgt_md5):
                return "target"
            if bs and all(ahashes.get(f) and ahashes.get(f) == base_md5.get(f) for f in hits if f in base_md5):
                return "base"
            return "stale" if in_delta else ""

        def _strong(hits: set, side: str) -> bool:
            """符号级：锚点符号代码段(行区间)在其归属侧坐标系中与变更 hunk 相交。"""
            for r in (a.get("astRefs") or []):
                f = _norm_path(r.get("file") or "")
                if f not in hits:
                    continue
                s_ = int(r.get("startLine") or 0)
                if not s_:
                    continue          # 无行信息的锚点不参与行级判定
                e_ = int(r.get("endLine") or 0) or s_
                h = hunks.get(f)
                if not h:
                    if f in added:
                        return True   # 未跟踪新文件：整文件皆新增
                    continue
                if side == "base":
                    if _span_hits(s_, e_, h.get("base") or []):
                        return True
                elif side == "target":
                    if _span_hits(s_, e_, h.get("tgt") or []):
                        return True
                else:                 # stale/未知侧：保守策略，任一侧命中即强
                    if _span_hits(s_, e_, h.get("tgt") or []) or _span_hits(s_, e_, h.get("base") or []):
                        return True
            return False

        if hit_del:
            removed_total += 1
            if len(removed) < _CAP_ASSETS:
                removed.append({**_asset_brief(a, sorted(hit_del), comp), "side": _side(hit_del | hit_mod),
                                "strong": True})
            continue
        if hit_add and not hit_mod:
            # 目标侧新增文件：资产哈希匹配目标侧 → 目标侧新增资产；否则中间态
            new_total += 1
            if len(new_at_target) < _CAP_ASSETS:
                new_at_target.append({**_asset_brief(a, sorted(hit_add), comp), "side": _side(hit_add),
                                      "strong": True})
            continue
        if hit_mod:
            changed_total += 1
            side = _side(hit_mod)
            strong = _strong(hit_mod, side)
            if strong:
                changed_strong += 1
            else:
                changed_weak += 1
            if len(changed) < _CAP_ASSETS:
                changed.append({**_asset_brief(a, sorted(hit_mod), comp), "side": side,
                                "strong": strong})
            continue
        stable_n += 1

    # 待提取：目标侧存在(added/modified)的变更文件，没有任何资产锚定其目标侧内容。
    # 仅代码扩展(可提取)：文档/配置等永远无资产产出，混入会让提取闭环永不清零。
    pending_files = [f for f in sorted(added | modified)
                     if _extractable(f) and tgt_md5.get(f)
                     and not any(h == tgt_md5.get(f) for _, h in anchored.get(f, []))]

    # 通用提取闭环：pending 中「目标侧内容 == 工作区当前内容」的子集可经工作区
    # 提取锚定(不限 target=worktree——任意 commit 对，只要该文件自 target 起未再
    # 变更)；内容已分叉的文件提取无效(资产身份=canonicalKey，提取历史内容会
    # 覆盖现役资产摘要，破坏性)，自动排除。
    if pending_files and target != "worktree":
        from .incremental import _file_md5
        extractable = [f for f in pending_files
                       if tgt_md5.get(f) and tgt_md5[f] == _file_md5(root, f)]
    else:
        extractable = list(pending_files)

    # ── 跨域联系：「其他」桶资产 → 组件内资产 的 relations(证据式, 合理联动) ──
    cross_links: List[dict] = []
    try:
        from .engine import _relation_target_index, _resolve_relation_target
        idx = _relation_target_index(rows)
        name_by_id = {a.get("id"): (a.get("name") or "") for a in rows}
        for a in other_delta_assets:
            if len(cross_links) >= _CAP_LINKS:
                break
            detail = a.get("detail") or {}
            rels = (detail.get("relations") or []) + (detail.get("inputs") or []) + (detail.get("outputs") or [])
            for rel in rels:
                tgt, resolved = _resolve_relation_target((rel.get("target") or "").strip(), idx)
                if not resolved or tgt == a.get("id") or tgt not in owned_ids:
                    continue
                cross_links.append({"fromId": a.get("id"), "fromName": a.get("name") or "",
                                    "toId": tgt, "toName": name_by_id.get(tgt) or "",
                                    "type": rel.get("type") or "",
                                    "semantic": (rel.get("semantic") or "")[:80]})
                if len(cross_links) >= _CAP_LINKS:
                    break
    except Exception as e:
        logger.warning("[compare] 跨域联系解析失败(不影响对比主体): %s", e)

    return {
        "base": base, "baseIsBaseline": base == base_commit,
        "target": target, "targetIsWorktree": target == "worktree",
        "head": head,
        "noChanges": not changed_files,
        "files": files_cap,
        "counts": counts,
        "components": components,
        "newFileCount": counts["added"],
        "assets": {"stable": stable_n,
                   "changed": changed, "changedTotal": changed_total,
                   "changedStrong": changed_strong, "changedWeak": changed_weak,
                   "new": new_at_target, "newTotal": new_total,
                   "removed": removed, "removedTotal": removed_total,
                   "pending": {"count": len(pending_files),
                               "files": pending_files[:_CAP_PENDING],
                               "extractable": extractable[:_CAP_PENDING],
                               "extractableCount": len(extractable)}},
        "crossLinks": cross_links,
        "crossLinkCount": len(cross_links),
    }


def cached_compare(root: Optional[str], project: Optional[str],
                   base: str = "", target: str = "worktree") -> dict:
    """带进程内缓存的对比入口（TTL 60s + LRU 32；键含 pid/base/target）。"""
    _root = (resolve_root(root, project) or "").strip()
    pid = project_id_for(_root, project) if _root else ""
    _base = (base or "").strip() or (baseline_commit(_root, project) if _root else "")
    key = (pid, _base, (target or "worktree").strip() or "worktree")
    now = time.time()
    hit = _cmp_cache.get(key)
    if hit and now - hit[0] < CACHE_TTL:
        _cmp_cache.move_to_end(key)
        return dict(hit[1], cached=True)
    res = compare_changes(root, project, base, target)
    if not res.get("error"):
        _cmp_cache[key] = (now, res)
        if len(_cmp_cache) > CACHE_MAX:
            _cmp_cache.popitem(last=False)
    return res


def invalidate_compare_cache() -> None:
    """测试/强制刷新用：清空对比缓存。"""
    _cmp_cache.clear()
