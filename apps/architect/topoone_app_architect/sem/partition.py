"""大项目分区(D3) —— >5000 文件的基线采集自动拆分 + 人工确认。

定稿方案(用户裁决):
- 单任务上限 5000 源码文件(≈2-5 万符号 < KB communityFromGraph
  _MAX_NODES=50000);
- 自动拆分提案: 轻量 import 扫描(正则, 不走全 AST)→ 弱连通分量 →
  分量超限按一级目录贪心装箱 → 未超限分量同语言合并装箱(不同语言
  不合并——TS/JS 互连靠族内 imports 边, PY 与 TS 无边天然分离);
- 人工确认: 分区勾选(基线管理页预览), 可部分执行;
- ≤5000 文件全链路与现状一致(无提案无确认单作业)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_partition.py -q
"""
import os
import re
from typing import Dict, List, Set, Tuple

MAX_FILES_PER_TASK = 5000

# 轻量 import 提取(每语言一条正则; 只为建依赖图, 不求完备)
_IMPORT_RES = [
    re.compile(r"""^\s*import\s+['"]([^'"]+)['"]""", re.M),                # js/ts
    re.compile(r"""^\s*(?:import|export)\s[^;]*?from\s+['"]([^'"]+)['"]""", re.M),
    re.compile(r"""^\s*import\(\s*['"]([^'"]+)['"]\s*\)""", re.M),
    re.compile(r"""^\s*from\s+([\.\w]+)\s+import""", re.M),                # py
    re.compile(r"""^\s*import\s+([\.\w]+)""", re.M),
    re.compile(r"""^\s*import\s+([\w.]+)\s*;""", re.M),                    # java/kt/cs
    re.compile(r"""^\s*use\s+([\w:]+)\s*;""", re.M),                       # rust/php
    re.compile(r"""^\s*#include\s+["]([^"]+)[""]""", re.M),                # c 引号
    re.compile(r"""^\s*require(?:_relative)?\s+['"]([^'"]+)['"]""", re.M), # rb
]

_EXT_LANG = {".ts": "typescript", ".tsx": "typescript", ".js": "javascript",
             ".jsx": "javascript", ".vue": "vue", ".mjs": "javascript",
             ".cjs": "javascript", ".py": "python", ".go": "go",
             ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
             ".scala": "scala", ".rs": "rust", ".cs": "c_sharp",
             ".php": "php", ".rb": "ruby", ".lua": "lua", ".dart": "dart",
             ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
             ".hh": "cpp", ".swift": "swift"}


def file_lang(rel: str) -> str:
    return _EXT_LANG.get(os.path.splitext(rel)[1].lower(), "")


def scan_dependencies(root: str, files: List[str], limit_bytes: int = 262144) -> Dict[str, Set[str]]:
    """轻量 import 扫描 → {file: {原始模块串}}(只为连通性, 解析容错)。"""
    deps: Dict[str, Set[str]] = {}
    for rel in files:
        full = os.path.join(root, rel.replace("/", os.sep))
        try:
            if os.path.getsize(full) > limit_bytes:
                deps[rel] = set()
                continue
            with open(full, "rb") as fh:
                head = fh.read(limit_bytes).decode("utf-8", "replace")
        except OSError:
            deps[rel] = set()
            continue
        found: Set[str] = set()
        for rx in _IMPORT_RES:
            for m in rx.finditer(head):
                found.add(m.group(1))
        deps[rel] = found
    return deps


def _link_file(mod: str, from_rel: str, file_set: Set[str]) -> str:
    """模块串 → 项目内文件(分区扫描用轻量版: 相对路径 + 同名探测)。"""
    if mod.startswith("."):
        base = os.path.dirname(from_rel)
        stem = os.path.normpath(os.path.join(base, mod)).replace(os.sep, "/")
    elif "/" in mod or mod.endswith((".py", ".h", ".rb")):
        stem = mod
    else:
        return ""
    if stem in file_set:
        return stem
    stem_n = stem.lstrip("./")
    for ext in (".ts", ".tsx", ".js", ".jsx", ".vue", ".py", ".go", ".java",
                ".kt", ".rs", ".h", ".cpp", ".rb", ".php", ".dart"):
        if stem_n + ext in file_set:
            return stem_n + ext
    for nm in ("index", "__init__"):
        for ext in (".ts", ".js", ".py", ".tsx"):
            cand = f"{stem_n}/{nm}{ext}"
            if cand in file_set:
                return cand
    return ""


