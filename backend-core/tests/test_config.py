"""Test backend-core config module."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import (
    MAX_AST_NODES,
    PARSE_WORKERS,
    ZMQ_DEALER_PORT,
    ZMQ_PUB_PORT,
    ZMQ_BIND_HOST,
)


class TestConfig:
    def test_max_ast_nodes_is_positive(self):
        assert MAX_AST_NODES > 0

    def test_parse_workers_is_positive(self):
        assert PARSE_WORKERS > 0

    def test_zmq_ports_are_different(self):
        assert ZMQ_DEALER_PORT != ZMQ_PUB_PORT

    def test_zmq_ports_in_ephemeral_range(self):
        assert 1024 <= ZMQ_DEALER_PORT <= 65535
        assert 1024 <= ZMQ_PUB_PORT <= 65535

    def test_zmq_bind_host_is_localhost(self):
        assert ZMQ_BIND_HOST == "127.0.0.1"
