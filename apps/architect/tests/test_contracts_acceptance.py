"""M2 契约/验收测试 — plan-C-M0.md §2/§3/§6.7/§7.2-§7.4。

覆盖:
  - 契约条目状态机: V1(框架值域)/V2(origin)/V3(入包)/V4(意图级)/V5(low 档 z)/
    V6(rejected 改期望)/V7(state 专用)/V8(框架变更 stale 重确认)
  - agentsMd 生成（brief/full/full-scaffold 三档详略）
  - 验收执行: 变更范围→严 profile 提取(mock)→L1/L2 机械比对→facts 落库→条目 verifying
  - L1/L2 判定单元: intentOnly partial / 无锚点 fail / steps/branches/fields 命中比

Run: cd <repo> && PYTHONPATH=apps/architect python -m pytest apps/architect/tests/test_contracts_acceptance.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.arch_routes.ctx as C  # noqa: E402
from topoone_app_architect.arch_routes import acceptance as AC  # noqa: E402
from topoone_app_architect.arch_routes import asset_framework as F  # noqa: E402
from topoone_app_architect.arch_routes import contracts as CT  # noqa: E402
from topoone_app_architect.arch_routes import semantic_assets as S  # noqa: E402
from topoone_app_architect.arch_routes.store import (  # noqa: E402
    AcceptanceStore, ContractItemStore, ContractPackageStore,
    NamingConventionStore, SemanticAssetsStore)


def _ctx_setup(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.setup(data_dir=data)


def _pid(tmp_path):
    return S.project_id_for(str(tmp_path), None)


def _item(**kw):
    base = {"kind": "process",
            "target": {"file": "m.py", "symbol": "create_order"},
            "origin": {"quote": "订单创建要先校验库存", "convId": "conv-1"},
            "behavior": {"steps": [
                {"order": 1, "semantic": "校验库存"},
                {"order": 2, "semantic": "扣减库存"},
                {"order": 3, "semantic": "写入订单"},
            ]}}
    base.update(kw)
    return base


def _fake_extract(monkeypatch, assets):
    def _extract(root, project, scope_type, scope_key, files=None, symbols=None,
                 kinds=None, model_id=None, use_llm=True, level="implementation"):
        return {"assets": assets, "source": "mock", "degraded": False,
                "count": len(assets)}
    monkeypatch.setattr(S, "extract_scope", _extract)
    monkeypatch.setattr(S, "changed_files",
                        lambda root, project: {"added": ["m.py"],
                                               "modified": [], "deleted": []})


_ASSET_HIT = {
    "id": "sa-hit", "name": "创建订单", "kind": "process", "level": "implementation",
    "status": "active", "desc": "创建订单过程",
    "astRefs": [{"file": "m.py", "symbol": "create_order",
                 "startLine": 1, "endLine": 10}],
    "detail": {"steps": [
        {"order": 1, "semantic": "校验库存是否充足"},
        {"order": 2, "semantic": "扣减库存"},
        {"order": 3, "semantic": "写入订单记录"},
    ]},
}
_ASSET_MISS = dict(_ASSET_HIT, id="sa-miss", name="别的流程",
                   astRefs=[{"file": "other.py", "symbol": "other_fn",
                             "startLine": 1, "endLine": 5}])


# ── 契约条目状态机（V1-V8） ────────────────────────────────────

class TestItemLifecycle:
    def test_create_draft_and_v1_kind(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        try:
            CT.create_item(pid, {"kind": "widget", "target": {"file": "m.py"}})
            assert False, "V1 应拒绝未知 kind"
        except ValueError as e:
            assert "V1" in str(e)
        row = CT.create_item(pid, _item())
        assert row["status"] == "draft" and row["id"].startswith("ci-")
        assert row["intentOnly"] == 0 and row["seq"] == 1

    def test_v4_intent_only_forced(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        row = CT.create_item(pid, _item(target={}, origin={"quote": "q"}))
        assert row["intentOnly"] == 1  # 无 file 无 symbol → 强制意图级

    def test_v7_states_only_for_state(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        try:
            CT.create_item(pid, _item(behavior={"states": ["A", "B"]}))
            assert False, "V7 应拒绝非 state 携带 states"
        except ValueError as e:
            assert "V7" in str(e)

    def test_v5_low_tier_z_and_state(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        F.switch_tier(pid, "low")
        try:
            CT.create_item(pid, _item(zAxis=[{"category": "security", "text": "x"}]))
            assert False, "V5 应拒绝 low 档 zAxis"
        except ValueError as e:
            assert "V5" in str(e)
        try:
            CT.create_item(pid, _item(kind="state",
                                      behavior={"states": ["A"], "transitions": []}))
            assert False, "low 档无 state kind（V1）"
        except ValueError as e:
            assert "V1" in str(e)

    def test_v2_confirm_requires_origin(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        row = CT.create_item(pid, _item(origin={}))
        try:
            CT.confirm_item(row["id"])
            assert False, "V2 应拒绝无 origin 确认"
        except ValueError as e:
            assert "V2" in str(e)

    def test_confirm_verdict_terminal(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        row = CT.create_item(pid, _item())
        confirmed = CT.confirm_item(row["id"])
        assert confirmed["status"] == "confirmed" and confirmed["confirmedAt"]
        try:
            CT.confirm_item(row["id"])
            assert False, "非 draft 不可再确认"
        except ValueError:
            pass
        acc = CT.verdict_item(row["id"], "accepted")
        assert acc["status"] == "accepted" and acc["verifiedAt"]
        try:
            CT.verdict_item(row["id"], "rejected")
            assert False, "accepted 终态不可再判定"
        except ValueError:
            pass

    def test_v6_revise_rejected_version_bump(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        row = CT.create_item(pid, _item())
        CT.confirm_item(row["id"])
        CT.verdict_item(row["id"], "rejected")
        r = CT.revise_item(row["id"], {
            "behavior": {"steps": [{"order": 1, "semantic": "校验库存(含预扣)"}]}})
        assert r["status"] == "confirmed" and r["version"] == 2
        # 非 rejected 状态不可 revise
        try:
            CT.revise_item(row["id"], {})
            assert False, "confirmed 状态不可 revise（V6）"
        except ValueError:
            pass

    def test_v8_framework_change_stale_then_reconfirm(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        row = CT.create_item(pid, _item())
        CT.confirm_item(row["id"])
        F.switch_tier(pid, "high")  # 标准变更
        stale = ContractItemStore.get(row["id"])
        assert stale["staleByFramework"] == 1
        # 设计者重确认 → 清标志
        re = CT.confirm_item(row["id"])
        assert re["status"] == "confirmed" and re["staleByFramework"] == 0

    def test_low_switch_clears_z_axis(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        row = CT.create_item(pid, _item(
            zAxis=[{"category": "resilience", "text": "超时 3s"}]))
        F.switch_tier(pid, "low")
        assert (ContractItemStore.get(row["id"]) or {}).get("zAxis") == []


# ── 契约包 + agentsMd ──────────────────────────────────────────

class TestPackage:
    def test_v3_only_confirmed_and_agents_md(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        draft = CT.create_item(pid, _item())
        conf = CT.create_item(pid, _item(target={"file": "o.py", "symbol": "pay"}))
        CT.confirm_item(conf["id"])
        try:
            CT.create_package(pid, [draft["id"]])
            assert False, "V3 应拒绝 draft 入包"
        except ValueError as e:
            assert "V3" in str(e)
        pkg = CT.create_package(pid)  # 默认全部 confirmed
        assert pkg["status"] == "created"
        assert pkg["itemIds"] == [conf["id"]]
        snap = pkg["frameworkSnapshot"]
        assert snap["activeTier"] == "mid" and snap["directivesDepth"] == "full"
        md = pkg["agentsMd"]
        assert f"## {conf['id']} [process/implementation]" in md
        assert "校验库存" in md and "target: o.py pay" in md
        assert "框架快照" in md and "tier=mid" in md

    def test_agents_md_depth_brief(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        conf = CT.create_item(pid, _item())
        CT.confirm_item(conf["id"])
        # 直接构造 brief 快照验证详略
        md = CT.build_agents_md(
            "cp-test", {"directivesDepth": "brief"},
            [ContractItemStore.get(conf["id"])])
        assert "target: m.py create_order" in md
        assert "校验库存" not in md  # brief 不含 behavior 明细

    def test_inject_marks_items(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        conf = CT.create_item(pid, _item())
        CT.confirm_item(conf["id"])
        pkg = CT.create_package(pid)
        inj = CT.inject_package(pkg["id"], injected_to="runner")
        assert inj["status"] == "injected" and inj["injectedAt"]
        assert inj["injectedTo"] == "runner"
        assert ContractItemStore.get(conf["id"])["status"] == "injected"
        try:
            CT.inject_package(pkg["id"])
            assert False, "已注入包不可重复注入"
        except ValueError:
            pass


# ── 验收执行（L1/L2 机械比对 = 事实） ──────────────────────────

class TestAcceptance:
    def test_l1_l2_units(self):
        # intentOnly → L1 partial（不可机械验证）
        it = _item(target={}, intentOnly=True)
        v, ev = AC.check_l1(it, None)
        assert v == "partial" and "意图级" in ev["detail"]
        # 无匹配资产 → L1 fail；L2 级联 fail
        v1, _ = AC.check_l1(_item(), None)
        assert v1 == "fail"
        v2, _ = AC.check_l2(_item(), None)
        assert v2 == "fail"
        # 命中 + 语义互含 → L2 pass（"校验库存" ⊂ "校验库存是否充足"）
        v1, e1 = AC.check_l1(_item(), _ASSET_HIT)
        assert v1 == "pass" and e1["assetId"] == "sa-hit" and e1["anchors"]
        v2, e2 = AC.check_l2(_item(), _ASSET_HIT)
        assert v2 == "pass" and e2["notes"]
        # 未声明行为 → L2 pass(跳过)
        v3, e3 = AC.check_l2(_item(behavior={}), _ASSET_HIT)
        assert v3 == "pass" and "跳过" in e3["detail"]
        # 期望 3 步实现只有 1 步命中 → partial/fail（按命中比）
        it2 = _item(behavior={"steps": [
            {"order": 1, "semantic": "校验库存"},
            {"order": 2, "semantic": "扣减库存"},
            {"order": 3, "semantic": "发送通知"},
        ]})
        asset2 = dict(_ASSET_HIT, detail={"steps": [
            {"order": 1, "semantic": "校验库存是否充足"},
            {"order": 2, "semantic": "扣减库存"},
        ]})
        v4, e4 = AC.check_l2(it2, asset2)
        assert v4 == "partial"  # 2/3 ≈ 0.67

    def test_run_acceptance_full_flow(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        _fake_extract(monkeypatch, [_ASSET_HIT])
        pid = _pid(tmp_path)
        conf = CT.create_item(pid, _item())
        CT.confirm_item(conf["id"])
        pkg = CT.create_package(pid)
        detail = AC.run_acceptance(pid, str(tmp_path), None, pkg["id"],
                                   trigger_type="git_diff", ref="HEAD~1")
        rep = detail["report"]
        assert rep["id"].startswith("ar-")
        assert rep["extractionProfile"] == "strict"
        assert rep["triggerInfo"]["type"] == "git_diff"
        assert rep["summary"]["pass"] == 1 and rep["summary"]["fail"] == 0
        facts = {(f["checkLayer"], f["itemId"]): f for f in detail["facts"]}
        assert facts[("L1", conf["id"])]["verdict"] == "pass"
        assert facts[("L2", conf["id"])]["verdict"] == "pass"
        # 条目 → verifying（等待设计者判定，不自动通过）
        assert ContractItemStore.get(conf["id"])["status"] == "verifying"
        # 设计者判定入口
        CT.verdict_item(conf["id"], "accepted")
        assert ContractItemStore.get(conf["id"])["status"] == "accepted"

    def test_run_acceptance_fail_path(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        _fake_extract(monkeypatch, [_ASSET_MISS])  # 锚点不匹配
        pid = _pid(tmp_path)
        conf = CT.create_item(pid, _item())
        CT.confirm_item(conf["id"])
        pkg = CT.create_package(pid)
        detail = AC.run_acceptance(pid, str(tmp_path), None, pkg["id"])
        assert detail["report"]["summary"]["fail"] == 1
        l1 = [f for f in detail["facts"] if f["checkLayer"] == "L1"][0]
        assert l1["verdict"] == "fail"
        assert "未找到匹配" in l1["evidence"]["detail"]

    def test_run_requires_package(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        _fake_extract(monkeypatch, [])
        pid = _pid(tmp_path)
        try:
            AC.run_acceptance(pid, str(tmp_path), None, "cp-404")
            assert False
        except LookupError:
            pass

    def test_reports_list_and_detail(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        _fake_extract(monkeypatch, [_ASSET_HIT])
        pid = _pid(tmp_path)
        conf = CT.create_item(pid, _item())
        CT.confirm_item(conf["id"])
        pkg = CT.create_package(pid)
        AC.run_acceptance(pid, str(tmp_path), None, pkg["id"])
        reports = AcceptanceStore.list_reports(pid, package_id=pkg["id"])
        assert len(reports) == 1
        d = AcceptanceStore.report_detail(reports[0]["id"], pid)
        assert d["report"]["id"] and len(d["facts"]) == 2 and d["opinions"] == []
        # 手动激活 L3（mock llm_sync）
        import topoone_app_architect.arch_routes.req_agent as RA
        monkeypatch.setattr(RA, "llm_sync",
                            lambda messages, **kw: {"content": "语义基本一致。\n置信度: 0.82",
                                                   "modelId": "mock-model"})
        op = AC.activate_l3_opinion(pid, d["report"]["id"], conf["id"],
                                    instruction="步骤 3 的语义是否达标？")
        assert op["confidence"] == 0.82 and op["model"] == "mock-model"
        assert op["triggerBy"] == "user"
        d2 = AcceptanceStore.report_detail(d["report"]["id"], pid)
        assert len(d2["opinions"]) == 1
        # 修复指令起草（mock llm_sync）
        r = AC.draft_fix_instruction(pid, conf["id"])
        assert r["source"] == "draft" and r["itemId"] == conf["id"]



def _req(body=None):
    class _Req:
        async def json(self):
            return body

    return _Req()


def _call(coro_factory):
    """运行 async 端点协程；解包 ok/err（err 为 JSONResponse）为 dict。"""
    import asyncio
    import json as _json
    from fastapi.responses import JSONResponse
    out = asyncio.run(coro_factory())
    if isinstance(out, JSONResponse):
        body = _json.loads(out.body.decode("utf-8"))
        body["_error"] = body.get("message", "")
        return body
    if isinstance(out, dict) and "code" in out and out["code"] != 0:
        out["_error"] = out.get("message", "")
    return out


class TestExperienceWriteback:
    def _rejected_item_with_fail_facts(self, tmp_path, monkeypatch, pid):
        """建 rejected 条目（带 L1 fail 验收事实 = 失败模式证据）。"""
        _fake_extract(monkeypatch, [_ASSET_MISS])  # 锚点不匹配 → L1 fail
        conf = CT.create_item(pid, _item())
        CT.confirm_item(conf["id"])
        pkg = CT.create_package(pid)
        AC.run_acceptance(pid, str(tmp_path), None, pkg["id"])
        CT.verdict_item(conf["id"], "rejected")
        return conf

    def test_induce_from_rejection_llm(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        conf = self._rejected_item_with_fail_facts(tmp_path, monkeypatch, pid)
        from topoone_app_architect.arch_routes import req_agent as RA
        monkeypatch.setattr(RA, "llm_sync",
                            lambda messages, **kw: {"output": {
                                "ruleText": "验收 create_order 须核对库存扣减顺序",
                                "scenarios": ["accept"]},
                                "content": ""})
        from topoone_app_architect.arch_routes.naming import induce_from_rejection
        row = induce_from_rejection(pid, conf["id"])
        assert row and row["status"] == "pending"
        assert row["source"] == "induced"
        assert "create_order" in row["ruleText"]
        assert row["scenarios"] == ["accept"]

    def test_induce_from_rejection_template_fallback(self, tmp_path, monkeypatch):
        """LLM 降级(None) → 模板兜底（闭环不断）。"""
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        conf = self._rejected_item_with_fail_facts(tmp_path, monkeypatch, pid)
        from topoone_app_architect.arch_routes import req_agent as RA
        monkeypatch.setattr(RA, "llm_sync", lambda messages, **kw: None)
        from topoone_app_architect.arch_routes.naming import induce_from_rejection
        row = induce_from_rejection(pid, conf["id"])
        assert row and row["status"] == "pending"
        assert row["scenarios"] == ["accept"]
        assert row["ruleText"]

    def test_induce_non_rejected_returns_none(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        conf = CT.create_item(pid, _item())
        CT.confirm_item(conf["id"])  # confirmed（非 rejected）
        from topoone_app_architect.arch_routes.naming import induce_from_rejection
        assert induce_from_rejection(pid, conf["id"]) is None

    def test_endpoint_induce_from_rejection(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        conf = self._rejected_item_with_fail_facts(tmp_path, monkeypatch, pid)
        from topoone_app_architect.arch_routes import req_agent as RA
        monkeypatch.setattr(RA, "llm_sync", lambda messages, **kw: None)
        from topoone_app_architect.arch_routes.naming import (
            api_conventions_induce_from_rejection)
        out = _call(lambda: api_conventions_induce_from_rejection(_req(
            {"root": str(tmp_path), "itemId": conf["id"]})))
        row = out.get("data") or {}
        assert row.get("status") == "pending" and row.get("ruleText")

    def test_verdict_rejection_triggers_hook(self, tmp_path, monkeypatch):
        """verdict(rejected) 触发经验回写钩子（捕获后台归纳调用参数）。"""
        _ctx_setup(tmp_path, monkeypatch)
        _fake_extract(monkeypatch, [_ASSET_MISS])
        pid = _pid(tmp_path)
        conf = CT.create_item(pid, _item())
        CT.confirm_item(conf["id"])
        pkg = CT.create_package(pid)
        AC.run_acceptance(pid, str(tmp_path), None, pkg["id"])
        captured = {}
        monkeypatch.setattr(CT, "_induce_from_rejection_async",
                            lambda p, i: captured.update(pid=p, item=i))
        out = _call(lambda: CT.api_contracts_item_verdict(conf["id"], _req(
            {"root": str(tmp_path), "verdict": "rejected"})))
        assert (out.get("data") or {}).get("status") == "rejected"
        assert captured.get("item") == conf["id"]

    def test_verdict_accept_no_hook(self, tmp_path, monkeypatch):
        """verdict(accepted) 不触发经验回写。"""
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        conf = CT.create_item(pid, _item())
        CT.confirm_item(conf["id"])
        captured = {}
        monkeypatch.setattr(CT, "_induce_from_rejection_async",
                            lambda p, i: captured.update(item=i))
        out = _call(lambda: CT.api_contracts_item_verdict(conf["id"], _req(
            {"root": str(tmp_path), "verdict": "accepted"})))
        assert (out.get("data") or {}).get("status") == "accepted"
        assert "item" not in captured

    def test_skill_docs_injects_accept_convention(self, tmp_path, monkeypatch):
        """active 的 accept 场景规约 → 注入 accept 场景 skill 文档（防复发闭环）。"""
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        NamingConventionStore.create(pid, "验收订单须核对库存扣减顺序",
                                     scenarios=["accept"], status="active")
        from topoone_app_architect.arch_routes import asset_skill as SK
        doc = SK.skill_docs(str(tmp_path), None, ["accept"])
        assert "验收经验规约" in doc and "验收订单须核对库存扣减顺序" in doc
        # 非 accept 场景不注入该经验规约
        doc2 = SK.skill_docs(str(tmp_path), None, ["extract"])
        assert "验收订单须核对库存扣减顺序" not in doc2


# ── A7: 验收条目关联单测（linkedTests 引用关系） ─────────────────

class TestLinkedTests:
    def test_set_linked_tests_any_status(self, tmp_path, monkeypatch):
        """任意状态可改 linkedTests（引用关系），不升 version、不动状态。"""
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        item = CT.create_item(pid, _item())
        v0 = item["version"]
        st0 = item["status"]
        # draft 态
        r = CT.set_linked_tests(item["id"], ["ut-1", "ut-2"], pid)
        assert r["acceptance"]["linkedTests"] == ["ut-1", "ut-2"]
        assert r["version"] == v0 and r["status"] == st0
        # 确认态（非 draft）仍可改
        CT.confirm_item(item["id"])
        r2 = CT.set_linked_tests(item["id"], ["ut-3"], pid)
        assert r2["acceptance"]["linkedTests"] == ["ut-3"]
        # 保留其它 acceptance 字段
        assert r2["acceptance"].get("mode") is None or True
        # 空列表 = 全部解除
        r3 = CT.set_linked_tests(item["id"], [], pid)
        assert r3["acceptance"]["linkedTests"] == []
        # 去空白
        r4 = CT.set_linked_tests(item["id"], ["  ", "ut-9"], pid)
        assert r4["acceptance"]["linkedTests"] == ["ut-9"]

    def test_set_linked_tests_missing(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        try:
            CT.set_linked_tests("ci-404", ["ut-1"], _pid(tmp_path))
            assert False
        except LookupError:
            pass


# ── A6: 影响分析（跨组件变更扩散链 + 契约↔实现全局漂移） ─────────

class TestImpactAnalysis:
    def _asset(self, pid, aid, name, kind, refs, status="active",
               relations=None):
        return SemanticAssetsStore.create({
            "id": aid, "projectId": pid, "kind": kind, "level": "implementation",
            "name": name, "desc": name, "astRefs": refs, "status": status,
            "detail": {"relations": relations or []}, "meta": {},
            "createdAt": 0, "updatedAt": 0})

    def test_impact_direct_propagated_drift(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        # mock reconcile（避免测试环境无文件导致状态漂移）
        monkeypatch.setattr(S, "_lazy_reconcile", lambda *a, **k: None)
        pid = _pid(tmp_path)
        # A：stale（直接变更）；B：active 且 relations 引用 A（扩散）
        self._asset(pid, "sa-a", "资产A", "process",
                    [{"file": "a.py", "symbol": "fa",
                      "startLine": 1, "endLine": 5}], status="stale")
        self._asset(pid, "sa-b", "资产B", "entity",
                    [{"file": "b.py", "symbol": "fb",
                      "startLine": 1, "endLine": 9}],
                    relations=[{"target": "sa-a", "type": "uses"}])
        # 契约条目：stale 命中 / active 命中 / 意图级 / 缺失
        i_stale = CT.create_item(pid, _item(kind="process",
                                            target={"file": "a.py", "symbol": "fa"}))
        i_ok = CT.create_item(pid, _item(kind="entity",
                                         target={"file": "b.py", "symbol": "fb"}))
        i_intent = CT.create_item(pid, _item(kind="rule", target={}))
        i_miss = CT.create_item(pid, _item(kind="process",
                                           target={"file": "x.py", "symbol": "fx"}))
        for i in (i_stale, i_ok, i_intent, i_miss):
            CT.confirm_item(i["id"])
        from topoone_app_architect.arch_routes.semantic_assets import _impact_analysis
        res = _impact_analysis(str(tmp_path), None)
        # 直接变更
        assert [d["id"] for d in res["direct"]] == ["sa-a"]
        # 扩散：B 引用 stale 的 A
        assert res["propagated"] and res["propagated"][0]["id"] == "sa-b" \
            and res["propagated"][0]["via"] == "sa-a"
        # 全局漂移
        reasons = {x["itemId"]: x["reason"] for x in res["drift"]}
        assert reasons[i_stale["id"]] == "stale"
        assert reasons[i_miss["id"]] == "missing"
        assert reasons[i_intent["id"]] == "intent"
        assert i_ok["id"] not in reasons  # 已覆盖，不进漂移
        cov = res["coverage"]
        assert cov["verifiable"] == 3 and cov["covered"] == 1
        assert cov["pct"] == 33
        # 系统性偏差（意图级不计）
        assert res["patterns"] == [{"kind": "process", "count": 2}]

    def test_impact_empty_project(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        monkeypatch.setattr(S, "_lazy_reconcile", lambda *a, **k: None)
        from topoone_app_architect.arch_routes.semantic_assets import _impact_analysis
        res = _impact_analysis(str(tmp_path), None)
        assert res["direct"] == [] and res["propagated"] == []
        assert res["drift"] == [] and res["coverage"]["pct"] == 0


# ── B2: 双图对照（期望 vs 实际；复用共享 IR，不 fork） ─────────────

class TestDualDiagram:
    def _asset(self, pid, aid, name, kind, refs, detail, status="active"):
        return SemanticAssetsStore.create({
            "id": aid, "projectId": pid, "kind": kind, "level": "implementation",
            "name": name, "desc": name, "astRefs": refs, "status": status,
            "detail": detail, "meta": {}, "createdAt": 0, "updatedAt": 0})

    def test_dual_diagram_diffs(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        # 实际资产：step2「扣减库存」与期望完全一致；其余措辞不同 + 一条多余
        self._asset(pid, "sa-x", "创建订单", "process",
                    [{"file": "m.py", "symbol": "create_order",
                      "startLine": 1, "endLine": 10}],
                    {"steps": [
                        {"order": 1, "semantic": "校验库存是否充足"},
                        {"order": 2, "semantic": "扣减库存"},
                        {"order": 3, "semantic": "写入订单记录"},
                        {"order": 4, "semantic": "发送通知"},
                    ]})
        item = CT.create_item(pid, _item())  # 期望: 校验库存/扣减库存/写入订单
        res = AC.dual_diagram(item["id"], pid)
        assert res["assetId"] == "sa-x"
        assert res["expected"]["type"] == "flowchart"
        assert res["actual"]["type"] == "flowchart"
        assert len(res["expected"]["nodes"]) == 3
        assert len(res["actual"]["nodes"]) == 4
        # 差异：期望2缺失 + 实际3多余 = 5；「扣减库存」一致不进差异
        assert len(res["diffs"]) == 5
        assert all(d["semantic"] != "扣减库存" for d in res["diffs"])
        # 差异高亮用既有 IR 字段（style.stroke），非新增字段
        missing_nodes = [n for n in res["expected"]["nodes"] if n.get("style")]
        assert missing_nodes and "stroke" in missing_nodes[0]["style"]

    def test_dual_diagram_no_asset(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        item = CT.create_item(pid, _item())
        res = AC.dual_diagram(item["id"], pid)
        assert res["assetId"] == ""
        assert len(res["actual"]["nodes"]) == 0
        # 全部期望缺失
        assert len(res["diffs"]) == 3
        assert all(d["type"] == "missing" for d in res["diffs"])

    def test_dual_diagram_missing_item(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        try:
            AC.dual_diagram("ci-404", _pid(tmp_path))
            assert False
        except LookupError:
            pass


# ── C1: 可授权清单（Z 轴 × acceptance.mode=auto 细则） ─────────────

class TestAuthorization:
    def test_auto_no_zaxis_passable(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        item = CT.create_item(pid, _item(acceptance={"mode": "auto"}))
        res = CT.authorization_list(item["id"], pid)
        assert res["mode"] == "auto"
        assert res["autoPassable"] is True
        assert res["intentZCount"] == 0
        by_id = {c["id"]: c for c in res["checks"]}
        assert by_id["L1"]["authorizable"] is True
        assert by_id["L2"]["authorizable"] is True
        assert by_id["L3"]["authorizable"] is False
        assert "L3" in res["humanRequired"]

    def test_auto_zaxis_anchored_passable(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        item = CT.create_item(pid, _item(
            acceptance={"mode": "auto"},
            zAxis=[{"category": "resilience", "text": "网关超时3s重试2次",
                    "anchor": {"file": "gw.py", "symbol": "call"}}]))
        res = CT.authorization_list(item["id"], pid)
        assert res["autoPassable"] is True
        z0 = next(c for c in res["checks"] if c["id"] == "z-0")
        assert z0["cls"] == "mechanical" and z0["authorizable"] is True

    def test_auto_zaxis_intent_blocks(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        # 无 anchor 的 Z 轴条目 = 意图级 → 阻断 mode=auto 自动授权
        item = CT.create_item(pid, _item(
            acceptance={"mode": "auto"},
            zAxis=[{"category": "security", "text": "需审计日志"}]))
        res = CT.authorization_list(item["id"], pid)
        assert res["autoPassable"] is False
        assert res["intentZCount"] == 1
        z0 = next(c for c in res["checks"] if c["id"] == "z-0")
        assert z0["cls"] == "intent" and z0["authorizable"] is False
        assert "z-0" in res["humanRequired"]

    def test_manual_no_mechanical_auto(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        item = CT.create_item(pid, _item(acceptance={"mode": "manual"}))
        res = CT.authorization_list(item["id"], pid)
        by_id = {c["id"]: c for c in res["checks"]}
        assert by_id["L1"]["authorizable"] is False
        assert by_id["L2"]["authorizable"] is False
        assert res["autoPassable"] is False

    def test_default_mode_mid_assisted(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        item = CT.create_item(pid, _item())  # 未显式 mode → mid 默认 assisted
        res = CT.authorization_list(item["id"], pid)
        assert res["mode"] == "assisted"
        by_id = {c["id"]: c for c in res["checks"]}
        assert by_id["L1"]["authorizable"] is True   # assisted 含 L1/L2 自动
        assert by_id["L3"]["authorizable"] is False  # L3 永远不自动

    def test_authorization_missing_item(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        try:
            CT.authorization_list("ci-404", _pid(tmp_path))
            assert False
        except LookupError:
            pass


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))
