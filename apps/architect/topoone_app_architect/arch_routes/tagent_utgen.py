"""单测生成（自主路径 · B1）：agentic_loop + KbGatewayLLMClient 分析 scope 生成单测草稿。

参照 tagent_extract 的组装模式（复用其工具注册表/序列化，不改 tAgent profiles）。
返回**草稿**(不直接落库)，由用户在 UI 确认后创建。KB/LLM 不可达或解析失败 → None。
"""
from typing import Optional

from .tagent_se import ArchitectToolAdapter, KbGatewayLLMClient
from .tagent_extract import _extraction_registry

GEN_SYSTEM = (
    "你是单元测试设计专家。给定一个测试范围(scope)，结合代码结构分析，"
    "提出应覆盖的单元测试。可用工具查询源码/常量/调用关系/路由/符号。"
    "分析完成后，最终只输出一个 JSON 对象(不要 markdown 代码块):\n"
    '{"tests":[{"name":"用例名","levels":["L2"],"scriptPath":"相对测试脚本路径","desc":"覆盖说明"}]}\n'
    "要求: 3~8 条; levels 取 L0~L5 组件层级; scriptPath 用 tests/ 下的相对路径; desc 简明。"
)

_LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")


async def _run_gen_async(llm, tools, messages, max_rounds: int, model: str) -> Optional[dict]:
    from topocode_agent.core.loop.runner import agentic_loop
    from topocode_agent.core.utils import extract_json_object

    result = await agentic_loop(llm, tools, messages,
                                max_turns=max_rounds + 1, model=model)
    content = result.content or ""
    output = extract_json_object(content)
    if not isinstance(output, dict) or not isinstance(output.get("tests"), list):
        return None
    tests = []
    for t in output.get("tests", []):
        if not isinstance(t, dict):
            continue
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        levels = [str(x) for x in (t.get("levels") or []) if str(x) in _LEVELS]
        tests.append({
            "name": name,
            "levels": levels,
            "scriptPath": str(t.get("scriptPath") or "").strip(),
            "desc": str(t.get("desc") or "").strip(),
        })
    return {"tests": tests}


def generate_unit_tests(*, scope: str, root: Optional[str], project: Optional[str],
                        model_id: str = "", max_rounds: int = 3) -> Optional[dict]:
    """生成单测草稿 {tests:[{name,levels,scriptPath,desc}]}。

    LLM/KB 不可达或解析失败 → None(调用方 502/降级)。同步外壳 + asyncio.run。
    """
    import asyncio
    from ..kb_gateway import get_gateway

    gateway = get_gateway()
    if gateway is None:
        return None
    llm = KbGatewayLLMClient(gateway, model_id=model_id or "")
    tools = _extraction_registry(root, project)
    messages = [
        {"role": "system", "content": GEN_SYSTEM},
        {"role": "user", "content": f"测试范围: {scope}\n请分析代码并生成单元测试草稿。"},
    ]
    try:
        return asyncio.run(
            _run_gen_async(llm, tools, messages, max_rounds, model_id or ""))
    except Exception:
        return None
