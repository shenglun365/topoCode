"""file_line_notes 行号区间键解析——模型常返回 "16-24" 区间键, 解析需展开逐行。

契约：单行键保留；区间键(-/–/~)展开为逐行注释并裁剪到窗口；窗口外丢弃。
"""
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from topoone_app_architect.sem import comp_graph


@pytest.fixture()
def header_root(tmp_path):
    (tmp_path / "ngx_http.h").write_text(
        "".join(f"line {i}: code\n" for i in range(1, 201)), encoding="utf-8")
    return str(tmp_path)


def _patch_model(monkeypatch, payload):
    from topoone_app_architect.agent.turns import catalog
    monkeypatch.setattr(catalog, "catalog_call", lambda role, msgs, max_tokens=0: {"content": payload})


def test_range_keys_expanded_and_clipped(monkeypatch, header_root):
    payload = json.dumps({
        "12": "单行说明",
        "16-24": "前向声明HTTP结构体",
        "195-260": "越界区间应整体丢弃(窗口被_MAX_SNIPPET=160截到160)",
    }, ensure_ascii=False)
    _patch_model(monkeypatch, payload)
    r = comp_graph.file_line_notes(header_root, None, "ngx_http.h", 1, 200)
    assert not r.get("degraded"), r
    notes = r["notes"]
    assert notes[12] == "单行说明"
    assert all(notes.get(l) == "前向声明HTTP结构体" for l in range(16, 25))
    assert 195 not in notes and 260 not in notes   # 越界丢弃
    assert len(notes) == 1 + 9


def test_unicode_dash_and_tilde_ranges(monkeypatch, header_root):
    payload = json.dumps({"30–33": "en-dash", "40~42": "tilde"}, ensure_ascii=False)
    _patch_model(monkeypatch, payload)
    r = comp_graph.file_line_notes(header_root, None, "ngx_http.h", 1, 200)
    assert all(r["notes"].get(l) == "en-dash" for l in range(30, 34))
    assert all(r["notes"].get(l) == "tilde" for l in range(40, 43))


def test_invalid_range_ignored(monkeypatch, header_root):
    payload = json.dumps({"50-40": "逆序无效", "abc": "非行键"}, ensure_ascii=False)
    _patch_model(monkeypatch, payload)
    r = comp_graph.file_line_notes(header_root, None, "ngx_http.h", 1, 200)
    assert r["notes"] == {}                        # 无效键不展开不崩溃
    assert r.get("degraded") is True               # 全无效→按既有语义降级
