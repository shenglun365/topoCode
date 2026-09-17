"""plan agent 工具调用块解析回归测试：extract_tool_calls / strip_tool_blocks。

覆盖模型输出的各种形态（含畸形：缺前导 '['、外套 markdown 围栏等），
防止「请求完成但工具未调用/裸块上屏」回归。

Run: cd <repo> && python -m pytest apps/architect/tests/test_tool_call_parser.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.arch_routes.req_agent import (
    extract_tool_calls, strip_tool_blocks, tool_parse_audit)


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


class TestUnclosedBlocks:
    """生产实测回归：部分模型省略闭合标签，裸 [TOOL_CALL]{...} 直接跟 JSON。
    旧解析器 0 解析 → 工具不执行、裸块透传上屏(资产管理「提取全部组件」)。"""

    def test_single_unclosed_block(self):
        t = '[TOOL_CALL]{"tool":"a","arguments":{"k":1}}'
        assert extract_tool_calls(t) == [{"tool": "a", "arguments": {"k": 1}}]

    def test_multiple_unclosed_blocks_with_extra_field(self):
        # 用户实测形态：连续 4 个未闭合块，各带额外 message 字段(应忽略)
        t = "\n".join(
            f'[TOOL_CALL]{{"tool":"asset.semantic.extract",'
            f'"arguments":{{"scope":{{"type":"comm","key":"comm-{i}"}},"kinds":["entity"]}},'
            f'"message":"正在提取组件 {i}..."}}'
            for i in range(4))
        calls = extract_tool_calls(t)
        assert len(calls) == 4
        assert all(c["tool"] == "asset.semantic.extract" for c in calls)
        assert calls[0]["arguments"]["scope"]["key"] == "comm-0"
        assert calls[3]["arguments"]["scope"]["key"] == "comm-3"

    def test_unclosed_multiline_json(self):
        t = ('[TOOL_CALL]{\n  "tool": "a",\n  "arguments": {\n    "k": "v"\n  }\n}'
             '\n后续说明')
        assert extract_tool_calls(t) == [{"tool": "a", "arguments": {"k": "v"}}]

    def test_mixed_closed_and_unclosed(self):
        t = ('[TOOL_CALL]{"tool":"a","arguments":{}}[/TOOL_CALL]\n'
             '[TOOL_CALL]{"tool":"b","arguments":{}}')
        assert [c["tool"] for c in extract_tool_calls(t)] == ["a", "b"]

    def test_unclosed_block_with_braces_in_string(self):
        # 字符串内含 '{'/'}' 不得破坏配对
        t = '[TOOL_CALL]{"tool":"a","arguments":{"tpl":"{x} {y}"}}'
        assert extract_tool_calls(t) == [{"tool": "a", "arguments": {"tpl": "{x} {y}"}}]

    def test_prose_mention_not_treated_as_block(self):
        # 无 JSON 的裸提及不当块处理(不误删正文)
        t = '格式参考：TOOL_CALL] 后跟 JSON 即可触发工具。'
        assert extract_tool_calls(t) == []
        assert strip_tool_blocks(t) == t.strip()

    def test_unclosed_stripped(self):
        t = '前言\n[TOOL_CALL]{"tool":"a","arguments":{}}\n后记'
        out = strip_tool_blocks(t)
        assert "TOOL_CALL" not in out
        assert "前言" in out and "后记" in out

    def test_multiple_unclosed_stripped(self):
        t = "\n".join(f'[TOOL_CALL]{{"tool":"t{i}","arguments":{{}}}}' for i in range(3))
        assert "TOOL_CALL" not in strip_tool_blocks(t)


class TestTruncatedJsonBlocks:
    """生产实测回归(cv-182, nginx-src 本地模型)：未闭合 且 JSON 残缺
    (花括号不配对，缺收尾 '}' )——旧解析器 0 regions → strip 失效，
    残缺协议块整段透传落库+假流式重发。修后：认块剥显示，payload 解析
    失败不执行(audit regions>0/valid=0 供数据集回流)，正文提及守卫保留。"""

    CV182_SHAPE = ('[TOOL_CALL]{"tool":"req.propose","arguments":{"title":"x",'
                   '"requirementMd":"构建脚本\\n\\n核心目标：覆盖 {全} 流程。",'
                   '"priority":"P1"')

    def test_truncated_json_region_detected(self):
        audit = tool_parse_audit(self.CV182_SHAPE)
        assert audit == {"regions": 1, "valid": 0}

    def test_truncated_json_not_executed(self):
        # 残缺载荷不得修 parse 后带残参执行
        assert extract_tool_calls(self.CV182_SHAPE) == []

    def test_truncated_json_stripped_clean(self):
        assert strip_tool_blocks(self.CV182_SHAPE) == ""

    def test_truncated_json_with_prose_around(self):
        t = '好的，我来创建需求。\n' + self.CV182_SHAPE
        out = strip_tool_blocks(t)
        assert "TOOL_CALL" not in out
        assert "我来创建需求" in out

    def test_prose_mention_still_guarded(self):
        # 正文提及(后跟散文而非 '{' 载荷)不当块处理
        t = '可输出 [TOOL_CALL] 调用工具，格式见文档。'
        assert tool_parse_audit(t) == {"regions": 0, "valid": 0}
        assert strip_tool_blocks(t) == t.strip()
