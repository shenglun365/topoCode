"""SkillExecutor — 多步 Tool 编排引擎。

将多个独立的 MCP Tool 调用组合成复合 Skill，
支持中间结果传递、Token Budget 控制和每步后处理。
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .dispatcher import ToolDispatcher
from .result_compressor import compress_result, limit_top_5, filter_by_range

logger = logging.getLogger(__name__)

POST_PROCESSORS: dict[str, Callable[[dict, int], dict]] = {
    "limit_top_5": lambda data, _: limit_top_5(data),
    "filter_by_range": lambda data, _: filter_by_range(data),
}


@dataclass
class SkillStepDef:
    name: str
    fn: Callable[[dict], dict]
    post_process: Optional[str] = None


@dataclass
class SkillDefinition:
    name: str
    description: str
    steps: list[SkillStepDef] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    max_tokens: int = 8000
    timeout_ms: int = 30000


class SkillExecutor:
    def __init__(self, dispatcher: ToolDispatcher):
        self._dispatcher = dispatcher
        self._skills: dict[str, SkillDefinition] = {}

    def register(self, skill: SkillDefinition):
        self._skills[skill.name] = skill

    def get_definition(self, name: str) -> Optional[SkillDefinition]:
        return self._skills.get(name)

    def list_skills(self) -> list[dict]:
        return [
            {
                "name": name,
                "description": s.description,
                "input_schema": s.input_schema,
            }
            for name, s in self._skills.items()
        ]

    async def execute(self, skill_name: str, arguments: dict) -> dict:
        skill = self._skills.get(skill_name)
        if not skill:
            return {"error": f"Unknown skill: {skill_name}"}

        logger.info("Executing skill %s with args=%s", skill_name, arguments)
        ctx: dict[str, Any] = {"arguments": arguments, "results": []}

        for i, step in enumerate(skill.steps):
            step_input = self._build_step_input(step.fn, ctx)
            raw = step.fn(step_input)
            if step.post_process and step.post_process in POST_PROCESSORS:
                raw = POST_PROCESSORS[step.post_process](raw, skill.max_tokens)
            ctx["results"].append(raw)

        merged = self._merge_results(ctx["results"], skill.max_tokens)
        return {"skill": skill_name, "steps": len(skill.steps), "result": merged}

    def _build_step_input(self, step: Callable, ctx: dict) -> dict:
        combined = dict(ctx["arguments"])
        if ctx["results"]:
            combined["_intermediate"] = ctx["results"][-1]
        return combined

    def _merge_results(self, results: list[dict], max_tokens: int) -> dict:
        merged: dict[str, Any] = {}
        est_tokens = 0
        for r in results:
            for k, v in r.items():
                if k in merged:
                    continue
                compressed = compress_result(v if isinstance(v, dict) else {"_value": v}, max_items=5)
                if "_value" in compressed:
                    v = compressed["_value"]
                else:
                    v = compressed
                merged[k] = v
                est_tokens += self._estimate_tokens(v)
                if est_tokens > max_tokens:
                    merged["_truncated"] = True
                    return merged
        return merged

    def _estimate_tokens(self, value: Any) -> int:
        text = str(value)
        return len(text) // 4
