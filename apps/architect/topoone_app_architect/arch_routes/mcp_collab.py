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
#   - imported: 从 KB 手动导入(重复导入会刷新此部分)
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
    """手动同步：从 KB 导入模型配置。

    - 已存在的 manual(source=manual) 项整体保留，不被重复导入覆盖；
    - 已存在同 identity 的 imported 项 → 刷新字段；
    - 其余 → 新增为 imported。
    """
    from .kb_gateway import call_kb
    raw = call_kb("settings.getModels")
    if not raw:
        return err(424, "KB 不可达或无可用模型")
    rows = raw if isinstance(raw, list) else list(raw.get("models") or [])

    existing = get_llm_models()
    manual = {_model_identity(m): m for m in existing if m.get("source") == "manual"}
    imported = [m for m in existing if m.get("source") == "imported"]

    added, updated, preserved = 0, 0, 0
    out_imported = []
    seen: set = set()
    for row in rows:
        model = _normalize_kb_model(row)
        key = _model_identity(model)
        if key in manual:
            preserved += 1
            continue
        prev = next((m for m in imported if _model_identity(m) == key), None)
        if prev:
            merged = {**prev, **{k: v for k, v in model.items() if k != "source"},
                      "updatedAt": _ts()}
            out_imported.append(merged)
            updated += 1
        else:
            out_imported.append(model)
            added += 1
        seen.add(key)

    # 保留仍未被 KB 提及的历史 imported 项(避免误删)，但刷新已存在项
    for m in imported:
        if _model_identity(m) not in seen:
            out_imported.append(m)

    save_llm_models(list(manual.values()) + out_imported)
    store.CollabConfigStore.set("llm.modelImportedAt", str(_ts()))
    return ok({
        "models": list(manual.values()) + out_imported,
        "added": added, "updated": updated, "preserved": preserved,
    })


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
    models = [m for m in get_llm_models() if m.get("source") != "manual" or _model_identity(m) != _model_identity(entry)]
    models.append(entry)
    save_llm_models(models)
    return ok(entry)


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
