"""MCP logs, collaboration mode, interactions, KB connection config (sqlite-backed)."""
import json
import logging
import urllib.error
import urllib.request
from fastapi import APIRouter, Request
from .common import _ts, _id, ok, err
from . import store

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_DATA_API = "http://127.0.0.1:3459"
DEFAULT_MCP_URL = "http://127.0.0.1:3460"

_KB_KEYS = ("dataApiUrl", "mcpUrl", "lastStatus", "lastDetail", "lastCheckAt", "updatedAt")


def get_kb_config() -> dict:
    return {
        "dataApiUrl": store.CollabConfigStore.get("kb.dataApiUrl", DEFAULT_DATA_API),
        "mcpUrl": store.CollabConfigStore.get("kb.mcpUrl", DEFAULT_MCP_URL),
        "lastStatus": store.CollabConfigStore.get("kb.lastStatus", "unknown"),
        "lastDetail": store.CollabConfigStore.get("kb.lastDetail", ""),
        "lastCheckAt": int(store.CollabConfigStore.get("kb.lastCheckAt", "0") or 0),
        "updatedAt": int(store.CollabConfigStore.get("kb.updatedAt", "0") or 0),
    }


def _save_kb_config(data: dict) -> None:
    for k, v in data.items():
        store.CollabConfigStore.set(f"kb.{k}", "" if v is None else str(v))


def probe_kb(cfg: dict) -> dict:
    """KB 连通性测试：data_api /health + MCP /health。"""
    data_api = (cfg.get("dataApiUrl") or DEFAULT_DATA_API).rstrip("/")
    mcp = (cfg.get("mcpUrl") or DEFAULT_MCP_URL).rstrip("/")
    failures = []
    for label, url in (("data_api", f"{data_api}/health"), ("mcp", f"{mcp}/health")):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=3) as resp:
                if resp.status != 200:
                    failures.append(f"{label}: HTTP {resp.status}")
        except urllib.error.URLError as e:
            failures.append(f"{label}: {getattr(e, 'reason', e)}")
        except Exception as e:
            failures.append(f"{label}: {e}")
    if failures:
        return {"status": "fail", "detail": "；".join(failures)}
    return {"status": "ok", "detail": "KB data_api 与 MCP 均可达"}


@router.get("/kb/config")
async def get_kb_config_route():
    """获取知识库连接配置(不含凭据)。"""
    return ok(get_kb_config())


@router.put("/kb/config")
async def set_kb_config_route(request: Request):
    """保存知识库连接配置。Body: { dataApiUrl?, mcpUrl? }"""
    body = await request.json() or {}
    now = _ts()
    data = {
        "dataApiUrl": (body.get("dataApiUrl") or DEFAULT_DATA_API).strip(),
        "mcpUrl": (body.get("mcpUrl") or DEFAULT_MCP_URL).strip(),
        "updatedAt": now,
    }
    _save_kb_config(data)
    return ok(get_kb_config())


@router.post("/kb/config/test")
async def test_kb_config_route():
    """知识库连通性测试(data_api + MCP)，写回 last_status。"""
    now = _ts()
    result = probe_kb(get_kb_config())
    _save_kb_config({"lastStatus": result["status"], "lastDetail": result["detail"], "lastCheckAt": now})
    return ok({**get_kb_config(), "test": result})


@router.get("/mcp/calls")
async def list_mcp_calls():
    return ok(store.McpCallsStore.all())


@router.post("/mcp/calls")
async def record_mcp_call(request: Request):
    body = await request.json()
    call = {
        "id": store.next_id("mcp"), "tool": body.get("tool", ""),
        "input": body.get("input"), "output": body.get("output"),
        "status": body.get("status", ""), "time": _ts(),
    }
    store.McpCallsStore.create(call)
    return ok(call)


@router.get("/collab/mode")
async def get_collab_mode():
    return ok({"mode": store.CollabConfigStore.get("mode", "main-agent")})


@router.put("/collab/mode")
async def set_collab_mode(request: Request):
    body = await request.json()
    mode = body.get("mode", "main-agent")
    store.CollabConfigStore.set("mode", mode)
    return ok({"mode": mode})


