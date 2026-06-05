"""Tests for MCP Server module (Phase 5).

Tests cover:
- Tool definitions
- Path validation
- JSON-RPC 2.0 protocol
- Tool dispatcher handlers
"""

import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "plugins", "parsers"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "plugins"))

import pytest
from mcp_server.tools import CORE_TOOLS, ToolDefinition
from mcp_server.path_validator import PathValidator
from mcp_server.dispatcher import ToolDispatcher
from mcp_server.server import MCPServer


# ==============================
# tools.py
# ==============================

class TestToolDefinitions:
    def test_core_tools_count(self):
        assert len(CORE_TOOLS) == 11

    def test_each_tool_has_required_fields(self):
        for t in CORE_TOOLS:
            assert isinstance(t, ToolDefinition)
            assert t.name
            assert t.description
            assert isinstance(t.inputSchema, dict)

    def test_get_definition_schema(self):
        t = [x for x in CORE_TOOLS if x.name == "get_definition"][0]
        assert "file_path" in t.inputSchema.get("properties", {})
        assert "line" in t.inputSchema.get("properties", {})
        assert "character" in t.inputSchema.get("properties", {})
        assert t.inputSchema.get("required") == ["file_path", "line", "character"]

    def test_search_symbol_schema(self):
        t = [x for x in CORE_TOOLS if x.name == "search_symbol"][0]
        assert "query" in t.inputSchema.get("properties", {})
        assert t.inputSchema.get("required") == ["query"]

    def test_get_file_symbols_schema(self):
        t = [x for x in CORE_TOOLS if x.name == "get_file_symbols"][0]
        assert "file_path" in t.inputSchema.get("properties", {})
        assert t.inputSchema.get("required") == ["file_path"]

    def test_all_tool_names_unique(self):
        names = [t.name for t in CORE_TOOLS]
        assert len(names) == len(set(names))


# ==============================
# path_validator.py
# ==============================

class TestPathValidator:
    def test_validates_path_within_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            validator = PathValidator(tmp)
            test_file = os.path.join(tmp, "src", "main.py")
            os.makedirs(os.path.dirname(test_file))
            with open(test_file, "w") as f:
                f.write("")
            result = validator.validate(test_file)
            assert result == os.path.abspath(test_file)

    def test_rejects_path_outside_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            validator = PathValidator(tmp)
            result = validator.validate("/etc/passwd")
            assert result is None

    def test_assert_valid_raises_on_outside(self):
        with tempfile.TemporaryDirectory() as tmp:
            validator = PathValidator(tmp)
            with pytest.raises(ValueError, match="Access denied"):
                validator.assert_valid("/etc/passwd")

    def test_relative_path_resolves_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            validator = PathValidator(tmp)
            test_file = os.path.join(tmp, "inner", "file.ts")
            os.makedirs(os.path.dirname(test_file))
            with open(test_file, "w") as f:
                f.write("")
            rel_path = os.path.relpath(test_file, tmp)
            result = validator.validate(rel_path)
            assert result == os.path.abspath(test_file)


# ==============================
# server.py — JSON-RPC protocol
# ==============================

