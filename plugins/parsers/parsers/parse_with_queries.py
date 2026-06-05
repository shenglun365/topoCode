"""Parse files using Tree-sitter queries and produce Symbol model + persistence

Flow:
  1. Detect language, get tree-sitter parser
  2. Parse source → AST
  3. Load QuerySet for the language (definitions, references, imports)
  4. Run queries → convert captures to Symbol/Reference/ImportRecord
  5. Build FileSymbolTable
  6. Resolve references via SimpleBinder
  7. Persist via SQLiteAdapter (graph_node + base_node)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from tree_sitter import Parser, Language

from parsers.language_loader import get_language, get_parser
from parsers.query_loader import QueryLoader, QuerySet
from parsers.symbol_model import (
    Symbol, Reference, ImportRecord, SourceLocation, FileSymbolTable,
    SymbolKind, RefKind,
)
from parsers.binder import SimpleBinder
from parsers.db_adapter import SQLiteAdapter

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE = 500 * 1024


def parse_with_queries(
    source_file_path: str,
    project_db,
    task_id: str,
    proj_path: str,
) -> int:
    """Parse a file using Tree-sitter queries and persist results.

    Args:
        source_file_path: Absolute path to the source file.
        project_db: SQLiteContext (project db connection).
        task_id: Analysis task ID.
        proj_path: Project root path.

    Returns:
        Number of symbols persisted, 0 on skip/failure, -1 on file too large.
    """
    logger.info(f"parse_with_queries: {source_file_path}")
    adapter = SQLiteAdapter(project_db, task_id)

    source_path = Path(source_file_path)
    if not source_path.exists():
        logger.error(f"File not found: {source_file_path}")
        return 0

    if source_path.stat().st_size > _MAX_FILE_SIZE:
        logger.warning(f"Skipping large file: {source_file_path}")
        return -1

    language_name = _detect_language(source_file_path)
    if not language_name:
        logger.warning(f"Unsupported language: {source_file_path}")
        return 0

    ts_language = get_language(language_name)
    if not ts_language:
        logger.warning(f"Tree-sitter language not available: {language_name}")
        return 0

    parser = get_parser(language_name)
    if not parser:
        logger.warning(f"Parser not available for: {language_name}")
        return 0

    src_content = source_path.read_bytes()
    tree = parser.parse(src_content)
    if not tree or not tree.root_node:
        logger.warning(f"Empty AST for: {source_file_path}")
        return 0

    qs = QueryLoader.load(language_name, ts_language)

    try:
        table = _build_symbol_table(tree, language_name, source_file_path, qs)
    except Exception as e:
        logger.exception(f"Failed to build symbol table for {source_file_path}: {e}")
        return 0

    if not table.symbols and not table.references and not table.imports:
        logger.info(f"No symbols found in {source_file_path}")
        return 0

    binder = SimpleBinder({table.file_path: table})
    for ref in table.references:
        result = binder.resolve(ref, file_path=table.file_path)
        if result and result.target:
            ref.target = f"{result.target.scope}.{result.target.name}"

    import os
    rel_path = os.path.relpath(source_file_path, proj_path)
    _persist_table(adapter, table, rel_path, language_name)

    logger.info(f"Parsed {len(table.symbols)} symbols, {len(table.references)} refs from {rel_path}")
    return len(table.symbols)


def _detect_language(file_path: str) -> Optional[str]:
    ext = Path(file_path).suffix.lower()
    ext_map = {
        ".ts": "typescript", ".tsx": "tsx", ".mts": "typescript", ".cts": "typescript",
        ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
        ".py": "python", ".pyw": "python",
        ".java": "java",
        ".c": "c", ".h": "c",
        ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hh": "cpp", ".hxx": "cpp",
        ".go": "go",
        ".rs": "rust",
        ".cs": "c_sharp",
        ".swift": "swift",
    }
    return ext_map.get(ext)


def _build_symbol_table(
    tree, language_name: str, file_path: str, qs: QuerySet,
) -> FileSymbolTable:
    """Run all three queries and convert captures to Symbol model."""
    root = tree.root_node
    table = FileSymbolTable(file_path=file_path, language=language_name)
    scope = "module"

    if qs.definitions:
        def_matches = QueryLoader.run_query(qs.definitions, root)
        for m in def_matches:
            sym = _match_to_symbol(m, file_path, language_name)
            if sym:
                table.add_symbol(sym)

    if qs.references:
        ref_matches = QueryLoader.run_query(qs.references, root)
        for m in ref_matches:
            ref = _match_to_reference(m, file_path, scope)
            if ref:
                table.add_reference(ref)

    if qs.imports:
        imports = _extract_imports(qs.imports, root, file_path)
        for imp in imports:
            table.add_import(imp)

    return table


def _match_to_symbol(match, file_path: str, language: str) -> Optional[Symbol]:
    """Convert a QueryMatch from definitions.scm into a Symbol."""
    name_node = (
        match.get("func.name")
        or match.get("class.name")
        or match.get("method.name")
        or match.get("var.name")
        or match.get("interface.name")
        or match.get("type_alias.name")
        or match.get("enum.name")
        or match.get("namespace.name")
        or match.get("prop_sig.name")
        or match.get("param.name")
        or match.get("opt_param.name")
        or match.get("ctor.name")
        or match.get("func_sig.name")
        or match.get("method_sig.name")
        or match.get("abs_method.name")
    )
    if not name_node:
        return None

    name = _node_text(name_node)
    if not name:
        return None

    kind = _detect_symbol_kind(match)

    def_node = match.get("func.def") or match.get("class.def") or match.get("method.def") or match.get("var.def") or match.get("interface.def") or match.get("type_alias.def") or match.get("enum.def") or match.get("namespace.def") or match.get("param.def") or match.get("prop_sig.def") or match.get("ctor.def") or match.get("func_sig.def") or match.get("method_sig.def") or match.get("abs_method.def") or match.get("arrow.def") or match.get("enum_member.def")
    location = _make_location(file_path, def_node or name_node)

    scope = "module"
    return Symbol(
        name=name,
        kind=kind,
        location=location,
        scope=scope,
    )


def _match_to_reference(match, file_path: str, scope: str) -> Optional[Reference]:
    """Convert a QueryMatch from references.scm into a Reference."""
    callee = match.get("call.callee")
    method = match.get("call.method")
    new_callee = match.get("new.callee")
    member_prop = match.get("member.prop")
    type_ref = match.get("type_ref.name")
    generic_ref = match.get("generic.name")
    ref_node = match.get("ref.name")
    assign_target = match.get("assign.target")
    return_val = match.get("return.value")

    if callee:
        kind = RefKind.CALL
        name = _node_text(callee)
        location = _make_location(file_path, callee)
    elif method:
        kind = RefKind.CALL
        name = _node_text(method)
        location = _make_location(file_path, method)
    elif new_callee:
        kind = RefKind.NEW
        name = _node_text(new_callee)
        location = _make_location(file_path, new_callee)
    elif member_prop:
        kind = RefKind.MEMBER
        name = _node_text(member_prop)
        location = _make_location(file_path, member_prop)
    elif type_ref:
        kind = RefKind.TYPE_REF
        name = _node_text(type_ref)
        location = _make_location(file_path, type_ref)
    elif generic_ref:
        kind = RefKind.TYPE_REF
        name = _node_text(generic_ref)
        location = _make_location(file_path, generic_ref)
    elif ref_node:
        kind = RefKind.IDENT
        name = _node_text(ref_node)
        location = _make_location(file_path, ref_node)
    elif assign_target:
        kind = RefKind.ASSIGN
        name = _node_text(assign_target)
        location = _make_location(file_path, assign_target)
    elif return_val:
        kind = RefKind.RETURN
        name = _node_text(return_val)
        location = _make_location(file_path, return_val)
    else:
        return None

    if not name:
        return None

    return Reference(name=name, kind=kind, location=location, scope=scope)


def _extract_imports(query, root_node, file_path: str) -> list[ImportRecord]:
    """Extract ImportRecords from imports query using flat captures dict.

    Different patterns in the .scm file produce captures under different
    pattern_indices in `query.matches()`, making per-match grouping impractical.
    Instead we use `query.captures()` (flat dict) and correlate by span.
    """
    from tree_sitter import Query, QueryCursor
    cursor = QueryCursor(query)
    cap_dict = cursor.captures(root_node)
    imports: list[ImportRecord] = []

    source_nodes = cap_dict.get("import.source", [])
    source_map = _build_span_index(source_nodes)

    name_nodes = cap_dict.get("import.name", [])
    default_nodes = cap_dict.get("import.default", [])
    ns_nodes = cap_dict.get("import.ns_name", [])
    alias_nodes = cap_dict.get("import.alias", [])
    export_source_nodes = cap_dict.get("export.source", [])
    dynamic_source_nodes = cap_dict.get("dynamic_import.source", [])
    require_source_nodes = cap_dict.get("require.source", [])

    for src_node in source_nodes:
        module = _node_text(src_node).strip("\"'")
        if not module:
            continue

        imported_names = []
        alias = None
        is_default = False
        is_namespace = False

        for n in name_nodes:
            if _is_descendant_of(n, src_node.parent if src_node.parent else src_node):
                imported_names.append(_node_text(n))

        alias_candidates = [a for a in alias_nodes if _is_descendant_of(a, src_node.parent if src_node.parent else src_node)]
        if alias_candidates:
            alias = _node_text(alias_candidates[0])

        for d in default_nodes:
            if _is_descendant_of(d, src_node.parent if src_node.parent else src_node):
                imported_names.append(_node_text(d))
                is_default = True

        for ns in ns_nodes:
            if _is_descendant_of(ns, src_node.parent if src_node.parent else src_node):
                imported_names.append(_node_text(ns))
                is_namespace = True

        if not imported_names:
            imported_names = ["*"]

        imports.append(ImportRecord(
            module=module,
            imported_names=imported_names,
            is_default=is_default,
            is_namespace=is_namespace,
            alias=alias,
        ))

    for src_node in export_source_nodes:
        module = _node_text(src_node).strip("\"'")
        if module:
            imports.append(ImportRecord(module=module, imported_names=["*"]))

    for src_node in dynamic_source_nodes:
        module = _node_text(src_node).strip("\"'")
        if module:
            imports.append(ImportRecord(module=module, imported_names=["*"]))

    for src_node in require_source_nodes:
        module = _node_text(src_node).strip("\"'")
        if module:
            imports.append(ImportRecord(module=module, imported_names=["*"]))

    return imports


def _build_span_index(nodes) -> dict:
    """Build a dict from start_byte to node for span lookup."""
    return {n.start_byte: n for n in nodes}


def _is_descendant_of(node, ancestor) -> bool:
    """Check if node is a descendant (or self) of ancestor by byte span."""
    if node is ancestor:
        return True
    if not node or not ancestor:
        return False
    return (
        ancestor.start_byte <= node.start_byte
        and node.end_byte <= ancestor.end_byte
    )


def _detect_symbol_kind(match) -> SymbolKind:
    if match.get("func.def") or match.get("func_sig.def") or match.get("arrow.def"):
        return SymbolKind.FUNCTION
    if match.get("class.def"):
        return SymbolKind.CLASS
    if match.get("method.def") or match.get("method_sig.def") or match.get("abs_method.def"):
        return SymbolKind.METHOD
    if match.get("ctor.def"):
        return SymbolKind.CONSTRUCTOR
    if match.get("var.def"):
        return SymbolKind.VARIABLE
    if match.get("interface.def"):
        return SymbolKind.INTERFACE
    if match.get("type_alias.def"):
        return SymbolKind.TYPE_ALIAS
    if match.get("enum.def") or match.get("enum_member.def"):
        return SymbolKind.ENUM
    if match.get("namespace.def"):
        return SymbolKind.MODULE
    if match.get("prop_sig.def"):
        return SymbolKind.PROPERTY
    if match.get("param.def") or match.get("opt_param.def"):
        return SymbolKind.PARAMETER
    return SymbolKind.VARIABLE


def _make_location(file_path: str, node) -> SourceLocation:
    return SourceLocation(
        file_path=file_path,
        start_byte=node.start_byte,
        end_byte=node.end_byte,
        start_line=node.start_point[0] + 1,
        start_col=node.start_point[1] + 1,
        end_line=node.end_point[0] + 1,
        end_col=node.end_point[1] + 1,
    )


def _node_text(node) -> str:
    try:
        return node.text.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _persist_table(
    adapter: SQLiteAdapter,
    table: FileSymbolTable,
    rel_path: str,
    language_name: str,
):
    """Write FileSymbolTable to graph_node via SQLiteAdapter."""
    file_info = adapter.get_file_by_path(rel_path)
    if not file_info:
        return
    file_id = file_info["id"]

    records = []
    for sym in table.symbols:
        loc = sym.location
        records.append({
            "symbol_node_type": "symbol",
            "file_id": file_id,
            "name": sym.name,
            "kind": sym.kind.value,
            "scope": sym.scope,
            "start_line": str(loc.start_line),
            "start_col": str(loc.start_col),
            "end_line": str(loc.end_line),
            "end_col": str(loc.end_col),
        })

    for ref in table.references:
        loc = ref.location
        records.append({
            "symbol_node_type": "reference",
            "file_id": file_id,
            "name": ref.name,
            "kind": ref.kind.value,
            "scope": ref.scope,
            "target": ref.target or "",
            "start_line": str(loc.start_line),
            "start_col": str(loc.start_col),
            "end_line": str(loc.end_line),
            "end_col": str(loc.end_col),
        })

    for imp in table.imports:
        loc = imp.location
        records.append({
            "symbol_node_type": "import",
            "file_id": file_id,
            "name": imp.module,
            "kind": "import",
            "scope": "module",
            "target": "",
            "start_line": str(loc.start_line) if loc else "0",
            "start_col": str(loc.start_col) if loc else "0",
            "end_line": str(loc.end_line) if loc else "0",
            "end_col": str(loc.end_col) if loc else "0",
        })

    if records:
        adapter.insert_graph(records)


def extract_dep_edges_from_imports(adapter: SQLiteAdapter) -> list[dict]:
    """从 graph_node 已有的 import 记录中提取依赖边 (新 Query 管线)

    parse_with_queries 已将导入记录写入 graph_node (symbol_node_type='import'),
    此函数读取并生成 dependence 记录供 community_analysis 使用.

    Args:
        adapter: SQLiteAdapter 实例

    Returns:
        依赖边列表
    """
    imports = adapter.find_graph(symbol_node_type='import')
    if not imports:
        return []

    dep_edges = []
    for imp in imports:
        dep_edges.append({
            "symbol_node_type": "dependence",
            "file_id": imp.get('file_id', ''),
            "include_path": imp.get('name', ''),
            "is_system": 0,
        })

    if dep_edges:
        adapter.insert_graph(dep_edges)
        logger.info(f"[extract_dep_edges_from_imports] 写入 {len(dep_edges)} 条依赖边")

    return dep_edges
