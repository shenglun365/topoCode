"""符号详情与 AI 解读缓存(链路跟踪符号卡配套)。

symbol_detail: 符号库元数据 + 代码段切片(链路符号节点点击 → 代码资产卡·符号形态);
symbol_note_*: AI 解读缓存表 arch_symbol_notes——生成 grounded 于真实代码段,
同步单次, 结果落库跨会话复用。
"""
from __future__ import annotations

import os
from typing import Optional

from .paths import project_id_for, resolve_root
from .symbols import close_symbol_conn, open_symbol_conn


def _now() -> int:
    import time
    return int(time.time() * 1000)


SNIPPET_MAX_LINES = 200   # 符号代码段切片上限(超长截断)


def _read_snippet(root: Optional[str], file: str, start: int, end: int) -> str:
    """文件行区间切片(1-based; 容错越界/缺失; 上限截断)。"""
    if not root or not file:
        return ""
    path = os.path.join(root, file)
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:  # noqa: BLE001
        return ""
    s = max(1, int(start or 1))
    e = min(len(lines), int(end or s) if end else s, s + SNIPPET_MAX_LINES - 1)
    return "".join(lines[s - 1:e])


def _sym_meta(conn, symbol: str) -> Optional[dict]:
    """符号 → 节点元数据(qualified_name 优先, 其次 name 精确)。"""
    try:
        row = conn.execute(
            "SELECT id, kind, name, qualified_name, file_path, start_line, end_line "
            "FROM nodes WHERE qualified_name = ? OR name = ? ORDER BY qualified_name LIMIT 1",
            (symbol, symbol)).fetchone()
    except Exception:  # noqa: BLE001
        return None
    if not row:
        return None
    return {"id": row[0], "kind": row[1] or "", "name": row[2] or symbol,
            "qualifiedName": row[3] or symbol, "file": row[4] or "",
            "startLine": int(row[5] or 0), "endLine": int(row[6] or 0)}


def symbol_detail(root: Optional[str], project: Optional[str], symbol: str) -> dict:
    """符号详情(代码资产卡·符号形态)：元数据 + 代码段切片 + AI 解读缓存。"""
    pid = project_id_for(root, project)
    if not pid:
        return {"error": "缺少项目"}
    conn, _src = open_symbol_conn(resolve_root(root, project), project)
    try:
        if conn is None:
            return {"error": "符号库不可用"}
        meta = _sym_meta(conn, (symbol or "").strip())
    finally:
        if conn is not None:
            close_symbol_conn(conn)
    if not meta:
        return {"error": "符号未找到"}
    snippet = _read_snippet(resolve_root(root, project), meta["file"],
                            meta["startLine"], meta["endLine"])
    note = symbol_note_get(pid, meta["qualifiedName"])
    return {"symbol": meta["qualifiedName"], "meta": meta, "snippet": snippet,
            "note": note}


# ---- AI 解读缓存(arch_symbol_notes: 符号级解读落库, 跨会话复用) ----

def symbol_note_get(pid: str, symbol_key: str) -> str:
    from ..store.base import _fetchall_routed
    rows, _ = _fetchall_routed(
        "arch_symbol_notes",
        "SELECT note FROM arch_symbol_notes WHERE project_id = ? AND symbol_key = ?",
        (pid, symbol_key), pid or None)
    return (rows[0]["note"] or "") if rows else ""


def symbol_note_put(pid: str, symbol_key: str, note: str) -> None:
    from ..store.base import _get, _insert, _update
    rid = f"sn-{abs(hash(f'{pid}|{symbol_key}')) % 10 ** 12:012d}"
    payload = {"note": (note or "").strip(), "updatedAt": _now()}
    if _get("arch_symbol_notes", rid):
        _update("arch_symbol_notes", rid, payload)
    else:
        _insert("arch_symbol_notes", {
            "id": rid, "projectId": pid, "symbolKey": symbol_key,
            "note": payload["note"], "createdAt": _now(), "updatedAt": _now()})


def symbol_note_generate(root: Optional[str], project: Optional[str],
                         symbol: str, model_id: Optional[str] = None) -> dict:
    """符号 AI 解读(同步单次, ≤120 字, grounded 于真实代码段)；结果落缓存。"""
    detail = symbol_detail(root, project, symbol)
    if detail.get("error"):
        return detail
    meta = detail["meta"]
    snippet = detail.get("snippet") or ""
    note = ""
    if snippet:
        try:
            from ..agent.tools.req_agent import get_max_tokens_preference
            from ..agent.turns.catalog import catalog_call
            sys_prompt = ("你是资深架构师。基于真实源码片段，用中文解读该符号『是什么/在做什么/"
                          "与谁协作』：必须引用源码中真实存在的符号名，贴着代码说。不超过 120 字。"
                          "只输出解读正文。")
            user_prompt = (f"符号: {meta['qualifiedName']} ({meta['kind']}, "
                           f"{meta['file']}:{meta['startLine']}-{meta['endLine']})\n\n"
                           f"真实源码片段:\n{snippet}\n\n请输出解读。")
            res = catalog_call("role:pseudo",
                               [{"role": "system", "content": sys_prompt},
                                {"role": "user", "content": user_prompt}],
                               max_tokens=get_max_tokens_preference(), model_id=model_id)
            note = (res.get("content") or "").strip() if res.get("ok") else ""
        except Exception:  # noqa: BLE001
            note = ""
    if note:
        pid = project_id_for(root, project)
        symbol_note_put(pid, meta["qualifiedName"], note)
        return {"note": note, "cached": False}
    cached = detail.get("note") or ""
    return {"note": cached, "cached": bool(cached), "degraded": not cached}
