"""演化帧序列引擎（B2+ 真数据深化）。

用户契约：版本链 / 基线→任意 HEAD / 基线后任意两 ref —— git diff 能力覆盖的演化都支持。
帧语义：anchor 图谱(KB 挂载版本 architecture.model)为基点，逐帧按
`git ls-tree <ref>` 文件存在性推演组件存活，`git diff prev..ref` 变更交集标 change。
节点 id 恒用 KB 稳定 comm-id（键稳定第一法则 → 帧间 move/morph 补间而非闪变）。

帧 = 独立快照：消失组件直接缺席（引擎 exit 补间），新增组件入列（enter）。
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

MAX_FRAMES = 30          # commit 粒度帧上限(超限均匀采样, 保持首尾)
_LABEL_MAX = 40          # commit subject 截断
_FILE_FRAME_CAP = 400    # 文件层单帧节点上限(超出取变更行数最大的前 N)


def _git(root: str, args: list, timeout: float = 30.0) -> Optional[str]:
    try:
        p = subprocess.run(["git", "-C", root] + args,
                           capture_output=True, text=True, timeout=timeout)
        return p.stdout if p.returncode == 0 else None
    except Exception:
        return None


def resolve_ref(root: str, ref: str, baseline_commit: str = "",
                version_heads: Optional[dict] = None) -> str:
    """ref 归一化为完整 commit sha。

    接受: 'baseline'(→基线 commit) / KB version id(ver-*, version_heads 查表)
    / branch / 'HEAD' / 任意 commit sha(前缀即可)。
    baseline 与版本链 head 直接返回(来自 KB version.head, 可能不在本地 fetch
    历史——rev-parse 会误杀); 其余走 rev-parse, 失败 → ''。
    """
    ref = (ref or "").strip()
    if version_heads and ref in version_heads and version_heads[ref]:
        return version_heads[ref]
    if not ref or ref.lower() == "baseline":
        return baseline_commit or _rev_parse(root, "HEAD")
    return _rev_parse(root, ref)


def _rev_parse(root: str, ref: str) -> str:
    out = _git(root, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])
    return (out or "").strip()


def _commit_list(root: str, base: str, head: str) -> list:
    """base..head 的 commit 序列(时间正序)。超 MAX_FRAMES 均匀采样(保首尾)。"""
    out = _git(root, ["log", "--reverse", "--format=%H%x00%s", f"{base}..{head}"])
    if not out:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split("\x00", 1)
        if parts and parts[0]:
            rows.append((parts[0], parts[1] if len(parts) > 1 else ""))
    if len(rows) > MAX_FRAMES:
        step = (len(rows) - 1) / (MAX_FRAMES - 1)
        rows = [rows[round(i * step)] for i in range(MAX_FRAMES)]
    return rows


def _ls_tree_files(root: str, ref: str) -> set:
    out = _git(root, ["ls-tree", "-r", "--name-only", ref])
    return set(out.splitlines()) if out else set()


def _diff_files(root: str, a: str, b: str) -> set:
    out = _git(root, ["diff", "--name-only", f"{a}..{b}"])
    return set(out.splitlines()) if out else set()


def _numstat_files(root: str, a: str, b: str) -> dict:
    """a..b 的变更文件 → {path: (add, del, status)}；deleted 文件 status=D。"""
    out: dict = {}
    for line in (_git(root, ["diff", "--numstat", f"{a}..{b}"]) or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2]:
            add = int(parts[0]) if parts[0].isdigit() else 0
            dele = int(parts[1]) if parts[1].isdigit() else 0
            out[parts[2]] = (add, dele, "M")
    for line in (_git(root, ["diff", "--name-status", f"{a}..{b}"]) or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1] in out:
            st = parts[0][0]
            add, dele, _ = out[parts[1]]
            out[parts[1]] = (add, dele, st)
    return out


def _import_file_edges(root: str) -> dict:
    """codegraph CLI 索引的 import 边 → {srcFile: set(dstFile)}(文件级, 去自环)。

    索引缺失/表结构不符 → {}(文件层帧退化为无连线, 不报错)。
    """
    db = os.path.join(root, ".codegraph", "codegraph.db")
    if not os.path.isfile(db):
        return {}
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT DISTINCT ns.file_path, nt.file_path FROM edges e "
                "JOIN nodes ns ON e.source = ns.id JOIN nodes nt ON e.target = nt.id "
                "WHERE e.kind = 'imports' AND ns.file_path IS NOT NULL AND nt.file_path IS NOT NULL "
                "AND ns.file_path != nt.file_path").fetchall()
        finally:
            conn.close()
        out: dict = {}
        for src, dst in rows:
            out.setdefault(src, set()).add(dst)
        return out
    except Exception as e:
        logger.warning("[evolution] import 边读取失败(退化无边): %s", e)
        return {}


def _build_file_frames(root: str, base: str, head: str,
                       version_names: Optional[dict] = None) -> dict:
    """文件层帧（粒度下沉裁决）：帧 = 「截至该 commit 的累积变更文件集」。

    - 节点 = 变更文件（id=路径稳定键）；本帧新出现 → added，已有且本帧再变 →
      modified，无新变化 → same；文件已删除 → 本帧起缺席（引擎 exit 补间）。
    - 行数标注：节点名携带累计 +add/-del。
    - 帧间差异显著（每 commit 的新增变更文件）→ 补间动画的天然素材。
    """
    if not root or not base or not head:
        return {"base": base, "head": head, "layer": "file", "frames": []}
    version_names = version_names or {}

    refs = [base]
    log_map: dict = {}
    for sha, subj in _commit_list(root, base, head):
        if sha != refs[-1]:
            refs.append(sha)
        log_map[sha] = subj
    if refs[-1] != head:
        refs.append(head)

    exist: dict[str, set] = {}
    stats: dict[tuple, dict] = {}
    for i, ref in enumerate(refs):
        if ref not in exist:
            exist[ref] = _ls_tree_files(root, ref)
        prev = refs[i - 1] if i else None
        if prev and (prev, ref) not in stats:
            stats[(prev, ref)] = _numstat_files(root, prev, ref)

    # 文件级关系线: codegraph CLI 索引的真实 import 边(每帧按存活文件集过滤)
    import_edges = _import_file_edges(root)

    # 累积变更集: path -> {add, del, deleted}
    cumulative: dict[str, dict] = {}
    frames = []
    prev_alive: Optional[set] = None
    for i, ref in enumerate(refs):
        files = exist[ref]
        changed = stats.get((refs[i - 1], ref), {}) if i else {}
        for path, (add, dele, st) in changed.items():
            ent = cumulative.setdefault(path, {"add": 0, "del": 0})
            ent["add"] += add
            ent["del"] += dele
            if st == "D":
                cumulative[path]["deleted"] = True
        comps = []
        alive = set()
        rows = []
        for path, ent in cumulative.items():
            if ent.get("deleted") or path not in files:
                continue  # 已删除/不在该帧树中 → 缺席(exit)
            alive.add(path)
            rows.append((path, ent))
        # 上限: 按累计变更行数取前 N
        rows.sort(key=lambda kv: -(kv[1]["add"] + kv[1]["del"]))
        rows = rows[:_FILE_FRAME_CAP]
        import os.path as _op
        for path, ent in rows:
            change = "same"
            if prev_alive is not None and path not in prev_alive:
                change = "added"
            elif path in changed:
                change = "modified"
            deps = [d for d in import_edges.get(path, ()) if d in alive and d != path]
            comps.append({
                "id": path,
                "name": f"{_op.basename(path)} (+{ent['add']}/-{ent['del']})",
                "change": change,
                "dependsOn": sorted(deps),
            })
        frames.append({
            "ref": ref,
            "short": ref[:7],
            "label": version_names.get(ref) or version_names.get(ref[:7]) or ref[:7],
            "components": comps,
        })
        prev_alive = alive

    for f in frames:
        subj = log_map.get(f["ref"])
        if subj:
            f["label"] = f"{f['label']} · {subj[:_LABEL_MAX]}"
    return {"base": base, "head": head, "layer": "file", "frames": frames}


def build_frames(root: str, base: str, head: str,
                 anchor_components: list[dict],
                 version_names: Optional[dict] = None,
                 layer: str = "component",
                 ref_points: Optional[list] = None) -> dict:
    """推演帧序列。

    layer=component: anchor_components(KB 组件目录 [{id,name,owns,dependsOn}])
    按 ls-tree 文件存在性推演存活。
    layer=file: 文件层帧(粒度下沉裁决)——累积变更文件集, 不需要 anchor。
    返回 {base, head, layer, frames: [{ref, short, label, components}]}——
    components 元素 {id,name,change,dependsOn}，change ∈ added/modified/same。
    """
    if layer == "file":
        return _build_file_frames(root, base, head, version_names)
    if not root or not base or not head:
        return {"base": base, "head": head, "frames": []}
    version_names = version_names or {}

    # 帧点 = base + (base..head commits) + head；去重保序
    # 批5(需求7)：ref_points 显式指定帧序列(分支/head 列表)——替代自动采样
    if ref_points:
        refs = [base] + [r for r in ref_points if r] 
        if refs[-1] != head:
            refs.append(head)
        # 去重保序
        seen_r: list = []
        for r in refs:
            if r not in seen_r:
                seen_r.append(r)
        refs = seen_r
    else:
        refs = [base]
        for sha, _subj in _commit_list(root, base, head):
            if sha != refs[-1]:
                refs.append(sha)
        if refs[-1] != head:
            refs.append(head)

    # 逐帧文件存在集合 + 相邻变更集(一次 diff, 复用于相邻帧对)
    exist: dict[str, set] = {}
    diffs: dict[str, set] = {}
    for i, ref in enumerate(refs):
        if ref not in exist:
            exist[ref] = _ls_tree_files(root, ref)
        prev = refs[i - 1] if i else None
        if prev and (prev, ref) not in diffs:
            diffs[(prev, ref)] = _diff_files(root, prev, ref)

    anchor_by_id = {c.get("id"): c for c in (anchor_components or []) if c.get("id")}
    frames = []
    prev_alive: Optional[set] = None
    for i, ref in enumerate(refs):
        files = exist[ref]
        changed = diffs.get((refs[i - 1], ref), set()) if i else set()
        comps = []
        alive = set()
        for cid, c in anchor_by_id.items():
            owns = c.get("owns") or []
            if not owns or not any(f in files for f in owns):
                continue  # 该帧此组件的文件尚不存在 → 不存活(基点后新增组件推演)
            alive.add(cid)
            change = "same"
            if prev_alive is not None and cid not in prev_alive:
                change = "added"
            elif changed and any(f in changed for f in owns):
                change = "modified"
            comps.append({
                "id": cid,
                "name": c.get("name") or cid,
                "change": change,
                "dependsOn": [d for d in (c.get("dependsOn") or []) if d in anchor_by_id],
            })
        frames.append({
            "ref": ref,
            "short": ref[:7],
            "label": version_names.get(ref) or version_names.get(ref[:7]) or ref[:7],
            "components": comps,
        })
        prev_alive = alive

    # head/末帧标注 commit subject（首帧若即 base 亦标注）
    log_map = {sha: subj for sha, subj in _commit_list(root, base, head)}
    for f in frames:
        subj = log_map.get(f["ref"])
        if subj:
            f["label"] = f"{f['label']} · {subj[:_LABEL_MAX]}"
    return {"base": base, "head": head, "frames": frames}


def build_graph_frames(root: str, base: str, head: str,
                       anchor_components: list[dict],
                       version_names: Optional[dict] = None,
                       layer: str = "component",
                       ref_points: Optional[list] = None) -> dict:
    """统一图 JSON（canonical + 存在性投影）——动画机制重裁的核心输出。

    在 build_frames（每帧 components 推演）之上做全帧汇聚：
    - canonical.nodes = 全帧组件/文件 id 并集（label 取末帧=最终态）；
    - canonical.edges = dependsOn 并集（from=组件 → to=依赖）；
    - canonical.containers = 组件层按 kind/level 分容器（文件层无容器）；
    - frames[i] = {id,ref,label,nodes,edges,modified} 存在性清单——
      边在场 = 两端节点均在帧内；modified = 该帧 change=modified 的节点。
    消费方（graph 播放组件）只布局一次，帧推进做存在性切换。
    """
    legacy = build_frames(root, base, head, anchor_components, version_names, layer,
                          ref_points=ref_points)
    frames = legacy.get("frames") or []

    names: dict = {}
    node_container: dict = {}
    container_defs: dict = {}
    edge_set: dict = {}
    for f in frames:
        for c in f["components"]:
            names[c["id"]] = c["name"]  # 后帧覆盖 → 最终态标签
            for d in c.get("dependsOn") or []:
                edge_set[(c["id"], d)] = None
    for c in anchor_components or []:
        cid = c.get("id")
        kind = c.get("kind") or c.get("level")
        if cid and kind and cid in names:
            container_defs.setdefault(str(kind), str(kind))
            node_container[cid] = str(kind)

    gf = []
    for f in frames:
        ids = {c["id"] for c in f["components"]}
        edges = [f"{a}->{b}" for a, b in sorted(edge_set) if a in ids and b in ids]
        gf.append({
            "id": f["short"],
            "ref": f["ref"],
            "label": f["label"],
            "nodes": sorted(ids),
            "edges": edges,
            "modified": sorted(c["id"] for c in f["components"] if c.get("change") == "modified"),
        })

    canonical = {
        "nodes": [
            {"key": k, "label": names[k],
             **({"container": node_container[k]} if k in node_container else {})}
            for k in sorted(names)
        ],
        "edges": [{"key": f"{a}->{b}", "from": a, "to": b} for a, b in sorted(edge_set)],
        "containers": [{"key": k, "label": v} for k, v in sorted(container_defs.items())],
    }
    return {
        "base": legacy.get("base"), "head": legacy.get("head"),
        "layer": legacy.get("layer", "component"),
        "canonical": canonical, "frames": gf,
    }
