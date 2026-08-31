"""I5c 测试：语义资产提取 → tAgent 上下文编译循环（方案 B）。

fake gateway（duck-typed .call）脚本化 llm.sync 响应，零真实 HTTP/LLM。
验证：
- 双轨已取消：提取恒走 tAgent 路径（不再回退 run_tools_loop）；
- 端到端：TextFallback [TOOL_CALL: name] 工具轮 + 底座(钉驻任务规格)写入 system
  + 上下文块注入(工具结果入清单) + JSON 解析增强；
- 工具同线程执行（in_thread=False，thread-local facts/ctx 亲和）；
- 可达性豁免：任务文件条目不被 LRU 误删（最旧条目也保留）；
- 共享 cm 注入：清单跨 (文件×类型) 组累积（长 cm 扩展口）；
- JSON 解析健壮性（围栏/前后文 prose）。
"""
import json
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.arch_routes import asset_extract
from topoone_app_architect.arch_routes import tagent_extract
import topoone_app_architect.arch_routes.req_agent as RA
import topoone_app_architect.arch_routes.kb_gateway as KG


class FakeGateway:
    """duck-typed KbGateway：.call(method, **params) 按脚本返回。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def call(self, method, timeout=None, **params):
        self.calls.append((method, params))
        if method != "llm.sync":
            return None
        if not self.script:
            return {"content": "", "mode": "chat"}
        return self.script.pop(0)


def _cand(sym="Order", file_="svc.py", kind="class"):
    return {"node": {"id": f"n-{sym}", "name": sym, "qualified_name": sym,
                     "file_path": file_, "kind": kind, "start_line": 1, "end_line": 4,
                     "signature": f"class {sym}:", "docstring": "订单"},
            "seed": {"fields": [{"name": "id", "type": "int"}]}}


def _msgs_text(call_params):
    return json.dumps(call_params.get("messages") or [], ensure_ascii=False)


# ── 双轨已取消：恒走 tAgent ──────────────────────────────────────

def test_extraction_always_uses_tagent(monkeypatch):
    called = {"tagent": 0, "legacy": 0}

    def fake_tagent(**kw):
        called["tagent"] += 1
        return {"content": "", "output": None}

    def fake_legacy(*a, **k):
        called["legacy"] += 1
        return {"content": "", "output": None}

    monkeypatch.setattr(tagent_extract, "run_extraction_agentic", fake_tagent)
    monkeypatch.setattr(RA, "run_tools_loop", fake_legacy)
    asset_extract._extract_group("/r", None, {}, "svc.py", "entity",
                                 [_cand()], "m", True)
    assert called == {"tagent": 1, "legacy": 0}


# ── 端到端：工具轮 + 上下文块 + 同线程 facts + JSON 增强 ───────────

def test_extraction_end_to_end_tool_loop(tmp_path, monkeypatch):
    src = tmp_path / "svc.py"
    src.write_text(
        "class Order:\n    def __init__(self):\n        self.id = 0\n"
        "        self.amount = 0\n", encoding="utf-8")
    ctx = {"nodes": [{"id": "n1", "name": "Order", "qualified_name": "Order",
                      "file_path": "svc.py", "kind": "class", "start_line": 1,
                      "end_line": 4, "signature": "class Order:",
                      "docstring": "订单"}],
           "edges": [], "implDetails": {}}
    gw = FakeGateway([
        {"content": '[TOOL_CALL: asset_read_source]\n'
                    '{"file": "svc.py", "symbol": "Order"}\n[/TOOL_CALL]',
         "mode": "chat"},
        {"content": '{"assets": [{"symbol": "Order", "name": "订单实体", '
                    '"desc": "订单核心实体"}]}', "mode": "chat"},
    ])
    monkeypatch.setattr(KG, "get_gateway", lambda: gw)

    assets = asset_extract._extract_group(str(tmp_path), None, ctx, "svc.py",
                                          "entity", [_cand()], "m", True)
    assert len(assets) == 1
    assert assets[0]["name"] == "订单实体"  # LLM 增强生效(非地板)
    assert len(gw.calls) == 2              # 工具轮 + 终调

    first = _msgs_text(gw.calls[0][1])
    # system 含：基座提示 + 钉驻任务规格(底座) + TextFallback 工具注入
    assert "你是代码语义资产补齐器" in first
    assert "候选类别(规则定死" in first
    assert "Available tools" in first
    # 协议切换：TextFallback [TOOL_CALL: name] 格式，无旧 [TOOL_CALL]{"tool" 协议
    assert "[TOOL_CALL: tool_name]" in first
    assert '[TOOL_CALL]{"tool"' not in first

    second = _msgs_text(gw.calls[1][1])
    # 工具结果经 observe_tool_result 入清单 → 第二轮编译注入上下文块
    assert "<<<TOPOCODE_CONTEXT>>>" in second
    assert "<<<END_TOPOCODE_CONTEXT>>>" in second
    # 工具确实执行且返回源码（thread-local ctx 同线程可见；否则报"符号未找到"）
    assert "self.id = 0" in second
    assert "符号未找到" not in second


# ── build_extraction_context ─────────────────────────────────────

def test_build_extraction_context_pins_spec_and_task_file():
    cm = tagent_extract.build_extraction_context(
        file_="svc.py", kind="entity", task_spec="SPEC-TEXT")
    assert cm.phase == "kb_analysis"
    assert cm.task_files == ["svc.py"]
    assert cm.reachability is not None
    assert "SPEC-TEXT" in cm.compile().system_base


# ── 可达性豁免：任务文件条目不被 LRU 误删 ─────────────────────────

def test_reachability_protects_task_file_entry():
    from topocode_agent.core.context import ContextManager
    from topocode_agent.core.context.reachability import ReachabilityAnalyzer

    cm = ContextManager(phase="kb_analysis", max_chars=900,
                        reachability=ReachabilityAnalyzer(kb=None))
    cm.set_task_files(["svc/order.py"])
    cm.pin_requirement("任务规格：维护订单逻辑")
    # 任务文件条目最旧（LRU 首选 victim）——无豁免必被先删
    cm.put("artifact", "order-active", "ORDER_ACTIVE_MARKER " * 4,
           meta={"path": "svc/order.py"})
    for i in range(40):
        cm.put("artifact", f"filler-{i}", f"filler-body-{i} " + "x" * 80,
               meta={"path": f"other/f{i % 7}.py"})
    block = ContextManager.build_block(cm.compile())
    assert "ORDER_ACTIVE_MARKER" in block            # 可达条目全文保留
    bodies = [i for i in range(40) if f"filler-body-{i}" in block]
    assert len(bodies) < 40                          # 部分 filler 被淘汰/降级


# ── 共享 cm 注入：跨 (文件×类型) 组累积（长 cm 扩展口）─────────────

def test_shared_cm_accumulates_across_groups(tmp_path, monkeypatch):
    from topocode_agent.core.context import ContextManager

    monkeypatch.delenv("TOPOCODE_CTX_ASSET", raising=False)
    shared = ContextManager(phase="kb_analysis")
    shared.pin_requirement("shared-spec-文本")
    gw = FakeGateway([
        {"content": '{"assets": [{"symbol": "A", "name": "实体A", "desc": "d"}]}',
         "mode": "chat"},
        {"content": '{"assets": [{"symbol": "B", "name": "实体B", "desc": "d"}]}',
         "mode": "chat"},
    ])
    monkeypatch.setattr(KG, "get_gateway", lambda: gw)
    ctx = {"nodes": [{"id": "nA", "name": "A", "qualified_name": "A",
                      "file_path": "f1.py", "kind": "class", "start_line": 1,
                      "end_line": 2, "signature": "class A:", "docstring": ""},
                     {"id": "nB", "name": "B", "qualified_name": "B",
                      "file_path": "f2.py", "kind": "class", "start_line": 1,
                      "end_line": 2, "signature": "class B:", "docstring": ""}],
           "edges": [], "implDetails": {}}

    a1 = asset_extract._extract_group(str(tmp_path), None, ctx, "f1.py",
                                      "entity", [_cand("A", "f1.py")], "m", True,
                                      shared)
    a2 = asset_extract._extract_group(str(tmp_path), None, ctx, "f2.py",
                                      "entity", [_cand("B", "f2.py")], "m", True,
                                      shared)
    assert a1[0]["name"] == "实体A" and a2[0]["name"] == "实体B"
    assert len(gw.calls) == 2
    assert shared.turn >= 2                          # 同一 cm 跨组累积轮次
    # 第二组 system 仍含共享钉驻规格（底座常驻）
    assert "shared-spec-文本" in _msgs_text(gw.calls[1][1])


# ── 结构化输出解析健壮性 ─────────────────────────────────────────

def test_output_parse_fenced_and_prose():
    from topocode_agent.core.utils import extract_json_object
    obj = extract_json_object(
        '好的，结果如下：\n```json\n{"assets": [{"symbol": "A"}]}\n```\n以上。')
    assert obj == {"assets": [{"symbol": "A"}]}
    assert extract_json_object("没有 JSON 的散文") is None
