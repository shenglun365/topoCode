import os
from typing import Any

from ..ingredient import ContextIngredient


_FILE_TYPE_PATTERNS = [
    (["entry"], ["main.py", "main.ts", "index.ts", "index.js", "main.rs", "main.go"]),
    (["test"], ["/test/", "/tests/", ".test.", "_test.", ".spec."]),
    (["config"], ["/config/", "/settings/", "config.", "setting."]),
    (["api", "route"], ["/api/", "/route/", "/controller/", "Controller.", "Resource."]),
    (["utility"], ["/util/", "/helper/", "/utils/"]),
    (["model"], ["/model/", "/entity/", "/schema/"]),
]


def _classify_file(filepath: str) -> str:
    name = os.path.basename(filepath)
    for types, patterns in _FILE_TYPE_PATTERNS:
        for p in patterns:
            if p in filepath or name == p:
                return types[0]
    return "module"


class FileMetadataIngredient(ContextIngredient):
    """单文件的导出符号/导入/引用方/类型。"""
    name = "file_metadata"

    def collect(self, ctx) -> dict:
        fp = ctx.file_path
        if not fp:
            return {}
        result = {"type": _classify_file(fp)}
        if ctx.db:
            result["exports"] = [
                dict(r) for r in ctx.db.execute(
                    "SELECT name, kind FROM graph_node WHERE task_id=? AND file_path=? AND is_exported=1",
                    (ctx.task_id, fp)
                ).fetchall()
            ]
            result["imports"] = [
                r[0] for r in ctx.db.execute(
                    "SELECT name FROM graph_node WHERE task_id=? AND file_path=? AND kind='import'",
                    (ctx.task_id, fp)
                ).fetchall()
            ]
            result["callers"] = [
                r[0] for r in ctx.db.execute(
                    """SELECT DISTINCT gn.file_path FROM graph_edge ge
                       JOIN graph_node gn ON gn.id = ge.source_id AND gn.task_id = ge.task_id
                       WHERE ge.task_id=? AND ge.kind IN ('calls','imports')
                         AND ge.target_id IN (
                            SELECT id FROM graph_node WHERE task_id=? AND file_path=?
                         ) LIMIT 5""",
                    (ctx.task_id, ctx.task_id, fp)
                ).fetchall()
            ]
        return result

    def format(self, data: dict) -> str:
        parts = []
        ft = data.get("type", "module")
        parts.append(f"[类型] {ft}")

        exports = data.get("exports", [])
        if exports:
            items = [f"{r['name']}({r['kind']})" for r in exports[:10]]
            parts.append(f"[导出] {', '.join(items)}")

        imports = data.get("imports", [])
        if imports:
            parts.append(f"[导入] {', '.join(imports[:15])}")

        callers = data.get("callers", [])
        if callers:
            rels = [os.path.relpath(r, "/") for r in callers]  # simplified
            parts.append(f"[引用方] {'; '.join(rels)}")

        return "\n".join(parts)
