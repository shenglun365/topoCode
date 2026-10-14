"""MCP logs, collaboration mode, interactions, KB connection config (sqlite-backed)."""
import json
import logging
import urllib.error
import urllib.request
from fastapi import APIRouter, Request
from ..common import _ts, _id, ok, err
from .. import store

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
    from ..agent.tools.req_agent import get_model_preference
    return ok({"modelId": get_model_preference()})


@router.put("/llm/model")
async def set_model_preference_route(request: Request):
    """设置 LLM 模型偏好。Body: { modelId: string }"""
    from ..agent.tools.req_agent import set_model_preference
    body = await request.json() or {}
    model_id = str(body.get("modelId") or "").strip()
    set_model_preference(model_id)
    return ok({"modelId": model_id})


@router.get("/llm/max-tokens")
async def get_max_tokens_preference_route():
    """LLM max_tokens 偏好(空 = 主后端按 model_configs.max_tokens)。"""
    from ..agent.tools.req_agent import get_max_tokens_preference
    return ok({"maxTokens": get_max_tokens_preference()})


@router.put("/llm/max-tokens")
async def set_max_tokens_preference_route(request: Request):
    """设置 LLM max_tokens 偏好。Body: { maxTokens: number }；0/空清除(回退模型配置)。"""
    from ..agent.tools.req_agent import set_max_tokens_preference
    body = await request.json() or {}
    raw = body.get("maxTokens")
    try:
        value = int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        value = None
    set_max_tokens_preference(value)
    return ok({"maxTokens": value})


# ── LLM 模型目录已拆分至 llm_catalog.py(§8.2)——此处 re-export 兼容
# 既有引用面(agent_executors 投影 / tests / 认知层), 新代码直连新模块 ──
from .llm_catalog import (  # noqa: E402,F401
    _APIKEY_MASK,
    _KB_PROVIDERS,
    _catalog_url,
    _mask_catalog,
    _model_identity,
    _normalize_kb_model,
    _sync_manual_to_kb,
    add_manual_llm_model_route,
    delete_llm_model_route,
    get_llm_models,
    get_llm_models_route,
    import_llm_models_route,
    probe_llm_model_route,
    save_llm_models,
    update_manual_llm_model_route,
)


@router.get("/llm/model-profiles")
async def get_model_profiles():
    """全部模型能力档案(tier/caps/探测历史; 无档案模型不出现在列表)。"""
    from ..agent.cognition import model_profile
    return ok({"profiles": list(model_profile.all_profiles().values()),
               "tiers": model_profile.TIERS})


@router.get("/llm/model-profiles/tier-suggestions")
async def get_tier_suggestions():
    """挡位建议(#3, 建议值+人审): dataset 失败画像 → tierSuggested 只读展示。

    绝不自动写档案(防守线②, D6); 采纳 = 人工 PUT /llm/model-profiles/{id}
    (manual 档); 人工已设的模型建议让位(manualPinned)。"""
    from ..agent.reflection.tier_suggest import suggest_tiers
    return ok(suggest_tiers())


@router.get("/llm/capability-probe/status")
async def capability_probe_gate_status():
    """探测闸门状态(自省): {running: 在跑模型id, queue: [排队模型id]}——
    前端置灰期间展示真实进度; 亦可供 curl 排查按钮全灰是否为探测在途。
    注意引真实模块: `from . import model_profile` 是兼容 shim, 不含 _probe_gate。"""
    from ..agent.cognition import model_profile
    return ok(model_profile._probe_gate.status())


@router.post("/llm/models/{model_id}/capability-probe")
async def capability_probe_route(model_id: str):
    """能力探测(~10 次小调用): 工具协议/JSON 围栏/指令边界 → tier 档案。
    并发治理: 全局互斥串行 + FIFO 排队 + 同模型滤重(重复点击立即回执)。"""
    from ..agent.cognition import model_profile
    import asyncio
    res = await asyncio.to_thread(model_profile.probe_model_gated, model_id)
    return ok(res["profile"])


@router.delete("/llm/model-profiles")
async def clear_model_profiles():
    """清空全部模型能力档案(旧套件/旧刻度残留清理; 各模型回到未探测态)。"""
    from ..agent.cognition import model_profile
    return ok({"cleared": model_profile.clear_profiles()})


@router.delete("/llm/model-profiles/{model_id}")
async def clear_model_profile(model_id: str):
    """清空单个模型档案(重探前复位)。"""
    from ..agent.cognition import model_profile
    return ok({"cleared": model_profile.clear_profile(model_id)})


@router.put("/llm/model-profiles/{model_id}")
async def set_model_profile_route(model_id: str, request: Request):
    """手工设置模型 tier(manual 优先级最高, 后续探测不覆盖)。Body: {tier} 或 {asset: {...}|null}。"""
    body = await request.json() or {}
    if "asset" in body:
        # 语义资产解析参数手动覆盖(独立字段, 与综合档 tier 互不干扰; null=清除)
        from ..agent.cognition import asset_probe
        return ok(asset_probe.set_asset_profile_manual(model_id, body.get("asset")))
    try:
        tier = int(body.get("tier"))
    except (TypeError, ValueError):
        return err(400, "缺少整数 tier (0-2) 或 asset 对象")
    from ..agent.cognition import model_profile
    return ok(model_profile.set_manual_tier(model_id, tier))


@router.post("/llm/models/{model_id}/asset-capability-probe")
async def asset_capability_probe(model_id: str, force: bool = False):
    """语义资产解析能力探测(独立套件, 10 次调用测稳定性) → 参数化档案
    (mode/listCap/chainLen/retries, 与综合档共表独立 asset 字段)。"""
    import asyncio
    from ..agent.cognition import asset_probe
    try:
        r = await asyncio.to_thread(asset_probe.probe_asset_capability, model_id, force=force)
    except Exception as e:  # noqa: BLE001
        return err(500, f"探测失败: {e}")
    return ok(r)


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
