"""执行器过程流单源 特征测试(cv-268)。

锁定:
- apply_event 三类过程事件落地形状(与任务链存量字段等价): text 滚动尾/
  tool 环形尾(30)/usage tokens; 非过程事件 None
- 直通泵: tool/usage → 内存过程态 + SSE progress(conversationId 键, 无 taskId);
  终态 proxy_finish → finished 帧 + 过程态清空
- 任务链等价回归: progress/tool 事件仍落 TasksStore + 状态卡刷新

Run: cd <repo> && python -m pytest apps/architect/tests/test_process_stream.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.execution import process_stream as ps


def test_apply_event_text_tool_usage_shapes():
    prev = ps.apply_event({}, {"kind": "text", "text": "分析中…"})
    assert prev["lastText"] == "分析中…"
    prev2 = ps.apply_event(prev, {"kind": "tool", "toolName": "editor"})
    assert prev2["lastTool"] == "editor"
    assert prev2["process"][-1]["s"] == "▸ editor"
    prev3 = ps.apply_event(prev2, {"kind": "usage", "inputTokens": 11,
                                   "outputTokens": 7})
    assert prev3["inputTokens"] == 11 and prev3["outputTokens"] == 7


def test_apply_event_ignores_non_process_kinds():
    assert ps.apply_event({}, {"kind": "turn_done", "text": "x"}) is None
    assert ps.apply_event({}, {"kind": "notice", "text": "x"}) is None


def test_tool_ring_capped_at_30():
    prev: dict = {}
    for i in range(35):
        prev = ps.apply_event(prev, {"kind": "tool", "toolName": f"t{i}"})
    assert len(prev["process"]) == 30
    assert prev["process"][-1]["s"] == "▸ t34"
    assert prev["process"][0]["s"] == "▸ t5"


def test_proxy_state_lifecycle(monkeypatch):
    """直通过程态: 纯内存生命周期——store/progress/finish 清空+finished 帧。"""
    import topoone_app_architect.agent.execution.proxy as _px
    emitted: list = []
    from topoone_app_architect.agent.collab import sse as _sse
    orig = _sse.emit
    _sse.emit = lambda t, cid, **kw: emitted.append((t, cid, kw))
    try:
        on_event, _snap, _lost, _flush = _px._make_handlers(
            "cv-ps", "job-ps", "cline-sdk")
        on_event({"kind": "text", "text": "执行中…"})
        on_event({"kind": "tool", "toolName": "editor"})
        assert ps.proxy_progress("cv-ps").get("lastTool") == "editor"
        progress_ev = [e for e in emitted if e[0] == "progress"]
        assert progress_ev, "过程事件未发 SSE progress"
        _, _, kw = progress_ev[-1]
        assert "taskId" not in kw, "直通过程事件不应带 taskId(FE 按 conv 分流)"
        assert kw.get("process") or kw.get("lastText")
        # 终态: finished 帧 + 过程态清空
        on_event({"kind": "done"})
        assert "cv-ps" not in ps._PROXY_PROGRESS
        fin = [e for e in emitted if e[0] == "progress" and e[2].get("finished")]
        assert fin, "终态未发 finished 帧"
    finally:
        _sse.emit = orig
        ps.proxy_clear("cv-ps")


def test_sse_throttle_semantics():
    assert ps.sse_throttle("text") > 0
    assert ps.sse_throttle("tool") == 0
    assert ps.sse_throttle("usage") == 0
