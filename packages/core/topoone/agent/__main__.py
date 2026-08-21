"""Agent 服务独立进程（P3b）— harness 引擎 :3482。

方法命名空间：agent.*（dispatch/progress/cancel/pause/resume/history/list_running/config）
事件：PUB :5684（agent.* 进度）
数据：读共享 project.db / topoone.db（agent_task_history）；sessions 经 llm 服务。

本服务把原 agent_worker 的 action 协议包装为 HTTP `/zmq/agent.*` 方法，
复用 AgentWorker 的 dispatch 逻辑（进程内），不再单独 spawn agent_worker。
supervisor 仍统一纳管 coding_agent_runner(:3458) 为其子进程。

用法：python -m topoone.agent --data-dir <dir> [--port 3482] [--pub-port 5684]
"""

import argparse
import logging
import os

from topoone.logging_config import setup_logging
setup_logging()
logger = logging.getLogger(__name__)


def register_methods(server, multi_db):
    """把 AgentWorker 的 action 协议注册为 agent.* HTTP 方法。"""
    from topoone.agent.worker import AgentWorker
    from topoone.db.manager import MultiDBManager

    worker = AgentWorker(multi_db.data_dir)
    worker._multi_db = multi_db  # 复用传入的 MultiDBManager（同一数据目录）
    from topoone.agent.agent_workflow.agent_queue import get_global_queue
    worker._agent_task_manager = get_global_queue()
    # 存到 server 上，供 action 方法使用
    server._agent_worker = worker

    @server.register("agent.dispatch")
    async def agent_dispatch(route: str, task_id: str, context: dict = None,
                             project_id: str = "", project_root: str = "",
                             project_summary: str = "", **extra):
        params = {
            "route": route, "task_id": task_id, "context": context or {},
            "project_id": project_id, "project_root": project_root,
            "project_summary": project_summary,
        }
        params.update(extra)
        return await worker._action_dispatch(params)

    @server.register("agent.getProgress")
    async def agent_get_progress(agent_id: str):
        return await worker._action_get_progress({"agent_id": agent_id})

    @server.register("agent.cancel")
    async def agent_cancel(agent_id: str):
        return await worker._action_cancel({"agent_id": agent_id})

    @server.register("agent.pause")
    async def agent_pause(agent_id: str):
        return await worker._action_pause({"agent_id": agent_id})

    @server.register("agent.resume")
    async def agent_resume(agent_id: str):
        return await worker._action_resume({"agent_id": agent_id})

    @server.register("agent.getHistory")
    async def agent_get_history(task_id: str, offset: int = 0, limit: int = 10):
        return await worker._action_get_history({"task_id": task_id, "offset": offset, "limit": limit})

    @server.register("agent.clearHistory")
    async def agent_clear_history(project_id: str, task_id: str):
        return await worker._action_clear_history({"project_id": project_id, "task_id": task_id})

    @server.register("agent.presummaryChain")
    async def agent_presummary_chain(**params):
        return await worker._action_presummary_chain(params)

    @server.register("agent.listRunning")
    async def agent_list_running():
        return worker._action_list_running()

    @server.register("agent.getConfig")
    async def agent_get_config():
        return worker._action_get_config({})

    # 代理原生 action（兼容旧协议调用方）：agent.raw/{action}
    @server.register("agent.raw")
    async def agent_raw(action: str, **params):
        return await worker._dispatch_action(action, params)


def main():
    parser = argparse.ArgumentParser(description="TopoOne Agent Service (harness)")
    parser.add_argument("--data-dir", type=str, default=None)
    parser.add_argument("--port", type=int, default=int(os.environ.get("AGENT_SERVICE_PORT", "3482")))
    parser.add_argument("--pub-port", type=int, default=int(os.environ.get("AGENT_PUB_PORT", "5684")))
    args = parser.parse_args()

    data_dir = args.data_dir or os.path.join(os.path.expanduser("~"), ".topocode")
    from topoone.rpc.service_app import run_service
    run_service(
        register_methods,
        data_dir=data_dir,
        port=args.port,
        pub_port=args.pub_port,
        pub_topic_prefix="",  # agent 进度事件 topic 直接使用（worker._publish_progress）
        title="agent-service",
    )


if __name__ == "__main__":
    main()
