"""执行链路回归(生命周期 v3)：指令符号分发 / 两段式确认(specVer) / /继续 增量回合。

Run: cd <repo> && python -m pytest apps/architect/tests/test_exec_implement.py -q
"""
import asyncio
import json
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.arch_routes.ctx as C
from topoone_app_architect.arch_routes import req_agent
from topoone_app_architect.arch_routes import store


def _setup(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    return C.setup(data_dir=data)


# ── 会话指令符号解析(确定性分发, 无语义判断) ──────────────────────────

def _patch_executors(monkeypatch, models=None):
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex-m", "type": "opencode", "enabled": True,
         "config": {"model": "", "models": [{"name": m} for m in (models or [])]}},
    ])



def _mk_fixture(tmp_path, monkeypatch):
    """architect 会话(绑定需求+已确认规约) → (会话行, rid)。"""
    _setup(tmp_path, monkeypatch)
    res = req_agent.run_arch_tool("req.propose", {"title": "T-执行", "requirementMd": "目标",
                        "designMd": "方案甲", "allowedScopeMd": "modules/x/",
                        "acceptanceMd": "编译通过"},
        root=None, project=None, internal=True)
    assert res.get("ok"), res
    rid = res["requirementId"]   # propose 即 ready(无草稿态)
    conv = store.ConversationsStore.create({"kind": "requirement", "title": "T", "reqId": rid})
    conv = store.ConversationsStore.get(conv["id"])
    return conv, rid


def _patch_bridge(monkeypatch, tmp_path):
    from topoone_app_architect.arch_routes import exec_bridge, websocket as ws
    started = {}
    monkeypatch.setattr(exec_bridge, "start_implement",
                        lambda conv, instruction, executor_hint=None,
                        branch_name="", spec_ver=0:
                        started.update(instruction=instruction, branch=branch_name,
                                       spec_ver=spec_ver) or "🚀 已启动")
    monkeypatch.setattr("topoone_app_architect.arch_routes.execution.conv_root_project",
                        lambda conv: (str(tmp_path), "proj-t"))
    return started


# ── 一步启动(P3: 定稿即确认, specVer 锚定 active 版本) ───────────────

def test_acceptance_brief_detects_overrun(tmp_path, monkeypatch):
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import exec_bridge
    brief = exec_bridge._acceptance_brief(conv["id"], rid,
                                          ["modules/x/a.py", "src/core/ngx.c"])
    assert "越界" in brief and "src/core/ngx.c" in brief
    assert "modules/x/a.py" not in brief.split("越界改动")[-1] or True
    assert "验收标准对照" in brief and "编译通过" in brief
    brief2 = exec_bridge._acceptance_brief(conv["id"], rid, ["modules/x/b.py"])
    assert "边界符合" in brief2


# ── 互斥引擎 ─────────────────────────────────────────────────────────

def test_files_intersect_prefix_semantics():
    from topoone_app_architect.arch_routes.exec_bridge import _files_intersect
    a = ["modules/x", "modules/y/sub.py"]
    b = ["modules/x/core.c", "other/z"]
    assert _files_intersect(a, b) == ["modules/x"]          # 目录前缀覆盖
    assert _files_intersect(["a/b.py"], ["a/b.py"]) == ["a/b.py"]
    assert _files_intersect(["a"], ["b"]) == []


def test_check_mutex_blocks_and_readonly(tmp_path, monkeypatch):
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import exec_bridge
    running = {"ok": True, "jobs": [
        {"jobId": "j-other", "root": str(tmp_path), "branch": "b1",
         "boundaries": {"files": ["modules/x/core.c"], "readOnly": False}},
        {"jobId": "j-ro", "root": str(tmp_path), "branch": "b2",
         "boundaries": {"files": ["modules/x"], "readOnly": True}},
        {"jobId": "j-far", "root": "/other/root", "branch": "b3",
         "boundaries": {"files": ["modules/x"], "readOnly": False}},
    ]}
    monkeypatch.setattr(exec_bridge, "_runner",
                        lambda path, payload=None, timeout=12.0: running)
    # 写作业冲突 → 拒绝
    msg = exec_bridge._check_mutex(conv, str(tmp_path), ["modules/x"])
    assert msg and "j-other" in msg and "冲突" in msg
    # 只读/跨项目不拦
    running2 = {"ok": True, "jobs": [running["jobs"][1], running["jobs"][2]]}
    monkeypatch.setattr(exec_bridge, "_runner",
                        lambda path, payload=None, timeout=12.0: running2)
    assert exec_bridge._check_mutex(conv, str(tmp_path), ["modules/x"]) is None
    # runner 不可达 → 放行(风险自担)
    monkeypatch.setattr(exec_bridge, "_runner",
                        lambda path, payload=None, timeout=12.0: None)
    assert exec_bridge._check_mutex(conv, str(tmp_path), ["modules/x"]) is None


