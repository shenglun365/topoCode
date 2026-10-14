"""变化识别器（批2-2）：锚点变化量的核心口径（需求 2-C/2-E）。

三级识别：
1) 文件级：git diff（name-status）vs 锚定基点——added/modified/deleted；
2) 符号级：变更文件 → structural_parse 行区间索引 → git diff hunk 行区间
   落点 → 变更符号清单（实现级资产的失效/重提判定粒度）；
3) 影响辐射：变更实现级资产 → 上层缓存打脏（逻辑级/组件级聚合视图）——
   辐射只标失效，不自动重提（用户手动触发，需求 2-F/2-G）。

轻量感知（需求 2-F）：detect_dirty 只判「有没有变更」（dirty 文件数），
不做深识别——供 badge/toast 提示轮询。
"""
from __future__ import annotations

import logging
import subprocess
from typing import Any, Dict, List, Optional

from .structural_parse import parse_file, symbol_index, symbols_in_range

logger = logging.getLogger(__name__)


def _git(root: str, *args: str, timeout: int = 60) -> Optional[str]:
    try:
        r = subprocess.run(["git", "-C", root, *args],
                           capture_output=True, timeout=timeout)
        if r.returncode != 0:
            return None
        return r.stdout.decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("[change] git %s failed: %s", args[:2], e)
        return None


def _norm(p: str) -> str:
    return (p or "").strip().replace("\\", "/").lstrip("./")


def detect_file_changes(root: str, base: str = "HEAD") -> Dict[str, List[str]]:
    """文件级变化（vs 锚定基点；base='HEAD' 即工作区含未提交）。

    → {added: [], modified: [], deleted: []}（仓库相对路径，正斜杠）。
    """
    out: Dict[str, List[str]] = {"added": [], "modified": [], "deleted": []}
    if not base:
        base = "HEAD"
    txt = _git(root, "diff", "--name-status", "-z", base, "--")
    if txt is None:
        # 非 git 仓库 / 基点无效 → 空变化（调用方如实呈现）
        return out
    toks = [t for t in txt.split("\0") if t]
    i = 0
    while i < len(toks):
        status, path = toks[i], toks[i + 1] if i + 1 < len(toks) else ""
        i += 2
        if not path:
            continue
        s0 = status[0].upper()
        if s0 == "A":
            out["added"].append(_norm(path))
        elif s0 == "D":
            out["deleted"].append(_norm(path))
        elif s0 in ("M", "R", "C", "T"):
            out["modified"].append(_norm(path.split("\t")[-1] if "\t" in path else path))
    return out


def detect_dirty(root: str) -> int:
    """轻量感知（需求 2-F）：未提交变更文件数（只判有无，不识别内容）。"""
    txt = _git(root, "status", "--porcelain")
    if txt is None:
        return 0
    return sum(1 for ln in txt.splitlines() if ln.strip())


def changed_symbols(root: str, rel: str, base: str = "HEAD") -> List[dict]:
    """符号级变化：变更文件的 diff hunk 行区间 ∩ 符号区间 → 变更符号。

    → [{name, kind, qualifiedName, startLine, endLine, hunks: [(s,e)...]}]
    解析失败（新文件可解析/历史不可解析）→ 返回 [{name:'<whole-file>'}]（整文件视为变更）。
    """
    idx = symbol_index(parse_file(root, rel, impl=False) or {})
    hunks = _diff_hunks(root, rel, base)
    if not hunks:
        return []
    if not idx:
        return _whole_file(hunks)
    hits: Dict[str, dict] = {}
    for s, e in hunks:
        for sym in symbols_in_range(idx, s, e):
            key = sym["qualifiedName"] or f"{sym['kind']}:{sym['name']}:{sym['startLine']}"
            if key not in hits:
                hits[key] = {**sym, "hunks": []}
            if len(hits[key]["hunks"]) < 8:
                hits[key]["hunks"].append((s, e))
    if not hits:
        # 有变更行但零符号命中(解析弱覆盖如 Vue SFC / 纯模板改动)——
        # 保守视为整文件变更(宁多提不错漏)
        return _whole_file(hunks)
    return list(hits.values())


def _whole_file(hunks: List[tuple]) -> List[dict]:
    return [{"name": "<whole-file>", "kind": "file", "qualifiedName": "",
             "startLine": 0, "endLine": 0, "hunks": hunks[:8]}]


def _diff_hunks(root: str, rel: str, base: str = "HEAD") -> List[tuple]:
    """git diff 单文件的新侧行区间列表 [(start, end)...]（unified=0）。"""
    txt = _git(root, "diff", "--unified=0", base, "--", rel)
    if txt is None:
        return []
    out: List[tuple] = []
    for ln in txt.splitlines():
        if not ln.startswith("@@"):
            continue
        try:
            head = ln.split("@@")[1].strip()
            new_part = head.split("+")[-1].split("-")[0].strip()
            start = int(new_part.split(",")[0])
            count = int(new_part.split(",")[1]) if "," in new_part else 1
            if count > 0:
                out.append((start, start + count - 1))
        except Exception:
            continue
    return out
