"""Agent Target Registry."""

from .base import AgentTarget
from .claude import ClaudeTarget
from .opencode import OpenCodeTarget
from .codex import CodexTarget
from .cursor import CursorTarget
from .copilot import CopilotTarget
from .gemini import GeminiTarget
from .windsurf import WindsurfTarget


TARGETS: dict[str, AgentTarget] = {
    t.id: t
    for t in [
        ClaudeTarget(),
        OpenCodeTarget(),
        CodexTarget(),
        CursorTarget(),
        CopilotTarget(),
        GeminiTarget(),
        WindsurfTarget(),
    ]
}


def detect_all() -> list[str]:
    """返回所有已检测到的 agent ID 列表。"""
    return [tid for tid, t in TARGETS.items() if t.detect()]


def get_target(agent_id: str) -> AgentTarget | None:
    return TARGETS.get(agent_id)
