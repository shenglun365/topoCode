"""直通作业卡(JobCard) 特征测试(cv-283)。

用户裁决: 任务卡归一——直通模式与 architect 指派模式任务卡功能统一规划、
样式一致(proxy 卡升级同构)。启动卡 meta 携作业快照键(jobCard/jobState/
executorType/mode/fingerprint), 终态/停止经 fingerprint 原位回写 jobState
(词汇 running|idle|ended 与执行器状态轴同源), items.py 统一投影 type=job。

Run: cd <repo> && python -m pytest apps/architect/tests/test_proxy_jobcard.py -q
"""
from __future__ import annotations

import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.store as store
from topoone_app_architect.agent.execution import proxy


def _conv() -> dict:
    return store.ConversationsStore.create(
        {"projectId": "", "title": "jobcard", "meta": {}})


def _job_msgs(conv_id: str) -> list:
    return [m for m in store.ConversationsStore.messages(conv_id, limit=20)
            if (m.get("meta") or {}).get("kind") == "proxy"
            and (m.get("meta") or {}).get("jobCard")]


def test_start_card_carries_job_snapshot():
    """启动回执=JobCard: meta 快照键齐全 + fingerprint 单卡锚。"""
    conv = _conv()
    from topoone_app_architect.agent.execution import exec_bridge as eb
    row = eb._append(conv["id"], "assistant", "🔗 已直通执行器",
                     msg_meta={"kind": "proxy", "jobId": "job-jc-1",
                               "jobCard": 1, "jobState": "running",
                               "executorType": "cline-sdk",
                               "mode": "inplace",
                               "fingerprint": proxy._job_card_fp(conv["id"])},
                     agent="cline-sdk")
    assert row
    cards = _job_msgs(conv["id"])
    assert len(cards) == 1
    meta = cards[0]["meta"]
    assert meta["jobId"] == "job-jc-1" and meta["jobState"] == "running"
    assert meta["executorType"] == "cline-sdk" and meta["mode"] == "inplace"
    assert meta["fingerprint"] == f"proxyjob:{conv['id']}"


def test_set_job_card_state_inplace_update():
    """状态回写: fingerprint 原位更新 jobState, 不落新卡。"""
    conv = _conv()
    from topoone_app_architect.agent.execution import exec_bridge as eb
    eb._append(conv["id"], "assistant", "🔗 已直通执行器",
               msg_meta={"kind": "proxy", "jobId": "job-jc-2",
                         "jobCard": 1, "jobState": "running",
                         "fingerprint": proxy._job_card_fp(conv["id"])})
    proxy._set_job_card_state(conv["id"], "idle")
    cards = _job_msgs(conv["id"])
    assert len(cards) == 1, "原位更新不刷屏"
    assert cards[0]["meta"]["jobState"] == "idle"
    proxy._set_job_card_state(conv["id"], "ended")
    cards = _job_msgs(conv["id"])
    assert len(cards) == 1
    assert cards[0]["meta"]["jobState"] == "ended"


def test_set_job_card_state_without_card_noop():
    conv = _conv()
    proxy._set_job_card_state(conv["id"], "ended")   # 无卡 → 静默不抛
    assert _job_msgs(conv["id"]) == []


def test_items_projection_job_type():
    """统一投影: kind=proxy → item.type=job(A6.2 守门, FE 按 jobCard 分流)。"""
    from topoone_app_architect.agent.execution.items import CARD_ITEM_MAP
    assert CARD_ITEM_MAP.get("proxy") == {"type": "job", "payload": "meta"}


def test_job_state_vocabulary():
    """状态词汇与执行器状态轴同源(不自造): running|idle|ended。"""
    from topoone_app_architect.agent.execution.proxy import _set_job_card_state  # noqa: F401
    import inspect
    import topoone_app_architect.agent.execution.proxy as px
    src = inspect.getsource(px)
    for state in ("running", "idle", "ended"):
        assert f'"{state}"' in src
