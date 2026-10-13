"""TurnAdapter 适配层 + 回合看门狗单测(不经真实 coding agent)。

Run: cd <repo> && python -m pytest packages/core/tests/test_turn_adapter.py -q
"""
import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "topoone"))

from topoone.plugins.runner import turn_adapter as ta  # noqa: E402
from topoone.plugins.runner import implement as impl  # noqa: E402
from topoone.plugins.runner.turn_adapter import (  # noqa: E402
    TurnAdapter, TurnOutcome, TurnProbe, build_adapter)


# ── 工厂 ──

def test_build_adapter_rejects_empty_type():
    """无静默降级(cv-153): 空/未知类型显式失败, 不再回退 opencode。"""
    with pytest.raises(RuntimeError, match="支持"):
        build_adapter("", "", {})
    with pytest.raises(RuntimeError, match="未知执行器类型: mock"):
        build_adapter("mock", "m", {})


def test_build_adapter_by_type():
    # 别名归一: cline→cline-sdk / codex→codex-server(与 architect 单源一致)
    assert build_adapter("cline", "cline", {}).executor_type == "cline-sdk"
    assert build_adapter("codex", "codex", {"codex_bin": "codex"}).executor_type == "codex-server"
    assert build_adapter("cline-sdk", "cline", {}).executor_type == "cline-sdk"
    assert build_adapter("codex-server", "codex",
                         {"codex_bin": "codex"}).executor_type == "codex-server"
    with pytest.raises(RuntimeError):
        build_adapter("remote-agent", "r", {})


# ── 看门狗(假 adapter 三态) ──

class _WatchFakeAdapter(TurnAdapter):
    """run_turn 挂起直至 job 终态——模拟执行器挂死; probe 返回预置快照。"""

    executor_id = "fake"

    def __init__(self, probe: TurnProbe):
        self._probe = probe
        self.abort_called = False

    async def start_session(self, job) -> None:
        job.session_id = "s1"
        job.serve_url = "fake://"

    async def run_turn(self, job, text: str) -> TurnOutcome:
        for _ in range(400):
            await asyncio.sleep(0.05)
            if job.status in ("done", "failed", "stopped"):
                raise RuntimeError("回合已被中止")
        return TurnOutcome(output="[[IMPLEMENT_DONE]] ok")

    async def probe(self, job) -> TurnProbe:
        return self._probe

    async def abort(self, job) -> bool:
        self.abort_called = True
        return True


def _run_job_with_watch(adapter: TurnAdapter, stall_sec: float = 0.5) -> "impl.ImplementJob":
    async def _flow():
        j = impl.ImplementJob("jw", root="/tmp/x", wt="/tmp/x-wt", base="HEAD",
                              branch="exec/t", instruction="do",
                              adapter=adapter, stall_sec=stall_sec)
        await j.start()          # start_session + 首轮(挂起) + 看门狗
        await asyncio.wait_for(j.turn_task, timeout=15)
        await asyncio.sleep(0.05)
        return j
    return asyncio.run(_flow())


def test_watchdog_kills_on_executor_error(monkeypatch):
    monkeypatch.setattr(impl, "_WATCH_INTERVAL", 0.1)
    a = _WatchFakeAdapter(TurnProbe("error", time.time(), "通道断流"))
    j = _run_job_with_watch(a)
    assert j.status == "failed"
    assert a.abort_called
    kinds = [e["kind"] for e in j.events]
    assert "failed" in kinds


def test_watchdog_kills_on_activity_stall(monkeypatch):
    monkeypatch.setattr(impl, "_WATCH_INTERVAL", 0.1)
    # 活动停在很久以前 + 非 busy → 停滞判定
    a = _WatchFakeAdapter(TurnProbe("idle", time.time() - 999, ""))
    j = _run_job_with_watch(a, stall_sec=0.5)
    assert j.status == "failed"
    assert a.abort_called


def test_watchdog_leaves_busy_alone(monkeypatch):
    monkeypatch.setattr(impl, "_WATCH_INTERVAL", 0.1)

    class _BusyDone(TurnAdapter):
        executor_id = "fake"

        async def start_session(self, job) -> None:
            job.session_id = "s1"
            job.serve_url = "fake://"

        async def run_turn(self, job, text: str) -> TurnOutcome:
            await asyncio.sleep(0.5)   # 正常回合(看门狗期间 busy)
            return TurnOutcome(output="完成 [[IMPLEMENT_DONE]]")

        async def probe(self, job) -> TurnProbe:
            return TurnProbe("busy", time.time())

        async def abort(self, job) -> bool:
            raise AssertionError("busy 状态不应被看门狗中止")

    async def _flow():
        j = impl.ImplementJob("jb", root="/tmp/x", wt="/tmp/x-wt", base="HEAD",
                              branch="exec/t", instruction="do",
                              adapter=_BusyDone(), stall_sec=0.5)
        await j.start()
        await asyncio.wait_for(j.turn_task, timeout=10)
        await asyncio.sleep(0.05)
        return j
    j = asyncio.run(_flow())
    assert j.status == "done"
    assert not [e for e in j.events if e["kind"] == "failed"]


# ── OpenCodeTurnAdapter.probe(/session/status 解析) ──

def test_opencode_probe_parses_status(monkeypatch):
    a = ta.OpenCodeTurnAdapter(auto_start=False)

    class _Resp:
        def __init__(self, data, code=200):
            self._d, self._c = data, code
            self.status_code = code
        def json(self): return self._d

    class _AC:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): return _Resp({"s1": {"status": "error",
                                                       "message": "LLM quota exceeded"}})

    monkeypatch.setattr(ta.httpx, "AsyncClient", _AC)

    class _Job:
        id = "j1"; session_id = "s1"; serve_url = "http://x"
        last_activity_ts = 123.0; last_error = ""

    p = asyncio.run(a.probe(_Job()))
    assert p.status == "error"
    assert "quota" in p.last_error


# ── CodexTurnAdapter(notifications 聚合 + 活动时间戳) ──

class _FakeCodexProc:
    """假 app-server: call 记录方法; events 可编程注入。"""

    def __init__(self):
        self.events: list = []
        self.calls: list = []

    async def call(self, method, params=None, timeout=None):
        self.calls.append(method)
        if method == "thread/start":
            return {"thread": {"id": "th1"}}
        if method == "turn/start":
            # 模拟服务端 notifications: 过程事件 + 终态
            self.events.append({"method": "item/updated",
                                "params": {"item": {"type": "agentMessage",
                                                    "content": [{"text": "工作中"}]}}})
            self.events.append({"method": "turn/completed",
                                "params": {"turn": {"status": "completed"}}})
            return {"turn": {"id": "t1"}}
        if method == "turn/interrupt":
            return {}
        return {}

    def events_since(self, idx):
        return self.events[idx:]


