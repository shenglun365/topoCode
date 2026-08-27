"""需求会话生命周期(4 段)分组测试：lifecycle_of 映射 + build_session_groups 分组。

Run: cd <repo> && python -m pytest plugins/architect/tests/test_requirement_sessions.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.arch_routes import lifecycle


class TestLifecycleOf:
    def test_mapping(self):
        assert lifecycle.lifecycle_of("raw") == "planning"
        assert lifecycle.lifecycle_of("analyzing") == "planning"
        assert lifecycle.lifecycle_of("analyzed") == "ready"
        assert lifecycle.lifecycle_of("designed") == "ready"
        assert lifecycle.lifecycle_of("planned") == "ready"
        assert lifecycle.lifecycle_of("executing") == "executing"
        assert lifecycle.lifecycle_of("done") == "done"

    def test_unknown_defaults_to_planning(self):
        assert lifecycle.lifecycle_of("") == "planning"
        assert lifecycle.lifecycle_of(None) == "planning"
        assert lifecycle.lifecycle_of("bogus") == "planning"

    def test_order(self):
        assert lifecycle.LIFECYCLE_ORDER == ["planning", "ready", "executing", "done"]


class TestBuildSessionGroups:
    def _req(self, rid, status, updated=0, **kw):
        r = {"id": rid, "status": status, "title": kw.pop("title", rid),
             "priority": "P1", "kind": "user-story", "location": "pool", "updatedAt": updated}
        r.update(kw)
        return r

    def test_groups_by_lifecycle(self):
        reqs = [self._req("r-1", "raw"), self._req("r-2", "analyzed"),
                self._req("r-3", "executing"), self._req("r-4", "done")]
        g = lifecycle.build_session_groups(reqs, [])
        assert [s["id"] for s in g["planning"]] == ["r-1"]
        assert [s["id"] for s in g["ready"]] == ["r-2"]
        assert [s["id"] for s in g["executing"]] == ["r-3"]
        assert [s["id"] for s in g["done"]] == ["r-4"]

    def test_conversation_latest_wins(self):
        # convs 已按 updatedAt 倒序：r-1 两条会话，最新 cv-2 命中
        reqs = [self._req("r-1", "raw")]
        convs = [{"id": "cv-2", "reqId": "r-1", "updatedAt": 200},
                 {"id": "cv-1", "reqId": "r-1", "updatedAt": 100}]
        g = lifecycle.build_session_groups(reqs, convs)
        assert g["planning"][0]["conversationId"] == "cv-2"

    def test_no_conversation_empty_id(self):
        g = lifecycle.build_session_groups([self._req("r-1", "raw")], [])
        assert g["planning"][0]["conversationId"] == ""

    def test_cancelled_excluded_by_default(self):
        reqs = [self._req("r-1", "cancelled"), self._req("r-2", "raw")]
        g = lifecycle.build_session_groups(reqs, [])
        assert [s["id"] for s in g["planning"]] == ["r-2"]

    def test_cancelled_included_on_flag(self):
        reqs = [self._req("r-1", "cancelled"), self._req("r-2", "raw")]
        g = lifecycle.build_session_groups(reqs, [], include_cancelled=True)
        assert set(s["id"] for s in g["planning"]) == {"r-1", "r-2"}

    def test_sorted_by_updated_desc(self):
        reqs = [self._req("r-1", "raw", updated=100), self._req("r-2", "analyzing", updated=300),
                self._req("r-3", "raw", updated=200)]
        g = lifecycle.build_session_groups(reqs, [])
        assert [s["id"] for s in g["planning"]] == ["r-2", "r-3", "r-1"]

    def test_analysis_and_design_flags(self):
        reqs = [self._req("r-1", "analyzed", analysis={"assetScope": []}, design={"dataChanges": []})]
        g = lifecycle.build_session_groups(reqs, [])
        s = g["ready"][0]
        assert s["hasAnalysis"] is True
        assert s["hasDesign"] is True
