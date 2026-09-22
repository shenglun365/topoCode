"""占位正文门禁(cv-224)特征测试 — 确定性拒绝壳卡, 走既有错误回喂自纠环。

背景: 模型遵从混乱时把「先澄清后落卡」执行成落壳卡(requirementMd/designMd
="..."), 快照全占位。门禁在 tool_req_propose/tool_req_amend 单点确定性校验,
零 LLM 判分(防守线: 结构校验属确定性层)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_req_body_gate.py -q
"""
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.arch_routes import ctx
from topoone_app_architect.arch_routes.req_agent import (
    _body_placeholder_error,
    tool_req_amend,
    tool_req_propose,
)


@pytest.fixture()
def conv_env(arch_env):
    """隔离 + ctx 设定; token 还原防 contextvar 跨测试泄漏(实测教训)。"""
    tok_c = ctx.set_conv("cv-gate")
    tok_r = ctx.set_req("")
    yield arch_env
    ctx.reset_conv(tok_c)
    ctx.reset_req(tok_r)


REAL_BODY = "构建 topo-animation 项目的完整开发环境，含依赖安装、本地启动与冒烟验证。"


# ── 校验器单源 ────────────────────────────────────────────────────────

def test_placeholder_variants_blocked():
    for t in ("...", "…", "。。。", "待补充", "待完善", "待定", "todo", "TBD",
              "无", "-", "—"):
        assert _body_placeholder_error(t, "requirementMd"), t


def test_real_body_thin_body_and_absent_pass():
    """短正文合法(缺口归 gap_matrix 澄清流, 门禁只拦占位)。"""
    assert _body_placeholder_error(REAL_BODY, "requirementMd") == ""
    assert _body_placeholder_error("修复登录按钮", "requirementMd") == ""
    assert _body_placeholder_error("", "designMd") == ""          # 未提供→放行
    assert _body_placeholder_error("  ", "designMd") == ""


# ── propose 门禁 ─────────────────────────────────────────────────────

def test_propose_rejects_placeholder_body(conv_env):
    """cv-224 复放: requirementMd="..." → 拒绝落卡, 错误可回喂自纠。"""
    r = tool_req_propose(title="壳卡", requirementMd="...", designMd="...")
    assert r.get("ok") is False and "占位" in str(r.get("error"))
    r2 = tool_req_propose(title="壳卡", requirementMd="...")     # design 占位同拦
    assert r2.get("ok") is False


def test_propose_allows_thin_and_partial_but_not_placeholder(conv_env):
    """只拦占位符: 短正文/design-only/title-only 均合法(缺口归澄清流)。"""
    r1 = tool_req_propose(title="短卡", requirementMd="修复登录按钮")
    assert r1.get("ok") is True
    r2 = tool_req_propose(title="设计先行", designMd="Node 20 + Vite 脚手架")
    assert r2.get("ok") is True
    r3 = tool_req_propose(title="T")
    assert r3.get("ok") is True


# ── amend 门禁(提供字段才校验; 设计-only 修订不受累) ──────────────────

def test_amend_rejects_placeholder_but_design_only_passes(conv_env):
    land = tool_req_propose(title="真实卡", requirementMd=REAL_BODY)
    rid = land["requirementId"]
    ctx.set_req(rid)
    r = tool_req_amend(reqId=rid, requirementMd="...")
    assert r.get("ok") is False and "占位" in str(r.get("error"))
    r2 = tool_req_amend(reqId=rid, designMd="## 技术选型\n- Node 20 + Vite")  # 设计-only
    assert r2.get("ok") is True
    r3 = tool_req_amend(reqId=rid, requirementMd=REAL_BODY + "（补充：含 CI 脚本）")
    assert r3.get("ok") is True