def test_codex_run_turn_aggregates_and_touches_activity(monkeypatch):
    fake = _FakeCodexProc()
    proxy = type("P", (), {"proc": fake, "dead": False, "dead_reason": ""})()
    monkeypatch.setitem(ta._CODEX_SERVERS, "codex:", proxy)
    a = ta.CodexTurnAdapter({"codex_bin": "codex"})

    async def _flow():
        class _Job:
            id = "jc"; session_id = ""; serve_url = ""
            wt = "/tmp/x-wt"; model = ""; turn_timeout = 10.0
            last_activity_ts = 0.0; last_error = ""
        j = _Job()
        await a.start_session(j)
        assert j.session_id == "th1"
        t0 = j.last_activity_ts
        await asyncio.sleep(0.01)
        out = await a.run_turn(j, "做任务")
        return j, t0, out
    j, t0, out = asyncio.run(_flow())
    assert "工作中" in out.output
    assert j.last_activity_ts > t0          # notifications 刷新活动
    assert "turn/interrupt" not in fake.calls


def test_codex_run_turn_error_event_fails(monkeypatch):
    fake = _FakeCodexProc()

    async def _turn_start_error(method, params=None, timeout=None):
        fake.calls.append(method)
        if method == "thread/start":
            return {"thread": {"id": "th1"}}
        if method == "turn/start":
            fake.events.append({"method": "error",
                                "params": {"error": {"message": "unauthorized"},
                                            "willRetry": False}})
            return {"turn": {"id": "t1"}}
        return {}

    fake.call = _turn_start_error
    proxy = type("P", (), {"proc": fake, "dead": False, "dead_reason": ""})()
    monkeypatch.setitem(ta._CODEX_SERVERS, "codex:", proxy)
    a = ta.CodexTurnAdapter({"codex_bin": "codex"})

    async def _flow():
        class _Job:
            id = "jc2"; session_id = ""; serve_url = ""
            wt = "/tmp/x-wt"; model = ""; turn_timeout = 10.0
            last_activity_ts = 0.0; last_error = ""
        j = _Job()
        await a.start_session(j)
        await a.run_turn(j, "x")
    with pytest.raises(RuntimeError, match="unauthorized"):
        asyncio.run(_flow())


def test_codex_abort_sends_interrupt(monkeypatch):
    fake = _FakeCodexProc()
    proxy = type("P", (), {"proc": fake, "dead": False, "dead_reason": ""})()
    monkeypatch.setitem(ta._CODEX_SERVERS, "codex:", proxy)
    a = ta.CodexTurnAdapter({"codex_bin": "codex"})

    async def _flow():
        class _Job:
            id = "jc3"; session_id = ""; serve_url = ""
            wt = "/tmp/x-wt"; model = ""; turn_timeout = 10.0
            last_activity_ts = 0.0; last_error = ""
        j = _Job()
        await a.start_session(j)
        return await a.abort(j)
    assert asyncio.run(_flow()) is True
    assert "turn/interrupt" in fake.calls


# ── OpenCode P1: 无头权限显式化 + 会话复活容错 ──────────────────────────────

def test_opencode_headless_config_shape():
    """内联配置: 权限全 allow 白名单 + mcp timeout 强制 >=60s。"""
    cfg = ta._opencode_headless_config("auto", {
        "fs": {"type": "local", "command": ["mcp-fs"], "timeout": 5000},
        "web": {"type": "remote", "url": "http://x"},
    })
    import json as _json
    data = _json.loads(cfg)
    assert data["permission"]["*"] == "allow"
    assert data["permission"]["doom_loop"] == "allow"
    assert data["permission"]["external_directory"] == "allow"
    assert data["mcp"]["fs"]["timeout"] == 60000      # 冷启动坑: 强制抬升
    assert data["mcp"]["web"]["timeout"] == 60000     # 缺省补齐


def test_opencode_mcp_shape_normalized():
    """2610 F6: 官方 schema type 必填——缺型条目归一(缺型被 opencode 忽略)。"""
    import json as _json
    data = _json.loads(ta._opencode_headless_config("auto", {
        "topo-architect": {"url": "http://127.0.0.1:3470/mcp", "timeout": 60000},
        "localtool": {"command": ["npx", "-y", "mcp-x"]},
        "typed": {"type": "remote", "url": "http://y", "enabled": False},
    }))
    a = data["mcp"]["topo-architect"]
    assert a["type"] == "remote" and a["enabled"] is True   # url 型补齐
    assert a["url"] == "http://127.0.0.1:3470/mcp"
    assert data["mcp"]["localtool"]["type"] == "local"      # command 型补齐
    assert data["mcp"]["localtool"]["enabled"] is True
    assert data["mcp"]["typed"]["enabled"] is False         # 显式值不被覆盖


def test_opencode_spawn_injects_config_env(monkeypatch):
    """spawn serve: OPENCODE_CONFIG_CONTENT 环境变量注入（不落 worktree）。"""
    captured = {}

    class _Proc:
        pid = 4242

        def poll(self):
            return None

        def kill(self):
            pass

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env") or {}
        return _Proc()

    monkeypatch.setattr(ta.subprocess, "Popen", fake_popen)

    async def fake_healthy(url):
        return True

    mgr = ta.OpenCodeServeManager(permission="auto",
                                  mcp_servers={"fs": {"timeout": 100}})
    monkeypatch.setattr(mgr, "_healthy", fake_healthy)

    async def _flow():
        return await mgr._spawn("/r", 3500, "http://127.0.0.1:3500")
    sp = asyncio.run(_flow())
    assert sp.proc is not None
    content = captured["env"].get("OPENCODE_CONFIG_CONTENT") or ""
    assert '"allow"' in content
    assert "doom_loop" in content
    assert "60000" in content
    # 空闲实例回收 env（InstanceStore 泄漏对策; SDK 最低 1h）
    assert captured["env"].get("OPENCODE_EXPERIMENTAL_INSTANCE_IDLE_TIMEOUT_MS") == "3600000"


def test_opencode_run_turn_recreates_on_404(monkeypatch):
    """serve 重启后会话丢失(404) → 自动重建 session 并重发当前指令。"""
    posts = []

    class _Resp:
        def __init__(self, code, data=None):
            self.status_code = code
            self._d = data or {}

        def raise_for_status(self):
            if self.status_code >= 400:
                import httpx as _hx
                raise _hx.HTTPStatusError("err", request=None, response=None)

        def json(self):
            return self._d

    class _AC:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            posts.append(url)
            if url.endswith("/session/old-ses/message"):
                return _Resp(404)
            if url.endswith("/session"):
                return _Resp(200, {"id": "new-ses"})
            if url.endswith("/session/new-ses/message"):
                return _Resp(200, {"parts": [{"type": "text", "text": "重建后完成"}]})
            return _Resp(500)

    monkeypatch.setattr(ta.httpx, "AsyncClient", _AC)
    a = ta.OpenCodeTurnAdapter(base_url="http://x")
    a._start_sse = lambda job: None   # SSE 订阅打桩

    class _J:
        id = "j404"
        session_id = "old-ses"
        serve_url = "http://x"
        wt = "/tmp/x-wt"
        model = ""
        turn_timeout = 10.0
        last_activity_ts = 0.0
        last_error = ""

        def emit(self, *a, **k):
            pass

    j = _J()
    out = asyncio.run(a.run_turn(j, "做任务"))
    assert j.session_id == "new-ses"            # 会话已重建
    assert out.output == "重建后完成"            # 指令已重发并拿到结果
    assert posts[0].endswith("/session/old-ses/message")
    assert posts[1].endswith("/session")        # 重建调用
    assert posts[2].endswith("/session/new-ses/message")


