"""git 历史探测(基线锚定选单): 基线后提交列表(数据主权批E)。

自 arch_git 拆出(§8.2 行数门禁)——纯函数, 供 project.git-info 端点消费。
"""
from __future__ import annotations

from .arch_git import _git


def git_log(root: str, since: str = "", limit: int = 10) -> list:
    """基线后的提交列表(基线设定探测选单): 新→旧, 含 hash/author/date/message。

    since 为基线 head(空 = 不限, 取最近 limit 条)。返回 [{hash,short,author,
    date,message,isHead}]。"""
    rng = f"{since}..HEAD" if since else "HEAD"
    out = _git(["log", rng, f"-n{int(limit)}", "--pretty=format:%H%x1f%h%x1f%an%x1f%at%x1f%s"],
               cwd=root) or ""
    rows = []
    head = (_git(["rev-parse", "HEAD"], cwd=root) or "").strip()
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 5:
            continue
        h, short, author, at, msg = parts
        rows.append({"hash": h, "short": short, "author": author,
                     "date": int(at) if at.isdigit() else 0,
                     "message": msg, "isHead": h == head})
    return rows


