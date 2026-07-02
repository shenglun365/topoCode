"""
符号查询工具 — 用于 LLM Agentic 工作流查询代码符号信息。
"""

import json
import logging
import os
from typing import Any, Optional

from ..tools import AgentTool, ToolResult

logger = logging.getLogger(__name__)


def _rel_path(path: str, project_root: Optional[str]) -> str:
    """将绝对路径转为相对路径（减少 LLM 上下文 token 开销）"""
    if project_root and os.path.isabs(path):
        try:
            return os.path.relpath(path, project_root)
        except ValueError:
            return path
    return path


class GetSymbolDetailTool(AgentTool):
    """获取指定符号的详细信息"""

    name = "get_symbol_detail"
    description = "获取指定符号的详细信息：类型、签名、代码片段、所在文件路径"
    category = "query"
    llm_visible = True

    def __init__(self, project_db=None, project_root=""):
        self._db = project_db
        self._project_root = project_root

    def to_openai_schema(self) -> Optional[dict]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbol_id": {
                            "type": "string",
                            "description": "符号的唯一标识 ID（graph_node.id）",
                        },
                    },
                    "required": ["symbol_id"],
                },
            },
        }

    async def execute(self, symbol_id: str = "", **kwargs) -> ToolResult:
        if not self._db:
            return ToolResult.fail("数据库未初始化")
        try:
            row = self._db.execute(
                "SELECT * FROM graph_node WHERE id = ?", (symbol_id,)
            ).fetchone()
            if not row:
                return ToolResult.fail(f"符号未找到: {symbol_id}")
            d = dict(row)
            if "file_path" in d:
                d["file_path"] = _rel_path(d["file_path"], self._project_root)
            return ToolResult.ok(data=json.dumps(d, ensure_ascii=False, default=str)[:5000])
        except Exception as e:
            logger.warning(f"[GetSymbolDetailTool] failed: {e}")
            return ToolResult.fail(str(e))


class SearchSymbolsTool(AgentTool):
    """按名称搜索代码符号"""

    name = "search_symbols"
    description = "按名称搜索代码符号（函数、类、方法等），返回匹配的符号列表"
    category = "query"
    llm_visible = True

    def __init__(self, project_db=None, project_root=""):
        self._db = project_db
        self._project_root = project_root

    def to_openai_schema(self) -> Optional[dict]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "符号名称关键字（支持 LIKE 模糊匹配）",
                        },
                        "kind": {
                            "type": "string",
                            "description": "符号类型过滤: function / method / class / variable（可选）",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "最大返回数量（默认 20）",
                        },
                    },
                    "required": ["pattern"],
                },
            },
        }

    async def execute(self, pattern: str = "", kind: str = "", limit: int = 20, **kwargs) -> ToolResult:
        if not self._db:
            return ToolResult.fail("数据库未初始化")
        try:
            # 兼容 LLM 可能传入字符串类型的数值参数
            if not isinstance(limit, int):
                try:
                    limit = int(limit)
                except (TypeError, ValueError):
                    limit = 20
            # 支持 | 分隔多个模式（OR 搜索）
            patterns = [p.strip() for p in pattern.split("|") if p.strip()] or [pattern]
            clauses = []
            params: list[Any] = []
            for p in patterns:
                clauses.append("name LIKE ?")
                params.append(f"%{p}%")
            sql = "SELECT id, name, kind, file_path FROM graph_node WHERE (" + " OR ".join(clauses) + ")"
            if kind:
                sql += " AND kind = ?"
                params.append(kind)
            sql += f" ORDER BY name LIMIT {min(limit, 100)}"
            rows = self._db.execute(sql, params).fetchall()
            if not rows:
                return ToolResult.fail(f"未找到匹配 '{pattern}' 的符号")
            results = [
                f"{r['name']} ({r['kind']}) — {_rel_path(r['file_path'], self._project_root)}"
                for r in rows
            ]
            return ToolResult.ok(data="\n".join(results))
        except Exception as e:
            logger.warning(f"[SearchSymbolsTool] failed: {e}")
            return ToolResult.fail(str(e))


