"""统一超时配置(单源, cv-199) — 全部框架级阻塞调用的超时在此登记。

纪律: **禁止字面量散落**——任何超时须在本表登记名字与缺省值, 调用点经
`get(name)` 读取; 应急调参不改代码(环境变量 `TOPO_TIMEOUT_<NAME>` 覆盖,
与既有 LLM_SYNC_TIMEOUT/ARCH_TURN_BUDGET_S 口径并存)。

回合总预算(ARCH_TURN_BUDGET_S)与轮次上限(max_rounds)属策略刻度,
分别在 turns/base.py 与 gears——不在本表重复。
"""
from __future__ import annotations

import os

# 名字 → (缺省秒, 说明)
_DEFAULTS: Dict[str, tuple] = {
    "llm_call": (300.0, "llm.sync/chat 单次调用上限(cognition.llm)"),
    "se_llm": (180.0, "SE 大脑 llm 通道(tagent_se)"),
    "kb_rpc": (10.0, "KB 网关 RPC 默认(kb_gateway)"),
    "kb_mcp_tools": (5.0, "KB MCP 工具目录(GET /v1/tools)"),
    "kb_mcp_call": (30.0, "mcp.call 工具执行"),
    "stream_idle": (60.0, "A 轴流式空闲判定(turns)"),
    "runner_snapshot": (8.0, "执行器面快照/探活(recover/boundary)"),
    "runner_steer": (15.0, "执行器面 steer(任务转向)"),
    "runner_finish": (30.0, "执行器面 finish(收尾/合并)"),
    "pump_ws_open": (3.0, "任务泵 ws 打开"),
    "git_push": (300.0, "git push -u origin"),
    "git_status": (10.0, "项目 git 状态采集"),
    "build_engine": (300.0, "cline 引擎构建"),
    "engine_inspect": (10.0, "cline 引擎探测/克隆检查"),
    "probe_ping": (2.0, "模型探活(cognition.llm 懒探测)"),
}


def _load() -> Dict[str, float]:
    out = {}
    for name, (default, _doc) in _DEFAULTS.items():
        try:
            out[name] = float(os.environ.get(f"TOPO_TIMEOUT_{name.upper()}",
                                             default))
        except (TypeError, ValueError):
            out[name] = float(default)
    return out


_TIMEOUTS = _load()


def get(name: str) -> float:
    """读登记超时(秒)。未登记名字 → KeyError(fail-fast, 禁止绕过单源)。"""
    return _TIMEOUTS[name]


def names() -> Dict[str, float]:
    """全部登记项(调试/设置页展示用)。"""
    return dict(_TIMEOUTS)
