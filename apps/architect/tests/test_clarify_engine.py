"""cv-190: 需求澄清挡位引擎测试——策略库/缺口矩阵/显式指令/管线注入/REST。

裁决: 澄清为会话挡位按钮(auto | forced); 策略库按具体目标切分, 未命中回落
模型自由提问(五要素框架); 明确指令(「按钮UI 修改为 xxx」)任意挡免澄清。

Run: cd <repo> && python -m pytest apps/architect/tests/test_clarify_engine.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.requirements.clarify import (
    clarify_directive, gap_matrix, is_explicit_instruction, match_strategy)


# ── 显式指令判定 ──────────────────────────────────────────────────────

def test_explicit_instruction_detection():
    assert is_explicit_instruction("按钮UI 修改为 深色主题")
    assert is_explicit_instruction("标题改成: 用户中心")
    assert is_explicit_instruction("删除导出按钮")
    assert is_explicit_instruction("新增一个导出 Excel 的入口")
    assert not is_explicit_instruction("搭建开发环境，基于 three.js 封装动画建模工具")
    assert not is_explicit_instruction("怎么优化这个模块的性能")
    assert not is_explicit_instruction("做一个组件封装方案")
    assert not is_explicit_instruction("")


# ── 策略库(按目标切分) ────────────────────────────────────────────────

def test_strategy_match_by_goal():
    assert match_strategy("搭建开发环境 安装依赖")["key"] == "env_setup"
    assert match_strategy("写个脚本转换日志格式")["key"] == "script_tool"
    assert match_strategy("封装一个下拉组件")["key"] == "ui_component"
    assert match_strategy("修复登录报错")["key"] == "bug_fix"
    assert match_strategy("新增用户查询接口 api")["key"] == "api_service"
    # 未命中 → None(回落模型自由提问)
    assert match_strategy("帮我把这句话翻译成英文") is None


# ── 缺口矩阵(确定性五要素) ────────────────────────────────────────────

def test_gap_matrix_deterministic():
    full = {"desc": "完整的需求描述文本超过十五个汉字以上",
            "designMd": "方案细节足够长" * 5,
            "allowedScope": ["src/"], "functionalScope": ["x"],
            "acceptance": ["ok"]}
    assert gap_matrix(full) == []
    empty = gap_matrix({"desc": "", "designMd": "", "acceptance": []})
    assert len(empty) == 5 and "⑤验收标准" in empty and "②方案要点" in empty


# ── 指令生成(挡位语义) ────────────────────────────────────────────────

def test_directive_forced_uses_strategy():
    d = clarify_directive("forced", "帮我搭建开发环境")
    assert "强制挡" in d and "环境搭建" in d and "禁止直接落需求卡" in d
    d2 = clarify_directive("forced", "帮我把这句话润色一下")   # 未命中策略库
    assert "五要素" in d2 and "策略库覆盖" in d2


def test_directive_explicit_skips_even_forced():
    assert clarify_directive("forced", "按钮UI 修改为 深色主题") == ""
    assert clarify_directive("auto", "删除导出按钮") == ""


def test_directive_auto_gap_driven():
    sparse = {"desc": "短", "designMd": "", "acceptance": []}
    d = clarify_directive("auto", "继续", sparse)
    assert "自动" in d and "缺口" in d and "⑤验收标准" in d
    # 强制挡 + 需求已建 → 缺口驱动(不重放"先澄清")
    d2 = clarify_directive("forced", "1. Node20 2. pnpm", sparse)
    assert "强制挡" in d2 and "缺口" in d2 and "禁止直接落需求卡" not in d2
    # 要素齐全 / 无需求绑定 → 不注入
    assert clarify_directive("auto", "继续", gap_matrix.__globals__ and {
        "desc": "完整的需求描述文本超过十五个汉字以上", "designMd": "方案" * 20,
        "allowedScope": ["x"], "functionalScope": ["y"], "acceptance": ["z"]}) == ""
    assert clarify_directive("auto", "继续", None) == ""


# ── 管线接线(context 注入) ───────────────────────────────────────────

def test_chat_context_injects_clarify_directive(arch_env):
    from topoone_app_architect.agent.turns import context as ctx_mod
    conv = {"analysisMode": "strict", "clarifyMode": "forced",
            "executorId": "", "reqId": ""}
    _, msgs, _ = ctx_mod._chat_context(
        {"root": "", "project": ""}, {"conv": conv, "question": "帮我搭建开发环境"},
        [], [], "", None)
    sys_text = "\n".join(m["content"] for m in msgs if m["role"] == "system")
    assert "强制挡" in sys_text and "环境搭建" in sys_text
    # 明确指令 → 不注入
    _, msgs2, _ = ctx_mod._chat_context(
        {"root": "", "project": ""}, {"conv": conv, "question": "按钮UI 修改为 深色"},
        [], [], "", None)
    assert "强制挡" not in "\n".join(m["content"] for m in msgs2 if m["role"] == "system")


# ── REST 端点 ─────────────────────────────────────────────────────────

def test_clarify_mode_rest_roundtrip(arch_env):
    from fastapi.testclient import TestClient
    from topoone_app_architect.server import build_app
    from topoone_app_architect.arch_routes import store
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    client = TestClient(build_app(data_dir=os.environ["ARCH_DATA_DIR"]))
    r = client.post(f"/api/architect/sessions/{conv['id']}/clarify-mode",
                    json={"mode": "forced"}).json()
    assert r.get("code") == 0 and r["data"]["clarifyMode"] == "forced"
    assert (store.ConversationsStore.get(conv["id"]) or {}).get("clarifyMode") == "forced"
    bad = client.post(f"/api/architect/sessions/{conv['id']}/clarify-mode",
                      json={"mode": "always"}).json()
    assert bad.get("code") == 400
    # 列表暴露 clarifyMode
    lst = client.get(f"/api/architect/sessions?scope=all&kind=generic").json()["data"]
    hit = [x for x in lst if x["id"] == conv["id"]]
    assert hit and hit[0]["clarifyMode"] == "forced"
