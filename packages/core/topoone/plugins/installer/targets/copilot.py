"""Agent Target: GitHub Copilot."""

import json
from pathlib import Path
from .base import AgentTarget


class CopilotTarget(AgentTarget):
    id = "copilot"
    name = "GitHub Copilot"

    def detect(self) -> bool:
        return bool((Path.home() / ".github" / "copilot" / "mcp.json").exists()
                    or (Path.home() / ".vscode" / "mcp.json").exists())

    def install(self, project_root: str | None = None, global_: bool = False) -> str | None:
        config_path = Path.home() / ".github" / "copilot" / "mcp.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)

        config = {}
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
            except json.JSONDecodeError:
                config = {}
        config.setdefault("mcpServers", {})["topocode"] = self._mcp_config()
        config_path.write_text(json.dumps(config, indent=2))
        return str(config_path)

    def uninstall(self, project_root: str | None = None, global_: bool = False) -> str | None:
        config_path = Path.home() / ".github" / "copilot" / "mcp.json"
        if not config_path.exists():
            return None
        config = json.loads(config_path.read_text())
        config.get("mcpServers", {}).pop("topocode", None)
        config_path.write_text(json.dumps(config, indent=2))
        return str(config_path)

    def describe_paths(self) -> list[str]:
        return [str(Path.home() / ".github" / "copilot" / "mcp.json")]
