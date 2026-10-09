"""外部 LLM 云 API apiKey 支持 — 模型目录 key 存取契约(2026-10 裁决)。

锁定:
  - manual 添加/修改收 apiKey; 存储 = 明文 kv; GET 出站 = 掩码 ****** + hasApiKey
  - 修改语义: ****** 回传 = 保留旧值; 空串 = 显式清除; 其余 = 新值
  - probe 按 modelId 取条目时补用已存 key
  - _sync_manual_to_kb: addModel 携带 key; kbShared 已匹配行经 updateModel
    推送(幂等); key 为空不动主库
  - imported 条目不落真 key(key 由主库持有, hasApiKey 回显)
  - 内置 cline 模型面投影: apiKey 真值 + provider → providerId 保守映射

Run: cd <repo> && python -m pytest apps/architect/tests/test_llm_apikey.py -q
"""
import asyncio
import sys
import os

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import pytest

from topoone_app_architect.arch_routes import mcp_collab as mc
from topoone_app_architect.arch_routes import llm_catalog as lc
from topoone_app_architect.arch_routes import agent_executors as ae


class _Req:
    """路由函数只 await request.json() — 鸭子类型桩。"""

    def __init__(self, body: dict):
        self._b = body

    async def json(self):
        return self._b


def _add_manual(body: dict):
    return asyncio.run(mc.add_manual_llm_model_route(_Req(body)))["data"]


def _update_manual(mid: str, body: dict):
    return asyncio.run(mc.update_manual_llm_model_route(mid, _Req(body)))["data"]


def _models_out():
    """GET 出站(掩码层)。"""
    return asyncio.run(mc.get_llm_models_route())["data"]["models"]


@pytest.fixture()
def catalog(arch_env):
    return arch_env


def test_manual_add_update_mask_roundtrip(catalog):
    row = _add_manual({"name": "GLM 云", "provider": "custom-cloud",
                       "model": "glm-4.7", "url": "https://open.bigmodel.cn/api/paas/v4",
                       "apiKey": "sk-test-123", "type": "cloud"})
    assert row["id"].startswith("man-")
    # 存储真值(明文 kv), 不打码
    stored = next(m for m in mc.get_llm_models() if m["id"] == row["id"])
    assert stored["apiKey"] == "sk-test-123"
    # 出站掩码: ****** + hasApiKey
    got = next(m for m in _models_out() if m["id"] == row["id"])
    assert got["apiKey"] == mc._APIKEY_MASK and got["hasApiKey"] is True


def test_update_key_semantics(catalog):
    row = _add_manual({"name": "DS", "model": "deepseek-chat", "apiKey": "sk-old"})
    mid = row["id"]
    # ****** 回传 = 保留
    _update_manual(mid, {"name": "DS", "model": "deepseek-chat", "apiKey": mc._APIKEY_MASK})
    assert next(m for m in mc.get_llm_models() if m["id"] == mid)["apiKey"] == "sk-old"
    # 新值覆盖
    _update_manual(mid, {"name": "DS", "model": "deepseek-chat", "apiKey": "sk-new"})
    assert next(m for m in mc.get_llm_models() if m["id"] == mid)["apiKey"] == "sk-new"
    # 空串 = 显式清除
    _update_manual(mid, {"name": "DS", "model": "deepseek-chat", "apiKey": ""})
    assert next(m for m in mc.get_llm_models() if m["id"] == mid)["apiKey"] == ""


def test_probe_uses_stored_key(catalog, monkeypatch):
    row = _add_manual({"name": "DS", "model": "deepseek-chat", "apiKey": "sk-probe"})
    captured = {}
    monkeypatch.setattr(ae, "_probe_llm_model",
                        lambda url, model, api_key="": captured.update(
                            url=url, model=model, api_key=api_key) or {"status": "ok"})
    asyncio.run(mc.probe_llm_model_route(_Req({"modelId": row["id"]})))
    assert captured["api_key"] == "sk-probe"


