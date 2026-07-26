"""Data API — HTTP write proxy for web端

Receives write requests from web端 (in multi-process mode) and executes
them via the registered ZMQ methods or directly on the database.

In single-process mode (current): web端 calls multi_db directly.
This API exists for multi-process mode where web端 runs as a subprocess.
"""

import json
import logging

import uvicorn
from fastapi import FastAPI, HTTPException

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
    db_name = body.get("db", "main")  # 'main', 'sessions', 'knowledge', or project_id
    sql = body.get("sql", "")
    params = body.get("params")

    if not multi_db:
        raise HTTPException(503, "Backend not ready")

    try:
        if db_name == "main":
            conn = multi_db.main_db
        elif db_name == "sessions":
            conn = multi_db.sessions_db
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


@app.post("/zmq/{method}")
async def call_zmq_method(method: str, body: dict):
    """Call a registered ZMQ method (for operations with side effects)"""
    if not zmq_server:
        raise HTTPException(503, "ZMQ server not ready")

    handler = zmq_server.methods.get(method)
    if not handler:
        raise HTTPException(404, f"Method {method} not found")

    try:
        result = handler(**body)
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