def test_opencode_run_turn_model_body(monkeypatch):
    """models[] 换模: provider/model → body.model(providerID/modelID)。"""
    bodies = []

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"parts": [{"type": "text", "text": "ok"}]}

    class _AC:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            bodies.append(json)
            return _Resp()

    monkeypatch.setattr(ta.httpx, "AsyncClient", _AC)
    a = ta.OpenCodeTurnAdapter(base_url="http://x")
    a._start_sse = lambda job: None

    class _J:
        id = "jm"
        session_id = "s1"
        serve_url = "http://x"
        wt = "/tmp/x-wt"
        model = "openai-compatible/qwen3"
        turn_timeout = 10.0
        last_activity_ts = 0.0

        def emit(self, *a, **k):
            pass

    out = asyncio.run(a.run_turn(_J(), "hi"))
    assert out.output == "ok"
    assert bodies[0]["model"] == {"providerID": "openai-compatible",
                                  "modelID": "qwen3"}


def test_opencode_run_turn_agent_body(monkeypatch):
    """executor config.agent 绑定 → body.agent 下发(opencode 代理选择)。"""
    bodies = []

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"parts": [{"type": "text", "text": "ok"}]}

    class _AC:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            bodies.append(json)
            return _Resp()

    monkeypatch.setattr(ta.httpx, "AsyncClient", _AC)
    a = ta.OpenCodeTurnAdapter(base_url="http://x")
    a._start_sse = lambda job: None

    class _J:
        id = "ja"
        session_id = "s1"
        serve_url = "http://x"
        wt = "/tmp/x-wt"
        model = ""
        agent = "plan"
        turn_timeout = 10.0
        last_activity_ts = 0.0

        def emit(self, *a, **k):
            pass

    asyncio.run(a.run_turn(_J(), "hi"))
    assert bodies[0]["agent"] == "plan"
    assert "model" not in bodies[0]

    class _J2(_J):
        agent = ""          # 未绑定 → 不下发 agent 字段

    asyncio.run(a.run_turn(_J2(), "hi"))
    assert "agent" not in bodies[1]


# ── P2: opencode/codex 流式事件 + codex sandbox 映射 ────────────────────────

def _stream_job(jid="js"):
    class _J:
        id = jid
        session_id = "s1"
        serve_url = "http://x"
        wt = "/tmp/x-wt"
        model = ""
        turn_timeout = 10.0
        boundaries = {}
        last_activity_ts = 0.0
        last_error = ""
        emitted: list = []

        def emit(self, kind, text="", **extra):
            self.emitted.append({"kind": kind, "text": text, **extra})
    return _J()


def test_opencode_sse_parts_stream_deltas():
    """text part 全量重放 → 只发新增片段; tool part 首见 → emit("tool")。

    2610 P1a: v1(message.parts 全量)与 v2(part.updated 单 part)双形状
    统一经 _diff_part 幂等 diff——游标共享, 双路径不重复发射。"""
    a = ta.OpenCodeTurnAdapter(base_url="http://x")
    j = _stream_job()

    def msg_event(text, parts_extra=None):
        parts = [{"type": "text", "text": text}] + (parts_extra or [])
        return {"type": "message.updated",
                "properties": {"sessionID": "s1",
                               "message": {"id": "m1", "parts": parts}}}

    # 第一次: 部分 text + 工具(v1 全量形状)
    for idx, p in enumerate(msg_event("正在分析")["properties"]["message"]["parts"]):
        a._diff_part(j, "m1", idx, p)
    a._diff_part(j, "m1", 1, {"type": "tool", "tool": "editor"})
    kinds = [(e["kind"], e["text"]) for e in j.emitted]
    assert ("text", "正在分析") in kinds
    assert any(e["kind"] == "tool" and e.get("toolName") == "editor"
               for e in j.emitted)

    # 第二次: 同 part 增长 → 只发增量; 工具首见去重
    j.emitted.clear()
    for idx, p in enumerate(msg_event("正在分析代码结构")["properties"]["message"]["parts"]):
        a._diff_part(j, "m1", idx, p)
    assert [(e["kind"], e["text"]) for e in j.emitted if e["kind"] == "text"] == \
        [("text", "代码结构")]
    assert not [e for e in j.emitted if e["kind"] == "tool"]


def test_opencode_v2_part_event_stream():
    """2610 P1a: v2 单 part 形状(properties.part, part.id 游标)——
    cv-8 实证 v2 事件与 v1 全量解析漂移 → 全程零 text 事件的回归锁。"""
    a = ta.OpenCodeTurnAdapter(base_url="http://x")
    j = _stream_job("jv2")
    a._diff_part(j, "mv1", 0, {"id": "prt_1", "type": "text", "text": "核查"})
    a._diff_part(j, "mv1", 0, {"id": "prt_1", "type": "text",
                               "text": "核查完毕。结论：能查到"})
    assert [(e["kind"], e["text"]) for e in j.emitted if e["kind"] == "text"] == \
        [("text", "核查"), ("text", "完毕。结论：能查到")]
    # v2 单 part 重复投递幂等(游标按 part.id)
    a._diff_part(j, "mv1", 0, {"id": "prt_1", "type": "text",
                               "text": "核查完毕。结论：能查到"})
    assert len([e for e in j.emitted if e["kind"] == "text"]) == 2
    assert a._turn_streamed["jv2"] == len("核查完毕。结论：能查到")


def test_opencode_run_turn_silent_flush(monkeypatch):
    """2610 P1c: 本轮流式全哑 → 最终回答整段 emit("text")保底 + 游标推进
    (cv-8 实证: 回答只存在 opencode 会话里, architect 侧零显示)。"""
    a = ta.OpenCodeTurnAdapter(base_url="http://x")
    j = _stream_job("jflush")
    j.serve_url = "http://x"
    j.session_id = "s1"
    j.turn_timeout = 5.0

    class _R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"info": {"id": "ma"},
                    "parts": [{"id": "pa", "type": "text",
                               "text": "核查完毕：能查到 KB 内容"}]}

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _R()

    monkeypatch.setattr(ta.httpx, "AsyncClient", _C)
    monkeypatch.setattr(ta, "_git_changed_files", lambda wt: [])
    a._turn_busy["jflush"] = True
    out = __import__("asyncio").run(a.run_turn(j, "hi"))
    assert out.output == "核查完毕：能查到 KB 内容"
    texts = [e["text"] for e in j.emitted if e["kind"] == "text"]
    assert texts == ["核查完毕：能查到 KB 内容"], "零流式应整段保底 emit"
    assert a._text_cursor.get("pa") == len(out.output), "游标推进防轮询重复"
    assert a._turn_streamed["jflush"] == len(out.output)

    # 轮询兜底不再重复发射(同一 part 已入游标)
    j.emitted.clear()
    a._diff_part(j, "ma", 0, {"id": "pa", "type": "text",
                              "text": "核查完毕：能查到 KB 内容"})
    assert not [e for e in j.emitted if e["kind"] == "text"]


