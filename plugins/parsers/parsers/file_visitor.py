"""FileVisitor — orchestrate query-based parsing across project files

Files are discovered by language extension, parsed via the query pipeline,
and results are persisted to graph_node.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional, Callable

from parsers.language_loader import get_language, get_parser
from parsers.query_loader import QueryLoader
from parsers.parse_with_queries import _build_symbol_table, _persist_table, _detect_language
from parsers.db_adapter import SQLiteAdapter
from parsers.binder import SimpleBinder

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]


class FileVisitor:
    """Walk project files, parse via queries, persist results."""

    def __init__(
        self,
        proj_path: str,
        extensions: Optional[set[str]] = None,
        progress_cb: Optional[ProgressCallback] = None,
    ):
        self.proj_path = Path(proj_path)
        self.extensions = extensions or {
            ".ts", ".tsx", ".mts", ".cts",
            ".js", ".jsx", ".mjs",
            ".py", ".pyw",
            ".java",
            ".c", ".h",
            ".cpp", ".hpp", ".cc", ".cxx", ".hh", ".hxx",
            ".go", ".rs",
            ".cs",
            ".swift",
        }
        self.progress_cb = progress_cb
        self._adapter = None

    def run(
        self,
        project_db=None,
        task_id: str = "",
        file_paths: Optional[list[str]] = None,
    ) -> int:
        """Parse a list of files (or all discovered files).

        Args:
            project_db: SQLiteContext for persistence. If None, skip persistence.
            task_id: Analysis task ID.
            file_paths: Specific files to parse. If None, discover from proj_path.

        Returns:
            Total symbols parsed.
        """
        if project_db is not None and task_id:
            self._adapter = SQLiteAdapter(project_db, task_id)
        self._task_id = task_id or ""

        if file_paths is not None:
            files = [Path(p) for p in file_paths]
        else:
            files = self._discover_files()

        total = len(files)
        symbols_total = 0

        for idx, file_path in enumerate(files):
            if self.progress_cb:
                self.progress_cb(idx + 1, total, str(file_path))

            result = self._parse_one(file_path)
            if result > 0:
                symbols_total += result

        logger.info(
            f"FileVisitor done: {total} files, {symbols_total} symbols "
            f"for task {self._task_id}"
        )
        return symbols_total

    def _parse_one(self, file_path: Path) -> int:
        """Parse a single file via the query pipeline."""
        if not file_path.exists():
            logger.warning(f"Skipping nonexistent file: {file_path}")
            return 0

        language_name = _detect_language(str(file_path))
        if not language_name:
            return 0

        ts_language = get_language(language_name)
        if not ts_language:
            return 0

        parser = get_parser(language_name)
        if not parser:
            return 0

        try:
            src_content = file_path.read_bytes()
        except Exception as e:
            logger.warning(f"Failed to read {file_path}: {e}")
            return 0

        tree = parser.parse(src_content)
        if not tree or not tree.root_node:
            return 0

        qs = QueryLoader.load(language_name, ts_language)

        try:
            table = _build_symbol_table(
                tree, language_name, str(file_path), qs
            )
        except Exception as e:
            logger.exception(f"Failed building symbol table for {file_path}: {e}")
            return 0

        if not table.symbols and not table.references and not table.imports:
            return 0

        binder = SimpleBinder({table.file_path: table})
        for ref in table.references:
            result = binder.resolve(ref, file_path=table.file_path)
            if result and result.target:
                ref.target = f"{result.target.scope}.{result.target.name}"

        if self._adapter is not None:
            rel_path = os.path.relpath(file_path, self.proj_path)
            _persist_table(self._adapter, table, rel_path, language_name)

        return len(table.symbols)

    def _discover_files(self) -> list[Path]:
        """Discover all source files under proj_path with matching extensions."""
        files: list[Path] = []
        for root, dirs, names in os.walk(self.proj_path):
            root_path = Path(root)
            for name in names:
                ext = Path(name).suffix.lower()
                if ext in self.extensions:
                    files.append(root_path / name)
        return sorted(files)
