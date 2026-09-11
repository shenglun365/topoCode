"""聊天流(tAgent 代码问答)：agentic_loop + KbGatewayLLMClient + KB/代码查询工具。

A7：替换原 opencode 直连聊天。用户问题 + 任务上下文 → agentic_loop 分析代码/KB → 回答。
与 tagent_extract/tagent_utgen 同组装模式(复用 _extraction_registry 代码查询工具，不改 tAgent profiles)。
KB/LLM 不可达或解析失败 → 返回 None(调用方降级回显用户消息)。
"""
from typing import Optional

from .tagent_se import KbGatewayLLMClient
from .tagent_extract import _extraction_registry

CHAT_SYSTEM = (
    "你是执行会话的编码工程师助手(执行/答疑双态)。"
    "用户的问题通常围绕本会话绑定需求要实现的代码：基于代码事实与知识库回答，"
    "可用工具查询源码、常量、调用关系、路由、符号。"
    "要求：回答简明、有依据；引用具体文件/符号时给出路径；不确定的地方明确说明，不要臆测。"
    "注意：实际的代码实施(开发/单测/编译)由用户通过「执行方案」触发独立作业完成，"
    "你负责答疑与上下文分析，不要承诺代为实施。"
)


async def _chat_async(llm, tools, messages, max_rounds: int, model: str) -> Optional[str]:
    from topocode_agent.core.loop.runner import agentic_loop
    result = await agentic_loop(llm, tools, messages,
                                max_turns=max_rounds + 1, model=model)
    content = (result.content or "").strip()
    return content or None


def chat_reply(*, question: str, root: Optional[str], project: Optional[str],
               task_context: str = "", model_id: str = "",
               max_rounds: int = 4) -> Optional[str]:
    """tAgent 代码问答：返回回答文本；KB/LLM 不可达或异常 → None。

    同步外壳 + asyncio.run(新事件循环)；调用方须经 asyncio.to_thread 运行
    (不能在运行中的事件循环里直接调用)。
    """
    import asyncio
    from .kb_gateway import get_gateway

    gateway = get_gateway()
    if gateway is None:
        return None
    llm = KbGatewayLLMClient(gateway, model_id=model_id or "")
    tools = _extraction_registry(root, project)
    if task_context:
        user = f"任务上下文:\n{task_context}\n\n用户问题: {question}"
    else:
        user = f"用户问题: {question}"
    messages = [{"role": "system", "content": CHAT_SYSTEM}, {"role": "user", "content": user}]
    try:
        return asyncio.run(_chat_async(llm, tools, messages, max_rounds, model_id or ""))
    except Exception:
        return None
