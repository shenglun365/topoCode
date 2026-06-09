"""Agent Target: Claude (claude.ai / Claude Code)."""

import json
import os
from pathlib import Path
from .base import AgentTarget


class ClaudeTarget(AgentTarget):
    id = "claude"
    name = "Claude Code"

    def detect(self) -> bool:
        paths = [
            Path.home() / ".claude" / "claude_desktop_config.json",
            Path.home() / ".claude.json",
        ]
        for p in paths:
            if p.exists():
                return True
        return bool(os.environ.get("CLAUDE_CONFIG_PATH"))

    def install(self, project_root: str | None = None, global_: bool = False) -> str | None:
        # Claude uses two possible config locations
        if global_ or project_root is None:
            config_dir = Path.home() / ".claude"
            config_path = config_dir / "mcp.json"
        else:
            config_dir = Path(project_root) / ".claude"
            config_path = config_dir / "mcp.json"

        config_dir.mkdir(parents=True, exist_ok=True)

        config = {}
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
            except json.JSONDecodeError:
                config = {}

        mcp_servers = config.setdefault("mcpServers", {})
        mcp_servers["topocode"] = self._mcp_config()

        config_path.write_text(json.dumps(config, indent=2))
        return str(config_path)

    def uninstall(self, project_root: str | None = None, global_: bool = False) -> str | None:
        if global_ or project_root is None:
            config_path = Path.home() / ".claude" / "mcp.json"
        else:
            config_path = Path(project_root) / ".claude" / "mcp.json"

        if not config_path.exists():
            return None

        config = json.loads(config_path.read_text())
        config.get("mcpServers", {}).pop("topocode", None)
        config_path.write_text(json.dumps(config, indent=2))
        return str(config_path)

    def describe_paths(self) -> list[str]:
        return [
            str(Path.home() / ".claude" / "mcp.json"),
        ]