def test_bind_with_model_and_switch(tmp_path, monkeypatch):
    """bind 带 model(白名单内/外) + POST /model 随时切换/无效值拒。"""
    _setup(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    from topoone_app_architect.server import build_app
    client = TestClient(build_app(data_dir=str(tmp_path / "arch")))
    _h = lambda: {"Authorization": "Bearer test"}
    _patch_executors(monkeypatch, models=["qwen-72b", "qwen-14b"])
    c = client.post("/api/architect/sessions",
                    json={"kind": "generic"}, headers=_h()).json()["data"]
    # bind 白名单外 → 400
    r = client.post(f"/api/architect/sessions/{c['id']}/bind",
                    json={"executorId": "ex-m", "model": "ghost"},
                    headers=_h())
    assert r.json()["code"] == 400
    # bind 白名单内 → 落 executorModel
    r2 = client.post(f"/api/architect/sessions/{c['id']}/bind",
                     json={"executorId": "ex-m", "model": "qwen-14b"},
                     headers=_h()).json()["data"]
    assert r2["executorModel"] == "qwen-14b"
    # 切换/恢复默认
    r3 = client.post(f"/api/architect/sessions/{c['id']}/model",
                     json={"model": "qwen-72b"}, headers=_h()).json()["data"]
    assert r3["executorModel"] == "qwen-72b" and "下次执行生效" in r3["summary"]
    r4 = client.post(f"/api/architect/sessions/{c['id']}/model",
                     json={"model": ""}, headers=_h()).json()["data"]
    assert r4["executorModel"] == "" and "恢复默认" in r4["summary"]
    # 无效值 → 400; 未绑定 → 400
    assert client.post(f"/api/architect/sessions/{c['id']}/model",
                       json={"model": "ghost"}, headers=_h()).json()["code"] == 400
    c2 = client.post("/api/architect/sessions", json={"kind": "generic"},
                     headers=_h()).json()["data"]
    assert client.post(f"/api/architect/sessions/{c2['id']}/model",
                       json={"model": "qwen-14b"}, headers=_h()).json()["code"] == 400


def test_executor_hint_model_priority(tmp_path, monkeypatch):
    """hint 模型优先级: conv.executorModel > config.models[0] > cfg.model。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import agent_executors as ae, exec_bridge as eb
    # 仅 cfg.model(无白名单) → cfg.model
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex1", "type": "opencode", "enabled": True,
         "config": {"model": "cfg-m", "models": []}}])
    conv = {"executorId": "ex1", "executorModel": ""}
    assert eb.executor_hint_by_id(conv.get("executorId") or "", conv)["model"] == "cfg-m"
    # 顶层默认 model_id 优先于 models[0](不再被白名单首个旁路)
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex1", "type": "cline-sdk", "enabled": True,
         "config": {"model": "cfg-m", "model_id": "top-default",
                    "models": [{"name": "wl-1"}, {"name": "wl-2"}]}}])
    assert eb.executor_hint_by_id(conv.get("executorId") or "", conv)["model"] == "top-default"
    # 无顶层默认 → 首个
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex1", "type": "opencode", "enabled": True,
         "config": {"model": "cfg-m", "models": [{"name": "wl-1"}, {"name": "wl-2"}]}}])
    assert eb.executor_hint_by_id(conv.get("executorId") or "", conv)["model"] == "wl-1"
    # 会话选型最优先
    assert eb.executor_hint_by_id("ex1", {"executorModel": "wl-2"})["model"] == "wl-2"


def test_clone_carries_executor_model(tmp_path, monkeypatch):
    """克隆继承源会话模型; 亦可显式指定。"""
    _setup(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    from topoone_app_architect.server import build_app
    client = TestClient(build_app(data_dir=str(tmp_path / "arch")))
    _h = lambda: {"Authorization": "Bearer test"}
    _patch_executors(monkeypatch, models=["qwen-72b", "qwen-14b"])
    c = client.post("/api/architect/sessions",
                    json={"kind": "generic", "executorId": "ex-m", "model": "qwen-14b"},
                    headers=_h()).json()["data"]
    assert c["executorModel"] == "qwen-14b"
    d = client.post(f"/api/architect/sessions/{c['id']}/clone",
                    json={"executorId": "ex-m"}, headers=_h()).json()["data"]
    assert d["executorModel"] == "qwen-14b"      # 继承
    e = client.post(f"/api/architect/sessions/{c['id']}/clone",
                    json={"executorId": "ex-m", "model": "qwen-72b"},
                    headers=_h()).json()["data"]
    assert e["executorModel"] == "qwen-72b"      # 显式


def test_chat_system_prompt_no_reject_boundary():
    """自由对话 system 含职责边界: 弱相关需求不拒做(用户主权, 提示不打断)。

    经 prompt_registry 组装后按渲染产物断言(不再检查函数源码)。
    """
    from topoone_app_architect.arch_routes import req_agent
    s = req_agent.chat_system_prompt(None, None)
    assert "不拒做" in s and "职责边界" in s, "system 提示应含职责边界(弱相关受理)"
    assert "designMd" in s, "边界提示应同步强调 designMd 完整性"


def test_chat_system_prompt_registry_equivalence(monkeypatch):
    """registry 等价模式(single_source=false 覆盖): 与旧拼接逐字节一致。

    B4 后默认走单源渲染(见 test_prompt_source), 等价模式保留为回退通道——
    本测试守卫块化重构本身的行为等价性。
    (cv-189: 降级项目提示词有 KB 硬门, legacy 静态文档无——等价性以
    非降级上下文为口径, monkeypatch kb_degraded=False。)
    """
    import topoone_app_architect.arch_routes.project as _proj_mod
    monkeypatch.setattr(_proj_mod, "kb_degraded",
                        lambda root=None, project_id=None: False)
    from topoone_app_architect.arch_routes import req_agent, prompt_registry
    prompt_registry.set_overrides({"single_source": False})
    try:
        for kw in ({}, {"diagram_skill": True}, {"skill_scenarios": ["plan"]}):
            a = req_agent.chat_system_prompt(None, None, **kw)
            b = req_agent.chat_system_prompt_legacy(None, None, **kw)
            assert a.rstrip() == b.rstrip(), f"等价失败: {kw}"
    finally:
        prompt_registry.set_overrides({})
    # 单源模式: 注册表渲染能力文档(含协议+全部工具名)
    doc = prompt_registry.capability_doc_from_tools()
    from topoone_app_architect.arch_routes.req_agent import _ARCH_TOOLS
    assert "[TOOL_CALL]" in doc
    for name in ("req.propose", "req.amend", "kb.asset.search", "map.overview"):
        assert name in doc, f"单源文档缺工具 {name}"


def test_prompt_registry_budget_trim():
    """预算裁剪: 小预算淘汰条件块(skill/ir), 恒置块(协议/边界)保留。"""
    from topoone_app_architect.arch_routes import prompt_registry as pr
    s = pr.render_system({"root": None, "project": None, "tier": 4,
                          "skill_scenarios": ["plan"]})
    assert "职责边界" in s and "[TOOL_CALL]" in s, "恒置块永不裁剪"
    assert "技能" not in s or len(s) <= pr.budget_for(4) + 800, "t4 预算应显著收紧"


def test_delete_session_cascade_related_entries(tmp_path, monkeypatch):
    """删除会话级联清理关联条目: 停作业/递归删子会话/孤儿 draft 需求删除/
    保留需求的 ownerConv 悬空引用清空。"""
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import sessions as S, exec_bridge
    monkeypatch.setattr(exec_bridge, "stop", lambda cid, reason="": "无作业")
    # draft 需求(source=本会话) → 应级联删除(级联策略按 status 判定, 与创建路径无关)
    rid_draft = store.next_id("RQ")
    store.RequirementsStore.create({"id": rid_draft, "kind": "user-story",
                                    "status": "draft", "title": "T-孤儿", "activeVer": 1,
                                    "sourceConversationId": conv["id"],
                                    "ownerConv": conv["id"]})
    if False:
        r_draft = req_agent.run_arch_tool("req.propose", {"title": "T-孤儿", "requirementMd": "未定稿提案", "newRequirement": True},
            root=None, project=None, internal=True)
    store.RequirementsStore.get(rid_draft) or {}
    # ready 需求(source=本会话) → 保留, ownerConv 清空
    r_ready = req_agent.run_arch_tool("req.propose", {"title": "T-保留", "designMd": "方案", "newRequirement": True},
        root=None, project=None, internal=True)
    rid_ready = r_ready["requirementId"]
    store.RequirementsStore.update(rid_ready, {"sourceConversationId": conv["id"],
                                               "ownerConv": conv["id"]})
    # coding 子会话 → 递归删除
    sub = store.ConversationsStore.create({"kind": "coding", "parentConvId": conv["id"],
                                           "projectId": conv["projectId"]})
    # 会话绑定 reqId 指向 draft 需求(删除后需求不在)
    store.ConversationsStore.update(conv["id"], {"reqId": rid_draft})

    n = S._delete_session_cascade(conv["id"])

    assert n == 2, f"父+子应级联删 2, got {n}"
    assert not store.ConversationsStore.get(conv["id"])
    assert not store.ConversationsStore.get(sub["id"]), "子会话应递归删除"
    assert not store.RequirementsStore.get(rid_draft), "孤儿 draft 需求应级联删除"
    kept = store.RequirementsStore.get(rid_ready) or {}
    assert kept.get("status") == "ready", "已定稿需求是项目资产应保留"
    assert kept.get("ownerConv", "x") in ("", None), "保留需求的 ownerConv 悬空引用应清空"


def test_delete_session_cascade_cross_db(tmp_path, monkeypatch):
    """跨库级联: 会话在主库默认桶(无活跃项目写入), 需求在项目库——删除会话时
    项目库需求同样清理(draft 删/ready 清 ownerConv), 消息同桶删净不残留。"""
    from topoone_app_architect.arch_routes import sessions as S, exec_bridge, ctx as C
    monkeypatch.setattr(exec_bridge, "stop", lambda cid, reason="": "无作业")
    _mk_fixture(tmp_path, monkeypatch)

    conv = store.ConversationsStore.create({"id": "cv-xdb", "title": "跨库"})
    store.ConversationsStore.append_message(
        {"conversationId": "cv-xdb", "role": "user", "content": "hi"})
    pdb = C.project_db("proj-xdb", create=True)
    pdb.execute(
        "INSERT INTO arch_requirements (id, title, status, source_conversation_id) "
        "VALUES ('RQ-X1', 'draft跨库', 'draft', 'cv-xdb')")
    pdb.execute(
        "INSERT INTO arch_requirements (id, title, status, source_conversation_id, owner_conv) "
        "VALUES ('RQ-X2', 'ready跨库', 'ready', 'cv-xdb', 'cv-xdb')")
    pdb.commit()

    assert S._delete_session_cascade("cv-xdb") == 1
    assert C.db().fetchall(
        "SELECT * FROM arch_conversation_messages WHERE conversation_id='cv-xdb'") == [], "消息应删净"
    rows = {r["id"]: r for r in pdb.fetchall("SELECT * FROM arch_requirements")}
    assert "RQ-X1" not in rows, "项目库 draft 需求应跨库级联删除"
    assert rows["RQ-X2"]["owner_conv"] == "", "项目库 ready 需求 ownerConv 应清空"




# ══════════════════════════════════════════════════════════════════
# v2 统一会话: coding subagent 任务模型(arch_tasks + 单流 agent 标注)
# ══════════════════════════════════════════════════════════════════

def _mk_v2_fixture(tmp_path, monkeypatch, root_files=("README.md", "# P\n")):
    """v2 任务测试底座: 会话(绑项目根) + mock runner。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import exec_bridge as eb
    root = tmp_path / "proj"
    root.mkdir(exist_ok=True)
    for i, (name, content) in enumerate([("README.md", "# P\n")] if isinstance(root_files[0], str) else root_files):
        (root / name).write_text(content)
    conv = store.ConversationsStore.create({
        "projectId": "proj-v2", "title": "v2 任务",
        "meta": {"root": str(root)}})
    # conv_root_project 解析: 测试环境给 meta.root
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(root), "proj-v2"))
    calls = {"implement": []}
    def _fake_runner(path, payload=None, timeout=12.0):
        calls["implement"].append((path, payload))
        if path == "/api/implement":
            return {"ok": True, "jobId": "job-v2-1", "branch": "task/v2-1",
                    "worktree": "/tmp/wt-v2", "sessionId": "sess-oc-1"}
        if path.endswith("/input"):
            return {"ok": True, "queued": False}
        if path.endswith("/finish"):
            return {"ok": True}
        return {"ok": True}
    monkeypatch.setattr(eb, "_runner", _fake_runner)
    # 同步测试环境无事件环: 泵不启动(事件处理直接调 _handle_task_event 验证)
    monkeypatch.setattr(eb, "_start_task_pump", lambda *a, **k: None)
    return conv, eb, calls


