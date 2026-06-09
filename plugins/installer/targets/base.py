"""AgentTarget 抽象基类。

每个 AI coding agent 作为一个 target 实现此接口。
"""

from abc import ABC, abstractmethod
from pathlib import Path


class AgentTarget(ABC):
    """单个 AI coding agent 的安装目标。"""

    id: str          # "claude", "opencode", "codex", ...
    name: str        # 显示名 "Claude Code"

    def __init__(self):
        self._topocode_path = "topocode"

    @abstractmethod
    def detect(self) -> bool:
        """检测 agent 是否已安装。
        
        Returns:
            True 如果检测到 agent 配置文件或安装目录存在
        """
        ...

    @abstractmethod
    def install(self, project_root: str | None = None, global_: bool = False) -> str | None:
        """写入 MCP 配置到 agent 的配置文件。

        Args:
            project_root: 项目根目录（None = 全局安装）
            global_: 是否全局安装

        Returns:
            写入的配置文件路径，或 None（如果未找到配置位置）
        """
        ...

    @abstractmethod
    def uninstall(self, project_root: str | None = None, global_: bool = False) -> str | None:
        """移除 MCP 配置。返回被修改的配置文件路径。"""
        ...

    def describe_paths(self) -> list[str]:
        """返回可能的配置文件路径列表（用于调试）。"""
        return []

    def _mcp_config(self) -> dict:
        """生成标准 MCP server 配置。"""
        return {
            "command": self._topocode_path,
            "args": ["serve"],
        }
