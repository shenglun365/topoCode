"""cv-188: 会话工具调用报错修复回归。

1) req.amend 别名折叠——小模型实测误传 title/items/patch/amendmentMd 四种
   形状, 确定性收编而非裸 TypeError 空转回合;
2) run_arch_tool TypeError → 可读「支持的参数」清单(模型一轮自纠);
3) req.amend 参数文档给具体 JSON 形状(注册点 params_doc 单源)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_req_amend_aliases.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.arch_routes import store


def _mk_ready_req(conv_id, title="原标题"):
    rid = f"RQ-am{abs(hash(title + conv_id)) % 100000}"
    store.RequirementsStore.create({
        "id": rid, "kind": "user-story", "status": "ready", "title": title,
        "priority": "P1", "activeVer": 1, "ownerConv": conv_id,
        "specVersions": [{"ver": 1, "state": "confirmed",
                          "snapshot": {"title": title, "desc": "原描述",
                                       "designMd": "原方案",
                                       "allowedScope": ["src/"], "forbiddenScope": [],
                                       "acceptance": ["原验收"],
                                       "functionalScope": [],
                                       "assessmentSummary": ""},
                          "source": {}, "reason": "t", "createdAt": 0}],
        "projectId": "", "updatedAt": 0, "createdAt": 0})
    return rid


def _amend(rid, args):
    from topoone_app_architect.arch_routes import req_agent, ctx
    tok = ctx.set_req(rid)
    tok2 = ctx.set_conv("cv-am")
    try:
        return req_agent.run_arch_tool("req.amend", args, root=None, project=None)
    finally:
        ctx.reset_req(tok)
        ctx.reset_conv(tok2)


def test_amend_alias_title_items_amendment_md(arch_env):
    """cv-188 实测误传形状: title/items/amendmentMd 折叠生效, 不再 TypeError。"""
    rid = _mk_ready_req("cv-am")
    r = _amend(rid, {"title": "新标题", "items": ["验收一", "验收二"],
                     "amendmentMd": "新描述全文"})
    assert r.get("ok") is True, r
    assert "标题" in r["amended"] and "验收标准" in r["amended"]
    snap = store.RequirementsStore.spec_active(rid)["snapshot"]
    assert snap["title"] == "新标题"
    assert snap["acceptance"] == ["验收一", "验收二"]
    assert snap["desc"] == "新描述全文"
    assert store.RequirementsStore.spec_active(rid)["ver"] == 2


def test_amend_patch_dict_fold(arch_env):
    """patch 字典形状: 已知字段并入快照, 未知字段忽略并列出。"""
    rid = _mk_ready_req("cv-am")
    r = _amend(rid, {"patch": {"designMd": "方案B", "allowedScope": ["app/"],
                               "bogusField": 1}})
    assert r.get("ok") is True, r
    snap = store.RequirementsStore.spec_active(rid)["snapshot"]
    assert snap["designMd"] == "方案B" and snap["allowedScope"] == ["app/"]
    assert "bogusField" in r["hint"]


def test_amend_real_fields_unchanged(arch_env):
    """正规字段(requirementMd/designMd)行为不变(等价护栏)。"""
    rid = _mk_ready_req("cv-am")
    r = _amend(rid, {"requirementMd": "目标X", "designMd": "方案X",
                     "reasoning": "补方案"})
    assert r.get("ok") and "方案" in r["amended"]
    snap = store.RequirementsStore.spec_active(rid)["snapshot"]
    assert snap["desc"] == "目标X" and snap["designMd"] == "方案X"


def test_run_arch_tool_readable_type_error(arch_env):
    """任意工具误传参数名 → 可读「参数不受支持 + 支持的参数清单」。"""
    from topoone_app_architect.arch_routes import req_agent
    r = req_agent.run_arch_tool("project.ctx", {"bogusKw": 1},
                                root=None, project=None)
    assert "bogusKw 不受支持" in str(r.get("error")), r
    assert "root" in str(r.get("error")) and "project" in str(r.get("error"))


def test_amend_params_doc_in_capability_doc(arch_env):
    """参数文档单源: 注册点 params_doc 渲染进能力文档(具体 JSON 形状)。"""
    from topoone_app_architect.agent.cognition.prompt import capability_doc_from_tools
    doc = capability_doc_from_tools()
    assert '"requirementMd"' in doc and "req.amend" in doc
    assert "见上方能力清单" not in doc