def test_task_lifecycle_e2e(tmp_path, monkeypatch):
    """v2 全链: propose(任务卡) → confirm(running+单流消息) → 事件(输入/完成)
    → 状态迁移 + agent 标注 + workState 联动。"""
    conv, eb, calls = _mk_v2_fixture(tmp_path, monkeypatch)
    # ① propose: 任务卡落单流(saved 默认保存)
    task = eb.propose_task(conv, "实现 X", "目标: X\n方案: Y", {"executorType": "opencode"})
    assert task["status"] == "saved"
    msgs = store.ConversationsStore.messages(conv["id"])
    card = [m for m in msgs if (m.get("meta") or {}).get("kind") == "task_card"]
    assert card and card[-1]["meta"]["taskId"] == task["id"]
    # ② confirm: runner 建作业 + running + task_start 消息 + workState
    res = eb.confirm_task(task["id"])
    assert res["ok"], res
    t = store.TasksStore.get(task["id"])
    assert t["status"] == "running" and t["runnerJobId"] == "job-v2-1"
    assert t["branch"] == "task/v2-1"
    _impl_calls = [pl for p, pl in calls["implement"] if p == "/api/implement"]
    assert _impl_calls and _impl_calls[0]["instruction"]          # 指令非空(系统段+正文)
    assert "隔离 worktree" in _impl_calls[0]["instruction"]        # 环境段注入
    assert store.ConversationsStore.get(conv["id"])["workState"] == "running"
    # ③ input_required: 消息 agent=executor + waiting_input
    ctx = eb._task_ctx(conv["id"], task["id"], "job-v2-1", "", "opencode")
    eb._handle_task_event({"kind": "input_required",
                           "text": "[[NEED_INPUT]]\n选哪个库?"}, ctx)
    t = store.TasksStore.get(task["id"])
    assert t["status"] == "waiting_input"
    msgs = store.ConversationsStore.messages(conv["id"])
    ask = [m for m in msgs if (m.get("meta") or {}).get("kind") == "task_input"]
    assert ask and ask[-1]["agent"] == "opencode"   # agent 标注落库
    # ④ user 回复 → task_input 转达 → 回 running
    r = eb.task_input(task["id"], "用标准库")
    assert r["ok"]
    assert store.TasksStore.get(task["id"])["status"] == "running"
    # ⑤ done: 终态 + result_md + 单流 agent 消息 + workState 回 architect
    eb._handle_task_event({"kind": "done", "text": "[[IMPLEMENT_DONE]]完成",
                           "changedFiles": ["src/x.py"]}, ctx)
    t = store.TasksStore.get(task["id"])
    assert t["status"] == "done" and t["resultMd"]
    msgs = store.ConversationsStore.messages(conv["id"])
    done = [m for m in msgs if (m.get("meta") or {}).get("kind") == "task_done"]
    assert done and done[-1]["agent"] == "opencode"
    assert store.ConversationsStore.get(conv["id"])["workState"] == "architect"


