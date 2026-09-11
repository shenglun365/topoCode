"""LLM 优化三件套回归：中央类型收敛(_coerce_args) + 聚焦修复外循环(repair_tool_args)
+ 守卫文案准确化(guard_notice) + llm_dataset 采集。

Run: cd <repo> && python -m pytest apps/architect/tests/test_arg_repair_dataset.py -q
"""
import json
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.arch_routes.ctx as C
from topoone_app_architect.arch_routes import req_agent


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


# ── 修复1: 中央类型收敛 ────────────────────────────────────────────────

def test_coerce_str_from_dict_list_scalar():
    def fn(a: str = "", b: str = "", c: str = ""):
        return a, b, c
    out = req_agent._coerce_args(fn, {
        "a": {"benefits": "解耦", "risks": "依赖链"},   # cv-71 实锤形状
        "b": ["第一行", "- 第二行", "3) 第三行"],
        "c": 42,
    })
    assert out["a"] == json.dumps({"benefits": "解耦", "risks": "依赖链"}, ensure_ascii=False)
    assert out["b"] == "第一行\n第二行\n第三行"
    assert out["c"] == "42"


def test_coerce_int_optional_and_garbage():
    def fn(x: int = 0, y: int = None):  # noqa: E721
        return x, y
    assert req_agent._coerce_args(fn, {"x": "15.7"})["x"] == 15
    assert req_agent._coerce_args(fn, {"x": True})["x"] == 1
    # 不可救: 保持原值 → 工具自身校验给可读错误
    assert req_agent._coerce_args(fn, {"x": "abc"})["x"] == "abc"


def test_coerce_list_of_str_and_dict_variants():
    from typing import Any, Dict, List, Optional
    def fn(items: list = None, scopes: list = None,  # noqa: E721 裸 list
           payload: Optional[List[Dict[str, Any]]] = None):
        return items, scopes, payload
    out = req_agent._coerce_args(fn, {
        "items": "l1\n- l2\n2) l3",                    # str → 按行拆
        "scopes": {"a": 1},                            # dict → [json串]
        "payload": '[{"k":1}]',                        # str → json 解析为 List[dict]
    })
    assert out["items"] == ["l1", "l2", "l3"]
    assert out["scopes"] == ['{"a": 1}']
    assert out["payload"] == [{"k": 1}]


def test_coerce_inverted_files_trap():
    """反向陷阱: 工具签名 str、模型自然传数组(_probe_run/_coding_task_plan 类)。

    coerce 把数组收敛为换行拼接；工具侧 re.split(r"[,，\n]") 双容忍。"""
    import re as _re
    def fn(files: str = ""):
        return [f.strip() for f in _re.split(r"[,，\n]", files) if f.strip()]
    out = req_agent._coerce_args(fn, {"files": ["a.py", "b.py"]})
    assert fn(**out) == ["a.py", "b.py"]
    # 逗号串直传同样可用(模型不经 coerce 的路径)
    assert fn(**req_agent._coerce_args(fn, {"files": "a.py,b.py"})) == ["a.py", "b.py"]


def test_run_arch_tool_cv71_shape_end_to_end(tmp_path, monkeypatch):
    """cv-71 复现回归: assessmentMd 传 dict 经 run_arch_tool 全链不再崩。"""
    _setup(tmp_path, monkeypatch)
    res = req_agent.run_arch_tool(
        "req.propose",
        {"title": "外循环回归", "requirementMd": "目标",
         "assessmentMd": {"benefits": "x", "estMin": 5},
         "acceptanceMd": ["验收一", "验收二"],
         "estMin": "12"},
        root=None, project=None)
    assert res.get("ok") is True, res
    rid = res.get("requirementId")
    row = req_agent.store.RequirementsStore.get(rid)
    assert isinstance(row.get("analysis", {}).get("assessmentSummary"), str)
    assert row["analysis"]["estMin"] == 12


# ── 修复3: 守卫文案准确化 ─────────────────────────────────────────────

def test_guard_notice_fabrication_vs_tool_failure():
    # 未调用 → 编造文案
    n1 = req_agent.guard_notice("引用不存在的需求编号 RQ-X", "req.propose", set(), {})
    assert "未经实际工具调用" in n1 and "执行失败" not in n1
    # 已调用但失败 → 非编造 + 失败原因
    n2 = req_agent.guard_notice("已生成规约", "req.propose",
                                {"req.propose"}, {"req.propose": "unhashable type: 'slice'"})
    assert "非编造" in n2 and "unhashable" in n2
    # 调用过但无错误记录(异常路径) → 仍编造文案
    n3 = req_agent.guard_notice("已生成规约", "req.propose", {"req.propose"}, {})
    assert "未经实际工具调用" in n3


