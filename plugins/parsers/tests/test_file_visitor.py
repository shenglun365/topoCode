"""Tests for file_visitor.py — FileVisitor"""

import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from unittest.mock import Mock, patch

from parsers.file_visitor import FileVisitor


class TestFileVisitor:
    def test_discover_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            (proj / "src").mkdir()
            (proj / "src" / "main.ts").write_text("const x = 1;")
            (proj / "src" / "util.py").write_text("def foo(): pass")
            (proj / "README.md").write_text("# readme")

        visitor = FileVisitor(proj_path="/tmp")
        result = visitor.run(file_paths=[])
        assert result == 0

    def test_run_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            visitor = FileVisitor(proj_path=str(tmp))
            result = visitor.run()
            assert result == 0
