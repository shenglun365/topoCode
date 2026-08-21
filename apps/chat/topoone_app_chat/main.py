"""Chat 应用服务独立进程（M12）— chat 子项目 :3483。

承载 chat.py 全部路由（/chat · /api/chat/* · /api/models · /api/skills ·
/api/template-locale · /api/drafts* · /api/notes · /api/archives）。
数据：topoone.db chat_drafts/chat_archives 主写；会话/消息经 llm 服务 session.*
（sessions.db）或现状内置路径（P3d 瘦身前）。

P3d 瘦身（任务 12.5，可选）：删除内置 LLM 客户端（直连 /v1/chat/completions）与
skills.py/web_tools.py —— 流式改经 llm 服务 llm.chat + SUB 5682 转发。

用法：python -m topoone_app_chat --data-dir <dir> [--port 3483]
"""

import argparse
import logging
import os

from topoone.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="TopoOne Chat Application Service")
    parser.add_argument("--data-dir", type=str, default=None)
    parser.add_argument("--port", type=int, default=int(os.environ.get("CHAT_SERVICE_PORT", "3483")))
    parser.add_argument("--host", type=str, default="127.0.0.1")
    args = parser.parse_args()

    data_dir = args.data_dir or os.path.join(os.path.expanduser("~"), ".topocode")
    os.makedirs(data_dir, exist_ok=True)

    import uvicorn
    from fastapi import FastAPI
    from topoone import service_common as common
    from topoone.db.manager import MultiDBManager
    from topoone_app_chat.web_tools import WebToolExecutor
    from topoone_app_chat.chat_tables import ensure_chat_tables
    from topoone_app_chat.chat import router as chat_router

    multi_db = MultiDBManager(data_dir)
    common.set_globals(multi_db, port=args.port, executor=WebToolExecutor(multi_db))
    ensure_chat_tables(multi_db)

    app = FastAPI(title="TopoOne Chat Application")
    app.include_router(chat_router)

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok", "service": "chat-service"}

    logger.info(f"[chat-service] starting on http://{args.host}:{args.port}")
    from topoone.http_logging import install_heartbeat_filter
    install_heartbeat_filter()
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    finally:
        multi_db.close_all()


if __name__ == "__main__":
    main()
