"""Agent Target: Codex (OpenAI Codex)."""

import json
from pathlib import Path
from .base import AgentTarget


class CodexTarget(AgentTarget):
    id = "codex"
    name = "OpenAI Codex"

    def detect(self) -> bool:
        return bool(
            (Path.home() / ".codex" / "config.json").exists()
            or (Path.home() / ".openai" / "codex.json").exists()
        )

    def install(self, project_root: str | None = None, global_: bool = False) -> str | None:
        if global_ or project_root is None:
            config_path = Path.home() / ".codex" / "mcp.json"
        else:
            config_path = Path(project_root) / ".codex" / "mcp.json"

        config_path.parent.mkdir(parents=True, exist_ok=True)

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
            config_path = Path.home() / ".codex" / "mcp.json"
        else:
            config_path = Path(project_root) / ".codex" / "mcp.json"
        if not config_path.exists():
            return None
        config = json.loads(config_path.read_text())
        config.get("mcpServers", {}).pop("topocode", None)
        config_path.write_text(json.dumps(config, indent=2))
        return str(config_path)

    def describe_paths(self) -> list[str]:
        return [str(Path.home() / ".codex" / "mcp.json")]
