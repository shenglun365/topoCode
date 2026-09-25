"""M1 角色注册表 + 规约场景注入测试（plan-C §9/§4.1）。

Run: cd <repo> && PYTHONPATH=apps/architect python -m pytest apps/architect/tests/test_agent_roles_skill.py -q
"""
import json
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.ctx as C
from topoone_app_architect.arch_routes import agent_roles as R
from topoone_app_architect.agent.cognition import roles as _cog_roles
import topoone_app_architect.sem.skill_docs as K
from topoone_app_architect.arch_routes import semantic_assets as S
from topoone_app_architect.agent.tools import req_agent
from topoone_app_architect.store import (
    CollabConfigStore, NamingConventionStore)


def _setup(tmp_path, monkeypatch):
    from tests.conftest import isolate_arch
    return isolate_arch(tmp_path, monkeypatch)


# ── 角色注册表 ─────────────────────────────────────────────────

class TestAgentRoles:
    def test_defaults_merge_and_override(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        roles = R.get_roles()
        assert {r["name"] for r in roles} == {"extract", "verify", "induce", "pseudo",
                                              "evaluate", "mine"}
        R.set_roles([{"name": "extract", "modelId": "qwen-fast"},
                     {"name": "verify", "modelId": "deepseek-r1"},
                     {"name": "unknown-role", "modelId": "x"}])  # 未知 name 丢弃
        roles = R.get_roles()
        by = {r["name"]: r for r in roles}
        assert by["extract"]["modelId"] == "qwen-fast"
        assert by["verify"]["modelId"] == "deepseek-r1"
        assert by["pseudo"]["modelId"] == ""  # 未设置保持空

    def test_set_roles_strips_dangling_model_id(self, tmp_path, monkeypatch):
        """cv-168 一揽子对齐: modelId 不在 llm.models 目录 → 剥离+告警,
        防止网关侧静默回退 KB 默认; 目录为空(未同步)时跳过校验不误伤。"""
        _setup(tmp_path, monkeypatch)
        orig_get = CollabConfigStore.get.__func__
        monkeypatch.setattr(CollabConfigStore, "get", classmethod(
            lambda cls, k, d="": json.dumps([
                {"id": "model-ok"}, {"id": "model-2"}])
            if k == "llm.models" else orig_get(cls, k, d)))
        R.set_roles([{"name": "extract", "modelId": "model-ok"},
                     {"name": "verify", "modelId": "model-gone"}])
        by = {r["name"]: r for r in R.get_roles()}
        assert by["extract"]["modelId"] == "model-ok"
        assert by["verify"]["modelId"] == ""       # 越界剥离
        # 目录为空 → 校验跳过
        monkeypatch.setattr(CollabConfigStore, "get", classmethod(
            lambda cls, k, d="": "" if k == "llm.models" else orig_get(cls, k, d)))
        R.set_roles([{"name": "induce", "modelId": "anything"}])
        assert R.role_model_id("induce") == "anything"

    def test_role_model_id_resolution(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        assert R.role_model_id("extract") == ""     # 未配置 → 空串回退
        assert R.role_model_id("") == ""            # 空角色 → 空串
        R.set_roles([{"name": "induce", "modelId": "glm-mid"}])
        assert R.role_model_id("induce") == "glm-mid"
        assert R.role_model_id("nope") == ""

    def test_persisted_in_collab_config(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        R.set_roles([{"name": "verify", "modelId": "m1"}])
        raw = CollabConfigStore.get("agent_roles", "")
        assert "verify" in raw and "m1" in raw

    def test_resolve_role_model_priority(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        # explicit 会话选择优先于角色注册表
        R.set_roles([{"name": "extract", "modelId": "role-fast"}])
        assert R.resolve_role_model("extract", "user-pick") == "user-pick"
        # 无 explicit → 角色注册表
        assert R.resolve_role_model("extract", "") == "role-fast"
        # 角色未配置 → None（调用方回退全局偏好）
        assert R.resolve_role_model("pseudo", "") is None
        assert R.resolve_role_model("", "explicit-only") == "explicit-only"

    def test_scenario_role_mapping(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        assert R.scenario_role(["extract"]) == "extract"
        assert R.scenario_role(["accept"]) == "verify"
        assert R.scenario_role(["naming"]) == "induce"
        # 首个命中生效
        assert R.scenario_role(["accept", "extract"]) == "verify"
        # 无角色场景 / 通用对话 → ''（保持既有模型链）
        assert R.scenario_role(["contract"]) == ""
        assert R.scenario_role([]) == ""
        assert R.scenario_role(None) == ""


# ── 规约场景注入（按场景加载，禁全量） ──────────────────────────

class TestAssetSkillDocs:
    def test_no_scenario_empty(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        assert K.skill_docs(str(tmp_path), None, []) == ""

    def test_extract_scenario_builtin(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        doc = K.skill_docs(str(tmp_path), None, ["extract"])
        assert "语义资产提取规约" in doc
        assert "asset.semantic.extract" in doc      # 指令化：统一走定向管线
        assert "组件ID" in doc                       # 指令携带组件ID作为权威范围
        assert "确定执行" in doc                     # 不再提议范围等确认
        assert "命名纪律" in doc

    def test_project_convention_injected(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        NamingConventionStore.create(S.project_id_for(str(tmp_path), None), "过程资产用动宾结构",
                                     scenarios=["extract"])
        doc = K.skill_docs(str(tmp_path), None, ["extract"])
        assert "项目命名规约" in doc and "过程资产用动宾结构" in doc

    def test_convention_other_scenario_not_leaked(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        NamingConventionStore.create(S.project_id_for(str(tmp_path), None), "仅验收场景的规约",
                                     scenarios=["accept"])
        doc = K.skill_docs(str(tmp_path), None, ["extract"])
        assert "仅验收场景的规约" not in doc  # R7：场景隔离

    def test_chat_prompt_gated_by_scenarios(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        # 无场景 → 不含 skill 段
        p0 = req_agent.chat_system_prompt(str(tmp_path), None)
        assert "语义资产技能" not in p0
        # extract 场景 → 注入
        p1 = req_agent.chat_system_prompt(str(tmp_path), None,
                                          skill_scenarios=["extract"])
        assert "语义资产技能" in p1 and "asset.semantic.save" in p1


class TestContractScenarioSkill:
    """🧾 期望固化：contract 场景规约按场景注入（M2）。"""

    def test_contract_scenario_builtin(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        doc = K.skill_docs(str(tmp_path), None, ["contract"])
        assert "期望固化规约" in doc
        assert "contract.propose" in doc
        assert "origin.quote" in doc
        assert "设计者" in doc  # 只产草稿，不代判

    def test_contract_not_in_extract(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        doc = K.skill_docs(str(tmp_path), None, ["extract"])
        assert "期望固化规约" not in doc  # 场景隔离

    def test_chat_prompt_contract_gated(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        p0 = req_agent.chat_system_prompt(str(tmp_path), None)
        assert "期望固化规约" not in p0
        p1 = req_agent.chat_system_prompt(str(tmp_path), None,
                                          skill_scenarios=["contract"])
        assert "期望固化规约" in p1
