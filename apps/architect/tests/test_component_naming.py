"""组件快速命名测试（数据主权批C）。

覆盖：编号清单解析（越界/重名/坏 JSON 忽略）、指纹、命名作业 e2e
（mock llm_sync → 落库+组件名回写+TTL 缓存跳过/force 重命名/编号回填）、
stale 标记、命名 status 形状。
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from topoone_app_architect import ctx as app_ctx
from topoone_app_architect.sem.component_naming import (
    _job_component_name, _parse_items, owns_fingerprint)
from topoone_app_architect.store.graph import ComponentStore, GraphStore


class _FakeCtx:
    def __init__(self, pid, scope=None):
        self._pid = pid
        self._scope = scope or {}

    pid = property(lambda self: self._pid)
    scope = property(lambda self: self._scope)
    job = property(lambda self: {"id": "j", "projectId": self._pid})

    def cancelled(self):
        return False

    def progress(self, **kw):
        pass


def _seed_components(pid, rev="baseline:nn"):
    comps = [
        {"id": "comp-a", "name": "comp-a", "owns": ["a/f0.py", "a/f1.py"]},
        {"id": "comp-b", "name": "comp-b", "owns": ["b/f0.py"]},
    ]
    ComponentStore.replace_rev(pid, rev, comps, [])
    nodes = []
    for rel, sym in (("a/f0.py", "loader"), ("a/f1.py", "parser"), ("b/f0.py", "render")):
        nodes.append({
            "id": f"cache:{rel}::{sym}::1", "kind": "function", "name": sym,
            "qualified_name": sym, "file_path": rel, "language": "python",
            "start_line": 1, "end_line": 30, "start_column": 0, "end_column": 0,
            "signature": f"def {sym}()", "docstring": "", "return_type": "",
            "is_exported": True,
        })
    GraphStore.replace_rev(pid, rev, nodes, [])
    return comps


class ComponentNamingTest(unittest.TestCase):
    PID = "proj-graph-c"
    REV = "baseline:nn"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        app_ctx.setup(data_dir=self._tmp.name)
        _seed_components(self.PID, self.REV)

    def tearDown(self):
        self._tmp.cleanup()

    def test_parse_items(self):
        res = {"items": [{"n": 0, "name": "采集", "summary": "s"},
                         {"n": "1", "name": "渲染"},          # 字符串编号兼容
                         {"n": 5, "name": "越界"},            # 忽略
                         {"n": 0, "name": "重名"},            # 忽略
                         {"n": 2, "name": "无组件"},          # n=2 越界(批2) 忽略
                         {"no-n": True}]}                     # 忽略
        items = _parse_items(res, 2)
        self.assertEqual([i["n"] for i in items], [0, 1])
        self.assertEqual(_parse_items(None, 2), [])
        self.assertEqual(_parse_items({"items": "not json"}, 2), [])

    def test_fingerprint_stable(self):
        self.assertEqual(owns_fingerprint(["b", "a"]), owns_fingerprint(["a", "b"]))
        self.assertNotEqual(owns_fingerprint(["a"]), owns_fingerprint(["a", "b"]))

    def test_naming_e2e_and_cache(self):
        responses = [
            {"items": [{"n": 0, "name": "采集处理", "summary": "解析装载模块"},
                       {"n": 1, "name": "渲染", "summary": "界面呈现"}]},
        ]

        def fake_llm(messages, **kw):
            self.assertIn("comp-a", messages[1]["content"])  # 编号清单含组件 id
            self.assertIn("loader", messages[1]["content"])  # 代表符号
            return responses[0]

        with patch("topoone_app_architect.agent.cognition.llm.llm_sync",
                   side_effect=fake_llm) as mk:
            r = _job_component_name(_FakeCtx(self.PID))
        self.assertEqual(r["named"], 2)
        self.assertNotIn("error", r)
        # 落库+组件名回写
        namings = ComponentStore.namings(self.PID, self.REV)
        self.assertEqual(namings["comp-a"]["name"], "采集处理")
        self.assertEqual(namings["comp-a"]["status"], "active")
        comps = {c["id"]: c for c in ComponentStore.list_rev(self.PID, self.REV)}
        self.assertEqual(comps["comp-a"]["name"], "采集处理")
        self.assertEqual(comps["comp-a"]["summary"], "解析装载模块")
        # 缓存: 二次跑全命中免 LLM
        r2 = _job_component_name(_FakeCtx(self.PID))
        self.assertEqual(r2.get("cached"), True)
        self.assertEqual(mk.call_count, 1)

    def test_owns_change_stales_naming(self):
        with patch("topoone_app_architect.agent.cognition.llm.llm_sync",
                   return_value={"items": [{"n": 0, "name": "甲", "summary": ""},
                                           {"n": 1, "name": "乙", "summary": ""}]}):
            _job_component_name(_FakeCtx(self.PID))
        # owns 变化 → 指纹失配 → 重命名该组件(仅该组件进 targets)
        comps = ComponentStore.list_rev(self.PID, self.REV)
        comps[0]["owns"] = ["a/f0.py", "a/f1.py", "a/f2.py"]
        ComponentStore.replace_rev(self.PID, self.REV, comps, [])

        called = []

        def fake_llm(messages, **kw):
            called.append(messages[1]["content"])
            return {"items": [{"n": 0, "name": "新名", "summary": ""}]}

        with patch("topoone_app_architect.agent.cognition.llm.llm_sync",
                   side_effect=fake_llm):
            r = _job_component_name(_FakeCtx(self.PID))
        self.assertEqual(r["named"], 1)
        self.assertEqual(len(called), 1)
        self.assertIn("comp-a", called[0])  # 只重命名指纹失配的
        namings = ComponentStore.namings(self.PID, self.REV)
        self.assertEqual(namings["comp-a"]["name"], "新名")
        self.assertEqual(namings["comp-b"]["name"], "乙")  # 未动

    def test_force_renames_all(self):
        with patch("topoone_app_architect.agent.cognition.llm.llm_sync",
                   return_value={"items": [{"n": 0, "name": "甲"}, {"n": 1, "name": "乙"}]}):
            _job_component_name(_FakeCtx(self.PID))
        with patch("topoone_app_architect.agent.cognition.llm.llm_sync",
                   return_value={"items": [{"n": 0, "name": "甲2"},
                                           {"n": 1, "name": "乙2"}]}) as mk:
            r = _job_component_name(_FakeCtx(self.PID, {"force": True}))
        self.assertEqual(r["named"], 2)
        self.assertEqual(mk.call_count, 1)  # 2 组件一批(≤8)

    def test_no_components_error(self):
        r = _job_component_name(_FakeCtx("proj-empty-c"))
        self.assertIn("error", r)

    def test_bad_output_retry(self):
        calls = {"n": 0}

        def fake_llm(messages, **kw):
            calls["n"] += 1
            return {"items": [{"n": 9, "name": "全越界"}]} if calls["n"] == 1 \
                else {"items": [{"n": 0, "name": "重试名"}, {"n": 1, "name": "乙3"}]}

        with patch("topoone_app_architect.agent.cognition.llm.llm_sync",
                   side_effect=fake_llm):
            r = _job_component_name(_FakeCtx(self.PID))
        self.assertEqual(r["named"], 2)
        self.assertEqual(calls["n"], 2)  # 首轮坏采样→重试


if __name__ == "__main__":
    unittest.main()
