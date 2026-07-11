"""
文件读写工具 — 用于 LLM Agentic 工作流读取和搜索源文件。
"""

import logging
import os
from typing import Optional

from ..tools import AgentTool, ToolResult

logger = logging.getLogger(__name__)


class ReadFileTool(AgentTool):
    """Read specified file content"""

    name = "read_file"
    description = "Read full content of specified file (auto-truncates beyond 5000 chars)"
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
                            "description": "File path (absolute, or relative to project root)",
                        },
                    },
                    "required": ["path"],
                },
            },
        }

    async def execute(self, path: str = "", **kwargs) -> ToolResult:
        try:
            # Compatible with LLM possibly passing file_path / filepath etc.
            if not path:
                path = kwargs.get("file_path", kwargs.get("filepath", kwargs.get("filename", "")))
            abs_path = path
            if self._project_root and not os.path.isabs(path):
                abs_path = os.path.join(self._project_root, path)
            if self._path_sandbox:
                abs_path = self._path_sandbox.validate_read(abs_path)
            if not os.path.isfile(abs_path) and self._project_root:
                # Exact path miss → fallback to basename fuzzy match
                from ..path_utils import resolve_file
                resolved = resolve_file(path, self._project_root)
                if resolved:
                    abs_path = resolved
            if not os.path.isfile(abs_path):
                logger.warning(f"[ReadFileTool] file not found: {path} (resolved: {abs_path})")
                return ToolResult.fail(f"File not found: {path}")
            try:
                with open(abs_path, "r", encoding="utf-8") as f:
                    content = f.read(10000)
            except (UnicodeDecodeError, LookupError):
                with open(abs_path, "r", encoding="latin-1") as f:
                    content = f.read(10000)
            if len(content) >= 10000:
                content += "\n\n...(file too long, truncated)"
            return ToolResult.ok(data=content)
        except Exception as e:
            logger.warning(f"[ReadFileTool] failed: {e}")
            return ToolResult.fail(str(e))


class SearchContentTool(AgentTool):
    """Search for keywords or regex patterns in file content"""

    name = "search_content"
    description = "Search for keywords or regex in files, returns matching lines with line numbers (max 50 lines)"
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
                            "description": "Search keyword or regex pattern",
                        },
                        "path": {
                            "type": "string",
                            "description": "File path (optional, searches all common source files if not specified)",
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
                return ToolResult.fail(f"No matching files found: {path or '(project root)'}")

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
                return ToolResult.fail(f"Content not found matching '{pattern}'")
            return ToolResult.ok(data="\n".join(results))
        except Exception as e:
            logger.warning(f"[SearchContentTool] failed: {e}")
            return ToolResult.fail(str(e))


class SummarizeFileTool(AgentTool):
    """Read and summarize files (LLM visible), uses cache to avoid repeated LLM calls"""

    name = "summarize_file"
    description = "Read one or more files and generate functional summaries (≤10 files). Already summarized files auto-use cache. Useful for quickly understanding many files."
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
                            "description": "List of file paths to summarize (absolute or relative, ≤10)",
                        },
                        "focus": {
                            "type": "string",
                            "description": "Summary focus, e.g. 'focus on function interface definitions' (optional)",
                        },
                        "force_refresh": {
                            "type": "boolean",
                            "description": "Ignore cache, force re-read and re-summarize (optional, default false)",
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
                return ToolResult.fail("No file path specified")

            from ..path_utils import to_abs
            safe_files = []
            for fp in files:
                abs_path = to_abs(fp, self._project_root)
                if self._path_sandbox:
                    abs_path = self._path_sandbox.validate_read(abs_path)
                if abs_path:
                    safe_files.append(abs_path)

            if not self._project_db or not self._project_id:
                return ToolResult.fail("File summary feature not configured: missing project_db")

            from ..file_summary_cache import FileSummaryCache
            from ..sub_agent import SubAgent

            cache = FileSummaryCache(self._project_db, self._project_id, self._project_root)
            sub = SubAgent(
                project_root=self._project_root,
                model_id=self._summary_model_id,
                multi_db=self._multi_db,
                project_db=self._project_db,
                task_id=self._task_id,
                cancel_event=getattr(self, 'cancel_event', None),
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
                    tag = f" (cached{', ' + ct if ct else ''})"
                lines.append(f"======== {fp_short}{tag} ========\n{s['summary']}\n")
            lines.append(
                f"[Summary stats: {result.files_processed} files, "
                f"cache hits {result.cache_hits}, "
                f"cache misses {result.cache_misses}, "
                f"saved ~{result.tokens_saved} tokens, "
                f"consumed {result.tokens_used} tokens"
                + (f", failed {result.failed}" if result.failed else "")
                + "]"
            )

            return ToolResult.ok(data="\n".join(lines), failed=result.failed)

        except Exception as e:
            logger.warning(f"[SummarizeFileTool] failed: {e}")
            return ToolResult.fail(str(e))