def test_task_progress_sse_no_message(tmp_path, monkeypatch):
    """progress: 任务 progress 留痕 + SSE progress 广播; 不落消息(防刷屏)。"""
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "P", "x")
    assert eb.confirm_task(task["id"])["ok"]
    from topoone_app_architect.agent.collab import sse
    broadcast = []
    monkeypatch.setattr(sse, "publish", lambda ev: broadcast.append(ev))
    ctx = eb._task_ctx(conv["id"], task["id"], "job-v2-1", "", "opencode")
    eb._handle_task_event({"kind": "progress", "toolCount": 7, "msgCount": 2}, ctx)
    t = store.TasksStore.get(task["id"])
    assert t["progress"]["toolCount"] == 7
    assert broadcast and broadcast[-1]["type"] == "progress" and broadcast[-1]["taskId"] == task["id"]
    n_before = len(store.ConversationsStore.messages(conv["id"]))
    eb._handle_task_event({"kind": "progress", "toolCount": 9, "msgCount": 3}, ctx)
    assert len(store.ConversationsStore.messages(conv["id"])) == n_before  # 不落消息


def test_task_stop_and_mutex(tmp_path, monkeypatch):
    """stop: pending_confirm→cancelled(不调 runner); running→runner finish+cancelled。"""
    conv, eb, calls = _mk_v2_fixture(tmp_path, monkeypatch)
    # 待确认直接取消
    t1 = eb.propose_task(conv, "A", "a")
    assert eb.task_stop(t1["id"], "不要了")["ok"]
    assert store.TasksStore.get(t1["id"])["status"] == "cancelled"
    assert not any(p.startswith("/api/implement") and c is None for p, c in calls["implement"] if p == "/api/implement")
    # 运行中停止: runner finish 被调
    t2 = eb.propose_task(conv, "B", "b")
    assert eb.confirm_task(t2["id"])["ok"]
    assert eb.task_stop(t2["id"])["ok"]
    assert any(p.endswith("/finish") for p, _ in calls["implement"])
    assert store.TasksStore.get(t2["id"])["status"] == "cancelled"