class TestMCPServer:
    @pytest.mark.asyncio
    async def test_handle_initialize(self):
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher = ToolDispatcher(project_root=tmp)
            server = MCPServer(dispatcher)
            req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
            resp = await server._handle_request(req)
            assert resp["jsonrpc"] == "2.0"
            assert resp["id"] == 1
            assert resp["result"]["protocolVersion"] == "2024-11-05"
            assert resp["result"]["serverInfo"]["name"] == "topocode-mcp"

    @pytest.mark.asyncio
    async def test_handle_ping(self):
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher = ToolDispatcher(project_root=tmp)
            server = MCPServer(dispatcher)
            req = {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}}
            resp = await server._handle_request(req)
            assert resp["result"] == {}

    @pytest.mark.asyncio
    async def test_tools_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher = ToolDispatcher(project_root=tmp)
            server = MCPServer(dispatcher)
            req = {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}}
            resp = await server._handle_request(req)
            assert "tools" in resp["result"]
            assert len(resp["result"]["tools"]) == 11
            names = [t["name"] for t in resp["result"]["tools"]]
            assert "get_definition" in names
            assert "get_references" in names
            assert "get_file_symbols" in names
            assert "search_symbol" in names

    @pytest.mark.asyncio
    async def test_prompts_list_returns_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher = ToolDispatcher(project_root=tmp)
            server = MCPServer(dispatcher)
            req = {"jsonrpc": "2.0", "id": 8, "method": "prompts/list", "params": {}}
            resp = await server._handle_request(req)
            prompts = resp["result"]["prompts"]
            assert len(prompts) == 7
            names = [p["name"] for p in prompts]
            assert "get_context_for_symbol" in names
            assert "get_impact_analysis" in names
            assert "explain_code_block" in names
            assert "prepare_refactor" in names
            assert "generate_docstring" in names
            assert "assess_merge_impact" in names
            assert "review_refactoring" in names

    @pytest.mark.asyncio
    async def test_prompts_get_known_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher = ToolDispatcher(project_root=tmp)
            server = MCPServer(dispatcher)
            req = {
                "jsonrpc": "2.0", "id": 9, "method": "prompts/get",
                "params": {"name": "explain_code_block"},
            }
            resp = await server._handle_request(req)
            assert resp["result"]["name"] == "explain_code_block"
            assert "prompt" in resp["result"]

    @pytest.mark.asyncio
    async def test_prompts_get_unknown_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher = ToolDispatcher(project_root=tmp)
            server = MCPServer(dispatcher)
            req = {
                "jsonrpc": "2.0", "id": 10, "method": "prompts/get",
                "params": {"name": "nonexistent"},
            }
            resp = await server._handle_request(req)
            assert "error" in resp
            assert resp["error"]["code"] == -32602

    @pytest.mark.asyncio
    async def test_unknown_method(self):
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher = ToolDispatcher(project_root=tmp)
            server = MCPServer(dispatcher)
            req = {"jsonrpc": "2.0", "id": 4, "method": "foobar", "params": {}}
            resp = await server._handle_request(req)
            assert "error" in resp
            assert resp["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_tools_call_returns_error_on_unknown_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher = ToolDispatcher(project_root=tmp)
            server = MCPServer(dispatcher)
            req = {
                "jsonrpc": "2.0", "id": 5, "method": "tools/call",
                "params": {"name": "nonexistent", "arguments": {}},
            }
            resp = await server._handle_request(req)
            # Unknown tool returns result with error field
            assert "error" in resp.get("result", {})

    @pytest.mark.asyncio
    async def test_tools_call_get_file_symbols_no_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher = ToolDispatcher(project_root=tmp)
            server = MCPServer(dispatcher)
            test_file = os.path.join(tmp, "test.ts")
            with open(test_file, "w") as f:
                f.write("")
            req = {
                "jsonrpc": "2.0", "id": 6, "method": "tools/call",
                "params": {
                    "name": "get_file_symbols",
                    "arguments": {"file_path": test_file},
                },
            }
            resp = await server._handle_request(req)
            result = resp["result"]
            content = result.get("content", [])
            assert len(content) == 1
            data = json.loads(content[0]["text"])
            assert data["file_path"] == test_file
            assert data["symbols"] == []

    @pytest.mark.asyncio
    async def test_tools_call_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher = ToolDispatcher(project_root=tmp)
            server = MCPServer(dispatcher)
            req = {
                "jsonrpc": "2.0", "id": 7, "method": "tools/call",
                "params": {
                    "name": "get_file_symbols",
                    "arguments": {"file_path": "/etc/passwd"},
                },
            }
            resp = await server._handle_request(req)
            result = resp.get("result", {})
            assert "error" in result or "Access denied" in str(result)


# ==============================
# dispatcher.py — handlers
# ==============================

class TestDispatcher:
    def test_unknown_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            disp = ToolDispatcher(project_root=tmp)
            result = disp._handlers.get("nonexistent")
            assert result is None

    def test_search_symbol_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            disp = ToolDispatcher(project_root=tmp)
            result = disp._handle_search_symbol({"query": "foo", "kind_filter": "all", "max_results": 20})
            assert result["matches"] == []
            assert result["total"] == 0

    def test_search_symbol_with_data(self):
        from parsers.symbol_model import (
            Symbol, SymbolKind, SourceLocation, FileSymbolTable,
        )
        with tempfile.TemporaryDirectory() as tmp:
            table = FileSymbolTable(file_path="/test.ts", language="typescript")
            loc = SourceLocation(file_path="/test.ts", start_byte=0, end_byte=10, start_line=1, start_col=0, end_line=1, end_col=5)
            table.add_symbol(Symbol(name="myFunction", kind=SymbolKind.FUNCTION, location=loc, scope="module"))
            disp = ToolDispatcher(project_root=tmp, tables=[table])
            result = disp._handle_search_symbol({"query": "myFunc", "kind_filter": "all", "max_results": 20})
            assert len(result["matches"]) == 1
            assert result["matches"][0]["name"] == "myFunction"
            assert result["matches"][0]["kind"] == "function"

    def test_get_file_symbols_with_data(self):
        from parsers.symbol_model import (
            Symbol, SymbolKind, SourceLocation, FileSymbolTable,
        )
        with tempfile.TemporaryDirectory() as tmp:
            test_file = os.path.join(tmp, "app.ts")
            table = FileSymbolTable(file_path=test_file, language="typescript")
            loc1 = SourceLocation(file_path=test_file, start_byte=0, end_byte=20, start_line=1, start_col=0, end_line=1, end_col=10)
            loc2 = SourceLocation(file_path=test_file, start_byte=0, end_byte=30, start_line=5, start_col=0, end_line=5, end_col=20)
            table.add_symbol(Symbol(name="foo", kind=SymbolKind.FUNCTION, location=loc1, scope="module"))
            table.add_symbol(Symbol(name="Bar", kind=SymbolKind.CLASS, location=loc2, scope="module"))
            disp = ToolDispatcher(project_root=tmp, tables=[table])
            result = disp._handle_file_symbols({"file_path": test_file})
            assert len(result["symbols"]) == 2
            names = [s["name"] for s in result["symbols"]]
            assert "foo" in names
            assert "Bar" in names

    def test_get_file_symbols_kind_filter(self):
        from parsers.symbol_model import (
            Symbol, SymbolKind, SourceLocation, FileSymbolTable,
        )
        with tempfile.TemporaryDirectory() as tmp:
            test_file = os.path.join(tmp, "app.ts")
            table = FileSymbolTable(file_path=test_file, language="typescript")
            loc1 = SourceLocation(file_path=test_file, start_byte=0, end_byte=20, start_line=1, start_col=0, end_line=1, end_col=10)
            loc2 = SourceLocation(file_path=test_file, start_byte=0, end_byte=30, start_line=5, start_col=0, end_line=5, end_col=20)
            table.add_symbol(Symbol(name="foo", kind=SymbolKind.FUNCTION, location=loc1, scope="module"))
            table.add_symbol(Symbol(name="Bar", kind=SymbolKind.CLASS, location=loc2, scope="module"))
            disp = ToolDispatcher(project_root=tmp, tables=[table])
            result = disp._handle_file_symbols({"file_path": test_file, "kind_filter": ["class"]})
            assert len(result["symbols"]) == 1
            assert result["symbols"][0]["name"] == "Bar"

    def test_get_dependencies(self):
        from parsers.symbol_model import FileSymbolTable, ImportRecord
        with tempfile.TemporaryDirectory() as tmp:
            test_file = os.path.join(tmp, "app.ts")
            table = FileSymbolTable(file_path=test_file, language="typescript")
            table.imports.append(ImportRecord(module="lodash", imported_names=["merge"]))
            disp = ToolDispatcher(project_root=tmp, tables=[table])
            result = disp._handle_dependencies({"file_path": test_file, "direction": "imports"})
            assert len(result["imports"]) == 1
            assert result["imports"][0]["module"] == "lodash"

    def test_get_definition_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            disp = ToolDispatcher(project_root=tmp)
            result = disp._handle_definition({"file_path": "/nonexistent.ts", "line": 1, "character": 0})
            assert result["found"] is False

    def test_get_references_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            disp = ToolDispatcher(project_root=tmp)
            result = disp._handle_references({"file_path": "/nonexistent.ts", "line": 1, "character": 0})
            assert result["found"] is False

    @pytest.mark.asyncio
    async def test_path_validator_rejects_outside(self):
        with tempfile.TemporaryDirectory() as tmp:
            disp = ToolDispatcher(project_root=tmp)
            result = await disp.dispatch("get_file_symbols", {"file_path": "/etc/passwd"})
            assert "error" in result
            assert "Access denied" in result["error"]
