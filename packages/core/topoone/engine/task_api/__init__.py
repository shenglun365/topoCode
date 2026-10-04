"""analysis.* RPC 注册聚合（MS5-V1 拆分）。

注册顺序 = 原 task_manager.register_analysis_methods 顺序（rpc_ids 基线锁序）；
每批次 parity 由 scripts/check-rpc-parity.py 与基线 diff 门禁兜底。
"""
from . import tasks_crud, community_query, agent_dispatch, subdocs, workspace_snapshot
from . import community_from_graph
from . import build_graph
from .common import Shared


def register_analysis_methods(server, multi_db):
    """将所有 analysis.* 方法注册到 RPC 服务器（顺序与拆分前一致）"""
    S = Shared(server, multi_db)
    S.bind_agent_proxy()
    S.startup_sweep()
    tasks_crud.register(server, multi_db, S)
    community_query.register(server, multi_db, S)
    agent_dispatch.register(server, multi_db, S)
    subdocs.register(server, multi_db, S)
    workspace_snapshot.register_workspace_methods(server, multi_db)
    community_from_graph.register_community_from_graph(server, multi_db)
    build_graph.register(server, multi_db)
    S.recover_orphans()
