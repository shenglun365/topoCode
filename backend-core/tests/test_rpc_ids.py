"""Test rpc_ids module."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rpc_ids import get_rpc_id


class TestRpcIds:
    def test_get_rpc_id_returns_string(self):
        rpc_id = get_rpc_id("analysis.start")
        assert isinstance(rpc_id, str)
        assert len(rpc_id) > 0

    def test_get_rpc_id_is_deterministic(self):
        id1 = get_rpc_id("analysis.start")
        id2 = get_rpc_id("analysis.start")
        assert id1 == id2

    def test_get_rpc_id_returns_api_format(self):
        rpc_id = get_rpc_id("analysis.listTasks")
        assert rpc_id.startswith("API-")

    def test_unknown_method_returns_fallback(self):
        rpc_id = get_rpc_id("nonexistent.method")
        assert rpc_id is not None
