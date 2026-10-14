"""I5c — 语义资产提取接入 tAgent 上下文编译循环（方案 B）。

替换 asset_extract 的 run_tools_loop 为 tAgent `agentic_loop` + `ContextManager`：

- phase=`kb_analysis`（与 KB 组件分析同型：读代码数据→结构化产出，工件权重 .70）；
- 任务规格（file/kind/验收模板/输出契约）钉驻 Base 层，全程保留；
- 可达性豁免（字符串模式）：`set_task_files([file])` + `ReachabilityAnalyzer(kb=None)`，
  当前任务文件/底座路径 token/近 3 轮工具锚点不被 LRU 误删；
- 工具结果由 loop 自动入工作集（预算内编译注入，GC 治理），替代旧的手写 tool_feed；
- 结构化输出：提示词约束 JSON + 客户端 `extract_json_object` 解析
  （旧路径 outputSchema 由主后端解析，新路径客户端解析，解析失败走既有验收/修复/地板）。

与 chat/SE 用户指令场景的区分：作用域=每 (file×kind) 组一实例（隔离并发），
播种=任务规格钉驻+工具结果工作集，阶段=kb_analysis——同机制、不同配置。

提取统一走本 tAgent 路径（旧 run_tools_loop 双轨已取消，恒 tAgent）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from .tagent_se import ArchitectToolAdapter, KbGatewayLLMClient

logger = logging.getLogger(__name__)

# 提取循环可见的 5 个 asset.* 工具（asset_tools 已注册进 req_agent._ARCH_TOOLS；
# 点号名由 ArchitectToolAdapter 净化为下划线安全名，TextFallback 标记正则可解析）
EXTRACT_TOOLS = (
    "asset.read_source",
    "asset.query_constants",
    "asset.query_calls",
    "asset.query_routes",
    "asset.query_symbol",
)

# 参数 schema（供 LLM 生成 [TOOL_CALL: name] 参数；root/project 由适配器注入）
EXTRACT_TOOL_PARAMS = {
    "asset.read_source": {
        "file": {"type": "string", "description": "相对路径", "required": True},
        "symbol": {"type": "string", "description": "符号名", "required": True},
        "max_lines": {"type": "integer", "description": "最大行数(默认120)"},
    },
    "asset.query_constants": {
        "file": {"type": "string", "description": "相对路径", "required": True},
    },
    "asset.query_calls": {
        "file": {"type": "string", "description": "相对路径", "required": True},
        "symbol": {"type": "string", "description": "符号名", "required": True},
    },
    "asset.query_routes": {
        "file": {"type": "string", "description": "相对路径", "required": True},
    },
    "asset.query_symbol": {
        "file": {"type": "string", "description": "相对路径", "required": True},
        "symbol": {"type": "string", "description": "符号名", "required": True},
    },
}

# 上下文块预算（与 C3 KB 组件分析 CTX_BLOCK_MAX_CHARS 同预算：保守不挤占输出）
CTX_BLOCK_MAX_CHARS = 24000


def build_extraction_context(*, file_: str = "", kind: str = "",
                             task_spec: str = "",
                             max_chars: int = CTX_BLOCK_MAX_CHARS):
    """构建提取场景 ContextManager（每 file×kind 组一实例，天然隔离并发）。

    - Base：任务规格钉驻（pin_requirement，L2 需求层，任务未完成前禁止淘汰）；
    - 可达性：字符串模式（任务文件最高优先种子；kb=None 不做符号级扩展）；
    - 工具结果由 agentic_loop 的 observe_tool_result 自动入清单（L3 工件/WS）。
    """
    from topocode_agent.core.context import ContextManager
    from topocode_agent.core.context.reachability import ReachabilityAnalyzer

    cm = ContextManager(phase="kb_analysis", max_chars=max_chars,
                        reachability=ReachabilityAnalyzer(kb=None))
    if task_spec:
        cm.pin_requirement(task_spec)
    if file_:
        cm.set_task_files([file_])
    return cm


def _serialize_result(fn):
    """dict/list 工具结果 → JSON 文本（与旧 tool_result_text 口径一致）：
    1) LLM 可读（避免 Python repr）；
    2) agentic_loop 仅把 str 结果路由进上下文清单（observe_tool_result），
       参与预算编译、GC 治理与可达性锚点抽取。
    facts 机制不受影响（record_fact 在工具内部已按 dict 记录）。"""
    import inspect as _inspect
    sig = _inspect.signature(fn)

    def wrapped(*args, **kwargs):
        result = fn(*args, **kwargs)
        if isinstance(result, (dict, list)):
            if isinstance(result, dict) and "error" in result:
                return str(result.get("error"))
            return json.dumps(result, ensure_ascii=False, default=str)
        return result

    wrapped.__signature__ = sig  # 保留原签名（ArchitectToolAdapter._invoke 按签名注入 root/project）
    return wrapped


def _extraction_registry(root: Optional[str], project: Optional[str]):
    """提取工具注册表：5 个 asset.* 工具，同线程同步执行（thread-local facts 亲和）。"""
    from topocode_agent.core.tool.base import ToolRegistry
    from ..agent.tools import req_agent

    reg = ToolRegistry()
    for name in EXTRACT_TOOLS:
        entry = req_agent._ARCH_TOOLS.get(name)
        if not entry:
            continue
        reg.register(ArchitectToolAdapter(
            name=name,
            description=entry.get("description", ""),
            fn=_serialize_result(entry["handler"]),
            parameters=EXTRACT_TOOL_PARAMS.get(name),
            root=root, project=project,
            in_thread=False,
        ))
    return reg


async def _run_extraction_async(llm, tools, messages: list[dict], cm,
                                max_rounds: int, max_tokens: Optional[int],
                                model: str) -> dict:
    from topocode_agent.core.loop.runner import agentic_loop
    from topocode_agent.core.utils import extract_json_object

    # 底座层（钉驻任务规格）由调用方写入 system（agentic_loop 只注入非底座增量块）：
    # 底座在循环内不变（提取轮不再 pin/播种）→ 循环前编译一次并入 system 即可。
    base = cm.compile().system_base
    if base and base.strip():
        messages[0]["content"] = (messages[0].get("content") or "") + "\n\n" + base
    # max_rounds=工具轮上限（旧 run_tools_loop 语义：max_rounds 轮工具 + 1 次终调）；
    # agentic_loop 的末轮不执行工具 → max_turns = max_rounds + 1 才与旧路径等效。
    result = await agentic_loop(llm, tools, messages, context=cm,
                                max_turns=max_rounds + 1, max_tokens=max_tokens,
                                model=model)
    content = result.content or ""
    output = extract_json_object(content)
    if not isinstance(output, dict):
        output = None
    return {"content": content, "output": output,
            "stop_reason": getattr(result, "stop_reason", "")}


