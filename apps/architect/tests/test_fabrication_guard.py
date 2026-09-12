"""防编造守卫 + 待执行会话生成。"""
from topoone_app_architect.arch_routes.req_agent import fabricated_claim
from topoone_app_architect.arch_routes import store


def test_claim_propose_no_tool():
    claim, need = fabricated_claim("已生成结构化需求提案 RQ-WS-REDIS-001", set())
    assert claim and "req.propose" in need


def _ensure_req(rid: str, title: str = "守卫测试") -> None:
    if not store.RequirementsStore.get(rid):
        store.RequirementsStore.create({
            "id": rid, "kind": "user-story", "tier": "raw", "location": "proposal",
            "title": title, "priority": "P1", "status": "raw",
            "desc": "", "acceptance": [], "traceTo": [],
        })


def test_claim_propose_with_tool_ok():
    _ensure_req("RQ-GUARD-OK")
    claim, _ = fabricated_claim("已生成需求提案 RQ-GUARD-OK", {"req.propose"})
    assert claim is None


def test_invented_id():
    # 提及不存在的编号 → 编造(自造编号兜底)
    claim, need = fabricated_claim("提案 RQ-TOTALLY-FAKE-99 已确认", {"req.finalize"})
    assert claim and "RQ-TOTALLY-FAKE-99" in claim and "req.propose" in need


def test_recap_existing_id_ok():
    # 引用既有编号的历史回顾 → 放行
    _ensure_req("RQ-GUARD-RECAP")
    claim, _ = fabricated_claim("你之前的提案已创建（RQ-GUARD-RECAP），等待确认。", set())
    assert claim is None


def test_claim_finalize():
    claim, need = fabricated_claim("方案已定稿，转入待执行。", set())
    assert claim and "req.finalize" in need
    claim, _ = fabricated_claim("方案已定稿，转入待执行。", {"req.finalize"})
    assert claim is None



def test_plain_answer_ok():
    assert fabricated_claim("nginx-http-core 组件的名称如上所述。", set()) == (None, None)


def test_extract_proposal_fence():
    from topoone_app_architect.arch_routes.req_agent import extract_proposal_fence
    text = '前言\n```proposal\n{"title": "T", "designMd": "细节", "estMin": 30}\n```\n后记'
    d = extract_proposal_fence(text)
    assert d and d["title"] == "T" and d["estMin"] == 30
    assert extract_proposal_fence("无围栏") is None
    assert extract_proposal_fence("```json\n{\"a\":1}\n```") is None  # 非 proposal 围栏不认
    assert extract_proposal_fence("```proposal\n{broken\n```") is None


def test_announced_tool_intent():
    from topoone_app_architect.arch_routes.req_agent import announced_tool_intent
    assert announced_tool_intent("请等待我完成上述检索...") != ""
    assert announced_tool_intent("我将立即执行以下检索") != ""
    assert announced_tool_intent("结论：nginx-http-core 是组件名。") == ""


def test_md_lines_tolerates_list():
    from topoone_app_architect.arch_routes.req_agent import _md_lines
    assert _md_lines(["- a.ts", "2. b/", "c"]) == ["a.ts", "b/", "c"]
    assert _md_lines("x\n- y") == ["x", "y"]
    assert _md_lines(None) == []
    assert _md_lines(123) == ["123"]
    # req.propose 全链: 数组字段不再崩
    from topoone_app_architect.arch_routes import store
    from topoone_app_architect.arch_routes import req_agent as R
    r = R.run_arch_tool("req.propose", {
        "title": "数组字段冒烟", "designMd": "d",
        "allowedScopeMd": ["src/a", "src/b"], "forbiddenScopeMd": ["core/"],
        "acceptanceMd": ["构建通过"],
    }, None, None)
    assert r.get("ok"), r
    row = store.RequirementsStore.get(r["requirementId"])
    assert row["analysis"]["allowedScope"] == ["src/a", "src/b"]
    store.RequirementsStore.update(r["requirementId"], {"status": "cancelled"})


def test_intent_patterns_cover_start_and_tool_announce():
    """PR 守卫补强: 「我将立即开始/我将调用工具 X」类宣布必须命中。"""
    from topoone_app_architect.arch_routes.req_agent import announced_tool_intent
    assert announced_tool_intent("我将立即开始代码编写与文件创建工作") != ""
    assert announced_tool_intent("我将调用工具 `req.finalize` 完成归档") != ""
    assert announced_tool_intent("我将开始创建模块目录结构") != ""
    # 纯结论性文本不命中
    assert announced_tool_intent("已完成模块创建, 构建通过。") == ""


# ── 守卫卡片化范式: suggestions / repair_fabricated_claim / propose 回写 ──