def test_opencode_poll_diff_stream(monkeypatch):
    """2610 P1b: 轮内轮询 REST 快照 diff——SSE 形状漂移时流式不丢。"""
    a = ta.OpenCodeTurnAdapter(base_url="http://x")
    j = _stream_job("jpoll")
    j.session_id = "s9"
    a._turn_busy["jpoll"] = True

    async def fake_fetch(job):
        return [{"info": {"id": "mz"},
                 "parts": [{"id": "pz", "type": "text", "text": "轮询兜底输出"}]}]

    monkeypatch.setattr(a, "_fetch_messages", fake_fetch)
    import asyncio as _aio
    seen = []

    real_diff = a._diff_part

    def spy_diff(job, mid, idx, p):
        real_diff(job, mid, idx, p)
        seen.extend(e["text"] for e in job.emitted if e["kind"] == "text")

    a._diff_part = spy_diff
    msgs = _aio.run(a._fetch_messages(j))
    for m in msgs:
        mid = str(((m or {}).get("info") or {}).get("id") or "")
        for idx, p in enumerate((m or {}).get("parts") or []):
            a._diff_part(j, mid, idx, p)
    assert "轮询兜底输出" in seen
    assert a._turn_streamed["jpoll"] == len("轮询兜底输出")


def test_codex_stream_items_delta_and_tools():
    """agent item 增长 → 增量 emit("text"); command item 首见 → emit("tool")。"""
    a = ta.CodexTurnAdapter({"codex_bin": "codex"})
    a._stream_cursor = {}
    a._stream_tools = set()
    j = _stream_job("jcx")

    a._stream_codex_item(j, {"method": "item/updated", "params": {"item": {
        "id": "it1", "type": "agentMessage",
        "content": [{"type": "text", "text": "第一步"}]}}})
    a._stream_codex_item(j, {"method": "item/updated", "params": {"item": {
        "id": "it1", "type": "agentMessage",
        "content": [{"type": "text", "text": "第一步完成"}]}}})
    a._stream_codex_item(j, {"method": "item/updated", "params": {"item": {
        "id": "it2", "type": "commandExecution", "command": "pytest -q"}}})
    texts = [e["text"] for e in j.emitted if e["kind"] == "text"]
    assert texts == ["第一步", "完成"]           # 增量: 第二次只发"完成"
    tools = [e for e in j.emitted if e["kind"] == "tool"]
    assert len(tools) == 1 and tools[0]["toolName"] == "pytest -q"
    # 工具重放去重
    a._stream_codex_item(j, {"method": "item/updated", "params": {"item": {
        "id": "it2", "type": "commandExecution", "command": "pytest -q"}}})
    assert len([e for e in j.emitted if e["kind"] == "tool"]) == 1


def test_codex_turn_sandbox_readonly(monkeypatch):
    """boundaries.readOnly → turn/start sandbox read-only（原生沙箱级只读）。"""
    fake = _FakeCodexProc()
    calls = {}
    orig_call = fake.call

    async def spy_call(method, params=None, timeout=None):
        if method == "turn/start":
            calls["params"] = params
        return await orig_call(method, params, timeout)

    fake.call = spy_call
    proxy = type("P", (), {"proc": fake, "dead": False, "dead_reason": ""})()
    monkeypatch.setitem(ta._CODEX_SERVERS, "codex:", proxy)
    a = ta.CodexTurnAdapter({"codex_bin": "codex"})

    async def _flow():
        class _J:
            id = "jro"
            session_id = ""
            serve_url = ""
            wt = "/tmp/x-wt"
            model = ""
            turn_timeout = 10.0
            boundaries = {"readOnly": True}
            last_activity_ts = 0.0
            last_error = ""

            def emit(self, *a, **k):
                pass
        j = _J()
        await a.start_session(j)
        await a.run_turn(j, "只读任务")
        return j
    asyncio.run(_flow())
    assert calls["params"]["sandbox"] == {"mode": "read-only"}
    assert calls["params"]["approvalPolicy"] == "never"


# ── P3: 内省补齐（opencode messages/usage/model + codex usage/messages/退避）──

def test_opencode_read_messages_dual_shape(monkeypatch):
    """opencode 消息双形状兼容: {role,parts} 与 {info:{role},parts}。"""
    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return [
                {"role": "user", "parts": [{"type": "text", "text": "问题"}]},
                {"info": {"role": "assistant"},
                 "parts": [{"type": "text", "text": "回答"},
                           {"type": "tool", "tool": "read"}]},
            ]

    class _AC:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _Resp()

    monkeypatch.setattr(ta.httpx, "AsyncClient", _AC)
    a = ta.OpenCodeTurnAdapter(base_url="http://x")

    class _J:
        session_id = "s1"
        serve_url = "http://x"
        model = ""

    msgs = asyncio.run(a.read_messages(_J()))
    assert msgs[0] == {"role": "user", "content": "问题"}
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == "回答"          # tool part 不混入文本


def test_opencode_usage_and_model(monkeypatch):
    """tokens 聚合（含 info 嵌套）; 换模记 job.model。"""
    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return [
                {"role": "user", "tokens": {"input": 10, "output": 5}},
                {"info": {"role": "assistant", "tokens": {"input": 100, "output": 50}}},
            ]

    class _AC:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _Resp()

    monkeypatch.setattr(ta.httpx, "AsyncClient", _AC)
    a = ta.OpenCodeTurnAdapter(base_url="http://x")

    class _J:
        session_id = "s1"
        serve_url = "http://x"
        model = ""

    j = _J()
    usage = asyncio.run(a.get_usage(j))
    assert usage == {"usage": {"inputTokens": 110, "outputTokens": 55}}
    assert asyncio.run(a.update_model(j, "qwen3")) is True
    assert j.model == "qwen3"


def test_codex_usage_and_transcript(monkeypatch):
    """turn/completed usage 采集 + events ring 转写。"""
    fake = _FakeCodexProc()
    orig_call = fake.call

    async def richer_call(method, params=None, timeout=None):
        if method == "turn/start":
            fake.events.append({"method": "item/updated",
                                "params": {"item": {"id": "it1",
                                                    "type": "agentMessage",
                                                    "content": [{"text": "分析完毕"}]}}})
            fake.events.append({"method": "turn/completed",
                                "params": {"turn": {"status": "completed",
                                                    "usage": {"inputTokens": 200,
                                                              "outputTokens": 80}}}})
            return {"turn": {"id": "t1"}}
        return await orig_call(method, params, timeout)

    fake.call = richer_call
    proxy = type("P", (), {"proc": fake, "dead": False, "dead_reason": ""})()
    monkeypatch.setitem(ta._CODEX_SERVERS, "codex:", proxy)
    a = ta.CodexTurnAdapter({"codex_bin": "codex"})

    async def _flow():
        class _J:
            id = "ju"
            session_id = ""
            serve_url = ""
            wt = "/tmp/x-wt"
            model = ""
            turn_timeout = 10.0
            boundaries = {}
            last_activity_ts = 0.0
            last_error = ""

            def emit(self, *a, **k):
                pass
        j = _J()
        await a.start_session(j)
        await a.run_turn(j, "x")
        usage = await a.get_usage(j)
        msgs = await a.read_messages(j)
        return usage, msgs
    usage, msgs = asyncio.run(_flow())
    assert usage["usage"]["inputTokens"] == 200
    assert usage["usage"]["outputTokens"] == 80
    assert any("分析完毕" in m["content"] for m in msgs)