def _wcc(files: List[str], deps: Dict[str, Set[str]], file_set: Set[str]) -> List[Set[str]]:
    """弱连通分量(无向并查)。"""
    parent = {f: f for f in files}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for f, mods in deps.items():
        for m in mods:
            tgt = _link_file(m, f, file_set)
            if tgt and tgt in parent:
                union(f, tgt)
    groups: Dict[str, Set[str]] = {}
    for f in files:
        groups.setdefault(find(f), set()).add(f)
    return sorted(groups.values(), key=len, reverse=True)


def _dir_of(rel: str) -> str:
    return rel.split("/")[0] if "/" in rel else "(root)"


def _box_by_dir(comp: Set[str], cap: int) -> List[List[str]]:
    """分量超限 → 一级目录贪心装箱(同目录优先同组, 每箱 ≤ cap)。"""
    by_dir: Dict[str, List[str]] = {}
    for f in sorted(comp):
        by_dir.setdefault(_dir_of(f), []).append(f)
    boxes: List[List[str]] = []
    cur: List[str] = []
    for d in sorted(by_dir, key=lambda x: -len(by_dir[x])):
        group = by_dir[d]
        if len(cur) + len(group) <= cap:
            cur.extend(group)
        else:
            # 大目录自身切分
            for i in range(0, len(group), cap):
                chunk = group[i:i + cap]
                if len(cur) + len(chunk) <= cap:
                    cur.extend(chunk)
                else:
                    if cur:
                        boxes.append(cur)
                    cur = chunk
    if cur:
        boxes.append(cur)
    return boxes


def build_partitions(root: str, files: List[str],
                     cap: int = MAX_FILES_PER_TASK) -> Tuple[List[dict], dict]:
    """自动拆分提案。返回 (partitions, stats)。

    partitions: [{idx, files, langs, est_symbols, reason}]。
    ≤cap 文件 → 单分区(现状路径, reason='single')。
    """
    file_set = set(files)
    if len(files) <= cap:
        langs = sorted({file_lang(f) for f in files if file_lang(f)})
        est = _est_symbols(root, files)
        return ([{"idx": 0, "files": list(files), "langs": langs,
                  "est_symbols": est, "reason": "single"}],
                {"components": 1, "files": len(files)})
    deps = scan_dependencies(root, files)
    comps = _wcc(files, deps, file_set)
    partitions: List[List[str]] = []
    overflow = 0
    for comp in comps:
        if len(comp) > cap:
            overflow += 1
            partitions.extend(_box_by_dir(comp, cap))
        else:
            partitions.append(sorted(comp))
    # 未超限分量同语言合并装箱(减少任务数; 语言集合相交则可并)
    merged = _merge_same_lang(partitions, cap)
    out = []
    for i, pf in enumerate(merged):
        langs = sorted({file_lang(f) for f in pf if file_lang(f)})
        out.append({
            "idx": i, "files": pf, "langs": langs,
            "est_symbols": _est_symbols(root, pf),
            "reason": "dir-box" if any(len(p) > cap for p in partitions) and i in () else
                      ("component" if len(pf) < len(files) else "merged"),
        })
    stats = {"components": len(comps), "files": len(files),
             "overflowSplit": overflow, "partitions": len(out)}
    return out, stats


def _merge_same_lang(groups: List[List[str]], cap: int) -> List[List[str]]:
    """语言集合相交的未超限组合并(贪心, 上限 cap)。"""
    groups = [sorted(g) for g in groups if len(g) <= cap]
    oversized = []
    merged: List[dict] = []
    for g in groups:
        langs = {file_lang(f) for f in g}
        hit = None
        for m in merged:
            if langs & m["langs"] and len(m["files"]) + len(g) <= cap:
                hit = m
                break
        if hit:
            hit["files"].extend(g)
            hit["langs"] |= langs
        else:
            merged.append({"files": list(g), "langs": langs})
    return [m["files"] for m in merged]


def _est_symbols(root: str, files: List[str], sample: int = 24) -> int:
    """粗估符号数: 抽样文件的符号密度 × 文件数(下限 1/文件)。"""
    if not files:
        return 0
    density = 0
    n = 0
    for rel in files[:sample]:
        full = os.path.join(root, rel.replace("/", os.sep))
        try:
            with open(full, "rb") as fh:
                txt = fh.read(131072).decode("utf-8", "replace")
        except OSError:
            continue
        # 粗略符号密度: 非空行 / 3
        loc = sum(1 for ln in txt.splitlines() if ln.strip())
        density += max(1, loc // 3)
        n += 1
    if n == 0:
        return len(files)
    return int(density / n * len(files))
