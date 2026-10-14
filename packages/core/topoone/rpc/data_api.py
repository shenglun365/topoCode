"""Data API — HTTP write proxy for web端

Receives write requests from web端 (in multi-process mode) and executes
them via the registered ZMQ methods or directly on the database.

In single-process mode (current): web端 calls multi_db directly.
This API exists for multi-process mode where web端 runs as a subprocess.
"""

import inspect
import json
import logging

import uvicorn
from fastapi import FastAPI, HTTPException, Request

logger = logging.getLogger(__name__)

app = FastAPI(title="TopoOne Data API")

# Injected by BackendApp
multi_db = None
zmq_server = None


def set_globals(multi_db_instance, zmq_server_instance=None):
    global multi_db, zmq_server
    multi_db = multi_db_instance
    zmq_server = zmq_server_instance


@app.post("/sql/execute")
async def execute_sql(body: dict):
    """Execute a SQL write operation"""
    db_name = body.get("db", "main")  # 'main', 'sessions', 'chat', 'knowledge', or project_id
    sql = body.get("sql", "")
    params = body.get("params")

    if not multi_db:
        raise HTTPException(503, "Backend not ready")

    try:
        if db_name == "main":
            conn = multi_db.main_db
        elif db_name == "sessions":
            conn = multi_db.sessions_db
        elif db_name == "chat":
            conn = multi_db.chat_db
        elif db_name == "knowledge":
            conn = multi_db.knowledge_db
        else:
            # Project DB
            conn = multi_db.get_project_db(db_name)

        if params:
            result = conn.execute(sql, tuple(params) if params else ())
        else:
            result = conn.execute(sql)

        return {"ok": True, "rowcount": result.rowcount if hasattr(result, 'rowcount') else None}
    except Exception as e:
        logger.error(f"[DataAPI] execute failed: {e}\nSQL: {sql[:200]}")
        raise HTTPException(500, str(e))


# 对外白名单：/zmq/{method} 面向外部调用方(architect 等)，仅暴露**任务无关**的稳定接口。
# 任务管理(analysis.createTask/runTask/rebuildUnified/clearProjectCache...)为 KB 内部方法，
# 仅限 KB 前端经 gateway /api/rpc 进程内调用；外部越权访问返回 403。
EXTERNAL_METHODS = {
    # 项目/视图（基线视图对外契约：view.* 任务挂载管理与状态）
    "project.list",
    "view.status", "view.summary", "view.mount", "view.unmount", "view.history",
    # 架构只读（去基线化后按最新 done 任务解析）
    "architecture.catalog", "architecture.model",
    # 版本只读(写/编排类 preview/sync/cleanup 已随去基线化退役出白名单;
    # list/get/diff/materialize 仍被 architect 演化帧/历史解析消费, 批E 复核)
    "version.list", "version.get", "version.diff", "version.materialize",
}


def _internal_token(request) -> str | None:
    """读本机 serve token（与 gateway 同源），用于识别 KB 内部链路。"""
    import os
    base = os.environ.get("TOPOCODE_DB_DIR") or os.path.join(
        os.path.expanduser("~"), ".topocode")
    p = os.path.join(base, "token")
    try:
        if os.path.isfile(p):
            with open(p) as f:
                return (f.read().strip() or None)
    except OSError:
        pass
    return None


@app.post("/zmq/{method}")
async def call_zmq_method(method: str, request: Request, body: dict):
    """Call a registered ZMQ method (for operations with side effects)

    双面语义：
    - **内部面**（gateway /api/rpc 代理，携带有效 X-KB-Internal 凭据）：全部方法可用；
    - **外部面**（architect 等直连 /zmq）：仅限 EXTERNAL_METHODS 白名单（任务无关的稳定接口）。
    """
    if not zmq_server:
        raise HTTPException(503, "ZMQ server not ready")

    token = _internal_token(request)
    internal = bool(token) and request.headers.get("X-KB-Internal") == token
    if not internal and method not in EXTERNAL_METHODS:
        raise HTTPException(
            403, f"method '{method}' is internal to KB and not exposed to external callers")

    handler = zmq_server.methods.get(method)
    if not handler:
        raise HTTPException(404, f"Method {method} not found")

    try:
        result = handler(**body)
        # 异步 handler：与 zmq_server 的 await 语义一致，否则返回的是 coroutine 无法序列化
        if inspect.iscoroutine(result) or inspect.isawaitable(result):
            result = await result
        return {"result": result}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/health")
async def health():
    return {"status": "ok"}


async def start_data_api(multi_db_instance, zmq_server_instance=None,
                         port: int = 3459, host: str = '127.0.0.1'):
    """Start the Data API server in a separate thread"""
    set_globals(multi_db_instance, zmq_server_instance)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    logger.info(f"Data API starting on http://{host}:{port}")
    await server.serve()