def test_codex_error_backoff_then_fail(monkeypatch):
    """willRetry=True × 2 → 退避(2s/4s); 第 3 次 willRetry=False → 失败。"""
    fake = _FakeCodexProc()
    orig_call = fake.call
    sleeps = []

    async def err_call(method, params=None, timeout=None):
        if method == "thread/start":
            return {"thread": {"id": "th1"}}
        if method == "turn/start":
            fake.events.extend([
                {"method": "error", "params": {"error": {"message": "rate limited"},
                                               "willRetry": True}},
                {"method": "error", "params": {"error": {"message": "rate limited"},
                                               "willRetry": True}},
                {"method": "error", "params": {"error": {"message": "quota exceeded"},
                                               "willRetry": False}},
            ])
            return {"turn": {"id": "t1"}}
        return await orig_call(method, params, timeout)

    fake.call = err_call

    real_sleep = asyncio.sleep

    async def fake_sleep(delay, *a, **k):
        sleeps.append(delay)
        await real_sleep(0)

    proxy = type("P", (), {"proc": fake, "dead": False, "dead_reason": ""})()
    monkeypatch.setitem(ta._CODEX_SERVERS, "codex:", proxy)
    a = ta.CodexTurnAdapter({"codex_bin": "codex"})

    async def _flow():
        class _J:
            id = "jb"
            session_id = ""
            serve_url = ""
            wt = "/tmp/x-wt"
            model = ""
            turn_timeout = 10.0
            boundaries = {}
            last_activity_ts = 0.0
            last_error = ""

            def emit(self, *a, **k):
                pass
        j = _J()
        await a.start_session(j)
        await a.run_turn(j, "x")
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    with pytest.raises(RuntimeError, match="quota exceeded"):
        asyncio.run(_flow())
    assert 2.0 in sleeps and 4.0 in sleeps     # 指数退避发生


# ── P4: cline steer 直达 + shutdown 清理 ────────────────────────────────────

def test_cline_v2_steer_dispatch(monkeypatch):
    """cline.steer → sidecar turn/steer（成功/失败两路）。"""
    fake = _FakeSidecar()
    _patch_sidecar(monkeypatch, fake)
    a = _adapter()
    j = _fake_job()
    j.session_id = "jc1"
    assert asyncio.run(a.steer(j, "改用方案 B")) is True
    method, params = [c for c in fake.calls if c[0] == "turn/steer"][0]
    assert params == {"sessionId": "jc1", "prompt": "改用方案 B"}
    # 失败路：sidecar 返回 ok=False
    fake2 = _FakeSidecar()
    fake2.results["turn/steer"] = {"ok": False, "steered": False}
    _patch_sidecar(monkeypatch, fake2)
    assert asyncio.run(a.steer(j, "x")) is False


def test_implement_steer_direct_when_busy(monkeypatch):
    """busy + steer → adapter.steer 直达（不排队）; 不支持 → 回退排队。"""
    j = impl.ImplementJob(
        "impl-st", "/tmp/x", "/tmp/x-wt", "HEAD", "b", "i",
        adapter=_WatchFakeAdapter(lambda: None))
    j._busy = True
    j.status = "running"

    async def fake_steer(text):
        return True

    j.adapter.steer = lambda job, text: fake_steer(text)
    res = asyncio.run(j.user_input("转向", steer=True))
    assert res["ok"] and res["delivery"] == "steered"  # A6.4 协议位
    assert j.pending_inputs == []            # 未排队

    # busy + steer 但 adapter 不支持 → 排队
    j2 = impl.ImplementJob(
        "impl-st2", "/tmp/x", "/tmp/x-wt", "HEAD", "b", "i",
        adapter=_WatchFakeAdapter(lambda: None))
    j2._busy = True
    res2 = asyncio.run(j2.user_input("继续", steer=True))
    assert res2["queued"] is True and res2["delivery"] == "queued"  # A6.4
    assert j2.pending_inputs == ["继续"]

    # busy + 无 steer → 排队（原行为）
    res3 = asyncio.run(j2.user_input("普通补充"))
    assert res3["queued"] is True and res3["delivery"] == "queued"


def test_implement_steer_terminal_rejected():
    j = impl.ImplementJob(
        "impl-st3", "/tmp/x", "/tmp/x-wt", "HEAD", "b", "i",
        adapter=_WatchFakeAdapter(lambda: None))
    j.status = "done"
    res = asyncio.run(j.user_input("x", steer=True))
    assert res["ok"] is False


def test_shutdown_executors_kills_shared(monkeypatch):
    """runner 退出钩子: 共享 sidecar/app-server 全部 kill。"""
    killed = []

    class _SC:
        async def kill(self):
            killed.append("cline")

    class _Proc:
        async def kill(self):
            killed.append("codex")

    monkeypatch.setitem(ta._CLINE_SIDECARS, "node:x.js", _SC())
    proxy = type("P", (), {"proc": type("Q", (), {"kill": lambda s: killed.append("codex") or asyncio.sleep(0)})()})()
    monkeypatch.setitem(ta._CODEX_SERVERS, "codex:", proxy)
    asyncio.run(ta.shutdown_executors())
    assert "cline" in killed
    assert ta._CLINE_SIDECARS == {} and ta._CODEX_SERVERS == {}


# ── P5: Teams/MCP/Rules 透传 ────────────────────────────────────────────────

def test_cline_v2_teams_mcp_passthrough(monkeypatch):
    """executorConfig teams/mcp_servers → session/start 参数。"""
    fake = _FakeSidecar()
    _patch_sidecar(monkeypatch, fake)
    a = _adapter(
        mcp_servers=[{"name": "arch", "transport": "streamableHttp",
                      "url": "http://127.0.0.1:3460/v1"}],
        teams={"enabled": True, "teamName": "impl-team"})
    j = _fake_job()

    async def _flow():
        await a.start_session(j)
    asyncio.run(_flow())
    _, params = fake.calls[0]
    assert params.get("mcpServers") == [{"name": "arch",
                                         "transport": "streamableHttp",
                                         "url": "http://127.0.0.1:3460/v1"}]
    assert params.get("teams") == {"enabled": True, "teamName": "impl-team"}
    # 未配置时不传
    fake2 = _FakeSidecar()
    _patch_sidecar(monkeypatch, fake2)
    a2 = _adapter()
    async def _f2():
        await a2.start_session(j)
    asyncio.run(_f2())
    _, params2 = fake2.calls[0]
    assert "mcpServers" not in params2 and "teams" not in params2


