"""core_pid.py — 仓库 root → KB core 项目 id 解析(自 symbols.py 拆分, §8.2)。

- 签名(.topocode/proj-id)优先; DB 反查兜底走三锚点 root_path/local_repo_path/
  remote_url(列感知拼接, 测试/旧库缺列自动回退) —— git-local 导入项目
  root_path=镜像 worktree, 原始根只在后两者, 只按 root_path 反查必漏。
- TTL 300s 缓存; 失效经 symbols.invalidate_native_cache(共享同一 dict)。
"""
from __future__ import annotations

import os
import sqlite3
import time
from typing import Optional

_core_pid_cache = {}  # root -> (core_pid|None, ts)
_PID_TTL = 300.0


def ctx_data_dir() -> str:
    try:
        from .. import ctx
        return ctx.data_dir()
    except Exception:
        return os.path.join(os.path.expanduser("~"), ".topocode")


def _core_data_dir() -> str:
    return os.environ.get("TOPOCODE_DB_DIR") or ctx_data_dir()


def _resolve_core_pid(root: Optional[str]):
    """仓库 root → core 注册表项目 id。签名优先，root_path 反查兜底。无 → None。TTL 300s。"""
    if not root:
        return None
    now = time.time()
    hit = _core_pid_cache.get(root)
    if hit and now - hit[1] < _PID_TTL:
        return hit[0]
    pid = None
    try:
        sig = os.path.join(root, ".topocode", "proj-id")
        if os.path.isfile(sig):
            with open(sig, 'r', encoding='utf-8') as f:
                pid = f.read().strip() or None
    except Exception:
        pid = None
    if not pid:
        try:
            db = os.path.join(_core_data_dir(), "topoone.db")
            if os.path.isfile(db):
                c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
                try:
                    # 三锚点(与 KB baseline_readiness._project_by_root 同口径):
                    # git-local 导入项目 root_path=镜像 worktree, 原始根在
                    # local_repo_path/remote_url —— 只按 root_path 反查必漏。
                    # 锚点列按实际 schema 拼接(测试/旧库可能缺列)。
                    a = os.path.abspath(root)
                    cols = {r[1] for r in c.execute("PRAGMA table_info(projects)")}
                    conds = ["root_path=?"]
                    params = [a]
                    for col in ("local_repo_path", "remote_url"):
                        if col in cols:
                            conds.append(f"{col}=?")
                            params.append(a)
                    r = c.execute(
                        f"SELECT id FROM projects WHERE {' OR '.join(conds)} "
                        "ORDER BY CASE WHEN root_path=? THEN 0 ELSE 1 END LIMIT 1",
                        tuple(params) + (a,)).fetchone()
                    pid = r[0] if r else None
                finally:
                    c.close()
        except Exception:
            pid = None
    _core_pid_cache[root] = (pid, now)
    return pid
