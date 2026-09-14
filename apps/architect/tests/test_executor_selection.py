"""执行器选定单源(P5) + 无静默降级(P6) 特征测试。

cv-153 实证回归锁定:
  - 注册表 default(cline-sdk) 为任务链缺省——/执行 直通与模型建卡都不再
    字面回落 opencode
  - 类型别名归一: cline→cline-sdk / codex→codex-server(单点 agent_executors)
  - @cline /执行 组合指令: 显式执行器建卡
  - 无可用执行器 → 建卡/确认显式失败(返回确切错误, 不降级)

Run: cd <repo> && python -m pytest apps/architect/tests/test_executor_selection.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.arch_routes.ctx as C
import topoone_app_architect.arch_routes.store as store
from topoone_app_architect.agent.perception import commands as cmds
from topoone_app_architect.agent.planning.task_plan import propose_task_tool
from topoone_app_architect.arch_routes import agent_executors as ae
from topoone_app_architect.arch_routes import exec_bridge as eb


def _env(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.setup(data_dir=data)


def _set_registry(entries):
    store.CollabConfigStore.set(ae.CONFIG_KEY,
                                store.json.dumps(entries, ensure_ascii=False)
                                if hasattr(store, "json") else __import__("json").dumps(entries, ensure_ascii=False))


def _mk_conv(**kw):
    return store.ConversationsStore.create({"kind": "generic", "title": "t", **kw})


# ── 单源助手 ─────────────────────────────────────────────────────────

def test_normalize_executor_type_aliases():
    assert ae.normalize_executor_type("cline") == "cline-sdk"
    assert ae.normalize_executor_type("codex") == "codex-server"
    assert ae.normalize_executor_type("cline-sdk") == "cline-sdk"
    assert ae.normalize_executor_type("opencode") == "opencode"
    assert ae.normalize_executor_type("") == ""


def test_default_executor_from_registry(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    # 存量默认注册表(DEFAULT_EXECUTORS): cline 为 default
    d = ae.default_executor()
    assert d and d["id"] == "cline" and d["type"] == "cline-sdk"
    # 用户改默认 → 跟随
    _set_registry([
        {"id": "opencode", "type": "opencode", "enabled": True, "default": True},
        {"id": "cline", "type": "cline-sdk", "enabled": True, "default": False},
    ])
    assert ae.default_executor()["id"] == "opencode"
    # 全部禁用 → None(调用方必须显式失败)
    _set_registry([
        {"id": "opencode", "type": "opencode", "enabled": False, "default": True},
    ])
    assert ae.default_executor() is None


# ── 建卡链: 默认执行器 + 显式失败 ────────────────────────────────────

def test_propose_task_uses_registry_default(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    conv = _mk_conv()
    t = eb.propose_task(conv, "标题", "指令内容")
    assert t["executorType"] == "cline-sdk"   # 注册表 default, 非 opencode


def test_propose_task_explicit_hint_normalized(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    conv = _mk_conv()
    t = eb.propose_task(conv, "标题", "指令内容", executor_hint={"executorType": "cline"})
    assert t["executorType"] == "cline-sdk"   # 别名归一


def test_propose_task_no_executor_fails_explicitly(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    _set_registry([{"id": "opencode", "type": "opencode", "enabled": False, "default": True}])
    conv = _mk_conv()
    r = eb.propose_task(conv, "标题", "指令内容")
    assert r.get("ok") is False and "无可用执行器" in r["error"]
    assert store.TasksStore.of_conv(conv["id"]) == []


def test_propose_task_tool_fallback_chain(tmp_path, monkeypatch):
    """模型建卡: 显式 > 会话绑定 > 注册表默认; 无 → 显式错误。"""
    _env(tmp_path, monkeypatch)
    conv = _mk_conv()
    C.set_conv(conv["id"])
    r = propose_task_tool("标题", "指令内容", root=None, project=None)
    assert r["ok"] is True
    assert store.TasksStore.get(r["taskId"])["executorType"] == "cline-sdk"


# ── /执行 直通: @执行器 组合 ─────────────────────────────────────────

def _mk_ready_req(conv_id):
    snap = {"title": "演示任务", "desc": "目标", "designMd": "方案",
            "allowedScope": [], "forbiddenScope": [], "acceptance": [],
            "functionalScope": [], "assessmentSummary": "", "estMin": 0}
    req = {"id": store.next_id("RQ"), "kind": "user-story", "status": "draft",
           "title": "演示任务", "priority": "P1", "activeVer": 1,
           "specVersions": [{"ver": 1, "state": "draft", "snapshot": snap,
                             "source": {}, "reason": "t", "createdAt": 0}],
           "ownerConv": conv_id, "projectId": "", "updatedAt": 0, "createdAt": 0}
    store.RequirementsStore.create(req)
    store.ConversationsStore.update(conv_id, {"reqId": req["id"]})
    store.RequirementsStore.spec_confirm(req["id"])
    return req["id"]

def test_run_execute_with_explicit_executor(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    conv = _mk_conv()
    _mk_ready_req(conv["id"])
    conv = store.ConversationsStore.get(conv["id"])   # 重取: reqId 回写后需最新行
    r = cmds.run_execute(conv, executor_id="cline")
    assert r["ok"] is True
    assert r["task"]["executorType"] == "cline-sdk"


def test_run_execute_unknown_executor_fails(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    conv = _mk_conv()
    _mk_ready_req(conv["id"])
    r = cmds.run_execute(conv, executor_id="不存在的执行器")
    assert r["ok"] is False
    assert "不在注册表" in r["receipt"]
    assert store.TasksStore.of_conv(conv["id"]) == []


# ── confirm_task: 无执行器 → 显式 failed ────────────────────────────

def test_confirm_task_without_executor_fails(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    _set_registry([{"id": "opencode", "type": "opencode", "enabled": False, "default": True}])
    conv = _mk_conv()
    t = store.TasksStore.create({"conversationId": conv["id"], "title": "T",
                                 "instruction": "x", "status": "pending_confirm",
                                 "executorType": ""})
    r = eb.confirm_task(t["id"])
    assert r.get("ok") is False and "无可用执行器" in r["error"]
    assert store.TasksStore.get(t["id"])["status"] == "failed"
    assert "无可用执行器" in (store.TasksStore.get(t["id"]).get("resultMd") or "")