def test_cline_v2_team_and_mcp_events(monkeypatch):
    """team/mcp_ready/mcp_failed sidecar 事件 → job.emit(team/mcp)。"""
    fake = _FakeSidecar()
    _patch_sidecar(monkeypatch, fake)
    a = _adapter()
    j = _fake_job()
    j.session_id = "jc1"

    async def _flow():
        await a.start_session(j)
        handler = fake.handlers["jc1"]
        handler({"type": "team", "sessionId": "jc1",
                 "payload": {"teamName": "t1", "summary": "teammate spawned"}})
        handler({"type": "mcp_ready", "sessionId": "jc1", "server": "arch",
                 "tools": 3})
        handler({"type": "mcp_failed", "sessionId": "jc1", "server": "bad",
                 "message": "connect timeout"})
    asyncio.run(_flow())
    kinds = [e["kind"] for e in j.emitted]
    assert "team" in kinds and "mcp" in kinds
    mcp_events = [e for e in j.emitted if e["kind"] == "mcp"]
    assert any(e.get("ok") is True and e.get("server") == "arch" for e in mcp_events)
    assert any(e.get("ok") is False and e.get("server") == "bad" for e in mcp_events)


# ── S3 子会话复活: sessionRef 预置 → adapter 复用执行器原生会话 ────────

def test_implement_sessionref_preset():
    """sessionRef 预置即复活键(job.session_id 注入 adapter)。"""
    import topoone.plugins.runner.implement as impl
    job = impl.ImplementJob(
        "impl-x", "/r", "/w", "HEAD", "b", "i",
        adapter=_WatchFakeAdapter(lambda: None))
    job.session_id = "ses-old"
    assert job.session_id == "ses-old"


def test_opencode_adapter_reuses_preset_session(monkeypatch):
    """OpenCodeTurnAdapter.start_session: 预置 session_id → 跳过 POST /session 直接订阅。"""
    import asyncio
    from topoone.plugins.runner.turn_adapter import OpenCodeTurnAdapter

    created = {"n": 0}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): created["n"] += 1; return {"id": "ses-new"}

    class _NoPostClient:
        def __init__(self, *a, **k): pass 
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return _Resp()

    import topoone.plugins.runner.turn_adapter as ta
    monkeypatch.setattr(ta.httpx, "AsyncClient", _NoPostClient)

    a = OpenCodeTurnAdapter(base_url="http://127.0.0.1:19999")
    a._start_sse = lambda job: None   # 订阅打桩

    class _J:
        id = "j1"; wt = "/w"; session_id = "ses-old"; serve_url = ""; sse_stop = None
    j = _J()
    asyncio.run(a.start_session(j))
    assert j.session_id == "ses-old"   # 未被覆盖
    assert created["n"] == 0           # 未新建会话


def test_cline_sidecar_script_default_fallback(tmp_path):
    """config 未携 sidecar_script(architect 注册表默认空串) → runner 回退包内默认路径。"""
    import os
    from topoone.plugins.runner.turn_adapter import (
        ClineTurnAdapter, _default_sidecar_script)
    a = ClineTurnAdapter({"sidecar_script": ""})
    assert a._script == _default_sidecar_script()
    assert os.path.isfile(a._script), "默认 sidecar 脚本应存在(需 npm run build -w packages/cline-sidecar)"
    b = ClineTurnAdapter({"sidecar_script": str(tmp_path / "x.js")})
    assert b._script == str(tmp_path / "x.js"), "显式配置不覆盖"


# ── ClineTurnAdapter v2（ClineCore 会话宿主; fake sidecar 不起真进程）────────

class _FakeSidecar:
    """v2 sidecar 假件: call 记录方法并可编程回包; 会话事件可注入。"""

    def __init__(self):
        self.calls: list = []
        self.handlers: dict = {}
        self.alive = True
        self.results: dict = {}      # method → 返回值
        self.scripts: dict = {}      # method → callable(params) → result

    def set_session_handler(self, sid, handler):
        self.handlers[sid] = handler

    def clear_session_handler(self, sid):
        self.handlers.pop(sid, None)

    async def call(self, method, params=None, timeout=None):
        self.calls.append((method, params))
        if method in self.scripts:
            return self.scripts[method](params or {})
        return self.results.get(method, {"ok": True})

    async def ensure(self):
        pass


def _fake_job(jid="jc1", boundaries=None, model=""):
    import time as _t

    _b = boundaries or {}
    _m = model

    class _Job:
        id = jid
        session_id = ""
        serve_url = ""
        wt = "/tmp/x-wt"
        model = _m
        turn_timeout = 10.0
        boundaries = _b
        project_id = "p1"
        last_activity_ts = 0.0
        last_error = ""
        emitted: list = []

        def emit(self, kind, text="", **extra):
            self.emitted.append({"kind": kind, "text": text, **extra})
    return _Job()


def _patch_sidecar(monkeypatch, fake):
    # 键与 ClineTurnAdapter._sidecar 同式: node:script:data_dir(引擎版本隔离维度)
    monkeypatch.setitem(ta._CLINE_SIDECARS, "node:test.js:", fake)


def _adapter(**cfg):
    # model_id 缺省给测试模型(未配置模型 → _resolve_model 抛错, 由专测锁定)
    base = {"node_bin": "node", "sidecar_script": "test.js", "model_id": "test-model"}
    base.update(cfg)
    return ta.ClineTurnAdapter(base)


def test_cline_v2_start_session_params_and_models(monkeypatch):
    """models[] 消费: 作业模型名命中条目 → url/apiKey 下发 session/start。"""
    fake = _FakeSidecar()
    _patch_sidecar(monkeypatch, fake)
    a = _adapter(models=[{
        "id": "m1", "name": "deepseek", "model": "openai-compatible/deepseek-chat",
        "url": "https://api.deepseek.com", "apiKey": "sk-test",
    }])
    j = _fake_job(model="deepseek")

    async def _flow():
        await a.start_session(j)
    asyncio.run(_flow())
    method, params = fake.calls[0]
    assert method == "session/start"
    assert params["sessionId"] == "jc1"
    assert params["cwd"] == j.wt
    assert params["model"]["providerId"] == "openai-compatible"
    assert params["model"]["modelId"] == "deepseek-chat"
    assert params["model"]["apiKey"] == "sk-test"
    assert params["model"]["baseUrl"] == "https://api.deepseek.com/v1"
    assert params["protocolTools"] is True
    assert j.session_id == "jc1"


def test_cline_v2_readonly_boundaries_block_write_tools(monkeypatch):
    """boundaries.readOnly → 写类工具 enabled:false 硬阻断（不依赖 Plan 模式语义）。"""
    fake = _FakeSidecar()
    _patch_sidecar(monkeypatch, fake)
    a = _adapter()
    j = _fake_job(boundaries={"readOnly": True, "files": ["src/"]})

    async def _flow():
        await a.start_session(j)
    asyncio.run(_flow())
    _, params = fake.calls[0]
    tp = params["toolPolicies"]
    for t in ("editor", "apply_patch", "run_commands"):
        assert tp[t]["enabled"] is False