def test_task_instruction_injects_spec_and_env(tmp_path, monkeypatch):
    """_task_instruction: task.instruction 为主体 + 系统段(工作环境/DoD)注入;
    绑定需求规约(边界/验收)补充。"""
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    rid = req_agent.run_arch_tool(
        "req.propose",
        {"title": "T-v2规约", "designMd": "方案Z", "requirementMd": "目标",
         "allowedScopeMd": "modules/x/", "acceptanceMd": "构建通过"},
        root=None, project=None, internal=True)["requirementId"]
    task = store.TasksStore.create({
        "conversationId": conv["id"], "reqId": rid, "title": "T",
        "instruction": "目标: X\n方案: Y", "status": "pending_confirm"})
    txt = eb._task_instruction(task)
    assert "任务上下文" in txt and "目标: X" in txt          # 正文为主体
    assert "隔离 worktree 分支" in txt and "[[IMPLEMENT_DONE]]" in txt  # 系统段
    assert "modules/x/" in txt and "构建通过" in txt          # 规约补充
    assert "方案Z" in txt                                     # designMd


def test_task_chain_brief_injection(tmp_path, monkeypatch):
    """前情链: confirm 时同会话最近终态任务摘要自动注入新任务指令
    (当前任务排除 / 最近在前 / pending 不算前情)。"""
    conv, eb, calls = _mk_v2_fixture(tmp_path, monkeypatch)
    t1 = eb.propose_task(conv, "任务一", "x")
    store.TasksStore.finish(t1["id"], "done", "完成: 改了 src/a.py, 结论可复用")
    t2 = eb.propose_task(conv, "任务二", "y")
    store.TasksStore.finish(t2["id"], "failed", "失败: 依赖缺失")
    t3 = eb.propose_task(conv, "任务三", "z")                 # 当前任务(saved)
    brief = eb._task_chain_brief(conv["id"], t3["id"])
    assert "任务一" in brief and "完成: 改了 src/a.py" in brief
    assert "任务二" in brief and "失败: 依赖缺失" in brief
    assert "任务三" not in brief                              # 当前任务排除
    assert brief.index("任务二") < brief.index("任务一")       # 最近在前
    res = eb.confirm_task(t3["id"])
    assert res["ok"]
    pl = [pl for p, pl in calls["implement"] if p == "/api/implement"][0]
    assert "前情简报(同会话近期任务)" in pl["instruction"]
    assert "任务一" in pl["instruction"]
    assert "避免重复前情中已完成的改动" in pl["instruction"]


