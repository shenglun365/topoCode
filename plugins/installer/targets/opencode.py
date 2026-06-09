"""Agent Target: OpenCode."""

import json
from pathlib import Path
from .base import AgentTarget


class OpenCodeTarget(AgentTarget):
    id = "opencode"
    name = "OpenCode"

    def detect(self) -> bool:
        return bool(
            (Path.home() / ".config" / "opencode" / "opencode.json").exists()
            or Path("opencode.json").exists()
        )

    def install(self, project_root: str | None = None, global_: bool = False) -> str | None:
        if global_ or project_root is None:
            config_dir = Path.home() / ".config" / "opencode"
            config_path = config_dir / "opencode.json"
        else:
            config_path = Path(project_root) / "opencode.json"

        config_dir = config_path.parent
        config_dir.mkdir(parents=True, exist_ok=True)

        config = {}
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
            except json.JSONDecodeError:
                config = {}

        mcp = config.setdefault("mcp", {})
        mcp["topocode"] = {
            "type": "local",
            "command": ["topocode", "serve"],
        }

        config_path.write_text(json.dumps(config, indent=2))
        return str(config_path)

    def uninstall(self, project_root: str | None = None, global_: bool = False) -> str | None:
        if global_ or project_root is None:
            config_path = Path.home() / ".config" / "opencode" / "opencode.json"
        else:
            config_path = Path(project_root) / "opencode.json"

        if not config_path.exists():
            return None

        config = json.loads(config_path.read_text())
        config.get("mcp", {}).pop("topocode", None)
        config_path.write_text(json.dumps(config, indent=2))
        return str(config_path)

    def describe_paths(self) -> list[str]:
        return [
            str(Path.home() / ".config" / "opencode" / "opencode.json"),
            str(Path("opencode.json").absolute()),
        ]