class GetSymbolCodeTool(AgentTool):
    """获取指定符号的完整源代码（支持 ID / name+file / line+file 三种查找）"""

    name = "get_symbol_code"
    description = (
        "获取指定符号的完整源代码片段。支持三种查找方式："
        "1) symbol_id: 精确查找 (graph_node.id)；"
        "2) file_path + name: 按文件名+符号名查找；"
        "3) file_path + line: 按文件名+行号范围查找"
    )
    category = "query"
    llm_visible = True

    def __init__(self, project_db=None, project_root=""):
        self._db = project_db
        self._project_root = project_root

    def to_openai_schema(self) -> Optional[dict]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbol_id": {
                            "type": "string",
                            "description": "符号 ID (graph_node.id, 结构化输出中可见)"
                        },
                        "file_path": {
                            "type": "string",
                            "description": "文件路径 (配合 name 或 line)"
                        },
                        "name": {
                            "type": "string",
                            "description": "符号名称 (配合 file_path)"
                        },
                        "line": {
                            "type": "integer",
                            "description": "行号 (配合 file_path, 返回包含该行的符号)"
                        },
                    },
                },
            },
        }

    async def execute(self, symbol_id: str = "", file_path: str = "",
                      name: str = "", line: int = 0, **kwargs) -> ToolResult:
        if not self._db:
            return ToolResult.fail("数据库未初始化")
        try:
            row = None
            method = ""

            # 1. symbol_id 主键
            if symbol_id:
                method = "symbol_id"
                row = self._db.execute(
                    "SELECT * FROM graph_node WHERE id=?", (symbol_id,)
                ).fetchone()

            # 2. file_path + name
            if not row and file_path and name:
                method = "file_path+name"
                qpath = _rel_path(file_path, self._project_root) if self._project_root else file_path
                row = self._db.execute(
                    "SELECT * FROM graph_node WHERE file_path=? AND name=? LIMIT 1",
                    (qpath, name)
                ).fetchone()

            # 3. file_path + line
            if not row and file_path and line > 0:
                method = "file_path+line"
                qpath = _rel_path(file_path, self._project_root) if self._project_root else file_path
                row = self._db.execute(
                    "SELECT * FROM graph_node WHERE file_path=? "
                    "AND start_line <= ? AND end_line >= ? LIMIT 1",
                    (qpath, line, line)
                ).fetchone()

            if not row:
                hint = ("未找到符号。可尝试: "
                        "1) get_symbol_code(file_path=\"...\", name=\"函数名\") 按名称查找; "
                        "2) search_symbols(pattern=\"...\") 搜索符号后再用 symbol_id 精确查找")
                return ToolResult.fail(hint)

            d = dict(row)
            logger.info(
                f"[GetSymbolCodeTool] found: name={d.get('name','')} "
                f"kind={d.get('kind','')} lookup={method} id={d.get('id','')[:16]}"
            )
            abs_path = d.get("file_path", "")
            if self._project_root and not os.path.isabs(abs_path):
                abs_path = os.path.join(self._project_root, abs_path)

            if not os.path.isfile(abs_path):
                return ToolResult.fail(
                    f"文件不在磁盘。使用 get_symbol_detail(symbol_id=\"{d['id']}\") 查看元数据"
                )

            start = max(1, d.get("start_line", 1) - 3)
            end = d.get("end_line", start + 30)
            try:
                with open(abs_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    code = "".join(lines[start-1:end])
            except (UnicodeDecodeError, LookupError):
                with open(abs_path, "r", encoding="latin-1") as f:
                    lines = f.readlines()
                    code = "".join(lines[start-1:end])

            return ToolResult.ok(data=json.dumps({
                "symbol_id": d["id"],
                "name": d.get("name", ""),
                "kind": d.get("kind", ""),
                "file_path": _rel_path(abs_path, self._project_root),
                "line_range": f"L{start}-{end}",
                "signature": d.get("signature", ""),
                "docstring": d.get("docstring", ""),
                "code": code[:10000],
                "lookup_method": method,
            }, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"[GetSymbolCodeTool] failed: {e}")
            return ToolResult.fail(str(e))
