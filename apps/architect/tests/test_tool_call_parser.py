"""plan agent 工具调用块解析回归测试：extract_tool_calls / strip_tool_blocks。

覆盖模型输出的各种形态（含畸形：缺前导 '['、外套 markdown 围栏等），
防止「请求完成但工具未调用/裸块上屏」回归。

Run: cd <repo> && python -m pytest apps/architect/tests/test_tool_call_parser.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.arch_routes.req_agent import extract_tool_calls, strip_tool_blocks


class TestExtractToolCalls:
    def test_standard(self):
        t = '[TOOL_CALL]{"tool":"project.ctx","arguments":{}}[/TOOL_CALL]'
        assert extract_tool_calls(t) == [{"tool": "project.ctx", "arguments": {}}]

    def test_malformed_missing_open_bracket_with_fence(self):
        # 模型丢前导 '[' 且外套围栏: ```TOOL_CALL]{...}[/TOOL_CALL]```
        t = '前言\n\n```TOOL_CALL]{"tool":"project.ctx","arguments":{}}[/TOOL_CALL]\n```'
        assert extract_tool_calls(t) == [{"tool": "project.ctx", "arguments": {}}]

    def test_fence_with_json_label(self):
        t = '```json\n[TOOL_CALL]{"tool":"kb.baseline","arguments":{}}[/TOOL_CALL]\n```'
        assert extract_tool_calls(t) == [{"tool": "kb.baseline", "arguments": {}}]

    def test_fence_inside_block(self):
        t = '[TOOL_CALL]\n```json\n{"tool":"kb.graph","arguments":{"comp_ids":["a"]}}\n```\n[/TOOL_CALL]'
        assert extract_tool_calls(t) == [{"tool": "kb.graph", "arguments": {"comp_ids": ["a"]}}]

    def test_tolerant_close_tag(self):
        t = '[TOOL_CALL]{"tool":"x","arguments":{}}[/TOOL_CALL>]'
        assert extract_tool_calls(t) == [{"tool": "x", "arguments": {}}]

    def test_multiple_blocks(self):
        t = ('[TOOL_CALL]{"tool":"a","arguments":{}}[/TOOL_CALL] '
             '文本 [TOOL_CALL]{"tool":"b","arguments":{}}[/TOOL_CALL]')
        assert [c["tool"] for c in extract_tool_calls(t)] == ["a", "b"]

    def test_malformed_json_skipped(self):
        t = '[TOOL_CALL]{not json}[/TOOL_CALL]'
        assert extract_tool_calls(t) == []

    def test_no_block(self):
        assert extract_tool_calls("正常回答，无工具调用") == []

    def test_empty(self):
        assert extract_tool_calls("") == []
        assert extract_tool_calls(None) == []


class TestStripToolBlocks:
    def test_standard_stripped(self):
        t = 'x[TOOL_CALL]{"tool":"a","arguments":{}}[/TOOL_CALL]y'
        assert strip_tool_blocks(t) == "xy"

    def test_malformed_stripped(self):
        t = '前言\n\n```TOOL_CALL]{"tool":"project.ctx","arguments":{}}[/TOOL_CALL]\n```'
        assert "TOOL_CALL" not in strip_tool_blocks(t)
        assert "前言" in strip_tool_blocks(t)
