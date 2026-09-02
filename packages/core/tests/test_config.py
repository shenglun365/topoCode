"""Test backend-core config module."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from topoone.config import (
    MAX_AST_NODES,
    PARSE_WORKERS,
    ZMQ_DEALER_PORT,
    KB_PUB_PORT,
    ZMQ_BIND_HOST,
)


class TestConfig:
    def test_max_ast_nodes_is_positive(self):
        assert MAX_AST_NODES > 0

    def test_parse_workers_is_positive(self):
        assert PARSE_WORKERS > 0

    def test_zmq_ports_are_different(self):
        assert ZMQ_DEALER_PORT != KB_PUB_PORT

    def test_zmq_ports_in_ephemeral_range(self):
        assert 1024 <= ZMQ_DEALER_PORT <= 65535
        assert 1024 <= KB_PUB_PORT <= 65535

    def test_kb_pub_port_single_source(self):
        """C4: kb PUB 端口单一源 —— 默认 5681 与 gateway 订阅端一致。"""
        assert KB_PUB_PORT == 5681

    def test_zmq_bind_host_is_localhost(self):
        assert ZMQ_BIND_HOST == "127.0.0.1"
