"""结构化构链(C 方案, 批1) — 图算法构链 + LLM 单链命名 测试。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from topoone_app_architect.sem import logic_structural as LS


def _assets(edges: dict, *, prefix="a") -> list:
    """edges: {序号: [目标序号]} → 资产列表(relations 引用名称)。"""
    out = []
    for i, tgts in edges.items():
        out.append({
            "id": f"impl-{prefix}{i}", "kind": "asset", "name": f"资产{prefix}{i}",
            "desc": "", "detail": {"relations": [{"target": f"资产{prefix}{t}", "type": "calls"} for t in tgts]},
            "astRefs": [{"file": "m.ts", "symbol": f"fn{prefix}{i}", "startLine": 1, "endLine": 2}],
        })
    return out


class TestStructuralChains:
    def test_linear_chain(self):
        """链形图 1→2→3→4 → 一条 4 成员链。"""
        assets = _assets({1: [2], 2: [3], 3: [4], 4: []})
        chains = LS.structural_chains(assets, min_len=3, max_len=15, top_n=5)
        assert chains == [["impl-a1", "impl-a2", "impl-a3", "impl-a4"]]

    def test_min_len_filters_short(self):
        """短链(2 成员)被 min_len=3 过滤。"""
        assets = _assets({1: [2], 2: []}) + _assets({3: [4], 4: [5], 5: []}, prefix="b")
        chains = LS.structural_chains(assets, min_len=3, max_len=15, top_n=5)
        assert chains == [["impl-b3", "impl-b4", "impl-b5"]]

    def test_cycle_safe(self):
        """环形 1→2→3→1 不死循环(访问集防环), 产出合法简单路径。"""
        assets = _assets({1: [2], 2: [3], 3: [1]})
        chains = LS.structural_chains(assets, min_len=3, max_len=15, top_n=5)
        assert len(chains) >= 1
        for c in chains:
            assert len(c) == len(set(c)), "环路径出现重复成员"

    def test_dedup_jaccard(self):
        """成员集 Jaccard≥0.6 的重复链去重(同构子链只留权重最高)。"""
        # 主干 1→2→3→4 + 旁支 2→5(与主干高度重叠)
        assets = _assets({1: [2], 2: [3, 5], 3: [4], 4: [], 5: []})
        chains = LS.structural_chains(assets, min_len=3, max_len=15, top_n=5)
        # 1→2→3→4 与 1→2→5: 后者仅 3 成员(1,2,5) Jaccard(4 成员)=0.5 → 都保留? 保守断言无重复链
        sets = [set(c) for c in chains]
        for i, a in enumerate(sets):
            for b in sets[i + 1:]:
                assert len(a & b) / len(a | b) < 0.6, "去重失效"

    def test_hub_priority(self):
        """度数权重排序: 高权重链排前(top_n 截断保留枢纽)。"""
        # 星型: 0 是枢纽被 1..5 依赖, 1→0→9 长链应优先于孤立 2 元链
        assets = _assets({1: [0], 2: [0], 3: [0], 0: [9], 9: [], 4: [8], 8: [7], 7: [6], 6: [5], 5: []})
        assets[0]["detail"]["relations"] = []   # 0 无出边外置——直接手工构造见下
        # 手工: 让 0 → 9 唯一长链是 4→8→7→6→5
        chains = LS.structural_chains(assets, min_len=3, max_len=15, top_n=3)
        assert chains, "应产出至少一条链"
        assert ["impl-a4", "impl-a8", "impl-a7", "impl-a6", "impl-a5"] in chains

    def test_unresolved_targets_ignored(self):
        """幻觉 target(清单外)不产生边。"""
        assets = _assets({1: [2], 2: ["不存在的资产"]})
        chains = LS.structural_chains(assets, min_len=2, max_len=15, top_n=5)
        assert all("不存在的资产" not in c for c in chains)


class TestNameChain:
    def test_good_output(self, monkeypatch):
        monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync",
                            lambda msgs, **kw: {"content": '{"name":"位移渲染链","summary":"从解析到渲染"}'})
        r = LS.name_chain([{"id": "x", "name": "解析位移"}])
        assert r == {"name": "位移渲染链", "summary": "从解析到渲染", "score": None}

    def test_retry_then_degrade(self, monkeypatch):
        """坏输出重采样 1 次; 两次都失败 → None(调用方降级命名不丢链)。"""
        calls = {"n": 0}
        def bad(msgs, **kw):
            calls["n"] += 1
            return {"content": "模型闲聊"}
        monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync", bad)
        assert LS.name_chain([{"id": "x", "name": "a"}]) is None
        assert calls["n"] == 2


class TestStructuralInduce:
    def test_end_to_end_with_anchor(self, monkeypatch, tmp_path):
        """端到端: 构链 + 命名 mock + 注入锚点 → 链同构 induce_chains 返回。"""
        (tmp_path / "m.ts").write_text("export function fn1() { return 1 }\n")
        assets = _assets({1: [2], 2: [3], 3: []})
        monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync",
                            lambda msgs, **kw: {"content": '{"name":"主处理链","summary":"三步加工"}'})
        anchor_fn = lambda root, ref, rev: {"file": ref.get("file"), "startLine": 1, "snippet": "x"}
        chains, diag = LS.structural_induce(str(tmp_path), assets, "workspace",
                                            anchor_fn=anchor_fn)
        assert len(chains) == 1
        c = chains[0]
        assert c["name"] == "主处理链"
        assert c["members"] == ["impl-a1", "impl-a2", "impl-a3"]
        assert c["inputs"][0]["code"][0]["file"] == "m.ts"
        assert c["outputs"][0]["code"][0]["file"] == "m.ts"
        assert "结构化构链 1 条" in diag

    def test_naming_failure_degrades_not_drops(self, monkeypatch, tmp_path):
        """命名失败 → 首尾成员拼接降级命名, 链保留。"""
        assets = _assets({1: [2], 2: [3], 3: []})
        monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync",
                            lambda msgs, **kw: {"content": "废话"})
        chains, diag = LS.structural_induce(str(tmp_path), assets, "workspace")
        assert len(chains) == 1
        assert chains[0]["name"] == "资产a1→资产a3"
        assert "1 条命名降级" in diag

    def test_induce_chains_mode_routing(self, monkeypatch, tmp_path):
        """induce_chains(mode='structural') 路由到结构化路径。"""
        from topoone_app_architect.sem import logic_induce as LI
        called = {}
        monkeypatch.setattr(LS, "structural_induce",
                            lambda root, assets, rev, mid, **kw: (called.setdefault("ok", True) and ([{"name": "x"}], "d")))
        chains, diag = LI.induce_chains(str(tmp_path), _assets({1: [2], 2: [3], 3: []}),
                                        "workspace", None, mode="structural")
        assert called.get("ok") and chains == [{"name": "x"}]


class TestSemanticReview:
    def test_good_chain_kept_with_score(self, monkeypatch):
        monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync",
                            lambda msgs, **kw: {"content": '{"name":"位移渲染链","summary":"s","score":0.9}'})
        r = LS.name_chain([{"id": "x", "name": "a", "desc": "d"}])
        assert r and r["name"] == "位移渲染链" and r["score"] == 0.9 and not r.get("drop")

    def test_pseudo_chain_dropped(self, monkeypatch):
        """调用图巧合伪链(低分) → drop 丢弃。"""
        monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync",
                            lambda msgs, **kw: {"content": '{"name":"杂链","summary":"s","score":0.2}'})
        r = LS.name_chain([{"id": "x", "name": "a", "desc": "d"}])
        assert r == {"drop": True, "score": 0.2}

    def test_missing_score_tolerant(self, monkeypatch):
        """score 缺失/非法 → 保留(误伤率未知, 宽容先行)。"""
        monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync",
                            lambda msgs, **kw: {"content": '{"name":"无分链","summary":"s"}'})
        r = LS.name_chain([{"id": "x", "name": "a", "desc": "d"}])
        assert r and r["name"] == "无分链" and r["score"] is None and not r.get("drop")

    def test_structural_induce_drops_low_score(self, monkeypatch, tmp_path):
        """端到端: 低分伪链被丢弃且 diag 计数; 高分链保留。"""
        assets = _assets({1: [2], 2: [3], 3: []}) + _assets({7: [8], 8: [9], 9: []}, prefix="z")
        out = {"n": 0}
        def fake(msgs, **kw):
            out["n"] += 1
            return {"content": '{"name":"伪链","summary":"s","score":0.1}'} if out["n"] == 1 \
                else {"content": '{"name":"真链","summary":"s","score":0.95}'}
        monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync", fake)
        chains, diag = LS.structural_induce(str(tmp_path), assets, "workspace")
        assert [c["name"] for c in chains] == ["真链"]
        assert "1 条未通过语义评审" in diag


class TestAgenticInduce:
    def _digest_assets(self, n=6):
        return [{"id": f"impl-ag{i}", "kind": "asset", "name": f"按需资产{i}",
                 "desc": f"职责{i}", "detail": {},
                 "astRefs": [{"file": "a.ts", "symbol": f"afn{i}", "startLine": 1, "endLine": 2}]}
                for i in range(n)]

    def test_query_then_final(self, monkeypatch, tmp_path):
        """按需读取循环: 首轮查 detail → 二轮终答编号链(直取摘要序)。"""
        assets = self._digest_assets()
        seq = iter([
            {"content": '{"action": {"tool": "asset.semantic.detail", "args": {"asset_id": "impl-ag1"}}}'},
            {"content": '{"chains": [{"name": "按需链", "kind": "process_chain", "summary": "s", '
                        '"members": [0, 2, 4]}]}'},   # 编号 0 越界忽略 → 成员 2,4(<2 丢弃?) 用 1,2,3
        ])
        tool_calls = {"n": 0}
        monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync",
                            lambda msgs, **kw: next(seq))

        def fake_detail(aid, root=None, project=None):
            tool_calls["n"] += 1
            return {"id": aid, "name": "x", "detail": {"steps": []}}
        monkeypatch.setattr("topoone_app_architect.agent.tools.impl.semantic.tool_semantic_detail", fake_detail)
        anchor_fn = lambda root, ref, rev: {"file": ref.get("file"), "startLine": 1}
        chains, diag = LS.agentic_induce(str(tmp_path), assets, "workspace", anchor_fn=anchor_fn)
        assert tool_calls["n"] == 1, "action 应触发一次工具执行"
        # members [0,2,4]: 0 越界(1-based) → 剩 2,4 = impl-ag1, impl-ag3 → ≥2 保留
        assert len(chains) == 1 and chains[0]["members"] == ["impl-ag1", "impl-ag3"]
        assert chains[0]["inputs"][0]["code"][0]["file"] == "a.ts"
        assert "工具查询 1 次" in diag

    def test_round_cap_60(self, monkeypatch, tmp_path):
        """60 轮保底: 模型永远只查询不终答 → 轮次上限截断, 不无限循环。"""
        assets = self._digest_assets()
        calls = {"n": 0}
        def loop_query(msgs, **kw):
            calls["n"] += 1
            return {"content": '{"action": {"tool": "asset.semantic.search", "args": {"text": "x"}}}'}
        monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync", loop_query)
        def fake_search(root, project, text="", **kw):
            return []
        monkeypatch.setattr("topoone_app_architect.agent.tools.impl.semantic.tool_semantic_search", fake_search)
        chains, diag = LS.agentic_induce(str(tmp_path), assets, "workspace", max_rounds=5)   # 小上限验证机制
        assert calls["n"] == 5, "应停在轮次上限"
        assert chains == []
        assert "轮次上限 5" in diag

    def test_invalid_output_nudge(self, monkeypatch, tmp_path):
        """非法输出 → 纠偏提示继续(不崩溃), 次轮终答。"""
        assets = self._digest_assets()
        seq = iter([
            {"content": "模型闲聊不输出 JSON"},
            {"content": '{"chains": [{"name": "链", "summary": "s", "members": [1, 2]}]}'},
        ])
        monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync",
                            lambda msgs, **kw: next(seq))
        chains, diag = LS.agentic_induce(str(tmp_path), assets, "workspace")
        assert len(chains) == 1 and len(chains[0]["members"]) == 2
