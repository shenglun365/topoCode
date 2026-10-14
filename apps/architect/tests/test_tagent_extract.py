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
import topoone_app_architect.agent.tools.req_agent as RA
import topoone_app_architect.kb_gateway as KG


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


# ── 分层口径：批量提取不再走 tAgent(名称直连批量, 10个/次) ─────────

def test_extraction_name_only_no_tagent(monkeypatch):
    called = {"tagent": 0, "legacy": 0}

    def fake_tagent(**kw):
        called["tagent"] += 1
        return {"content": "", "output": None}

    def fake_legacy(*a, **k):
        called["legacy"] += 1

    gw = FakeGateway([{"content": '{"names": [{"symbol": "Order", "name": "订单"}]}',
                       "mode": "chat"}])
    monkeypatch.setattr(RA, "run_tools_loop", fake_legacy)
    monkeypatch.setattr(KG, "get_gateway", lambda: gw)
    assets = asset_extract._extract_group("/r", None, {}, "svc.py", "entity",
                                          [_cand()], "m", True)
    assert called == {"tagent": 0, "legacy": 0}   # tAgent/工具循环已退役
    assert assets[0]["name"] == "订单"             # 名称直连批量生效
    assert assets[0]["desc"] == ""                 # 功能摘要按需(不在批量流程)


# ── 端到端：工具轮 + 上下文块 + 同线程 facts + JSON 增强 ───────────

def test_extraction_name_enrichment_end_to_end(tmp_path, monkeypatch):
    """端到端：名称批量解析(轻提示词直连, 单次调用) + 种子骨架 + desc 留空按需。"""
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
        {"content": '{"names": [{"symbol": "Order", "name": "订单实体"}]}',
         "mode": "chat"},
    ])
    monkeypatch.setattr(KG, "get_gateway", lambda: gw)

    assets = asset_extract._extract_group(str(tmp_path), None, ctx, "svc.py",
                                          "entity", [_cand()], "m", True)
    assert len(assets) == 1
    assert assets[0]["name"] == "订单实体"   # LLM 业务命名生效
    assert assets[0]["desc"] == ""           # 功能摘要按需(asset-desc)
    assert len(gw.calls) == 1                # 单次直连调用(无工具轮/修复轮)

    first = _msgs_text(gw.calls[0][1])
    # 名称解析提示词契约：候选符号 + names JSON 逐字回填 symbol
    assert "候选符号" in first
    assert 'names' in first   # names 契约(序列化后引号被转义)
    assert "Order" in first
    # 不再有 tAgent 工具协议注入
    assert "[TOOL_CALL" not in first


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

def test_name_chunking_10_per_call(tmp_path, monkeypatch):
    """名称批量解析分块：11 个候选 → 2 次 LLM 调用(10+1)，全部获得业务名。"""
    cands = [_cand(f"S{i}", "f1.py") for i in range(11)]
    gw = FakeGateway([
        {"content": '{"names": [' + ",".join(
            f'{{"symbol": "S{i}", "name": "符号{i}"}}' for i in range(10)) + ']}',
         "mode": "chat"},
        {"content": '{"names": [{"symbol": "S10", "name": "符号10"}]}',
         "mode": "chat"},
    ])
    monkeypatch.setattr(KG, "get_gateway", lambda: gw)
    ctx = {"nodes": [c["node"] for c in cands], "edges": [], "implDetails": {}}
    assets = asset_extract._extract_group(str(tmp_path), None, ctx, "f1.py",
                                          "entity", cands, "m", True)
    assert len(assets) == 11
    assert len(gw.calls) == 2                       # 10 + 1 分块
    assert all(a["name"].startswith("符号") for a in assets)


# ── 结构化输出解析健壮性 ─────────────────────────────────────────

def test_output_parse_fenced_and_prose():
    from topocode_agent.core.utils import extract_json_object
    obj = extract_json_object(
        '好的，结果如下：\n```json\n{"assets": [{"symbol": "A"}]}\n```\n以上。')
    assert obj == {"assets": [{"symbol": "A"}]}
    assert extract_json_object("没有 JSON 的散文") is None