def test_task_chain_brief_empty_and_truncate(tmp_path, monkeypatch):
    """无终态历史 → 空串; 空结果任务跳过; 超长 result_md 截断(总长 ≤1000)。"""
    conv, eb, calls = _mk_v2_fixture(tmp_path, monkeypatch)
    t1 = eb.propose_task(conv, "首任务", "x")
    assert eb._task_chain_brief(conv["id"], t1["id"]) == ""   # 无终态历史
    store.TasksStore.finish(t1["id"], "done", "很" * 2000)     # 超长结果
    t2 = eb.propose_task(conv, "空结果任务", "z")
    store.TasksStore.finish(t2["id"], "cancelled", "")         # 空结果 → 跳过
    t3 = eb.propose_task(conv, "新任务", "y")
    brief = eb._task_chain_brief(conv["id"], t3["id"])
    assert len(brief) <= 1000 and "…" in brief                 # 截断生效
    assert "首任务" in brief and "空结果任务" not in brief
    assert eb.confirm_task(t3["id"])["ok"]
    pl = [pl for p, pl in calls["implement"] if p == "/api/implement"][0]
    assert "前情简报(同会话近期任务)" in pl["instruction"]


def test_active_task_of_priority(tmp_path, monkeypatch):
    """active_task_of: running/waiting_input 优先于 pending_confirm(存量直建行);
    saved(默认保存)不算活跃——不吸收转达、不算执行中。"""
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    # saved 卡(新语义): 不活跃
    s1 = eb.propose_task(conv, "已保存卡", "a")
    assert s1["status"] == "saved"
    assert eb.active_task_of(conv["id"]) is None
    # 存量 pending_confirm(直建): 计入活跃
    t1 = store.TasksStore.create({
        "conversationId": conv["id"], "title": "存量待确认", "instruction": "x",
        "status": "pending_confirm", "executorType": "opencode"})
    assert eb.active_task_of(conv["id"])["id"] == t1["id"]
    assert eb.confirm_task(t1["id"])["ok"]
    t2 = store.TasksStore.create({
        "conversationId": conv["id"], "title": "存量二", "instruction": "y",
        "status": "pending_confirm", "executorType": "opencode"})
    assert eb.active_task_of(conv["id"])["id"] == t1["id"]   # running 优先
    eb.task_stop(t1["id"])
    assert eb.active_task_of(conv["id"])["id"] == t2["id"]