def test_sync_to_kb_add_and_update(catalog, monkeypatch):
    calls = []

    def fake_kb(method, **kw):
        calls.append((method, kw))
        if method == "settings.getModels":
            return [{"id": "kb-1", "model": "deepseek-chat"}]   # 已有同名行
        return {"id": "kb-new"}

    monkeypatch.setattr("topoone_app_architect.kb_gateway.call_kb", fake_kb)
    # 已匹配行 + 本条目持 key → updateModel 推送
    entry = {"source": "manual", "id": "man-x", "name": "DS",
             "model": "deepseek-chat", "provider": "deepseek",
             "url": "https://api.deepseek.com", "apiKey": "sk-share"}
    mc._sync_manual_to_kb(entry)
    assert entry.get("kbShared") is True and entry["id"] == "kb-1"
    assert any(m == "settings.updateModel" and k.get("apiKey") == "sk-share"
               for m, k in calls)
    # 未匹配 → addModel 携带 key
    calls.clear()
    entry2 = {"source": "manual", "id": "man-y", "name": "GLM",
              "model": "glm-4.7", "provider": "custom-cloud",
              "url": "https://x", "apiKey": "sk-glm", "type": "cloud"}
    mc._sync_manual_to_kb(entry2)
    add = next(k for m, k in calls if m == "settings.addModel")
    assert add["apiKey"] == "sk-glm" and add["ownerApp"] == "architect"
    # key 为空 → 不动主库(无 updateModel / addModel 不带 apiKey)
    calls.clear()
    entry3 = {"source": "manual", "id": "man-z", "name": "DS2",
              "model": "other-model", "provider": "deepseek", "apiKey": ""}
    mc._sync_manual_to_kb(entry3)
    assert not any(m == "settings.updateModel" for m, _ in calls)
    add3 = next(k for m, k in calls if m == "settings.addModel")
    assert "apiKey" not in add3


def test_imported_no_real_key(catalog):
    _add_manual({"name": "DS", "model": "deepseek-chat", "apiKey": "sk-x"})
    # imported 条目: hasApiKey 从 KB 行回显, 无 apiKey 字段(真值由主库持有)
    imp = {"source": "imported", "id": "kb-9", "name": "K", "provider": "deepseek",
           "model": "k-1", "url": "https://k", "hasApiKey": True}
    mc.save_llm_models(mc.get_llm_models() + [imp])
    mask = mc._mask_catalog(mc.get_llm_models())
    row = next(m for m in mask if m["id"] == "kb-9")
    assert "apiKey" not in row and row["hasApiKey"] is True
    man = next(m for m in mask if m["id"].startswith("man-"))
    assert man["apiKey"] == mc._APIKEY_MASK and man["hasApiKey"] is True


def test_builtin_cline_projection_provider_id(catalog, monkeypatch):
    # 同毫秒 _id 碰撞 → save_llm_models 按 id 去重丢条目; 注入递增 id
    seq = iter(range(1, 100))
    monkeypatch.setattr(lc, "_id", lambda p: f"{p}-t{next(seq)}")
    _add_manual({"name": "DS", "model": "deepseek-chat", "provider": "deepseek",
                 "url": "https://api.deepseek.com", "apiKey": "sk-ds"})
    _add_manual({"name": "LM", "model": "qwen", "provider": "custom-local",
                 "url": "http://192.168.1.5:8082"})
    _add_manual({"name": "GLM", "model": "glm-4.7", "provider": "custom-cloud",
                 "url": "https://open.bigmodel.cn/api/paas/v4", "apiKey": "sk-g"})
    proj = {m["name"]: m for m in ae._builtin_cline_models()}
    # 真值随投影(runner 透传 sidecar); providerId 保守映射
    assert proj["DS"]["apiKey"] == "sk-ds" and proj["DS"]["providerId"] == "deepseek"
    assert proj["LM"]["apiKey"] == "" and proj["LM"]["providerId"] == ""   # 本地: 默认路径不变
    assert proj["GLM"]["providerId"] == "openai-compatible"               # https 云兜底
