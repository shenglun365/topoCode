"""git 历史探测(基线锚定选单): 分支列表 + 提交分页/搜索(数据主权批E+)。

自 arch_git 拆出(§8.2 行数门禁)——纯函数, 供 project.git-info / git-commits /
git-branches 端点消费。
"""
from __future__ import annotations

from .arch_git import _git

_FMT = "--pretty=format:%H%x1f%h%x1f%an%x1f%at%x1f%s"
_SEARCH_CAP = 20000   # 搜索模式全量扫描上限(低频操作, 防超长历史失控)


def _parse_rows(out: str, head: str) -> list:
    rows = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 5:
            continue
        h, short, author, at, msg = parts
        rows.append({"hash": h, "short": short, "author": author,
                     "date": int(at) if at.isdigit() else 0,
                     "message": msg, "isHead": h == head})
    return rows


def git_log(root: str, since: str = "", limit: int = 10, branch: str = "",
            search: str = "", offset: int = 0) -> list:
    """提交列表(基线锚定选单/提交历史): 新→旧, 含 hash/author/date/message。

    branch 空 = 当前 HEAD; since 为基线 head 时只取其后提交(range 语义)。
    search 匹配 message/作者/hash 子串(忽略大小写; BE 端流式过滤, 分页在
    过滤后应用)。返回 [{hash,short,author,date,message,isHead}]。"""
    rev = branch.strip() or "HEAD"
    head = (_git(["rev-parse", "HEAD"], cwd=root) or "").strip()
    kw = (search or "").strip().casefold()
    if kw:
        # 搜索: 全量扫描(since 语义保留) → BE 端子串过滤 → 分页
        rng = f"{since}..{rev}" if since else rev
        out = _git(["log", rng, f"-n{_SEARCH_CAP}", _FMT], cwd=root) or ""
        rows = [r for r in _parse_rows(out, head)
                if kw in r["message"].casefold() or kw in r["author"].casefold()
                or kw in r["hash"].casefold()]
        return rows[int(offset):int(offset) + int(limit)]
    rng = f"{since}..{rev}" if since else rev
    out = _git(["log", rng, f"-n{int(limit)}", f"--skip={int(offset)}", _FMT],
               cwd=root) or ""
    return _parse_rows(out, head)


def git_branches(root: str) -> dict:
    """本地分支列表 + 当前分支(基线锚定选单分支下拉; 远端分支不列)。"""
    cur = (_git(["branch", "--show-current"], cwd=root) or "").strip()
    out = _git(["for-each-ref", "refs/heads", "--format=%(refname:short)"],
               cwd=root) or ""
    branches = [l.strip() for l in out.splitlines() if l.strip()]
    if cur and cur not in branches:
        branches.insert(0, cur)
    return {"branches": branches, "current": cur}
