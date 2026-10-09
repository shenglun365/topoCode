"""LLM 模型目录(单源拆分自 mcp_collab, §8.2) — KB 导入 / 手动条目 / apiKey / 连通探测。

存储 arch_collab_config 键 `llm.models`(JSON 列表), 每条含 `source`:
  - imported: 从 KB 手动导入(重复导入全量重建此部分)
  - manual  : architect 单独手动设置(重复导入不会覆盖)

外部云 API apiKey(2026-10 裁决): 明文 kv 存储 + 出站掩码 ******;
manual 条目 key 经 _sync_manual_to_kb 同步主库(llm.sync 推理真正生效处);
内置 cline 模型面 = 本目录实时投影(agent_executors._builtin_cline_models)。
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request

from ..common import _ts, _id, ok, err
from .. import store

router = APIRouter()

# ── LLM 模型配置: KB 导入 / 手动设置 ──────────────────────────────
# 存储于 arch_collab_config 键 `llm.models`(JSON 列表)。每条含 `source`:
#   - imported: 从 KB 手动导入(重复导入全量重建此部分)
#   - manual  : architect 单独手动设置(重复导入不会覆盖)

_MODELS_KEY = "llm.models"

# apiKey 出站掩码(对齐 agent_executors._SECRET_KEYS 先例: 明文 kv 存储 +
# API 层打码; 回传 ****** = 保留旧值, 空串 = 显式清除)
_APIKEY_MASK = "******"


def _mask_catalog(models: list) -> list:
    """出站掩码: 持有 apiKey 的条目打码为 ****** + hasApiKey 布尔回显。

    imported 条目不落真 key(key 由主库持有), hasApiKey 已在
    _normalize_kb_model 从 KB 行回显; manual 条目按本条目 apiKey 判定。"""
    out = []
    for m in models or []:
        row = dict(m or {})
        has = bool(str(row.pop("apiKey", "") or "").strip()) or bool(row.get("hasApiKey"))
        row["hasApiKey"] = has
        if has and row.get("source") == "manual":
            row["apiKey"] = _APIKEY_MASK
        out.append(row)
    return out


def get_llm_models() -> list:
    raw = store.CollabConfigStore.get(_MODELS_KEY, "")
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        for m in data:   # 惰性清理: 上下文字段已取消(运行时探测)——存量键弹出
            if isinstance(m, dict):
                m.pop("contextWindow", None)
        return data
    except (json.JSONDecodeError, TypeError):
        return []


def save_llm_models(models: list) -> None:
    """持久化模型目录。存储前按 id 归一: 同 id 保留 updatedAt 最新的一条。

    KB 同步按 model 名复用主库 id(_sync_manual_to_kb), 同一逻辑模型的
    多个名称/配置变体曾造成「同 id 双行」(id 冲突导致编辑歧义/渲染 key 冲突)。
    """
    by_id: dict = {}
    order: list = []
    extras: list = []
    for m in models or []:
        mid = str(m.get("id") or "")
        if not mid:
            extras.append(m)
            continue
        if mid in by_id:
            old = by_id[mid]
            if int(m.get("updatedAt") or 0) >= int(old.get("updatedAt") or 0):
                by_id[mid] = m
        else:
            by_id[mid] = m
            order.append(mid)
    merged = [by_id[k] for k in order] + extras
    store.CollabConfigStore.set(_MODELS_KEY, json.dumps(merged, ensure_ascii=False))


def _model_identity(m: dict) -> str:
    """模型身份(导入与手动的合并键)：name + provider + model。"""
    return f"{m.get('name', '')}|{m.get('provider', '')}|{m.get('model', '')}"


def _catalog_url(url: str) -> str:
    """模型目录 url 规范: 存服务根(剥 /v1)——上下文探测(/props, /api/v0)从根发起;
    SDK 侧的 /v1 拼接由 runner._ensure_v1 兜底, 两处语义分离。"""
    u = (url or "").strip().rstrip("/")
    if u.endswith("/v1"):
        u = u[:-3]
    return u


def _normalize_kb_model(row: dict) -> dict:
    """把主后端 settings.getModels 行归一化为 architect 模型配置。"""
    return {
        "source": "imported",
        "id": row.get("id") or "",
        "name": row.get("name") or "",
        "provider": row.get("provider") or "",
        "model": row.get("model") or "",
        "url": _catalog_url(row.get("url") or ""),
        "type": row.get("type") or "local",
        "isDefault": bool(row.get("isDefault") or row.get("is_default")),
        "hasApiKey": bool(row.get("hasApiKey")),
        "updatedAt": _ts(),
    }


@router.get("/llm/models")
async def get_llm_models_route():
    """模型配置列表(含 source: imported | manual)。"""
    models = get_llm_models()
    imported = [m for m in models if m.get("source") == "imported"]
    manual = [m for m in models if m.get("source") == "manual"]
    return ok({
        "models": _mask_catalog(manual + imported),
        "imported": len(imported),
        "manual": len(manual),
        "modelId": store.CollabConfigStore.get("llm.modelId", ""),
    })


@router.post("/llm/models/import")
async def import_llm_models_route():
    """手动同步：从 KB 导入模型配置(全量重建导入)。

    - 每次导入先清除原有全部 imported(source=imported) 记录，再按 KB 当前列表重建；
    - manual(source=manual) 项整体保留；identity 与手动项重复的 KB 项跳过(preserved)。
    """
    from ..kb_gateway import call_kb
    raw = call_kb("settings.getModels")
    if not raw:
        return err(424, "KB 不可达或无可用模型")
    rows = raw if isinstance(raw, list) else list(raw.get("models") or [])

    existing = get_llm_models()
    manual = {_model_identity(m): m for m in existing if m.get("source") == "manual"}

    added, preserved = 0, 0
    out_imported: list = []
    for row in rows:
        model = _normalize_kb_model(row)
        if _model_identity(model) in manual:
            preserved += 1
            continue
        out_imported.append(model)
        added += 1

    catalog = list(manual.values()) + out_imported
    # 上下文窗口不再落库(2026-10-02 裁决: KB/architect 双侧 ctx 字段取消，
    # 一律运行时探测 probe_context_window → resolve_context_budget——
    # 落库快照会过时失真(8192 vs 实测 262144)，max_tokens 仍由两侧自行设置)
    save_llm_models(catalog)
    store.CollabConfigStore.set("llm.modelImportedAt", str(_ts()))
    # 当前选中模型若已不在重建后的列表中 → 清空偏好(回退主后端默认模型)
    model_id = store.CollabConfigStore.get("llm.modelId", "")
    if model_id and model_id not in {m.get("id") for m in out_imported + list(manual.values())}:
        store.CollabConfigStore.set("llm.modelId", "")
    return ok({
        "models": list(manual.values()) + out_imported,
        "added": added, "preserved": preserved,
    })


_KB_PROVIDERS = ("ollama", "lm-studio", "custom-local", "deepseek",
                 "minimax-cn", "minimax-global", "openrouter", "custom-cloud")


def _sync_manual_to_kb(entry: dict) -> dict:
    """manual 条目同步主后端模型库(探测/对话链路经 llm.sync 只认主库 modelId)。

    先在 KB 自有条目中按 model 名匹配(复用 id, 用户已在主后端配置过的不重复建);
    匹配不到 → settings.addModel 注册到 architect 专属域(ownerApp='architect',
    不污染 KB 模型列表, KB 导入也不会拉回造成重复配置)。KB 不可达 → 条目保持
    本地 id(探测会回退默认模型, 前端连通性测试仍可用直连 url)。

    apiKey 同步(外部云 API 支持): addModel 携带 key 注册; 已匹配主库行且
    本条目持有 key → updateModel 推送(幂等, 同值重复推送无害)。key 为空不
    动主库既有 key(保守: architect 端清 key 不隐式清除主库配置)。"""
    try:
        from ..kb_gateway import call_kb
        raw = call_kb("settings.getModels")
        rows = raw if isinstance(raw, list) else list((raw or {}).get("models") or [])
        model_name = str(entry.get("model") or "").strip()
        url_clean = str(entry.get("url") or "").rstrip("/")
        api_key = str(entry.get("apiKey") or "").strip()
        for row in rows or []:
            if str(row.get("model") or "").strip() == model_name:
                entry["id"] = row["id"]          # 绑定主库 id
                entry["kbShared"] = True          # 复用 KB 自有条目——删除时不可动主库
                if api_key and api_key != _APIKEY_MASK:
                    try:
                        call_kb("settings.updateModel", id=row["id"], apiKey=api_key)
                    except Exception as e:  # noqa: BLE001
                        logging.getLogger("arch.mcp_collab").warning(
                            "[llm-manual] 主库 apiKey 推送失败(本地条目仍保留): %s", e)
                return entry
        provider = str(entry.get("provider") or "").strip().lower()
        if provider not in _KB_PROVIDERS:
            provider = "lm-studio" if provider == "lms" else "custom-local"
        kwargs = dict(name=str(entry.get("name") or model_name),
                      provider=provider, model=model_name,
                      url=url_clean, type=str(entry.get("type") or "local"),
                      ownerApp="architect")
        if api_key and api_key != _APIKEY_MASK:
            kwargs["apiKey"] = api_key
        row = call_kb("settings.addModel", **kwargs)
        if isinstance(row, dict) and row.get("id"):
            entry["id"] = row["id"]
            entry.pop("kbShared", None)           # 注册到 architect 专属域——删除时可清理
    except Exception as e:  # noqa: BLE001
        logging.getLogger("arch.mcp_collab").warning(
            "[llm-manual] 主库同步失败(条目保留本地, 探测将回退默认模型): %s", e)
    return entry


@router.post("/llm/models/manual")
async def add_manual_llm_model_route(request: Request):
    """手动添加模型(独立于 KB)。Body: { name, provider?, model, url?, apiKey? }"""
    body = await request.json() or {}
    name = str(body.get("name") or "").strip()
    model_val = str(body.get("model") or "").strip()
    if not name or not model_val:
        return err(400, "name 与 model 必填")
    entry = {
        "source": "manual",
        "id": _id("man"),
        "name": name,
        "provider": str(body.get("provider") or "custom").strip(),
        "model": model_val,
        "url": str(body.get("url") or "").strip(),
        "apiKey": str(body.get("apiKey") or "").strip(),
        "type": str(body.get("type") or "local").strip(),
        "isDefault": bool(body.get("isDefault")),
        "updatedAt": _ts(),
    }
    entry = _sync_manual_to_kb(entry)
    # id 唯一化: KB 同步按 model 名复用主库 id, 旧变体行可能已持同 id → 移除
    # (否则同 id 双行: 编辑歧义 + 前端 :key 冲突); 身份去重保持原语义
    eid = str(entry.get("id") or "")
    models = [m for m in get_llm_models()
              if str(m.get("id") or "") != eid
              and (m.get("source") != "manual"
                   or _model_identity(m) != _model_identity(entry))]
    models.append(entry)
    save_llm_models(models)
    return ok(entry)


@router.put("/llm/models/manual/{model_id}")
async def update_manual_llm_model_route(model_id: str, request: Request):
    """修改模型条目。Body: { name?, provider?, model?, url?, apiKey? }

    - manual: 直接修改后重同步主库绑定;
    - imported: 修改后转为 manual(独立条目, KB 重新导入不覆盖——同 identity
      的 KB 项会被 preserved 跳过; id 保持主库绑定, 推理路由不受影响)。
    - apiKey: ****** = 保留旧值; 空串 = 显式清除; 其余 = 新值(对齐
      agent_executors 掩码先例)。"""
    body = await request.json() or {}
    models = get_llm_models()
    target = next((m for m in models if m.get("id") == model_id), None)
    if not target:
        return err(404, "模型条目不存在")
    if target.get("source") not in ("manual", "imported"):
        return err(400, "不可修改的条目")
    name = str(body.get("name") or target.get("name") or "").strip()
    model_val = str(body.get("model") or target.get("model") or "").strip()
    if not name or not model_val:
        return err(400, "name 与 model 必填")
    target.update({
        "source": "manual",
        "name": name,
        "provider": str(body.get("provider") or target.get("provider") or "custom").strip() or "custom",
        "model": model_val,
        "url": str(body.get("url") or "").strip(),
        "updatedAt": _ts(),
    })
    if "apiKey" in body:
        new_key = str(body.get("apiKey") or "").strip()
        if new_key != _APIKEY_MASK:   # ****** 回传(编辑态未改) → 保留旧值; 空串 = 显式清除
            target["apiKey"] = new_key
    target = _sync_manual_to_kb(target)
    save_llm_models(models)
    return ok(target)


@router.delete("/llm/models/{model_id}")
async def delete_llm_model_route(model_id: str):
    """删除模型条目(均不动 KB 主库自有配置):

    - imported: 仅解除导入——architect 端移除, 主库条目保留, 重新导入可恢复;
    - manual  : 移除 architect 条目; 若其绑定 id 是主库 architect 域注册条目
                (kbShared 非真) → 同步清理, 防孤儿堆积。
    """
    models = get_llm_models()
    target = next((m for m in models if m.get("id") == model_id), None)
    if not target:
        return err(404, "Model not found")
    if target.get("source") not in ("manual", "imported"):
        return err(400, "不可删除的条目")
    if target.get("source") == "manual" and not target.get("kbShared") \
            and not str(model_id).startswith("man-"):
        try:
            from ..kb_gateway import call_kb
            call_kb("settings.removeModel", id=model_id)
        except Exception as e:  # noqa: BLE001
            logging.getLogger("arch.mcp_collab").warning(
                "[llm-manual] 主库注册条目清理失败(本地条目仍删除): %s", e)
    save_llm_models([m for m in models if m.get("id") != model_id])
    if store.CollabConfigStore.get("llm.modelId", "") == model_id:
        store.CollabConfigStore.set("llm.modelId", "")
    return ok({"id": model_id})


@router.post("/llm/models/probe")
async def probe_llm_model_route(request: Request):
    """architect 实例模型连通性测试。Body: { url, model, apiKey? | modelId?(取已存条目) }。"""
    body = await request.json() or {}
    url = str(body.get("url") or "").strip()
    model = str(body.get("model") or "").strip()
    api_key = str(body.get("apiKey") or "").strip()
    mid = str(body.get("modelId") or "").strip()
    if mid and not (url and model):
        target = next((m for m in get_llm_models() if m.get("id") == mid), None)
        if not target:
            return err(404, "模型条目不存在")
        url = target.get("url") or ""
        model = target.get("model") or ""
        api_key = api_key or str(target.get("apiKey") or "").strip()
    if not model:
        return err(400, "缺少 model")
    from .agent_executors import _probe_llm_model
    return ok(_probe_llm_model(url, model, api_key))


