"""LLM 服务独立进程（P3a）— 模型网关 :3484。

方法命名空间：llm.* · session.* · analysisSession.* · promptTemplate.*
事件：PUB :5682（llm.* 流式 chunk 等）
数据：sessions.db 主写（llm_sessions/llm_messages/analysis_sessions）；
      topoone.db 读 model_configs、写 model_daily_usage/llm_call_logs；
      llm_prompt_templates 读写。

用法：python -m topoone.llm --data-dir <dir> [--port 3484] [--pub-port 5682]
"""

import argparse
import logging
import os

from topoone.logging_config import setup_logging
setup_logging()
logger = logging.getLogger(__name__)


def register_methods(server, multi_db):
    from topoone.llm.service import register_llm_methods
    register_llm_methods(server, multi_db)


def main():
    parser = argparse.ArgumentParser(description="TopoOne LLM Service (model gateway)")
    parser.add_argument("--data-dir", type=str, default=None)
    parser.add_argument("--port", type=int, default=int(os.environ.get("LLM_SERVICE_PORT", "3484")))
    parser.add_argument("--pub-port", type=int, default=int(os.environ.get("LLM_PUB_PORT", "5682")))
    args = parser.parse_args()

    data_dir = args.data_dir or os.path.join(os.path.expanduser("~"), ".topocode")
    from topoone.rpc.service_app import run_service
    run_service(
        register_methods,
        data_dir=data_dir,
        port=args.port,
        pub_port=args.pub_port,
        pub_topic_prefix="",  # llm_service 发布时 topic 已带 "llm"
        title="llm-service",
    )


if __name__ == "__main__":
    main()
