"""Tests for stack_graphs_service.py"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
from unittest.mock import patch, MagicMock, PropertyMock

from stack_graphs_service import StackGraphsService, StackGraphsResult


def async_run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return asyncio.run(coro)
    except RuntimeError:
        return asyncio.run(coro)


class TestStackGraphsService:
    def test_available_false_when_not_installed(self):
        sg = StackGraphsService("/tmp", "typescript")
        with patch("stack_graphs_service.shutil.which", return_value=None):
            assert sg.available is False

    def test_available_true_when_installed(self):
        sg = StackGraphsService("/tmp", "typescript")
        with patch("stack_graphs_service.shutil.which", return_value="/usr/bin/stack-graphs"):
            assert sg.available is True

    def test_available_cached(self):
        sg = StackGraphsService("/tmp", "typescript")
        with patch("stack_graphs_service.shutil.which", return_value=None) as mock:
            _ = sg.available
            _ = sg.available
            assert mock.call_count == 1

    def test_index_returns_false_when_not_available(self):
        sg = StackGraphsService("/tmp", "typescript")
        with patch.object(type(sg), "available", PropertyMock(return_value=False)):
            result = async_run(sg.index())
            assert result is False

    def test_definition_returns_none_when_not_available(self):
        sg = StackGraphsService("/tmp", "typescript")
        with patch.object(type(sg), "available", PropertyMock(return_value=False)):
            result = async_run(sg.definition("f.ts", 1, 1))
            assert result is None

    def test_references_returns_empty_when_not_available(self):
        sg = StackGraphsService("/tmp", "typescript")
        with patch.object(type(sg), "available", PropertyMock(return_value=False)):
            result = async_run(sg.references("f.ts", 1, 1))
            assert result == []

    def test_shutdown_noop_when_no_process(self):
        sg = StackGraphsService("/tmp", "typescript")
        async_run(sg.shutdown())
        assert sg._process is None

    def test_index_returns_false_on_failure(self):
        sg = StackGraphsService("/tmp", "typescript")
        with patch.object(type(sg), "available", PropertyMock(return_value=True)):
            with patch("stack_graphs_service.asyncio.create_subprocess_exec") as mock:
                proc = MagicMock()
                proc.returncode = 1
                async def mock_communicate(data=b""):
                    return (b"", b"error".encode())
                proc.communicate = mock_communicate
                mock.return_value = proc
                result = async_run(sg.index())
                assert result is False

    def test_stack_graphs_result_dataclass(self):
        r = StackGraphsResult(file="f.ts", line=10, column=5, scope_stack=[])
        assert r.file == "f.ts"
        assert r.line == 10
        assert r.column == 5
        assert r.scope_stack == []
