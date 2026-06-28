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
            if not os.path.isfile(abs_path) and self._project_root:
                # 精确路径未命中 → basename 模糊匹配兜底
                from ..path_utils import resolve_file
                resolved = resolve_file(path, self._project_root)
                if resolved:
                    abs_path = resolved
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


class SummarizeFileTool(AgentTool):
    """读取并摘要文件（LLM 可见），利用缓存避免重复 LLM 调用"""

    name = "summarize_file"
    description = "读取一个或多个文件并生成功能摘要（≤10个文件）。已摘要的文件自动复用缓存。适用于快速了解大量文件的功能。"
    category = "io"
    llm_visible = True

    def __init__(self, project_root: str = "", project_db=None,
                 project_id: str = "", task_id: str = "",
                 multi_db=None, path_sandbox=None,
                 summary_model_id: str = "", concurrency: int = 1):
        self._project_root = project_root
        self._project_db = project_db
        self._project_id = project_id
        self._task_id = task_id
        self._multi_db = multi_db
        self._path_sandbox = path_sandbox
        self._summary_model_id = summary_model_id
        self._concurrency = max(1, min(concurrency, 10))

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
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要摘要的文件路径列表（绝对或相对路径，≤10个）",
                        },
                        "focus": {
                            "type": "string",
                            "description": "摘要侧重点，如'关注函数接口定义'（可选）",
                        },
                        "force_refresh": {
                            "type": "boolean",
                            "description": "忽略缓存，强制重新读取并摘要（可选，默认 false）",
                        },
                    },
                    "required": ["path"],
                },
            },
        }

    async def execute(self, path=None, focus: str = "", force_refresh: bool = False, **kwargs) -> ToolResult:
        try:
            files = path or kwargs.get("paths", kwargs.get("files", []))
            if isinstance(files, str):
                files = [files]
            files = files[:10]

            if not files:
                return ToolResult.fail("未指定文件路径")

            from ..path_utils import to_abs
            safe_files = []
            for fp in files:
                abs_path = to_abs(fp, self._project_root)
                if self._path_sandbox:
                    abs_path = self._path_sandbox.validate_read(abs_path)
                if abs_path:
                    safe_files.append(abs_path)

            if not self._project_db or not self._project_id:
                return ToolResult.fail("文件摘要功能未配置 project_db")

            from ..file_summary_cache import FileSummaryCache
            from ..sub_agent import SubAgent

            cache = FileSummaryCache(self._project_db, self._project_id)
            sub = SubAgent(
                project_root=self._project_root,
                model_id=self._summary_model_id,
                multi_db=self._multi_db,
                project_db=self._project_db,
                task_id=self._task_id,
            )

            result = await sub.summarize_files(
                files=safe_files,
                task_id=self._task_id,
                project_id=self._project_id,
                file_cache=cache,
                focus=focus,
                force_refresh=bool(force_refresh),
                max_concurrent=self._concurrency,
            )

            lines = []
            for s in result.summaries:
                fp_short = os.path.relpath(s["path"], self._project_root) \
                    if self._project_root and os.path.isabs(s["path"]) else s["path"]
                tag = ""
                if s.get("cached"):
                    ct = s.get("cached_at", "")
                    tag = f" (缓存{', ' + ct if ct else ''})"
                lines.append(f"======== {fp_short}{tag} ========\n{s['summary']}\n")
            lines.append(
                f"[摘要统计: {result.files_processed} 文件, "
                f"缓存命中 {result.cache_hits}, "
                f"缓存未命中 {result.cache_misses}, "
                f"节省 ~{result.tokens_saved} tokens, "
                f"消耗 {result.tokens_used} tokens"
                + (f", 失败 {result.failed} 个" if result.failed else "")
                + "]"
            )

            return ToolResult.ok(data="\n".join(lines), failed=result.failed)

        except Exception as e:
            logger.warning(f"[SummarizeFileTool] failed: {e}")
            return ToolResult.fail(str(e))
