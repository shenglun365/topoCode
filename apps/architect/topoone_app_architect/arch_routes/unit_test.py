"""Unit-test workbench routes (sqlite-backed).

契约见 docs/architect/api-unit-test.md。执行/对话走 WS(/ws/unit-test)。
"""
from fastapi import APIRouter, Request
from ..common import _ts, ok, err
from .. import store

router = APIRouter()


@router.get("/unit-tests")
async def list_unit_tests():
    return ok(store.UnitTestsStore.all())


@router.post("/unit-tests/generate")
async def generate_unit_tests_route(request: Request):
    """单测生成(自主路径·B1)：agentic_loop 分析 scope 返回**草稿**，用户确认后创建。

    KB/LLM 不可达或解析失败 → 502(明确降级，不伪造草稿)。
    """
    from fastapi.responses import JSONResponse
    body = await request.json()
    scope = (body.get("scope") or "").strip()
    if not scope:
        return err(400, "测试范围不能为空")
    import asyncio
    from . import tagent_utgen
    # generate_unit_tests 内部 asyncio.run(新事件循环) → 须经 to_thread 在独立线程运行，
    # 不能在 async 端点的运行中事件循环里直接调用。
    draft = await asyncio.to_thread(
        tagent_utgen.generate_unit_tests,
        scope=scope, root=body.get("root") or "", project=body.get("project") or "",
        model_id=body.get("modelId") or "")
    if draft is None or not draft.get("tests"):
        return JSONResponse(status_code=502, content={
            "code": 502,
            "message": "KB/LLM 不可达或生成失败，无法产出单测草稿。请检查知识库网关后重试。",
            "data": None,
        })
    return ok({"scope": scope, "tests": draft["tests"], "draft": True})


@router.post("/unit-tests")
async def add_unit_test(request: Request):
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return err(400, "单测名称不能为空")
    now = _ts()
    test = {
        "id": store.next_id("ut"),
        "name": name,
        "levels": body.get("levels", []),
        "scriptPath": body.get("scriptPath", ""),
        "source": body.get("source", "manual"),
        "status": "idle",
        "assetRefs": body.get("assetRefs", []),
        "createdAt": now,
        "updatedAt": now,
    }
    store.UnitTestsStore.create(test)
    # 语义资产引用登记(test→sa-*)
    try:
        from .semantic_assets import register_scope_refs
        register_scope_refs(body.get("assetRefs") or [], "test", test["id"])
    except Exception:
        pass
    return ok(store.UnitTestsStore.get(test["id"]))


@router.patch("/unit-tests/{test_id}")
async def update_unit_test(test_id: str, request: Request):
    body = await request.json()
    row = store.UnitTestsStore.update(test_id, {**body, "updatedAt": _ts()})
    if not row:
        return err(404, "Unit test not found")
    return ok(row)


@router.get("/unit-test-sessions")
async def list_unit_test_sessions():
    return ok(store.UnitTestSessionsStore.all())


@router.post("/unit-test-sessions")
async def create_unit_test_session(request: Request):
    body = await request.json()
    title = (body.get("title") or "").strip()
    if not title:
        return err(400, "会话标题不能为空")
    now = _ts()
    channel = body.get("channel", "cli")
    adapter = body.get("adapter", "opencode")
    init_msg = {
        "id": store.next_id("m"),
        "role": "user",
        "time": now,
        "content": f"创建单测会话「{title}」 · 执行通道: {'topocode 命令行' if channel == 'cli' else '三方 agent'}",
    }
    session = {
        "id": store.next_id("uts"),
        "title": title,
        "channel": channel,
        "adapter": adapter,
        "testIds": body.get("testIds", []),
        "status": "created",
        "stats": {"requests": 0, "tokensIn": 0, "tokensOut": 0, "bytesIn": 0, "bytesOut": 0},
        "createdAt": now,
        "updatedAt": now,
    }
    store.UnitTestSessionsStore.create(session)
    store.UnitTestSessionsStore.append_message({**init_msg, "sessionId": session["id"]})
    return ok(_with_messages(session["id"]))


def _with_messages(session_id: str):
    session = store.UnitTestSessionsStore.get(session_id)
    if not session:
        return None
    session["messages"] = store.UnitTestSessionsStore.messages(session_id)
    return session


@router.get("/unit-test-sessions/{session_id}")
async def get_unit_test_session(session_id: str):
    session = _with_messages(session_id)
    if not session:
        return err(404, "Session not found")
    return ok(session)
