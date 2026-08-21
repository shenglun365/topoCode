"""资产提取专用只读工具 —— 全部返回 AST/缓存 ground truth，模型只抄不造。

上下文注入：`asset_extract` 在工具循环前 set_extraction_context(ctx)，
工具优先读内存上下文(快/准)；无上下文(如 req agent 直接调用)时降级读
arch_ast_cache + 源码。所有工具结果记入 facts(供验收溯源)。
"""
from __future__ import annotations

import re
import threading
from typing import Any, Dict, List, Optional

from .req_agent import register_architect_tool

_tl = threading.local()


def set_extraction_context(root: Optional[str], project: Optional[str],
                           ctx: Optional[dict]) -> None:
    _tl.root = root
    _tl.project = project
    _tl.ctx = ctx or {}
    _tl.facts = []


def clear_extraction_context() -> None:
    for k in ("root", "project", "ctx", "facts"):
        try:
            delattr(_tl, k)
        except AttributeError:
            pass


def record_fact(tool: str, args: dict, result: Any) -> Any:
    """记录工具结果(ground truth 溯源)并返回原结果。"""
    try:
        facts = getattr(_tl, "facts", None)
        if facts is not None:
            facts.append({"tool": tool, "args": args, "result": result})
    except Exception:
        pass
    return result


def _ctx() -> dict:
    return getattr(_tl, "ctx", None) or {}


def _impl(file_: str) -> dict:
    """implDetails(内存优先 → arch_ast_cache 降级)。"""
    impls = _ctx().get("implDetails") or {}
    if file_ in impls:
        return impls[file_] or {}
    try:
        from . import store
        from .semantic_assets import project_id_for
        pid = project_id_for(getattr(_tl, "root", None), getattr(_tl, "project", None))
        row = store.AstCacheStore.get(pid, file_) if pid else None
        if row:
            return {"statements": row.get("statements") or [],
                    "routes": row.get("routes") or [],
                    "constants": row.get("constants") or []}
    except Exception:
        pass
    return {}


def _nodes() -> List[dict]:
    return _ctx().get("nodes") or []


def _find_node(file_: str, symbol: str) -> Optional[dict]:
    sym = (symbol or "").strip()
    tail = re.split(r"::|\.", sym)[-1]
    for n in _nodes():
        if (n.get("file_path") or "") != (file_ or ""):
            continue
        if sym in (n.get("name"), n.get("qualified_name")) or tail == (n.get("name") or ""):
            return n
    # 无文件约束的兜底
    for n in _nodes():
        if sym in (n.get("name"), n.get("qualified_name")) or tail == (n.get("name") or ""):
            return n
    return None


def _read_source(root: Optional[str], rel: str, start: int, end: int,
                 max_lines: int = 120) -> str:
    import os
    if not root:
        return ""
    full = os.path.join(root, (rel or "").lstrip("/").replace("/", os.sep))
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().split("\n")
    except Exception:
        return ""
    s0 = max(1, int(start or 1))
    s1 = max(s0, int(end or s0))
    body = lines[s0 - 1:s1]
    if len(body) <= 2 and s1 - s0 < 3:
        body = lines[s0 - 1:s0 - 1 + 80]
    return "\n".join(body[:max_lines])


@register_architect_tool(
    "asset.read_source",
    "读取某符号的源码切片(类体/函数体)。补齐 entity 字段时使用。"
    "参数: file(相对路径), symbol(符号名), max_lines(可选,默认120)",
)
def tool_asset_read_source(root: Optional[str], project: Optional[str],
                           file: str, symbol: str,
                           max_lines: int = 120) -> Dict[str, Any]:
    node = _find_node(file, symbol)
    if node is None:
        return {"error": f"符号未找到: {symbol} @ {file}"}
    src = _read_source(getattr(_tl, "root", None) or root, file,
                       node.get("start_line") or 0, node.get("end_line") or 0,
                       max_lines)
    return record_fact("asset.read_source", {"file": file, "symbol": symbol}, {
        "file": file, "symbol": symbol,
        "startLine": int(node.get("start_line") or 0),
        "endLine": int(node.get("end_line") or 0), "source": src})


@register_architect_tool(
    "asset.query_constants",
    "查询某文件的常量值清单(name=value+行号)。补齐 rule 约束时使用。参数: file",
)
def tool_asset_query_constants(root: Optional[str], project: Optional[str],
                               file: str) -> Dict[str, Any]:
    cons = _impl(file).get("constants") or []
    return record_fact("asset.query_constants", {"file": file},
                       {"file": file, "constants": cons[:50]})


@register_architect_tool(
    "asset.query_calls",
    "查询某符号的行序直接调用链(被调符号名+行号)。补齐 process steps 时使用。"
    "参数: file, symbol",
)
def tool_asset_query_calls(root: Optional[str], project: Optional[str],
                           file: str, symbol: str) -> Dict[str, Any]:
    from .asset_rules import RuleContext
    node = _find_node(file, symbol)
    if node is None:
        return {"error": f"符号未找到: {symbol} @ {file}"}
    node_by_id = {n.get("id"): n for n in _nodes()}
    rc = RuleContext(_ctx().get("edges") or [], _ctx().get("implDetails") or {},
                     node_by_id)
    out = []
    for ln, _i, t in rc.callees_of(node):
        if t:
            out.append({"symbol": t.get("qualified_name") or t.get("name"),
                        "line": ln if ln < (1 << 29) else None,
                        "file": t.get("file_path") or ""})
    return record_fact("asset.query_calls", {"file": file, "symbol": symbol},
                       {"file": file, "symbol": symbol, "calls": out[:20]})


@register_architect_tool(
    "asset.query_routes",
    "查询某文件的框架 API 路由清单(path/methods/handler/line/framework)。"
    "补齐 contract relations 时使用。参数: file",
)
def tool_asset_query_routes(root: Optional[str], project: Optional[str],
                            file: str) -> Dict[str, Any]:
    routes = _impl(file).get("routes") or []
    return record_fact("asset.query_routes", {"file": file},
                       {"file": file, "routes": routes[:50]})


@register_architect_tool(
    "asset.query_symbol",
    "查询符号的 AST 信息(kind/签名/docstring/返回类型/行号)。参数: file, symbol",
)
def tool_asset_query_symbol(root: Optional[str], project: Optional[str],
                            file: str, symbol: str) -> Dict[str, Any]:
    node = _find_node(file, symbol)
    if node is None:
        return {"error": f"符号未找到: {symbol} @ {file}"}
    return record_fact("asset.query_symbol", {"file": file, "symbol": symbol}, {
        "file": file, "symbol": symbol, "kind": node.get("kind") or "",
        "signature": node.get("signature") or "",
        "docstring": (node.get("docstring") or "").strip()[:400],
        "returnType": node.get("return_type") or "",
        "startLine": int(node.get("start_line") or 0),
        "endLine": int(node.get("end_line") or 0)})