def test_cline_v2_run_turn_streams_events_and_markers(monkeypatch):
    """turn/send 事件流 → job.emit; 协议工具结局 → [[IMPLEMENT_DONE]] 标记。"""
    fake = _FakeSidecar()

    def _turn_send(params):
        handler = fake.handlers.get(params["sessionId"])
        handler({"type": "text", "sessionId": params["sessionId"], "text": "正在修改…"})
        handler({"type": "tool_start", "sessionId": params["sessionId"],
                 "toolName": "editor"})
        handler({"type": "turn_outcome", "sessionId": params["sessionId"],
                 "status": "done", "summary": "开发+单测+编译完成"})
        # 与 sidecar v2 真实返回形状一致（outputText/turnOutcome）
        return {"ok": True, "status": "completed", "outputText": "完成",
                "turnOutcome": {"status": "done", "summary": "开发+单测+编译完成"}}

    fake.scripts["turn/send"] = _turn_send
    _patch_sidecar(monkeypatch, fake)
    a = _adapter()
    j = _fake_job()
    j.session_id = "jc1"

    async def _flow():
        await a.start_session(j)   # 注册 adapter 事件 handler
        return await a.run_turn(j, "做任务")
    out = asyncio.run(_flow())
    kinds = [e["kind"] for e in j.emitted]
    assert "text" in kinds and "tool" in kinds
    assert any(e.get("toolName") == "editor" for e in j.emitted)
    assert "[[IMPLEMENT_DONE]]" in out.output
    assert "开发+单测+编译完成" in out.output


def test_cline_v2_need_input_marker(monkeypatch):
    fake = _FakeSidecar()
    fake.scripts["turn/send"] = lambda p: {
        "ok": True, "status": "completed", "outputText": "请问?",
        "turnOutcome": {"status": "need_input", "summary": "需要提供 API key"}}
    _patch_sidecar(monkeypatch, fake)
    a = _adapter()
    j = _fake_job()
    j.session_id = "jc1"
    out = asyncio.run(asyncio.wait_for(a.run_turn(j, "x"), 5))
    assert "[[NEED_INPUT]]" in out.output


def test_cline_v2_probe_and_abort(monkeypatch):
    fake = _FakeSidecar()
    _patch_sidecar(monkeypatch, fake)
    a = _adapter()
    j = _fake_job()
    j.session_id = "jc1"

    async def _flow():
        p_idle = await a.probe(j)
        fake.alive = False
        p_dead = await a.probe(j)
        ok = await a.abort(j)
        return p_idle, p_dead, ok
    p_idle, p_dead, ok = asyncio.run(_flow())
    assert p_idle.status == "idle"
    assert p_dead.status == "error"
    assert ok is True
    assert any(m == "session/abort" for m, _ in fake.calls)


def test_cline_v2_respond_approval(monkeypatch):
    fake = _FakeSidecar()
    _patch_sidecar(monkeypatch, fake)
    a = _adapter()
    j = _fake_job()
    j.session_id = "jc1"

    async def _flow():
        return await a.respond_approval(j, "apr-3", False, "out of boundary")
    assert asyncio.run(_flow()) is True
    method, params = [c for c in fake.calls if c[0] == "approval/respond"][0]
    assert params["requestId"] == "apr-3"
    assert params["approved"] is False
    assert params["reason"] == "out of boundary"


def test_cline_v2_events_new_kinds_accepted():
    """events schema: cline v2 流式 kind 合法（只增兼容）。"""
    from topoone.plugins.runner.events import EventKind, make_event
    for kind in (EventKind.TOOL, EventKind.USAGE, EventKind.NOTICE,
                 EventKind.TURN_OUTCOME, EventKind.APPROVAL_REQUEST):
        ev = make_event(1, kind, "x", toolName="editor")
        assert ev["kind"] == kind


# ── cv-161 回归: cline 回合错误详情必须透出(error 事件→run_turn 异常) ──

def test_cline_run_turn_surfaces_error_detail(tmp_path, monkeypatch):
    """sidecar error 事件的 message 必须进入 run_turn 的失败原因——
    曾被丢弃(recoverable 才记), 失败只剩 generic「cline 回合失败(status=error)」。"""
    import asyncio
    import time
    from types import SimpleNamespace
    from topoone.plugins.runner.turn_adapter import ClineTurnAdapter

    adapter = ClineTurnAdapter({"provider_id": "openai-compatible",
                                "model_id": "m-1"}, executor_id="cline")
    job = SimpleNamespace(id="j-err", session_id="s-err", turn_timeout=30.0,
                          wt=str(tmp_path), model="", last_activity_ts=time.time())
    captured = {}

    class _FakeSc:
        async def call(self, method, params=None, timeout=None):
            captured["method"] = method
            # 模拟 sidecar: finishReason=error 且返回体不带 error 字段
            return {"ok": False, "status": "error"}

    monkeypatch.setattr(adapter, "_sidecar", lambda: _FakeSc())

    # 先来一条 error 事件(recoverable=True 也必须记)
    adapter._on_event(job, {"type": "error", "sessionId": "s-err",
                            "message": "API 401: invalid api key", "recoverable": True})
    with pytest.raises(RuntimeError, match="invalid api key"):
        asyncio.run(adapter.run_turn(job, "写个测试"))
    assert captured["method"] == "turn/send"


def test_resolve_model_base_url_ensures_v1():
    """cv-163: 模型条目 url 缺 /v1 → LM Studio 200+JSON 错误体(非 SSE) →
    "stream ended without a finish reason"。_resolve_model 必须兜底补 /v1。"""
    from topoone.plugins.runner.turn_adapter import ClineTurnAdapter, _ensure_v1
    a = ClineTurnAdapter(config={
        "provider_id": "openai-compatible",
        "models": [{"name": "m", "model": "q", "url": "http://10.0.0.75:1234"}],
    })
    r = a._resolve_model(type("J", (), {"model": "m"})())
    assert r["baseUrl"] == "http://10.0.0.75:1234/v1"
    assert _ensure_v1("http://h:8082/v1/") == "http://h:8082/v1"
    assert _ensure_v1("") == ""


def test_resolve_model_top_level_model_id_wins_over_models0(monkeypatch):
    """cv-163: 作业未指定模型时, 顶层 model_id 命中条目优先于 models[0]——
    否则实际执行的模型与 UI 展示的默认模型不一致。"""
    fake = _FakeSidecar()
    _patch_sidecar(monkeypatch, fake)
    a = _adapter(
        model_id="LMS-Qwen3.6-35B",
        models=[
            {"id": "m1", "name": "LMS-9b", "model": "qwen3.5-9b-mtp", "url": "http://h:1234"},
            {"id": "m2", "name": "LMS-Qwen3.6-35B", "model": "qwen3.6-35b", "url": "http://h:8082"},
        ])
    j = _fake_job(model="")
    asyncio.run(a.start_session(j))
    _, params = fake.calls[0]
    assert params["model"]["modelId"] == "qwen3.6-35b"
    assert params["model"]["baseUrl"] == "http://h:8082/v1"