# ── 修复5: 聚焦修复外循环 ─────────────────────────────────────────────

def test_is_repairable_error_classification():
    assert req_agent._is_repairable_error("req.propose 执行失败: unhashable type: 'slice'")
    assert req_agent._is_repairable_error("执行失败: missing 1 required argument: 'title'")
    assert not req_agent._is_repairable_error("需求 RQ-9 不存在")
    assert not req_agent._is_repairable_error("会话已归档(只读)")
    assert not req_agent._is_repairable_error("未知工具: nope")
    assert not req_agent._is_repairable_error("")


def test_repair_tool_args_roundtrip(tmp_path, monkeypatch):
    """错误形状 →(聚焦LLM修复)→ 正确形状 → 工具真实落库; 样本入 llm_dataset。"""
    _setup(tmp_path, monkeypatch)
    good = {"title": "修复后提案", "requirementMd": "目标",
            "assessmentMd": "评估文本", "estMin": 20}

    def _fake_llm_sync(messages, **kw):
        assert "参数修复器" in messages[0]["content"]
        assert "req.propose" in messages[0]["content"]
        return {"content": "```json\n" + json.dumps(
            {"tool": "req.propose", "arguments": {
                "title": "修复后提案", "requirementMd": "目标",
                "assessmentMd": {"benefits": "x"}, "estMin": "20"}}) + "\n```"}
    monkeypatch.setattr(req_agent, "llm_sync", _fake_llm_sync)
    fixed = req_agent.repair_tool_args(
        "req.propose",
        {"title": "修复后提案", "assessmentMd": {"benefits": "x"}, "estMin": "20"},
        "执行失败: unhashable type: 'slice'", model_id="m9b")
    assert isinstance(fixed, dict)
    res = req_agent.run_arch_tool("req.propose", fixed, root=None, project=None)
    assert res.get("ok") is True, res

    # 修复失败(模型输出不可解析) → None 回落守卫
    monkeypatch.setattr(req_agent, "llm_sync",
                        lambda *a, **k: {"content": "不可解析文本"})
    assert req_agent.repair_tool_args(
        "req.propose", {"title": "x"}, "执行失败: boom") is None


def test_repair_channel_in_run_tools_loop(tmp_path, monkeypatch):
    """降级通道(run_tools_loop)内: 首次形状错误→自动修复→工具成功→结果带标注。"""
    _setup(tmp_path, monkeypatch)
    calls = {"n": 0}

    def _fake_llm_sync(messages, **kw):
        calls["n"] += 1
        sys_msg = messages[0].get("content") or ""
        if "参数修复器" in sys_msg:
            # 聚焦修复请求: 返回补齐 title 的修正 args
            return {"content": "```json\n" + json.dumps(
                {"tool": "req.propose",
                 "arguments": {"title": "t2", "requirementMd": "r",
                               "assessmentMd": "文本"}}) + "\n```"}
        if calls["n"] == 1:
            # 模型首答: 缺 title(coerce 救不了) → 「缺少」错误触发修复外循环
            return {"content": '[TOOL_CALL]{"tool":"req.propose","arguments":'
                               '{"assessmentMd":{"a":1}}}[/TOOL_CALL]'}
        # 修复成功后的结果回喂轮: 直接收尾
        return {"content": "已基于工具结果完成提案。"}
    monkeypatch.setattr(req_agent, "llm_sync", _fake_llm_sync)
    res = req_agent.run_tools_loop([{"role": "user", "content": "生成提案"}],
                                   mode="chat", max_rounds=2)
    assert res.get("content"), res
    # 聚焦修复请求确实发生过(首答 + 修复 + 结果收尾 ≥ 3 次)
    assert calls["n"] >= 3, calls
    # 落库真实发生(修复后的 args 被重执行)
    rows = req_agent.store.RequirementsStore.all()
    assert any(r.get("title") == "t2" for r in rows)


# ── llm_dataset 采集 ──────────────────────────────────────────────────

def test_llm_dataset_records_and_stats(tmp_path, monkeypatch):
    C2 = _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import llm_dataset
    llm_dataset.record("tool_call", tool="req.propose", ok=True, args={"a": 1},
                       result="ok", latencyMs=3, project="p1")
    llm_dataset.record("arg_repair", tool="req.propose", argsBefore={"a": {"b": 1}},
                       error="boom", argsAfter={"a": "x"}, ok=True, model="m")
    st = llm_dataset.stats()
    assert st["kinds"]["tool_call"]["count"] == 1
    assert st["kinds"]["arg_repair"]["count"] == 1
    assert st["bytes"] > 0
    # REST 端点挂载
    import topoone_app_architect.arch_routes as routes
    paths = [r.path for r in routes.router.routes]
    assert "/api/architect/llm-dataset/stats" in paths
