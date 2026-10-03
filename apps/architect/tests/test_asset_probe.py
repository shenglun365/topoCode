"""语义资产解析能力探测(批4) — 判分/参数推导/档案/消费策略 测试。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from topoone_app_architect.agent.cognition import asset_probe as AP


class TestScores:
    def test_name_recall_hit_and_miss(self):
        assets = AP.synth_assets(5)
        names = [a["name"] for a in assets]
        raw = ('```json\n{"chains":[{"name":"x","summary":"s","members":['
               f'"{names[0]}", "{names[1]}（注释）", "幻觉名"'
               ']}]}\n```')
        # 2/3 命中(幻觉名 miss; 带注释名 norm 命中)
        assert AP.score_name_recall(raw, assets) == pytest.approx(2 / 3, abs=0.01)

    def test_numbered_valid_range(self):
        assets = AP.synth_assets(10)
        raw = '{"chains":[{"members":[1, 10, 11, "abc"]}]}'
        assert AP.score_numbered_recall(raw, assets) == 0.5   # 2/4 有效

    def test_chain_naming(self):
        assert AP.score_chain_naming('{"name":"位移链","summary":"s"}') == 1
        assert AP.score_chain_naming("模型闲聊不含 JSON") == 0


class TestDerive:
    def test_numbered_model(self):
        """num 稳 name 不稳(主力形态, 批0: 35b num=1.0/name@200=0) → numbered+200。"""
        ev = {"name@100": [1.0, 0.5, 1.0],      # min 0.5 不通过
              "num@100": [1.0, 1.0, 1.0], "num@200": [1.0, 1.0], "len@15": [1, 1]}
        p = AP.derive_asset_profile(ev)
        assert p["mode"] == "numbered" and p["listCap"] == 200
        assert p["chainLen"] == [3, 15] and p["retries"] == 2

    def test_free_model(self):
        """name 全稳(批0: gemma-4-12b-it 形态) → free+100。"""
        ev = {"name@100": [1.0, 1.0, 1.0], "num@100": [1.0, 0.0, 1.0],
              "num@200": [1.0, 0.0], "len@15": [1, 1]}
        p = AP.derive_asset_profile(ev)
        assert p["mode"] == "free" and p["listCap"] == 100

    def test_structural_model(self):
        """都不稳(批0: nex-n2.5-mini num=0) → 构链兜底。"""
        ev = {"name@100": [0.0, 0.5, 0.0], "num@100": [0.0, 0.0, 0.0],
              "num@200": [0.0, 0.0], "len@15": [1, 1]}
        p = AP.derive_asset_profile(ev)
        assert p["mode"] == "structural" and p["listCap"] is None

    def test_num100_only(self):
        """num@200 不稳 num@100 稳 → numbered+100。"""
        ev = {"name@100": [0.0, 0.0, 0.0], "num@100": [1.0, 1.0, 0.95],
              "num@200": [0.5, 1.0], "len@15": [1, 1]}
        p = AP.derive_asset_profile(ev)
        assert p["mode"] == "numbered" and p["listCap"] == 100


class TestPolicy:
    def test_default_unprobed(self):
        """统一裁决(2026-10-03): 未探测也恒 structural(大清单=信息干扰)。"""
        assert AP.asset_parse_policy("") == {"mode": "structural", "ref_form": "name",
                                             "brief_cap": None, "chain_len": [3, 15],
                                             "retries": 1}

    def test_numbered_policy_manual_only(self, monkeypatch, tmp_path):
        """探测档案 numbered 不驱动策略(恒 structural); 手动 numbered 才生效。"""
        from topoone_app_architect.agent.cognition import model_profile as MP
        _setup_store(tmp_path, monkeypatch)
        AP._save_asset_profile("m1", {"mode": "numbered", "listCap": 200,
                                      "chainLen": [3, 15], "retries": 1, "source": "probed"})
        assert AP.asset_parse_policy("m1")["mode"] == "structural"   # probed 仅参考
        AP.set_asset_profile_manual("m1", {"mode": "numbered", "listCap": 200})
        pol = AP.asset_parse_policy("m1")
        assert pol["ref_form"] == "num" and pol["brief_cap"] == 200 * AP.ROW_CHARS

    def test_structural_policy(self, tmp_path, monkeypatch):
        _setup_store(tmp_path, monkeypatch)
        AP._save_asset_profile("m2", {"mode": "structural", "listCap": None,
                                      "chainLen": [3, 10], "retries": 2})
        pol = AP.asset_parse_policy("m2")
        assert pol["mode"] == "structural" and pol["chain_len"] == [3, 10]

    def test_manual_overrides_probe(self, tmp_path, monkeypatch):
        _setup_store(tmp_path, monkeypatch)
        AP._save_asset_profile("m3", {"mode": "numbered", "listCap": 200})
        r = AP.set_asset_profile_manual("m3", {"mode": "agentic"})
        assert r["asset"]["source"] == "manual"
        assert AP.asset_parse_policy("m3")["mode"] == "agentic"
        AP.set_asset_profile_manual("m3", None)   # 清除回缺省(=统一 structural)
        assert AP.asset_parse_policy("m3")["mode"] == "structural"


class TestProbeFlow:
    def test_probe_end_to_end(self, tmp_path, monkeypatch):
        """探测主流程: mock LLM 10 次(num 全满分/name 摆动) → numbered 档案落库。"""
        _setup_store(tmp_path, monkeypatch)
        calls = {"n": 0}

        def fake_llm(msgs, **kw):
            calls["n"] += 1
            user = msgs[-1]["content"]
            if "成员序列" in user:      # len@15
                return {"content": '{"name":"x链","summary":"s"}'}
            if "(编号)" in user:        # num → 全满分(有效编号)
                assets_n = 200 if calls["n"] >= 7 else 100
                return {"content": '{"chains":[{"members":[1, 2, 3]}]}'}
            # name: 第二次采样崩(0/1 摆动 → min<0.9 不通过)
            return {"content": '{"chains":[{"members":["幻觉名"]}]}' if calls["n"] == 2
                    else '{"chains":[{"members":[' + ",".join(f'"{a}"' for a in _names_in(user, 3)) + ']}]}'}

        def _names_in(user, k):
            import re as _re
            return _re.findall(r"\[asset\] (\S+) \(sym:", user)[:k]

        monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync", fake_llm)
        r = AP.probe_asset_capability("m-probe", force=True)
        assert calls["n"] == 10
        assert r["profile"]["mode"] == "numbered"
        assert r["profile"]["source"] == "probed"
        # 幂等: 未 force 且已 probed → skip
        r2 = AP.probe_asset_capability("m-probe")
        assert r2.get("skipped")


def _setup_store(tmp_path, monkeypatch):
    import topoone_app_architect.ctx as C
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None; C._kb = None; C._data_dir = None; C._project_dbs.clear()
    C.setup(data_dir=data)


class TestPolicyUnified:
    def test_probed_numbered_still_structural(self, tmp_path, monkeypatch):
        """统一裁决(2026-10-03): 探测档案(numbered)不驱动策略——恒 structural,
        探测数据仅参考展示。"""
        _setup_store(tmp_path, monkeypatch)
        AP._save_asset_profile("m-u1", {"mode": "numbered", "listCap": 200,
                                        "source": "probed"})
        pol = AP.asset_parse_policy("m-u1")
        assert pol["mode"] == "structural"

    def test_manual_free_respected(self, tmp_path, monkeypatch):
        """手动覆盖(实验选项)显式 free → 尊重。"""
        _setup_store(tmp_path, monkeypatch)
        AP.set_asset_profile_manual("m-u2", {"mode": "free", "listCap": 100})
        pol = AP.asset_parse_policy("m-u2")
        assert pol["mode"] == "free" and pol["ref_form"] == "name"
