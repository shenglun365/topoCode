"""task_input 持久回声回归（R4 requestId 回声）。

转达成功 → 主流落 role=user + meta.kind=task_input_echo 的持久回执
（携带 requestId/queued/steer）——「发出→落地」可对账; 投喂路径 echo=False 防双写。

Run: cd <repo> && python -m pytest apps/architect/tests/test_task_input_echo.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_exec_implement import _mk_v2_fixture  # noqa: E402

from topoone_app_architect import store  # noqa: E402


def test_input_echo_durable_with_request_id(tmp_path, monkeypatch):
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "E", "x")
    assert eb.confirm_task(task["id"])["ok"]
    eb._handle_task_event({"kind": "input_required", "text": "[[NEED_INPUT]]\n选哪个库?"},
                          eb._task_ctx(conv["id"], task["id"], "job-v2-1", "", "opencode"))
    r = eb.task_input(task["id"], "用标准库")
    assert r["ok"] and r.get("requestId")
    msgs = store.ConversationsStore.messages(conv["id"])
    echo = [m for m in msgs if (m.get("meta") or {}).get("kind") == "task_input_echo"]
    assert echo, "主流缺 task_input_echo 持久回执"
    last = echo[-1]
    assert last["role"] == "user" and "用标准库" in (last["content"] or "")
    assert last["meta"]["requestId"] == r["requestId"]
    assert last["meta"]["queued"] is False and last["meta"]["steer"] is False


def test_input_echo_disabled_no_double_write(tmp_path, monkeypatch):
    """echo=False（投喂路径）→ 不落主流回执, 其余行为不变。"""
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "E", "x")
    assert eb.confirm_task(task["id"])["ok"]
    r = eb.task_input(task["id"], "投喂内容", echo=False)
    assert r["ok"] and r.get("requestId")
    msgs = store.ConversationsStore.messages(conv["id"])
    assert not [m for m in msgs if (m.get("meta") or {}).get("kind") == "task_input_echo"]


def test_input_failure_no_echo_no_request_id(tmp_path, monkeypatch):
    """runner 不可达 → 失败路径无 requestId、无回执（回声只在落地后出现）。"""
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "E", "x")
    assert eb.confirm_task(task["id"])["ok"]

    def unreachable(path, payload=None, timeout=12.0):
        return None

    monkeypatch.setattr(eb, "_runner", unreachable)
    r = eb.task_input(task["id"], "任何内容")
    assert not r["ok"] and not r.get("requestId")
    msgs = store.ConversationsStore.messages(conv["id"])
    assert not [m for m in msgs if (m.get("meta") or {}).get("kind") == "task_input_echo"]


def test_input_echo_delivery_note_a64(tmp_path, monkeypatch):
    """A6.4 降级提示(回执卡, 拍板: 回执卡): 实际送达语义进回执内容与 meta。"""
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "D", "x")
    assert eb.confirm_task(task["id"])["ok"]

    class _Res:
        ok = True
        queued = True
        error = ""
        delivery = "queued"
        reason = "执行器 steer 未送达（适配器拒绝/不支持当前形态）"

    class _Client:
        def input(self, job_id, text, steer=False, timeout=15.0):
            return _Res()

    monkeypatch.setattr(eb, "_client", lambda: _Client())
    r = eb.task_input(task["id"], "排队补一句")
    assert r["ok"] and r["delivery"] == "queued" and r["reason"]
    msgs = store.ConversationsStore.messages(conv["id"])
    echo = [m for m in msgs if (m.get("meta") or {}).get("kind") == "task_input_echo"]
    assert echo, "回执缺失"
    last = echo[-1]
    assert last["meta"]["delivery"] == "queued"
    assert "已排队" in (last["content"] or "")
    assert "steer" in (last["content"] or "")