@router.get("/llm/model")
async def get_model_preference_route():
    """LLM 模型偏好(空 = 主后端默认模型兜底)。"""
    from .req_agent import get_model_preference
    return ok({"modelId": get_model_preference()})


@router.put("/llm/model")
async def set_model_preference_route(request: Request):
    """设置 LLM 模型偏好。Body: { modelId: string }"""
    from .req_agent import set_model_preference
    body = await request.json() or {}
    model_id = str(body.get("modelId") or "").strip()
    set_model_preference(model_id)
    return ok({"modelId": model_id})


@router.get("/llm/max-tokens")
async def get_max_tokens_preference_route():
    """LLM max_tokens 偏好(空 = 主后端按 model_configs.max_tokens)。"""
    from .req_agent import get_max_tokens_preference
    return ok({"maxTokens": get_max_tokens_preference()})


@router.put("/llm/max-tokens")
async def set_max_tokens_preference_route(request: Request):
    """设置 LLM max_tokens 偏好。Body: { maxTokens: number }；0/空清除(回退模型配置)。"""
    from .req_agent import set_max_tokens_preference
    body = await request.json() or {}
    raw = body.get("maxTokens")
    try:
        value = int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        value = None
    set_max_tokens_preference(value)
    return ok({"maxTokens": value})


# ── LLM 模型配置: KB 导入 / 手动设置 ──────────────────────────────
# 存储于 arch_collab_config 键 `llm.models`(JSON 列表)。每条含 `source`:
#   - imported: 从 KB 手动导入(重复导入全量重建此部分)
#   - manual  : architect 单独手动设置(重复导入不会覆盖)

_MODELS_KEY = "llm.models"


def get_llm_models() -> list:
    raw = store.CollabConfigStore.get(_MODELS_KEY, "")
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def save_llm_models(models: list) -> None:
    store.CollabConfigStore.set(_MODELS_KEY, json.dumps(models, ensure_ascii=False))


def _model_identity(m: dict) -> str:
    """模型身份(导入与手动的合并键)：name + provider + model。"""
    return f"{m.get('name', '')}|{m.get('provider', '')}|{m.get('model', '')}"