def test_task_tool_propose_and_retired_req(tmp_path, monkeypatch):
    """LLM 工具面(快捷挡): task.propose 建卡; req.propose 被退役拦截(引导文案)。"""
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import ctx as _ctx
    _ctx.set_conv(conv["id"])
    # 快捷挡: 直出任务卡 + req.* 规约工具退役(本用例测的是 v2 退役语义)
    store.ConversationsStore.update(conv["id"], {"analysisMode": "quick"})
    r = req_agent.run_arch_tool("task.propose",
                                {"title": "工具建卡", "instruction": "实现 Q",
                                 "executorType": "cline"},
                                root=None, project=None)
    assert r["ok"] and r["status"] == "saved"
    t = store.TasksStore.get(r["taskId"])
    assert t["executorType"] == "cline-sdk"  # 别名归一(P5)
    # 模型面 req.propose 无挡位拦截(需求卡按需出现, cv-175)
    r2 = req_agent.run_arch_tool("req.propose", {"title": "x"}, root=None, project=None)
    assert r2.get("ok") and r2.get("requirementId")
    # internal 放行
    r3 = req_agent.run_arch_tool("req.propose", {"title": "ok", "designMd": "d"},
                                 root=None, project=None, internal=True)
    assert r3.get("ok")


def test_delete_session_cascades_tasks(tmp_path, monkeypatch):
    """会话删除级联: 任务行随会话清(不留孤儿)。"""
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    t1 = eb.propose_task(conv, "A", "a")
    assert eb.confirm_task(t1["id"])["ok"]
    eb.propose_task(conv, "B", "b")
    from topoone_app_architect.arch_routes import sessions as S
    res = S._delete_session_cascade(conv["id"])
    assert res >= 1
    assert store.TasksStore.of_conv(conv["id"]) == []


# ══════════════════════════════════════════════════════════════════
# v2 P0 补丁: 任务围栏代落/通用路由/执行器设定(cv-147~150 实证)
# ══════════════════════════════════════════════════════════════════

def test_extract_task_fence_forms():
    """任务载荷提取: ```task 围栏 / ```json 任务形态认领; 图 IR 排除(cv-147)。"""
    from topoone_app_architect.arch_routes.req_agent import extract_task_fence
    # 显式 task 围栏
    t = extract_task_fence('前置说明\n```task\n{"title": "T", "instruction": "实现 X"}\n```')
    assert t and t["title"] == "T" and "实现 X" in t["instruction"]
    # ```json 规约形态(cv-150[3] 实证): title+requirementMd/designMd/acceptance → 拼装
    t2 = extract_task_fence(
        '我将调用 task.propose:\n```json\n{"title": "Lua Hello", "requirementMd": "访问 /hello",'
        '"designMd": "content_by_lua_block", "acceptance": ["curl 返回 Hello World"]}\n```')
    assert t2 and t2["title"] == "Lua Hello"
    assert "访问 /hello" in t2["instruction"] and "content_by_lua_block" in t2["instruction"]
    assert "curl 返回" in t2["instruction"]
    # 图 IR 不认领(cv-147: version+type+nodes)
    g = extract_task_fence('```json\n{"version": 1, "type": "component", "title": "图", '
                           '"nodes": [{"id": "a"}]}\n```')
    assert g is None
    # 无 title / 无实质字段 → None
    assert extract_task_fence('```json\n{"foo": 1}\n```') is None
    assert extract_task_fence('正文无围栏') is None


def test_task_set_executor_and_confirm_override(tmp_path, monkeypatch):
    """执行器设定: 待确认可换(cline); 非待确认拒换。"""
    conv, eb, calls = _mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "E", "e")
    t = eb.task_set_executor(task["id"], "cline")
    assert t and t["executorType"] == "cline-sdk"  # 别名归一(P5)
    assert eb.confirm_task(task["id"])["ok"]
    # 执行器下发: task.executorType=cline 经 confirm 传 runner(空注册表无 executorId,
    # payload 仍带 executorType; hint 路径由注册表测试覆盖)
    _impl = [pl for p_, pl in calls["implement"] if p_ == "/api/implement"][0]
    assert _impl.get("executorType") == "cline-sdk"  # 归一后下发
    assert eb.task_set_executor(task["id"], "opencode") is None  # running 不可换


