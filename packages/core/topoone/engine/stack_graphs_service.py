"""StackGraphsService — wrapper around stack-graphs CLI tool

Detects the stack-graphs binary via shutil.which and manages subprocess
lifecycle for indexing and querying. Falls back gracefully when the tool
is not installed.

Usage:
    sg = StackGraphsService("/path/to/project", "typescript")
    if sg.available:
        result = await sg.definition("file.ts", 10, 5)
        refs = await sg.references("file.ts", 10, 5)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

STACK_GRAPHS_BIN = "stack-graphs"


@dataclass
class StackGraphsResult:
    file: str
    line: int
    column: int
    scope_stack: list[dict]


class StackGraphsService:
    """Manages stack-graphs CLI subprocess lifecycle."""

    def __init__(self, project_root: str, language: str):
        self.project_root = os.path.abspath(project_root)
        self.language = language
        self._process: Optional[asyncio.subprocess.Process] = None
        self._available: Optional[bool] = None

    @property
    def available(self) -> bool:
        if self._available is None:
            self._available = shutil.which(STACK_GRAPHS_BIN) is not None
        return self._available

    async def index(self) -> bool:
        """Index the project using stack-graphs CLI.

        Returns:
            True if indexing succeeded, False otherwise.
        """
        if not self.available:
            logger.warning("stack-graphs CLI not found, skipping index")
            return False

        try:
            proc = await asyncio.create_subprocess_exec(
                STACK_GRAPHS_BIN, "index",
                "--project", self.project_root,
                "--language", self.language,
                cwd=self.project_root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=120
            )
            if proc.returncode != 0:
                logger.error(
                    f"stack-graphs index failed (code={proc.returncode}): "
                    f"{stderr.decode(errors='replace')}"
                )
                return False

            logger.info(
                f"stack-graphs index complete for {self.project_root} "
                f"({self.language})"
            )
            return True

        except asyncio.TimeoutError:
            logger.error("stack-graphs index timed out after 120s")
            return False
        except Exception as e:
            logger.exception(f"stack-graphs index error: {e}")
            return False

    async def definition(
        self, file: str, line: int, column: int
    ) -> Optional[StackGraphsResult]:
        """Query definition location for a symbol.

        Args:
            file: Path to source file (relative to project_root).
            line: 1-based line number.
            column: 1-based column number.

        Returns:
            StackGraphsResult if found, None if not available or not found.
        """
        if not self.available:
            return None

        cmd = json.dumps({
            "command": "definition",
            "file": file,
            "line": line,
            "column": column,
        })

        try:
            result = await self._run_query(cmd)
            if result and "file" in result:
                return StackGraphsResult(
                    file=result["file"],
                    line=result.get("line", line),
                    column=result.get("column", column),
                    scope_stack=result.get("scope_stack", []),
                )
            return None
        except Exception as e:
            logger.exception(f"stack-graphs definition error: {e}")
            return None

    async def references(
        self, file: str, line: int, column: int
    ) -> list[StackGraphsResult]:
        """Query all references for a symbol.

        Args:
            file: Path to source file (relative to project_root).
            line: 1-based line number.
            column: 1-based column number.

        Returns:
            List of StackGraphsResult, empty if not available or not found.
        """
        if not self.available:
            return []

        cmd = json.dumps({
            "command": "references",
            "file": file,
            "line": line,
            "column": column,
        })

        try:
            results = await self._run_query(cmd)
            if isinstance(results, list):
                return [
                    StackGraphsResult(
                        file=r["file"],
                        line=r.get("line", line),
                        column=r.get("column", column),
                        scope_stack=r.get("scope_stack", []),
                    )
                    for r in results if "file" in r
                ]
            return []
        except Exception as e:
            logger.exception(f"stack-graphs references error: {e}")
            return []

    async def _run_query(self, command_json: str) -> Optional[dict | list]:
        """Run a single query via stdin/stdout JSON protocol."""
        proc = await asyncio.create_subprocess_exec(
            STACK_GRAPHS_BIN, "query",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(command_json.encode()), timeout=30
        )
        if proc.returncode != 0:
            logger.error(
                f"stack-graphs query failed (code={proc.returncode}): "
                f"{stderr.decode(errors='replace')}"
            )
            return None
        if stdout:
            return json.loads(stdout.decode())
        return None

    async def shutdown(self):
        """Terminate the index subprocess if running."""
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=10)
            except Exception as e:
                logger.warning(f"stack-graphs shutdown error: {e}")
            self._process = None
