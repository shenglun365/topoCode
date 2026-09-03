"""符号源双后端：codegraph(外部 CLI，可选) vs native(core 分析库原生 AST)。

质量持平设计：native 后端用 TEMP 视图把 core 分析库(project.db)的
graph_node/graph_edge 映射为下游同构符号模型(nodes/edges，contains 由
同文件行区间推导)，上游 _query_nodes/_query_edges/_cg_* 全部零改动复用。
桥接：architect 仓库 root → core 注册表项目 id（.topocode/proj-id 签名优先，
否则 core 主库 projects.root_path 反查）→ {core_data_dir}/projects/{core_pid}/project.db
（注意：不是 architect 侧的 arch.db——arch.db 无符号表）。
开关：env ARCH_CODEGRAPH(on|off|auto) > main_db KV > auto（见 codegraph.py）。
变更跟踪：symbol_source_state() 只识别变更范围(HEAD/dirty vs 跟踪 KV)，不实时解析；
基线变更(含 AST 重析/社区重划分)由 KB 知识库管理执行，architect 仅提示+手动触发。
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from typing import Optional, Tuple

from . import codegraph as _cg_mod
from .codegraph import effective_mode, logger

_native_cache = {}   # core_pid -> (conn, ts)
_state_cache = {}    # root -> (state, ts)
_core_pid_cache = {} # root -> (core_pid|None, ts)
_diff_cache = {}     # root -> (diff, ts)
_NATIVE_TTL = 300.0
_STATE_TTL = 60.0
_PID_TTL = 300.0
_STATE_KV_KEY = "arch.symbolSource."   # + core_pid


def _core_data_dir() -> str:
    return os.environ.get("TOPOCODE_DB_DIR") or ctx_data_dir()


def ctx_data_dir() -> str:
    try:
        from .. import ctx
        return ctx.data_dir()
    except Exception:
        return os.path.join(os.path.expanduser("~"), ".topocode")


def _git(root: str, args: list, timeout: float = 20.0):
    """只读 git 命令；失败返回 None。"""
    try:
        p = subprocess.run(['git', '-C', root] + list(args),
                           capture_output=True, text=True, timeout=timeout)
        return p.stdout if p.returncode == 0 else None
    except Exception:
        return None


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
                    r = c.execute("SELECT id FROM projects WHERE root_path=?",
                                  (os.path.abspath(root),)).fetchone()
                    pid = r[0] if r else None
                finally:
                    c.close()
        except Exception:
            pid = None
    _core_pid_cache[root] = (pid, now)
    return pid


def _open_core_conn(core_pid: str):
    """core 分析库只读连接 + TEMP 同构视图（按 core_pid 缓存 300s）。失败 None。

    视图映射（下游 snake_case 符号模型）：
    - nodes ← graph_node（qualified_name/file_path/start_line/…；return_type 空占位）
    - edges ← graph_edge（type_of→references；metadata 缺省时按 provenance 注入证据）
      UNION edges_contains（class 行区间包住 method/function，物化 TEMP 表）
    """
    now = time.time()
    hit = _native_cache.get(core_pid)
    if hit and now - hit[1] < _NATIVE_TTL:
        return hit[0]
    db = os.path.join(_core_data_dir(), "projects", core_pid, "project.db")
    if not os.path.isfile(db):
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
        conn.execute("CREATE TEMP VIEW IF NOT EXISTS nodes AS SELECT "
                     "id, kind, name, qualified_name, file_path, "
                     "start_line, end_line, start_col AS start_column, end_col AS end_column, "
                     "signature, docstring, '' AS return_type "
                     "FROM graph_node")
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS edges_contains "
                     "(source TEXT, target TEXT, kind TEXT, line INTEGER, col INTEGER, metadata TEXT)")
        conn.execute("DELETE FROM edges_contains")
        conn.execute("INSERT INTO edges_contains "
                     "SELECT c.id, m.id, 'contains', m.start_line, m.start_col, '' "
                     "FROM graph_node c JOIN graph_node m ON c.file_path = m.file_path AND c.id != m.id "
                     "WHERE c.kind = 'class' AND m.kind IN ('method', 'function') "
                     "AND m.start_line >= c.start_line AND m.end_line <= c.end_line")
        conn.execute("CREATE TEMP VIEW IF NOT EXISTS edges AS SELECT "
                     "source_id AS source, target_id AS target, "
                     "CASE kind WHEN 'type_of' THEN 'references' ELSE kind END AS kind, "
                     "line, col, "
                     "CASE WHEN metadata IS NULL OR metadata = '' THEN "
                     "json_object('confidence', CASE provenance WHEN 'parser' THEN 'exact' ELSE 'heuristic' END, "
                     "'resolvedBy', 'native-ast') ELSE metadata END AS metadata "
                     "FROM graph_edge "
                     "UNION ALL SELECT source, target, kind, line, col, metadata FROM edges_contains")
        _native_cache[core_pid] = (conn, now)
        return conn
    except Exception as e:
        logger.warning("[semantic] native 符号源打开失败(core=%s): %s", core_pid, e)
        return None


def _open_native(root: Optional[str], project: Optional[str]) -> Optional[sqlite3.Connection]:
    """core 分析库符号源入口：root → core_pid → 只读连接。任何失败 → None（降级路径）。"""
    try:
        pid = _resolve_core_pid(root)
        if not pid:
            return None
        return _open_core_conn(pid)
    except Exception as e:
        logger.warning("[semantic] native 符号源打开失败: %s", e)
        return None


def invalidate_native_cache() -> None:
    """基线同步/测试后清空 native 连接与 pid 缓存。"""
    for k, v in list(_native_cache.items()):
        try:
            v[0].close()
        except Exception:
            pass
    _native_cache.clear()
    _core_pid_cache.clear()
    _state_cache.clear()


def _read_state_kv(core_pid: str) -> dict:
    try:
        from .. import ctx
        row = ctx.db().fetchone(
            "SELECT value FROM arch_settings WHERE key=?", (_STATE_KV_KEY + core_pid,))
        v = (row or {}).get('value')
        return json.loads(v) if v else {}
    except Exception:
        return {}


def _write_state_kv(core_pid: str, head: str) -> None:
    try:
        from .. import ctx
        from .codegraph import ensure_arch_settings_table
        ensure_arch_settings_table()
        val = json.dumps({'lastHead': head, 'lastSyncAt': time.time()},
                         ensure_ascii=False)
        ctx.db().execute(
            "INSERT INTO arch_settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (_STATE_KV_KEY + core_pid, val))
    except Exception as e:
        logger.warning("[semantic] 符号源跟踪状态写入失败: %s", e)


def symbol_source_state(root: Optional[str], project: Optional[str] = None) -> dict:
    """符号源状态 + 变更范围识别（只识别范围，不实时解析）。TTL 60s。

    返回 {mode, source, corePid, head, lastHead, dirty, stale, staleFiles}：
    - stale：HEAD 相对上次同步的 commit 发生变化（前进或回滚）
    - staleFiles：lastHead..HEAD 的变更文件清单（cap 500）；无 lastHead 时为空
    - dirty：工作区未提交文件数（未提交不入基线，仅提示）
    """
    now = time.time()
    hit = _state_cache.get(root or '')
    if hit and now - hit[1] < _STATE_TTL:
        return hit[0]
    mode = effective_mode()
    conn, source = open_symbol_conn(root, project)
    pid = _resolve_core_pid(root)
    head_out = _git(root, ['rev-parse', 'HEAD']) if root else None
    head = head_out.strip() if head_out else ''
    dirty = 0
    stale_files: list = []
    stale = False
    last_head = ''
    if pid:
        last_head = (_read_state_kv(pid) or {}).get('lastHead') or ''
    if root and head:
        out = _git(root, ['status', '--porcelain'])
        if out is not None:
            dirty = len([l for l in out.splitlines() if l.strip()])
        if last_head and last_head != head:
            stale = True
            diff = _git(root, ['diff', '--name-only', f'{last_head}..{head}', '--'])
            if diff:
                stale_files = [l for l in diff.splitlines() if l.strip()][:500]
        elif not last_head:
            # 尚无同步记录：视为待首次基线对齐（不标 stale，避免误导；由 UI 显示“未对齐”）
            pass
    state = {
        'mode': mode, 'source': source, 'corePid': pid or '',
        'head': head, 'lastHead': last_head,
        'dirty': dirty, 'stale': stale, 'staleFiles': stale_files,
        'nativeAvailable': conn is not None and source == 'native',
    }
    _state_cache[root or ''] = (state, now)
    return state


def record_sync(core_pid: str, head: str) -> None:
    """基线同步完成后记录跟踪状态（head 对齐）。"""
    _write_state_kv(core_pid, head)
    invalidate_native_cache()
    _diff_cache.clear()


def _git_name_status(root: str, base: str) -> dict:
    """git diff --name-status base..HEAD → {added,modified,deleted}（已提交漂移）。"""
    res = {'added': [], 'modified': [], 'deleted': []}
    out = _git(root, ['diff', '--name-status', f'{base}..HEAD', '--'])
    if not out:
        return res
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split('\t', 1)
        if len(parts) < 2:
            continue
        st, path = parts[0].strip(), parts[1].strip()
        if st.startswith('A'):
            res['added'].append(path)
        elif st.startswith('D'):
            res['deleted'].append(path)
        elif st[:1] in ('M', 'R', 'C', 'T'):
            res['modified'].append(path)
    return res


def _git_porcelain_status(root: str) -> dict:
    """git status --porcelain → {added,modified,deleted}（工作区未提交）。"""
    res = {'added': [], 'modified': [], 'deleted': []}
    out = _git(root, ['status', '--porcelain'])
    if not out:
        return res
    for line in out.splitlines():
        if len(line) < 4:
            continue
        x, y, path = line[0], line[1], line[3:].strip()
        if ' -> ' in path:
            path = path.split(' -> ')[-1].strip()
        if x == '?' and y == '?':
            res['added'].append(path)
            continue
        st = x if x not in (' ',) else y
        if st == 'A':
            res['added'].append(path)
        elif st == 'D':
            res['deleted'].append(path)
        elif st in ('M', 'R', 'C', 'T'):
            res['modified'].append(path)
    return res


def baseline_diff(root: Optional[str], project: Optional[str] = None,
                  cap: int = 500) -> dict:
    """基线(lastHead) → 工作区 的变更文件集（分类 added/modified/deleted）。TTL 60s。

    三视图 diff 数据源：files = 已提交漂移(lastHead..HEAD) ∪ 工作区未提交，
    按路径去重、工作区态优先。core 侧图谱/语义资产无版本快照，故 diff 以
    「变更文件集 × 当前资产/节点文件引用」叠加，而非历史版本对比。
    返回 {head,lastHead,stale,aligned,dirty,files:{added,modified,deleted},counts}。
    """
    now = time.time()
    ck = root or ''
    hit = _diff_cache.get(ck)
    if hit and now - hit[1] < _STATE_TTL:
        return hit[0]
    head_out = _git(root, ['rev-parse', 'HEAD']) if root else None
    head = head_out.strip() if head_out else ''
    pid = _resolve_core_pid(root)
    last_head = ((_read_state_kv(pid) or {}).get('lastHead') or '') if pid else ''
    if root and last_head and last_head != head:
        committed = _git_name_status(root, last_head)
    else:
        committed = {'added': [], 'modified': [], 'deleted': []}
    worktree = _git_porcelain_status(root) if root else {'added': [], 'modified': [], 'deleted': []}
    cat = {}  # path -> 类别（工作区覆盖已提交）
    for src in (committed, worktree):
        for k in ('added', 'modified', 'deleted'):
            for p in src[k]:
                cat[p] = k
    files = {'added': [], 'modified': [], 'deleted': []}
    for p, c in cat.items():
        if len(files[c]) < cap:
            files[c].append(p)
    for k in files:
        files[k].sort()
    diff = {
        'head': head, 'lastHead': last_head,
        'stale': bool(last_head) and last_head != head,
        'aligned': bool(last_head) and last_head == head,
        'dirty': sum(len(v) for v in worktree.values()),
        'files': files,
        'counts': {k: len(files[k]) for k in files},
    }
    _diff_cache[ck] = (diff, now)
    return diff


def open_symbol_conn(root: Optional[str], project: Optional[str]
                     ) -> Tuple[Optional[sqlite3.Connection], str]:
    """按有效模式返回 (只读符号库连接, source标签)。

    on   → 仅 codegraph（缺失 → (None, 'codegraph')，调用方按缺失降级）；
    off  → 仅 native（不触碰用户项目目录，零外部 CLI）；
    auto → codegraph 可用则用之，否则 native（质量持平，如实标注来源）。
    """
    mode = effective_mode()
    if mode in ('on', 'auto'):
        conn = _cg_mod._open_cg(root) if root else None
        if conn is not None:
            return conn, 'codegraph'
        if mode == 'on':
            return None, 'codegraph'
    native = _open_native(root, project)
    if native is not None:
        return native, 'native'
    return None, 'native'