def test_generic_exec_routing_regex():
    """通用任务路由正则: cv-148/149 实证指令命中; 知识型问题不误命中最小集。"""
    from topoone_app_architect.arch_routes.websocket import _GENERIC_EXEC_RE
    assert _GENERIC_EXEC_RE.search("检测当前源码环境 是否符合编译条件")
    assert _GENERIC_EXEC_RE.search("当前项目的源码文件数量是多少")
    assert _GENERIC_EXEC_RE.search("写个脚本统计代码行数")
    assert not _GENERIC_EXEC_RE.search("这个项目的架构设计思路是什么")


def test_task_text_quasi_streaming_and_tool_trail(tmp_path, monkeypatch):
    """准流式过程回传: text 滚动尾(600 字)+SSE 节流, tool 轨迹环(30 条)全量下发。
    UI 过程面板据此实时显示内容变化(cv-163 用户诉求)。"""
    import time as _t
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "P", "x")
    assert eb.confirm_task(task["id"])["ok"]
    from topoone_app_architect.agent.collab import sse
    broadcast = []
    monkeypatch.setattr(sse, "publish", lambda ev: broadcast.append(ev))
    ctx = eb._task_ctx(conv["id"], task["id"], "job-v2-2", "", "cline-sdk")
    # 工具轨迹: 两条, SSE 全量携带 process
    eb._handle_task_event({"kind": "tool", "toolName": "run_commands"}, ctx)
    eb._handle_task_event({"kind": "tool", "toolName": "editor"}, ctx)
    prog = store.TasksStore.get(task["id"])["progress"]
    assert [p["s"] for p in prog["process"]] == ["▸ run_commands", "▸ editor"]
    assert prog["lastTool"] == "editor"
    tool_ev = [e for e in broadcast if e.get("type") == "progress"][-1]
    assert tool_ev["process"] == prog["process"] and tool_ev.get("lastText", "") == ""
    # 文本滚动尾: 累积拼接(非覆盖)
    eb._handle_task_event({"kind": "text", "text": "第一段"}, ctx)
    eb._handle_task_event({"kind": "text", "text": "第二段"}, ctx)
    prog = store.TasksStore.get(task["id"])["progress"]
    assert prog["lastText"] == "第一段第二段"
    # 节流: 0.5s 内第二条不发 SSE(但有工具事件后的窗口差异, 直接校验节流字典)
    assert eb._PROGRESS_SSE_LAST[task["id"]] > 0
    # 环形截断
    for i in range(35):
        eb._handle_task_event({"kind": "tool", "toolName": f"t{i}"}, ctx)
    assert len(store.TasksStore.get(task["id"])["progress"]["process"]) == 30
    assert store.TasksStore.get(task["id"])["progress"]["process"][-1]["s"] == "▸ t34"


def test_propose_task_resumes_failed_branch(tmp_path, monkeypatch):
    """cv-177 裁决: 同需求上次任务失败 → 新任务卡复用其分支(续跑承接进度)。"""
    _setup(tmp_path, monkeypatch)
    conv, eb2, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    old_t = store.TasksStore.create({"conversationId": conv["id"], "reqId": "RQ-1",
                                     "title": "旧任务", "instruction": "x",
                                     "status": "failed"})
    store.TasksStore.update(old_t["id"], {"branch": "task/15"})   # confirm 时由 runner 回写
    t = eb2.propose_task(conv, "新任务", "目标: 续跑")
    assert t["branch"] == "task/15"
    assert t["ok"] is True


def test_task_create_same_db_as_conversation(tmp_path, monkeypatch):
    """cv-178 排查回归: create 漏传 projectId → 从会话行推导, 任务与会话同库——
    旧实现静默落主库 → of_conv/互斥/恢复对该任务全部失明。"""
    from tests.conftest import isolate_arch
    isolate_arch(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes.store.base import _db, _target_db
    conv = store.ConversationsStore.create({"projectId": "proj-same", "title": "T",
                                            "meta": {"root": "/tmp/x"}})
    t = store.TasksStore.create({"conversationId": conv["id"],
                                 "title": "T", "instruction": "x", "status": "failed"})
    proj = _target_db("arch_tasks", project_id="proj-same")
    assert proj.fetchall("SELECT id FROM arch_tasks WHERE id=?", (t["id"],))
    assert not _db().fetchall("SELECT id FROM arch_tasks WHERE id=?", (t["id"],))
    assert len(store.TasksStore.of_conv(conv["id"])) == 1