def test_guard_suggestions_amend_and_correct():
    from topoone_app_architect.arch_routes.req_agent import guard_suggestions
    s = guard_suggestions("定稿入池(转入待执行)", "req.finalize|req.amend", False)
    labels = [x["label"] for x in s]
    assert "修正落库" in labels and "更正声明" in labels
    assert all(len(x["label"]) <= 8 for x in s)   # 指令简洁(点击区短文案)


def test_guard_suggestions_finalize_only():
    from topoone_app_architect.arch_routes.req_agent import guard_suggestions
    s = guard_suggestions("已定稿", "req.finalize", True)
    actions = [x["action"] for x in s]
    assert "repair_finalize" in actions and "repair_retry" in actions


def test_repair_fabricated_claim_amends(monkeypatch):
    """裸 JSON 载荷 → 修复器提取为 req.amend 并真实执行。"""
    import json
    from topoone_app_architect.arch_routes import req_agent as ra

    _ensure_req("RQ-GUARD-AM")
    captured = {}

    def fake_run_tool(name, args, root=None, project=None):
        captured["name"], captured["args"] = name, args
        return {"ok": True, "reqId": args.get("reqId"), "ver": 2}

    raw = ("```json\n" + json.dumps({
        "title": "非侵入式网关", "designMd": "插件化架构…",
        "acceptanceMd": "- 编译通过",
        "allowedScopeMd": "- modules/gw/\n",
    }) + "\n```")
    monkeypatch.setattr(ra, "llm_sync", lambda *a, **k: {"content":
        f'[TOOL_CALL]{{"tool":"req.amend","arguments":{{"designMd":"插件化架构…",'
        f'"acceptance":["编译通过"],"reasoning":"守卫修复"}}}}[/TOOL_CALL]'})
    monkeypatch.setattr(ra, "run_arch_tool", fake_run_tool)
    r = ra.repair_fabricated_claim("定稿入池(转入待执行)", "req.finalize|req.amend",
                                   raw, req_id="RQ-GUARD-AM")
    assert r["action"] == "amended"
    assert captured["name"] == "req.amend"
    assert captured["args"]["reqId"] == "RQ-GUARD-AM"   # 缺省回填会话绑定


def test_repair_rejects_invented_reqid(monkeypatch):
    """修复器产出自造编号 → 拒绝该调用, 不落库。"""
    from topoone_app_architect.arch_routes import req_agent as ra

    def fake_run_tool(name, args, root=None, project=None):  # 不应被调用
        raise AssertionError("不应执行自造编号的落库")

    monkeypatch.setattr(ra, "llm_sync", lambda *a, **k: {"content":
        '[TOOL_CALL]{"tool":"req.amend","arguments":{"reqId":"RQ-NGW-001",'
        '"designMd":"x"}}[/TOOL_CALL]'})
    monkeypatch.setattr(ra, "run_arch_tool", fake_run_tool)
    r = ra.repair_fabricated_claim("已定稿", "req.amend", "…", req_id="RQ-GUARD-AM")
    assert r["action"] == "failed"


def test_repair_correction_branch(monkeypatch):
    """载荷不可信 → 更正声明(过 fabricated_claim 复查)。"""
    from topoone_app_architect.arch_routes import req_agent as ra
    monkeypatch.setattr(ra, "llm_sync", lambda *a, **k: {"content":
        "【更正】需求定稿动作尚未发生，当前无已定稿的需求。"})
    r = ra.repair_fabricated_claim("已定稿", "req.finalize", "…", req_id="")
    assert r["action"] == "corrected"
    assert "尚未发生" in r["summary"]


def test_propose_writes_back_conv_reqid(monkeypatch):
    """req.propose 新建需求 → 回写会话绑定(conv.reqId 后端真相源)。"""
    from topoone_app_architect.arch_routes import req_agent as ra
    from topoone_app_architect.arch_routes import store, ctx as ctx_mod

    conv_id = f"cv-gw-test-{store.next_id('m')}"
    store.ConversationsStore.create({"id": conv_id, "kind": "asset", "title": "回写测试"})
    try:
        monkeypatch.setattr(ctx_mod, "get_conv", lambda: conv_id, raising=False)
        monkeypatch.setattr(ctx_mod, "get_req", lambda: "", raising=False)
        r = ra.tool_req_propose(title="回写验证需求", designMd="方案x",
                                acceptanceMd="- 验收y", newRequirement=True)
        assert r["ok"]
        row = store.ConversationsStore.get(conv_id)
        assert (row.get("reqId") or "") == r["requirementId"]
    finally:
        try:
            store.ConversationsStore.delete(conv_id)
        except Exception:
            pass
        try:
            store.RequirementsStore.delete(r["requirementId"])
        except Exception:
            pass
