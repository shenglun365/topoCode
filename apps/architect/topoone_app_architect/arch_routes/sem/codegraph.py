"""semantic_assets 拆分模块（A1 修正：纯移动，逻辑零改动）。

原 semantic_assets.py 5555 行 god-file 按段拆出；本模块由构建脚本生成段内容，
跨模块引用为显式 import。每步拆分均跑 28 个后端测试文件保护。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from .. import store
from .. import ctx
from ..common import _ts, err, ok  # noqa: F401

logger = logging.getLogger(__name__)

from .taxonomy import _NODE_COLS
from .paths import _norm_path


# ── codegraph 适配器 ──────────────────────────────────────────

def cg_dir(root: str) -> Optional[str]:
    """定位项目 codegraph 索引目录(.codegraph/)。"""
    if not root or not os.path.isdir(root):
        return None
    d = os.path.join(root, ".codegraph")
    if os.path.isdir(d) and os.path.isfile(os.path.join(d, "codegraph.db")):
        return d
    return None


# ── 识别 + 手动开关（env ARCH_CODEGRAPH > main_db KV > auto） ─────────
_KV_KEY = 'arch.codegraph.mode'
_cli_cache = None      # (path|None, ts)
_mode_cache = None     # (mode, ts)


def codegraph_cli():
    """codegraph CLI 可用性识别(进程级缓存 TTL 300s，避免反复探测)。"""
    global _cli_cache
    now = time.time()
    if _cli_cache and now - _cli_cache[1] < 300:
        return _cli_cache[0]
    p = shutil.which('codegraph')
    _cli_cache = (p, now)
    return p


def codegraph_status() -> dict:
    p = codegraph_cli()
    return {'cli': bool(p), 'cliPath': p or ''}


def ensure_arch_settings_table() -> None:
    ctx.db().execute("CREATE TABLE IF NOT EXISTS arch_settings("
                     "key TEXT PRIMARY KEY, value TEXT)")


def kv_mode():
    try:
        row = ctx.db().fetchone("SELECT value FROM arch_settings WHERE key=?", (_KV_KEY,))
        v = (row or {}).get('value')
        return v if v in ('on', 'off', 'auto') else None
    except Exception:
        return None


def set_kv_mode(mode: str) -> bool:
    if mode not in ('on', 'off', 'auto'):
        return False
    ensure_arch_settings_table()
    d = ctx.db()
    d.execute("INSERT INTO arch_settings(key, value) VALUES(?,?) "
              "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (_KV_KEY, mode))
    try:
        d.conn.commit()
    except Exception:
        pass
    global _mode_cache
    _mode_cache = None
    return True


def effective_mode() -> str:
    global _mode_cache
    now = time.time()
    if _mode_cache and now - _mode_cache[1] < 30:
        return _mode_cache[0]
    env = os.environ.get('ARCH_CODEGRAPH', '').strip().lower()
    mode = env if env in ('on', 'off', 'auto') else (kv_mode() or 'auto')
    _mode_cache = (mode, now)
    return mode


def ensure_synced(root: str, timeout: int = 90) -> bool:
    """确保 codegraph 索引存在且保鲜。

    未初始化时自动 `codegraph init`(init 自带首建索引，给更长超时)；
    仍失败 → 返回 False(调用方降级 AST 缓存/live 扫描，不阻塞提取)。
    """
    mode = effective_mode()
    if mode == 'off':
        return False                      # 手动关闭：零 subprocess，不触碰用户项目目录
    if codegraph_cli() is None:
        if mode == 'on':
            logger.warning("[semantic] codegraph 显式开启但 CLI 缺失: %s", root)
        return False                      # CLI 缺失：缓存期内不再反复探测
    if not root or not os.path.isdir(root):
        return False

    def _initialized() -> bool:
        try:
            r = subprocess.run(["codegraph", "status", "-j", root],
                               capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0:
                data = json.loads(r.stdout or "{}") if (r.stdout or "").strip() else {}
                return bool(data.get("initialized"))
        except Exception as e:
            logger.warning("[semantic] codegraph status 失败: %s", e)
        return False

    if not _initialized():
        # 此前只检查不建：首次提取永远走降级路径(degraded 误报)。现在自动补建。
        try:
            logger.info("[semantic] codegraph 未初始化，自动 init(首建索引): %s", root)
            subprocess.run(["codegraph", "init", root],
                           capture_output=True, text=True,
                           timeout=max(timeout * 3, 300))
        except Exception as e:
            logger.warning("[semantic] codegraph init 失败: %s", e)
            return False
        if not _initialized():
            logger.warning("[semantic] codegraph init 后仍未初始化: %s", root)
            return False
    try:
        subprocess.run(["codegraph", "sync", "-q", root],
                       capture_output=True, text=True, timeout=timeout)
    except Exception:
        logger.warning("[semantic] codegraph sync failed (best-effort)")
    return True


def _open_cg(root: str) -> Optional[sqlite3.Connection]:
    d = cg_dir(root)
    if not d:
        return None
    try:
        conn = sqlite3.connect(f"file:{os.path.join(d, 'codegraph.db')}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.warning("[semantic] open codegraph.db failed: %s", e)
        return None


def _query_nodes(conn: sqlite3.Connection, files: Optional[List[str]] = None,
                 symbols: Optional[List[str]] = None, limit: int = 400) -> List[dict]:
    """查询符号节点。files 为相对路径(正斜杠)；symbols 按 name/qualified_name 匹配。"""
    conds, params = [], []
    if files:
        fs = [_norm_path(f) for f in files if f][:200]
        if fs:
            ph = ",".join("?" * len(fs))
            conds.append(f"file_path IN ({ph})")
            params += fs
    if symbols:
        sym_conds, sym_params = [], []
        for s in symbols[:60]:
            sym_conds.append("(name = ? OR qualified_name = ?)")
            sym_params += [s, s]
        conds.append("(" + " OR ".join(sym_conds) + ")")
        params += sym_params
    if not conds:
        conds.append("1=1")
    sql = (
        f"SELECT {_NODE_COLS} FROM nodes "
        f"WHERE ({' AND '.join(conds)}) AND kind NOT IN ('file','import') "
        f"ORDER BY file_path, start_line LIMIT ?"
    )
    params.append(int(limit))
    try:
        rows = [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]
        if files and fs and not rows:
            logger.warning("[semantic] codegraph 未匹配到任何节点: 请求文件 %d 个(如 %s)，"
                           "codegraph file_path 可能是绝对路径/格式不同。"
                           "样例 codegraph file_path: %s",
                           len(fs), fs[:3], _cg_sample_paths(conn))
        return rows
    except Exception as e:
        logger.warning("[semantic] query nodes failed: %s", e, exc_info=True)
        return []


def _cg_sample_paths(conn: sqlite3.Connection, limit: int = 5) -> list:
    """取 codegraph 里实际存储的 file_path 样例，辅助诊断相对/绝对路径差异。"""
    try:
        rows = conn.execute(
            "SELECT DISTINCT file_path FROM nodes WHERE file_path IS NOT NULL AND file_path != '' "
            "ORDER BY file_path LIMIT ?", (limit,)).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def _query_edges(conn: sqlite3.Connection, node_ids: List[str], limit: int = 3000) -> List[dict]:
    ids = list(dict.fromkeys(node_ids))[:1500]
    if not ids:
        return []
    ph = ",".join("?" * len(ids))
    try:
        rows = conn.execute(
            f"SELECT source, target, kind, line, col FROM edges "
            f"WHERE (source IN ({ph}) OR target IN ({ph})) "
            f"AND kind IN ('calls','contains','extends','imports','references','instantiates') "
            f"LIMIT ?",
            tuple(ids + ids + [int(limit)]),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("[semantic] query edges failed: %s", e)
        return []


