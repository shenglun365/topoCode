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