def _normalize_kb_model(row: dict) -> dict:
    """把主后端 settings.getModels 行归一化为 architect 模型配置。"""
    return {
        "source": "imported",
        "id": row.get("id") or "",
        "name": row.get("name") or "",
        "provider": row.get("provider") or "",
        "model": row.get("model") or "",
        "url": row.get("url") or "",
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
        "models": manual + imported,
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
    from .kb_gateway import call_kb
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

    save_llm_models(list(manual.values()) + out_imported)
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
    """
    try:
        from .kb_gateway import call_kb
        raw = call_kb("settings.getModels")
        rows = raw if isinstance(raw, list) else list((raw or {}).get("models") or [])
        model_name = str(entry.get("model") or "").strip()
        url_clean = str(entry.get("url") or "").rstrip("/")
        for row in rows or []:
            if str(row.get("model") or "").strip() == model_name:
                entry["id"] = row["id"]          # 绑定主库 id
                return entry
        provider = str(entry.get("provider") or "").strip().lower()
        if provider not in _KB_PROVIDERS:
            provider = "lm-studio" if provider == "lms" else "custom-local"
        row = call_kb("settings.addModel", name=str(entry.get("name") or model_name),
                      provider=provider, model=model_name,
                      url=url_clean, type=str(entry.get("type") or "local"),
                      ownerApp="architect")
        if isinstance(row, dict) and row.get("id"):
            entry["id"] = row["id"]
    except Exception as e:  # noqa: BLE001
        logging.getLogger("arch.mcp_collab").warning(
            "[llm-manual] 主库同步失败(条目保留本地, 探测将回退默认模型): %s", e)
    return entry


@router.post("/llm/models/manual")
async def add_manual_llm_model_route(request: Request):
    """手动添加模型(独立于 KB)。Body: { name, provider?, model, url? }"""
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
        "type": str(body.get("type") or "local").strip(),
        "isDefault": bool(body.get("isDefault")),
        "updatedAt": _ts(),
    }
    entry = _sync_manual_to_kb(entry)
    models = [m for m in get_llm_models() if m.get("source") != "manual" or _model_identity(m) != _model_identity(entry)]
    models.append(entry)
    save_llm_models(models)
    return ok(entry)


@router.put("/llm/models/manual/{model_id}")
async def update_manual_llm_model_route(model_id: str, request: Request):
    """修改手动添加的模型条目。Body: { name?, provider?, model?, url? }——仅 manual
    可改(导入项以主库为源, 重新导入会覆盖, 请在主后端模型库修改)。"""
    body = await request.json() or {}
    models = get_llm_models()
    target = next((m for m in models if m.get("id") == model_id), None)
    if not target:
        return err(404, "模型条目不存在")
    if target.get("source") != "manual":
        return err(400, "KB 导入项不可在此修改(以主库为源)，请在主后端模型库调整后重新导入")
    name = str(body.get("name") or target.get("name") or "").strip()
    model_val = str(body.get("model") or target.get("model") or "").strip()
    if not name or not model_val:
        return err(400, "name 与 model 必填")
    target.update({
        "name": name,
        "provider": str(body.get("provider") or target.get("provider") or "custom").strip() or "custom",
        "model": model_val,
        "url": str(body.get("url") or "").strip(),
        "updatedAt": _ts(),
    })
    target = _sync_manual_to_kb(target)
    save_llm_models(models)
    return ok(target)


@router.delete("/llm/models/{model_id}")
async def delete_llm_model_route(model_id: str):
    """删除手动模型条目(不影响 KB 导入项)。"""
    models = get_llm_models()
    target = next((m for m in models if m.get("id") == model_id), None)
    if not target:
        return err(404, "Model not found")
    if target.get("source") != "manual":
        return err(400, "KB 导入项不可删除，请通过重新导入刷新")
    save_llm_models([m for m in models if m.get("id") != model_id])
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
    if not model:
        return err(400, "缺少 model")
    from .agent_executors import _probe_llm_model
    return ok(_probe_llm_model(url, model, api_key))


@router.get("/llm/model-profiles")
async def get_model_profiles():
    """全部模型能力档案(tier/caps/探测历史; 无档案模型不出现在列表)。"""
    from . import model_profile
    return ok({"profiles": list(model_profile.all_profiles().values()),
               "tiers": model_profile.TIERS})


@router.post("/llm/models/{model_id}/capability-probe")
async def capability_probe_route(model_id: str):
    """能力探测(同步执行, ~9 次小调用): 工具协议/JSON 围栏/指令边界 → tier 档案。"""
    from . import model_profile
    import asyncio
    return ok(await asyncio.to_thread(model_profile.probe_model, model_id))


@router.put("/llm/model-profiles/{model_id}")
async def set_model_profile_route(model_id: str, request: Request):
    """手工设置模型 tier(manual 优先级最高, 后续探测不覆盖)。Body: {tier}。"""
    body = await request.json() or {}
    try:
        tier = int(body.get("tier"))
    except (TypeError, ValueError):
        return err(400, "缺少整数 tier (0-4)")
    from . import model_profile
    return ok(model_profile.set_manual_tier(model_id, tier))


@router.get("/collab/interactions")
async def list_interactions():
    return ok(store.InteractionsStore.all())


@router.post("/collab/interactions")
async def create_interaction(request: Request):
    body = await request.json()
    interaction = {
        "id": store.next_id("it"), "prompt": body.get("prompt", ""),
        "status": body.get("status", ""), "answer": body.get("answer", ""),
        "time": _ts(),
    }
    store.InteractionsStore.create(interaction)
    return ok(interaction)


@router.post("/collab/interactions/{interaction_id}/resolve")
async def resolve_interaction(interaction_id: str, request: Request):
    body = await request.json()
    row = store.InteractionsStore.update(interaction_id, {
        "status": "resolved", "answer": body.get("answer"),
    })
    if not row:
        return err(404, "Interaction not found")
    return ok(row)


@router.get("/health")
async def health():
    return {"status": "ok", "service": "architect-api"}
