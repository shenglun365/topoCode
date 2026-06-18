"""
文件读写工具 — 用于 LLM Agentic 工作流读取和搜索源文件。
"""

import logging
import os
from typing import Optional

from ..tools import AgentTool, ToolResult

logger = logging.getLogger(__name__)


class ReadFileTool(AgentTool):
    """读取指定文件内容"""

    name = "read_file"
    description = "读取指定文件的完整内容（自动截断超过 5000 字符的部分）"
    category = "io"
    llm_visible = True

    def __init__(self, project_root: str = "", path_sandbox=None):
        self._project_root = project_root
        self._path_sandbox = path_sandbox

    def to_openai_schema(self) -> Optional[dict]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "文件路径（绝对路径，或相对于项目根目录的相对路径）",
                        },
                    },
                    "required": ["path"],
                },
            },
        }

    async def execute(self, path: str = "", **kwargs) -> ToolResult:
        try:
            # 兼容 LLM 可能传入的 file_path / filepath 等参数名
            if not path:
                path = kwargs.get("file_path", kwargs.get("filepath", kwargs.get("filename", "")))
            abs_path = path
            if self._project_root and not os.path.isabs(path):
                abs_path = os.path.join(self._project_root, path)
            if self._path_sandbox:
                abs_path = self._path_sandbox.validate_read(abs_path)
            if not os.path.isfile(abs_path):
                logger.warning(f"[ReadFileTool] file not found: {path} (resolved: {abs_path})")
                return ToolResult.fail(f"文件不存在: {path}")
            try:
                with open(abs_path, "r", encoding="utf-8") as f:
                    content = f.read(10000)
            except (UnicodeDecodeError, LookupError):
                with open(abs_path, "r", encoding="latin-1") as f:
                    content = f.read(10000)
            if len(content) >= 10000:
                content += "\n\n...（文件过长已截断）"
            return ToolResult.ok(data=content)
        except Exception as e:
            logger.warning(f"[ReadFileTool] failed: {e}")
            return ToolResult.fail(str(e))


class SearchContentTool(AgentTool):
    """在文件内容中搜索关键字或正则表达式"""

    name = "search_content"
    description = "在文件中搜索关键字或正则表达式，返回匹配行及其行号（最多 50 行）"
    category = "io"
    llm_visible = True

    def __init__(self, project_root: str = "", path_sandbox=None):
        self._project_root = project_root
        self._path_sandbox = path_sandbox

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
                            "description": "搜索关键字或正则表达式",
                        },
                        "path": {
                            "type": "string",
                            "description": "文件路径（可选，不指定则在项目内所有常见源码文件中搜索）",
                        },
                    },
                    "required": ["pattern"],
                },
            },
        }

    async def execute(self, pattern: str = "", path: str = "", **kwargs) -> ToolResult:
        try:
            import re
            regex = re.compile(pattern, re.IGNORECASE)
            target_paths: list[str] = []

            if path:
                abs_path = path
                if self._project_root and not os.path.isabs(path):
                    abs_path = os.path.join(self._project_root, path)
                if self._path_sandbox:
                    abs_path = self._path_sandbox.validate_read(abs_path)
                if os.path.isfile(abs_path):
                    target_paths = [abs_path]
                elif os.path.isdir(abs_path):
                    for root, dirs, files in os.walk(abs_path):
                        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
                        for f in files:
                            if any(f.endswith(ext) for ext in (".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".hpp", ".go", ".rs", ".vue", ".tsx", ".jsx")):
                                target_paths.append(os.path.join(root, f))
            elif self._project_root:
                for root, dirs, files in os.walk(self._project_root):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
                    for f in files:
                        if any(f.endswith(ext) for ext in (".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".hpp", ".go", ".rs", ".vue", ".tsx", ".jsx")):
                            target_paths.append(os.path.join(root, f))

            if not target_paths:
                return ToolResult.fail(f"未找到匹配的文件: {path or '(project root)'}")

            results: list[str] = []
            for fp in target_paths[:200]:
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as f:
                        for i, line in enumerate(f, 1):
                            if regex.search(line):
                                rel = os.path.relpath(fp, self._project_root) if self._project_root else fp
                                results.append(f"{rel}:{i}: {line.rstrip()[:200]}")
                                if len(results) >= 50:
                                    break
                except Exception:
                    continue
                if len(results) >= 50:
                    break

            if not results:
                return ToolResult.fail(f"未找到匹配 '{pattern}' 的内容")
            return ToolResult.ok(data="\n".join(results))
        except Exception as e:
            logger.warning(f"[SearchContentTool] failed: {e}")
            return ToolResult.fail(str(e))
