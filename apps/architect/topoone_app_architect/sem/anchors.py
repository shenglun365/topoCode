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
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from .. import store
from ..common import _ts, err, ok  # noqa: F401

logger = logging.getLogger(__name__)

from .taxonomy import _AST_KIND_MAP
from .paths import _norm_path


# ── AST 解析: LLM 符号引用 → 真实节点 ─────────────────────────

def resolve_ast_refs(symbols_in: Optional[List[str]], table: Dict[str, dict],
                     llm_refs: Optional[List[dict]] = None) -> List[dict]:
    """把符号引用解析为 AstNodeRef 列表(去重；优先真实节点行号)。"""
    refs: Dict[str, dict] = {}
    keys = set(symbols_in or [])
    for s in keys:
        node = table.get(s)
        if not node:
            continue
        refs[s] = _node_to_ref(node)
    for r in (llm_refs or []):
        if not isinstance(r, dict):
            continue
        file = _norm_path(r.get("file") or "")
        symbol = (r.get("symbol") or "").strip()
        if not symbol or not file:
            continue
        node = table.get(symbol)
        if node and node["file_path"] == file:
            refs[symbol] = _node_to_ref(node)
        elif symbol in refs:
            continue
        else:
            refs[symbol] = {"file": file, "symbol": symbol,
                            "kind": r.get("kind") or "func",
                            "startLine": int(r.get("startLine") or 0),
                            "endLine": int(r.get("endLine") or 0)}
    return list(refs.values())


def _node_to_ref(n: dict) -> dict:
    return {
        "file": n["file_path"],
        "symbol": n["qualified_name"] or n["name"],
        "kind": _AST_KIND_MAP.get(n.get("kind"), "func"),
        "startLine": int(n.get("start_line") or 0),
        "endLine": int(n.get("end_line") or 0),
    }


def _symbol_tail(sym: str) -> str:
    """提取符号尾段(处理 file::sym / Class::method / obj.method 形式)。"""
    s = (sym or "").strip()
    for sep in ("::", "."):
        if sep in s:
            s = s.split(sep)[-1]
    return s


def _node_index(table: Dict[str, dict]) -> Dict[str, list]:
    """节点表 → (尾段符号名, 归一化文件) → 节点列表 索引(宽容锚点解析用)。"""
    idx: Dict[str, list] = {}
    for node in table.values():
        key = _symbol_tail(node.get("qualified_name") or node.get("name") or "")
        f = _norm_path(node.get("file_path") or "")
        if key:
            idx.setdefault(key, []).append(node)
        if f:
            idx.setdefault(f"@{f}", []).append(node)
    return idx


def _resolve_symbol_node(sym: str, file: str, line: int,
                         table: Dict[str, dict],
                         idx: Optional[Dict[str, list]] = None) -> Optional[dict]:
    """宽容符号→AST 节点解析(供 LLM 锚点/启发式兜底)。

    命中策略(依次):
      1) table 精确匹配(原有行为)；
      2) 尾段符号名匹配(Class::method / obj.method → method)；
      3) 行号回退: 在指定文件内找 start_line<=line<=end_line 或最近的节点，
         优先函数/方法/路由(路由字符串 GET:/path 的 startLine 指向装饰器行时，
         取其后的函数定义节点)。
    """
    if sym:
        node = table.get(sym)
        if node:
            return node
        tail = _symbol_tail(sym)
        if tail and tail != sym:
            node = table.get(tail)
            if node:
                return node
        if idx and tail:
            for n in idx.get(tail, []):
                f = _norm_path(n.get("file_path") or "")
                if f and file and _norm_path(file) == f:
                    return n
            if len(idx.get(tail, [])) == 1:
                return idx[tail][0]
    # 行号回退: 同文件内找覆盖/最近的函数/方法/路由节点
    if file and idx:
        fnodes = sorted(
            (n for n in idx.get(f"@{_norm_path(file)}", [])
             if n.get("kind") in ("function", "method", "route")),
            key=lambda n: int(n.get("start_line") or 0),
        )
        if line > 0 and fnodes:
            # 装饰器行(@router.get)落在函数定义之前: 取 start_line>=line 的第一个
            nxt = next((n for n in fnodes if int(n.get("start_line") or 0) >= line), None)
            if nxt:
                return nxt
            for n in reversed(fnodes):
                if int(n.get("start_line") or 0) <= line:
                    return n
        elif fnodes:
            return fnodes[0]
    return None


def _attach_step_refs(detail: dict, table: Dict[str, dict]) -> None:
    """把步骤/分支里的 symbols[] 解析进对应 astRefs。"""
    for i, s in enumerate(detail.get("steps") or []):
        if isinstance(s, dict):
            s["astRefs"] = resolve_ast_refs(s.get("symbols"), table)
    for i, b in enumerate(detail.get("branches") or []):
        if isinstance(b, dict):
            b["astRefs"] = resolve_ast_refs(b.get("symbols"), table)