def test_resolve_model_fallback_models0_when_model_id_misses(monkeypatch):
    """顶层 model_id 无命中(改名/删除) → 兜底 models[0], 不空转。"""
    a = _adapter(
        model_id="gone-model",
        models=[{"id": "m1", "name": "9b", "model": "qwen3.5-9b-mtp", "url": "http://h:1234"}])
    r = a._resolve_model(type("J", (), {"model": ""})())
    assert r["modelId"] == "qwen3.5-9b-mtp"


def test_resolve_model_raises_when_unconfigured():
    """cv-168 用户裁决: 模型全链路无配置 → 明确抛错(禁止 sidecar 自带默认兜底)。"""
    import pytest as _pt
    a = _adapter(model_id="", models=[])
    with _pt.raises(RuntimeError, match="未配置模型"):
        a._resolve_model(type("J", (), {"model": ""})())


def test_resolve_model_carries_max_tokens_per_turn():
    """生成容量接入请求链: 模型条目 maxTokens>0 → session/start 携 maxTokensPerTurn
    (cline 适用; 0/缺省不传——opencode/codex 按其自身内部设置)。"""
    a = _adapter(models=[{"id": "m1", "name": "m", "model": "q", "url": "http://h",
                          "maxTokens": 16384}])
    r = a._resolve_model(type("J", (), {"model": "m"})())
    assert r["maxTokensPerTurn"] == 16384
    a2 = _adapter(models=[{"id": "m1", "name": "m", "model": "q", "url": "http://h",
                           "maxTokens": 0}])
    r2 = a2._resolve_model(type("J", (), {"model": "m"})())
    assert "maxTokensPerTurn" not in r2


def test_cline_system_prompt_dod_discipline():
    """cv-176 裁决: cline 验证边界=构建通过+运行冒烟, 禁独立单测(单测归独立流程);
    仅 cline systemPrompt 注入——任务指令公共路径不含(负断言锁边界)。"""
    a = _adapter()
    prompt = a._DEFAULT_SYSTEM_PROMPT
    assert "禁止编写独立单元测试" in prompt
    assert "运行层面冒烟验证" in prompt
    assert "由独立 subagent 流程负责" in prompt
    # 任务指令公共路径(exec_bridge._task_instruction, architect 侧)不含该纪律
    # ——此处锁 core 侧事实: 纪律只存在于 cline adapter
    assert "验证边界" in prompt and "cv-176" not in prompt


# ── cline 引擎多版本共存: 数据目录随版本隔离 ────────────────────────────────

def test_cline_data_dir_isolation():
    """cline_data_dir(cline_engines 引擎解析下发) → sidecar 单例键含数据目录
    ——同脚本不同版本 → 独立进程; 空则继承默认存储(仓库内置回退链不变)。"""
    a1 = ta.ClineTurnAdapter({"node_bin": "node", "sidecar_script": "a.js",
                              "cline_data_dir": "/d/v0.0.82", "model_id": "m"})
    a2 = ta.ClineTurnAdapter({"node_bin": "node", "sidecar_script": "a.js",
                              "cline_data_dir": "/d/v0.0.83", "model_id": "m"})
    a0 = ta.ClineTurnAdapter({"node_bin": "node", "sidecar_script": "a.js",
                              "model_id": "m"})
    assert a1._data_dir == "/d/v0.0.82"
    sc1, sc2 = a1._sidecar(), a2._sidecar()
    assert sc1 is not sc2                    # 不同版本 → 独立 sidecar 进程
    assert sc1._data_dir == "/d/v0.0.82" and sc2._data_dir == "/d/v0.0.83"
    assert a1._sidecar() is sc1              # 同版本复用单例
    assert a0._data_dir == "" and a0._sidecar()._data_dir == ""
    # env 注入面: 有数据目录才设 TOPOCODE_CLINE_DATA_DIR(host.configureStorage 消费)
    import inspect
    src = inspect.getsource(ta._SidecarProcess._start_locked)
    assert "TOPOCODE_CLINE_DATA_DIR" in src


def test_opencode_role_filter_user_not_echoed():
    """2610 D1: 用户提示词不回显成执行器输出——快照入账按 role 过滤,
    v2 单 part 未知/非助手角色一律跳过(cv-9/11 三轮实证的回显根因)。"""
    a = ta.OpenCodeTurnAdapter(base_url="http://x")
    j = _stream_job("jrole")
    a._ingest_snapshot(j, [
        {"info": {"id": "mu", "role": "user"},
         "parts": [{"type": "text", "text": "继续执行，给出基线分析"}]},
        {"info": {"id": "ma", "role": "assistant"},
         "parts": [{"type": "text", "text": "检查结论: MCP 可查"}]},
    ])
    texts = [(e["kind"], e["text"]) for e in j.emitted if e["kind"] == "text"]
    assert texts == [("text", "检查结论: MCP 可查")], "用户消息不得发射"
    assert a._msg_roles.get("mu") == "user" and a._msg_roles.get("ma") == "assistant"

    # v2 单 part: 未知角色跳过(不抢跑) → 角色校准后入账
    j.emitted.clear()
    a._ingest_v2_part(j, {"id": "px", "messageID": "m_new",
                          "type": "text", "text": "未知角色文本"})
    assert not [e for e in j.emitted if e["kind"] == "text"], "未知角色应跳过"
    a._msg_roles["m_new"] = "assistant"
    a._ingest_v2_part(j, {"id": "px", "messageID": "m_new",
                          "type": "text", "text": "助手文本"})
    assert [e["text"] for e in j.emitted if e["kind"] == "text"] == ["助手文本"]


def test_opencode_run_turn_drain_captures_final_part(monkeypatch):
    """2610 D2 收束扫尾: 轮询错过的最后 part 在 POST 返回后确定性补采
    (cv-11 实证: 最终报告只留 turn_done 载荷, 卡片缺失/迟到一轮)。"""
    a = ta.OpenCodeTurnAdapter(base_url="http://x")
    j = _stream_job("jdrain")
    j.serve_url = "http://x"
    j.session_id = "s1"
    j.turn_timeout = 5.0

    class _R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"info": {"id": "mfin", "role": "assistant"},
                    "parts": [{"id": "pf", "type": "text",
                               "text": "# 基线分析报告（最终结论）"}]}

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _R()

        async def get(self, *a, **k):
            return _R()

    monkeypatch.setattr(ta.httpx, "AsyncClient", _C)
    monkeypatch.setattr(ta, "_git_changed_files", lambda wt: [])
    import asyncio as _aio
    out = _aio.run(a.run_turn(j, "hi"))
    texts = [e["text"] for e in j.emitted if e["kind"] == "text"]
    # 扫尾 diff 捕获最终 part(经游标, 仅此一次; P1c 因流式计数>0 不重复发射)
    assert texts == ["# 基线分析报告（最终结论）"], texts
    assert out.output == "# 基线分析报告（最终结论）"
    assert a._turn_streamed["jdrain"] == len(out.output)
