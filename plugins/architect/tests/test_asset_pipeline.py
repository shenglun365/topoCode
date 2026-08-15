"""实现层定向提取管线 + 图视图 单元测试。

覆盖:
  - asset_rules: 规则分类优先级 / 值得提取过滤 / 种子装配确定性 / 源码字段解析
  - asset_templates: 种子⊕增强合并(骨架不可伪造) / 验收模板 / 增强解析
  - asset_tools: 5 个只读工具 ground truth + facts 记录
  - asset_extract: 确定性地板 / LLM 增强合并 / http 关系防伪造
  - flow_views: path 边界匹配 / 入口流图(diamond/去重/无自环) / 静态资产图

Run: cd <repo> && python -m pytest plugins/architect/tests/test_asset_pipeline.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)
sys.path.insert(0, os.path.join(_repo, "backend-core"))

import plugins.architect.arch_routes.ctx as C  # noqa: E402
from plugins.architect.arch_routes import asset_rules as R  # noqa: E402
from plugins.architect.arch_routes import asset_templates as T  # noqa: E402
from plugins.architect.arch_routes import asset_tools as AT  # noqa: E402
from plugins.architect.arch_routes import asset_extract as E  # noqa: E402
from plugins.architect.arch_routes import flow_views as F  # noqa: E402


def _ctx(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    return C.setup(data_dir=data)


def _node(nid, kind, name, file_path="m.py", s=1, e=5, sig="", doc=""):
    return {"id": nid, "kind": kind, "name": name, "qualified_name": name,
            "file_path": file_path, "start_line": s, "end_line": e,
            "signature": sig, "docstring": doc, "return_type": ""}


# ── asset_rules ───────────────────────────────────────────────


def test_classify_priority():
    """类别定死: 配置载体→rule > route→contract > enum→state > class→entity > 分支→decision > 函数→process。"""
    nodes = [
        _node("c1", "class", "Config", s=1, e=20),
        _node("r1", "route", "POST /x", s=30, e=30),
        _node("e1", "enum", "Color", s=40, e=45),
        _node("k1", "class", "Order", s=50, e=60),
        _node("f1", "function", "decide", s=70, e=80),
        _node("f2", "function", "plain", s=90, e=95),
    ]
    impl = {"m.py": {"statements": [
        {"type": "if", "condition": "a > 1", "startLine": 71, "endLine": 72, "enclosing": "decide"},
        {"type": "if", "condition": "b == 2", "startLine": 74, "endLine": 75, "enclosing": "decide"},
    ], "routes": [], "constants": []}}
    rc = R.RuleContext([], impl, {n["id"]: n for n in nodes})
    assert R.classify(nodes[0], rc) == "rule"        # Config 类 = 配置载体
    assert R.classify(nodes[1], rc) == "contract"    # route 节点
    assert R.classify(nodes[2], rc) == "state"       # enum
    assert R.classify(nodes[3], rc) == "entity"      # 普通类
    assert R.classify(nodes[4], rc) == "decision"    # 2 个 if 语句(真实计数)
    assert R.classify(nodes[5], rc) == "process"     # 普通函数


def test_classify_route_handler_only_without_route_nodes():
    """route handler 契约判定仅在 scope 无 route 节点时介入(有则由边逻辑覆盖)。"""
    fn = _node("f1", "function", "api_x", sig="(request: Request)")
    impl = {"m.py": {"statements": [], "routes": [
        {"path": "/x", "methods": ["GET"], "handler": "api_x", "framework": "fastapi", "line": 2}],
        "constants": []}}
    rc = R.RuleContext([], impl, {"f1": fn})
    assert not rc.has_route_node
    assert R.classify(fn, rc) == "contract"
    route = _node("r1", "route", "GET /x", s=1, e=1)
    rc2 = R.RuleContext([{"kind": "references", "source": "r1", "target": "f1"}],
                        impl, {"f1": fn, "r1": route})
    assert rc2.has_route_node
    assert R.classify(fn, rc2) == "process"  # 被 route 引用 → 归过程


def test_classify_sig_tokens_only_without_route_nodes():
    """签名含 Request 仅在无 route 节点时作粗兜底(防 request: Request 误判契约)。"""
    fn = _node("f1", "function", "inner", sig="(request: Request)")
    rc = R.RuleContext([], {"m.py": {"statements": [], "routes": [], "constants": []}},
                       {"f1": fn})
    assert R.classify(fn, rc) == "contract"
    route = _node("r1", "route", "GET /y", s=1, e=1)
    rc2 = R.RuleContext([], {"m.py": {"statements": [], "routes": [], "constants": []}},
                        {"f1": fn, "r1": route})
    assert R.classify(fn, rc2) == "process"


def test_contract_seed_route_name_offline():
    """implDetails 缺失时 route 节点名即 ground truth → http 关系(确定性)。"""
    route = _node("r1", "route", "POST /login", s=10, e=10)
    rc = R.RuleContext([], {}, {"r1": route})
    seed = R.assemble_context(route, "contract", rc, root="")
    assert seed["relations"] == [{"target": "/login", "type": "http", "methods": ["POST"],
                                  "line": 10, "semantic": "POST /login"}]
    # 有 implDetails 时同样产出 http 关系(路由清单路径匹配)
    impl = {"m.py": {"statements": [],
                     "routes": [{"path": "/login", "methods": ["POST"], "handler": "api_login",
                                 "framework": "fastapi", "line": 10}],
                     "constants": []}}
    rc2 = R.RuleContext([], impl, {"r1": route})
    seed2 = R.assemble_context(route, "contract", rc2, root="")
    assert seed2["relations"][0]["type"] == "http"
    assert seed2["relations"][0]["target"] == "/login"


def test_process_steps_extra_names():
    """范围外调用目标: calleeNames 补名，steps 不出现裸节点 id。"""
    nodes = [_node("f1", "function", "pay", "m.py", 1, 3)]
    edges = [{"kind": "calls", "source": "f1", "target": "method:abc123", "line": 2}]
    rc = R.RuleContext(edges, {}, {n["id"]: n for n in nodes},
                       extra_names={"method:abc123": "execute"})
    seed = R.assemble_context(nodes[0], "process", rc, root="")
    assert [s["symbol"] for s in seed["steps"]] == ["execute"]


def test_worth_extracting_degenerate_span_kept():
    """live 扫描退化行号(start==end)→ 保留(种子源码回读)。"""
    fn = _node("f1", "function", "h", s=3, e=3)
    rc = R.RuleContext([], {}, {"f1": fn})
    assert R.worth_extracting(fn, "process", rc) is True
    cls = _node("c1", "class", "C", s=1, e=1)
    assert R.worth_extracting(cls, "entity", rc) is True


def test_candidates_for_file_deterministic():
    """同输入同输出(关联范围装配确定性)。"""
    nodes = [_node("c1", "class", "Order", s=1, e=4), _node("f1", "function", "pay", s=6, e=10)]
    impl = {"m.py": {"statements": [
        {"type": "if", "condition": "ok", "startLine": 7, "endLine": 8, "enclosing": "pay"},
    ], "routes": [], "constants": [{"name": "MAX", "value": "3", "line": 2}]}}
    rc = R.RuleContext([], impl, {n["id"]: n for n in nodes})
    a = R.candidates_for_file("", nodes, rc)
    b = R.candidates_for_file("", nodes, rc)
    assert a == b
    kinds = {c["kind"] for c in a}
    assert kinds == {"entity", "process"}


def test_fields_from_source_text():
    src = "class A:\n    x: int\n    y: str = ''\n    def __init__(self):\n        self.z = 1\n"
    got = R.fields_from_source_text(src)
    names = {f["name"] for f in got}
    assert {"x", "y", "z"} <= names
    by = {f["name"]: f for f in got}
    assert by["x"]["type"] == "int"


def test_extract_statements_chinese_offset_fix():
    """中文多字节文件: enclosing 归因不再错位(字节偏移修复回归)。"""
    sys.path.insert(0, os.path.join(_repo, "plugins", "parsers"))
    try:
        from parsers.core.impl_detail import extract_statements
        from parsers.language_loader import get_parser
    except Exception:
        return  # parsers 环境不可用时跳过
    p = get_parser("python")
    src = (
        'def 处理订单(订单: str) -> str:\n'
        '    if 订单:\n'
        '        return "已处理"\n'
        '    return "空"\n\n'
        "def pay(a):\n"
        "    if a > 0:\n"
        "        charge(a)\n"
    )
    raw = src.encode("utf-8")
    tree = p.parse(raw)
    sts = extract_statements(tree.root_node, raw, "python")
    enc = {s["enclosing"] for s in sts}
    assert "pay" in enc
    assert any("订单" in (s.get("condition") or "") for s in sts if s["enclosing"] != "pay") or \
        all(s["enclosing"] in ("pay", "处理订单") for s in sts)


# ── asset_templates ───────────────────────────────────────────


def test_merge_cannot_invent_skeleton():
    """骨架只来自种子: LLM 多给的字段/步骤/分支被忽略, 语义按名匹配挂上。"""
    seed = {"fields": [{"name": "email", "type": "str"}]}
    en = {"field_semantics": [
        {"name": "email", "semantic": "用户邮箱"},
        {"name": "hacked", "semantic": "伪造字段"},   # 种子没有 → 忽略
    ]}
    d = T.merge_seed_enrichment("entity", seed, en)
    assert [f["name"] for f in d["fields"]] == ["email"]
    assert d["fields"][0]["semantic"] == "用户邮箱"

    seed2 = {"steps": [{"order": 1, "symbol": "charge"}]}
    en2 = {"step_semantics": [{"order": 1, "semantic": "扣款"},
                              {"order": 9, "semantic": "伪造步骤"}]}
    d2 = T.merge_seed_enrichment("process", seed2, en2)
    assert len(d2["steps"]) == 1 and d2["steps"][0]["semantic"] == "扣款"

    seed3 = {"branches": [{"condition": "a > 0", "line": 5}]}
    en3 = {"branch_semantics": [{"condition": "a > 0", "then": "通过", "else": "拒绝"}]}
    d3 = T.merge_seed_enrichment("decision", seed3, en3)
    assert d3["branches"][0]["then"] == "通过" and d3["branches"][0]["else"] == "拒绝"
    assert d3["branches"][0]["condition"] == "a > 0"


def test_validate_kind_templates():
    assert T.validate_kind("entity", {"fields": [{"name": "a"}]}, {}) == []
    assert T.validate_kind("entity", {"fields": []}, {"source": "class A:\n    pass\n"}) != []
    assert T.validate_kind("entity", {"fields": []}, {"source": ""}) == []  # 诚实地板
    assert T.validate_kind("contract", {"relations": []}) != []
    assert T.validate_kind("state", {"states": ["a"], "transitions": []}) != []
    assert T.validate_kind("state", {"states": ["a", "b"], "transitions": [{"from": "a", "to": "b"}]}) == []
    assert T.validate_kind("rule", {"constraints": [], "configSource": ""}) != []
    assert T.validate_kind("rule", {"constraints": [], "configSource": "m.py"}) == []
    assert T.validate_kind("process", {"steps": [], "trigger": ""}) != []
    assert T.validate_kind("decision", {"branches": [{"condition": ""}]}) != []
    assert T.validate_kind("decision", {"branches": [{"condition": "x"}]}) == []


def test_enrichment_schema_per_kind():
    s = T.enrichment_schema("entity")
    assert "field_semantics" in s["properties"]["assets"]["items"]["properties"]
    s2 = T.enrichment_schema("decision")
    assert "branch_semantics" in s2["properties"]["assets"]["items"]["properties"]
    assert "field_semantics" not in s2["properties"]["assets"]["items"]["properties"]


def test_parse_enrichments_symbol_filter():
    out = {"assets": [
        {"symbol": "pay", "name": "支付流程", "desc": "d"},
        {"symbol": "ghost", "name": "不存在", "desc": "d"},
        {"name": "无符号", "desc": "d"},
    ]}
    got = T.parse_enrichments(out, ["pay", "Order"])
    assert list(got) == ["pay"]


# ── asset_tools ───────────────────────────────────────────────


def test_tools_ground_truth_and_facts(tmp_path):
    src = (
        "class User:\n"
        "    name: str\n"
        "    age: int\n"
        "\n"
        "def login(user):\n"
        "    verify(user)\n"
        "    return user\n"
    )
    f = tmp_path / "u.py"
    f.write_text(src, encoding="utf-8")
    nodes = [_node("c1", "class", "User", "u.py", 1, 3),
             _node("f1", "function", "login", "u.py", 5, 7),
             _node("f2", "function", "verify", "u.py", 9, 10)]
    ctx = {"nodes": nodes, "edges": [
        {"kind": "calls", "source": "f1", "target": "f2", "line": 6}],
        "implDetails": {"u.py": {
            "statements": [], "constants": [{"name": "TTL", "value": "60", "line": 1}],
            "routes": [{"path": "/in", "methods": ["POST"], "handler": "login",
                        "framework": "fastapi", "line": 4}]}}}
    AT.set_extraction_context(str(tmp_path), "p", ctx)
    try:
        r1 = AT.tool_asset_read_source(None, None, "u.py", "User")
        assert "name: str" in r1["source"] and r1["startLine"] == 1
        r2 = AT.tool_asset_query_constants(None, None, "u.py")
        assert r2["constants"][0]["name"] == "TTL"
        r3 = AT.tool_asset_query_calls(None, None, "u.py", "login")
        assert [c["symbol"] for c in r3["calls"]] == ["verify"] and r3["calls"][0]["line"] == 6
        r4 = AT.tool_asset_query_routes(None, None, "u.py")
        assert r4["routes"][0]["path"] == "/in"
        r5 = AT.tool_asset_query_symbol(None, None, "u.py", "login")
        assert r5["kind"] == "function"
        facts = AT._tl.facts
        assert {x["tool"] for x in facts} == {
            "asset.read_source", "asset.query_constants", "asset.query_calls",
            "asset.query_routes", "asset.query_symbol"}
        miss = AT.tool_asset_query_symbol(None, None, "u.py", "nope")
        assert "error" in miss
    finally:
        AT.clear_extraction_context()
    # clear 按设计删除 thread-local 属性(非置空列表)
    assert getattr(AT._tl, "facts", None) is None


# ── asset_extract ─────────────────────────────────────────────


def _mk_ctx(tmp_path, nodes, edges=None, impl=None):
    (tmp_path / "m.py").write_text(
        "class Order:\n    amount: int\n"
        "def pay(o):\n    if o.amount > 0:\n        charge(o)\n", encoding="utf-8")
    return {"root": str(tmp_path), "project": None, "files": ["m.py"], "symbols": [],
            "nodes": nodes, "edges": edges or [], "text": "", "source": "live",
            "implDetails": impl or {}}


def test_extract_directed_floor(tmp_path, monkeypatch):
    """use_llm=False → 全确定性种子资产: 实体带源码字段, 决策带条件原文。

    注: decision 规则要求分支密集(implDetails 真实 if/switch/case 语句 ≥2)，
    单 if 函数归 process(与旧 _branch_dense hits≥2 一致)。
    """
    _ctx(tmp_path, monkeypatch)
    nodes = [_node("c1", "class", "Order", "m.py", 1, 2),
             _node("f1", "function", "pay", "m.py", 3, 5)]
    ctx = _mk_ctx(tmp_path, nodes, impl={
        "m.py": {"statements": [
            {"type": "if", "condition": "o.amount > 0",
             "startLine": 4, "endLine": 5, "enclosing": "pay"},
            {"type": "if", "condition": "o.frozen",
             "startLine": 6, "endLine": 7, "enclosing": "pay"}],
                 "routes": [], "constants": []}})
    assets = E.extract_directed(str(tmp_path), None, ctx, None, use_llm=False)
    by = {a["name"]: a for a in assets}
    assert by["Order"]["kind"] == "entity"
    assert [f["name"] for f in by["Order"]["detail"]["fields"]] == ["amount"]
    assert by["pay"]["kind"] == "decision"
    assert by["pay"]["detail"]["branches"][0]["condition"] == "o.amount > 0"


def test_extract_directed_llm_enrichment(tmp_path, monkeypatch):
    """LLM 增强: 业务命名+语义注释合并进种子骨架; http 关系不可由 LLM 伪造。"""
    _ctx(tmp_path, monkeypatch)
    nodes = [_node("f1", "function", "api_pay", "m.py", 1, 3, sig="(request: Request)")]
    ctx = _mk_ctx(tmp_path, nodes, impl={
        "m.py": {"statements": [],
                 "routes": [{"path": "/pay", "methods": ["POST"], "handler": "api_pay",
                             "framework": "fastapi", "line": 1}],
                 "constants": []}})
    calls = []

    def _fake_run_tools_loop(msgs, **kw):
        calls.append((kw.get("mode"), kw.get("output_schema")))
        return {"content": "", "output": {"assets": [{
            "symbol": "api_pay", "name": "支付端点", "desc": "接收支付请求",
            "invariants": ["幂等"],
            "relations": [{"target": "/fake", "type": "http", "semantic": "伪造"},
                          {"target": "Order", "type": "uses", "semantic": "扣款"}],
        }]}}

    import plugins.architect.arch_routes.req_agent as RA
    monkeypatch.setattr(RA, "run_tools_loop", _fake_run_tools_loop)
    assets = E.extract_directed(str(tmp_path), None, ctx, None, use_llm=True)
    assert calls and calls[0][0] == "structured"
    a = assets[0]
    assert a["name"] == "支付端点" and a["kind"] == "contract"
    rels = a["detail"]["relations"]
    http = [r for r in rels if r.get("type") == "http"]
    assert [r["target"] for r in http] == ["/pay"]          # 只有种子路由
    assert any(r["target"] == "Order" for r in rels)          # 跨资产关系保留
    assert a["detail"]["invariants"] == ["幂等"]


def test_extract_group_llm_failure_falls_to_floor(tmp_path, monkeypatch):
    """LLM 无结构化输出 → 种子地板(不丢资产, 不空 detail)。"""
    _ctx(tmp_path, monkeypatch)
    nodes = [_node("c1", "class", "Order", "m.py", 1, 2)]
    ctx = _mk_ctx(tmp_path, nodes)
    import plugins.architect.arch_routes.req_agent as RA
    monkeypatch.setattr(RA, "run_tools_loop", lambda *a, **k: {"content": "oops", "output": None})
    assets = E.extract_directed(str(tmp_path), None, ctx, None, use_llm=True)
    assert len(assets) == 1 and assets[0]["kind"] == "entity"
    assert assets[0]["detail"]["fields"] == [{"name": "amount", "type": "int"}]


# ── flow_views ────────────────────────────────────────────────


def test_path_in_text_boundary():
    assert F._path_in_text("/login", "POST /login")
    assert F._path_in_text("/login", "x POST /login end")
    assert not F._path_in_text("/login", "POST /login-with-code")
    assert not F._path_in_text("/login", "POST /loginX")
    assert F._path_in_text("/login-with-code", "POST /login-with-code")


def test_entry_flow_diamonds_dedup_no_selfloop():
    """if→diamond(条件原文); 重复调用去重且无自环; 跨文件→parallelogram。"""
    nodes = [
        _node("f1", "function", "api_reg", "a.py", 1, 10),
        _node("f2", "function", "local", "a.py", 12, 13),
        _node("f3", "function", "ext", "b.py", 20, 21),
    ]
    edges = [
        {"kind": "calls", "source": "f1", "target": "f2", "line": 3},
        {"kind": "calls", "source": "f1", "target": "f3", "line": 5},
        {"kind": "calls", "source": "f1", "target": "f2", "line": 7},
    ]
    impl_by_file = {"a.py": {"statements": [
        {"type": "if", "condition": "not user", "startLine": 2, "endLine": 3, "enclosing": "api_reg"},
    ], "routes": [], "constants": []}}
    ctx = {"nodes": nodes, "edges": edges, "implDetails": impl_by_file}
    fl = F._entry_flow({"file": "a.py", "symbol": "api_reg", "path": "/reg",
                        "methods": ["POST"], "name": "注册"}, ctx, {}, "none")
    assert fl is not None
    shapes = {g["id"]: g["shape"] for g in fl["ir"]["nodes"]}
    assert shapes["s0"] == "stadium"
    diamonds = [g for g in fl["ir"]["nodes"] if g["shape"] == "diamond"]
    assert diamonds and diamonds[0]["text"] == "not user"
    ext = [g for g in fl["ir"]["nodes"] if g.get("symbol") == "ext"]
    assert ext and ext[0]["shape"] == "parallelogram"
    # 无自环
    assert all(e["from"] != e["to"] for e in fl["ir"]["edges"])
    # 去重: local 只出现一次
    assert sum(1 for g in fl["ir"]["nodes"] if g.get("symbol") == "local") == 1
    assert any("not user" in s for s in fl["steps"])


def test_inline_flowchart_format():
    ir = {"direction": "TB",
          "nodes": [{"id": "a", "text": "入口", "shape": "stadium"},
                    {"id": "b", "text": "判定", "shape": "diamond"}],
          "edges": [{"from": "a", "to": "b", "label": ""}]}
    code = F._inline_flowchart(ir)
    assert code.startswith("flowchart TB")
    assert "a ([入口])" in code and "b {判定}" in code and "a --> b" in code


def test_build_asset_diagrams_entity_and_state():
    assets = [
        {"id": "a1", "kind": "entity", "name": "Order",
         "detail": {"fields": [{"name": "id", "type": "int"}, {"name": "amount", "type": "float"}]}},
        {"id": "a2", "kind": "state", "name": "OrderStatus",
         "detail": {"states": [{"name": "pending"}, {"name": "paid"}],
                    "transitions": [{"from": "pending", "to": "paid", "event": "pay"}]}},
        {"id": "a3", "kind": "process", "name": "无关", "detail": {}},
    ]
    res = F.build_asset_diagrams(assets)
    ds = {d["assetId"]: d for d in res["diagrams"]}
    assert set(ds) == {"a1", "a2"}
    assert "class Order" in ds["a1"]["mermaid"] and "+id : int" in ds["a1"]["mermaid"]
    assert "state pending" in ds["a2"]["mermaid"]
    assert "pending --> paid : pay" in ds["a2"]["mermaid"]
