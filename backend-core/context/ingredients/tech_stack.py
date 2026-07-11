import json
import os
from typing import Any

from ..ingredient import ContextIngredient


class TechStackIngredient(ContextIngredient):
    """Extract tech stack from project build files."""
    name = "tech_stack"

    def collect(self, ctx) -> list[str]:
        root = ctx.project_root
        if not root:
            return []
        lines = []
        # package.json
        pkg = os.path.join(root, "package.json")
        if os.path.isfile(pkg):
            try:
                with open(pkg) as f:
                    data = json.load(f)
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                top = sorted(deps.items(), key=lambda x: -len(x[0]))[:20]
                lines.append("• Node.js: " + ", ".join(
                    f"{k}" for k, v in top
                ))
            except Exception:
                pass
        # Cargo.toml
        cargo = os.path.join(root, "Cargo.toml")
        if os.path.isfile(cargo):
            lines.append("• Rust / Cargo")
        # pom.xml
        if os.path.isfile(os.path.join(root, "pom.xml")):
            lines.append("• Java / Maven")
        # go.mod
        if os.path.isfile(os.path.join(root, "go.mod")):
            lines.append("• Go module")
        # requirements.txt / pyproject.toml
        if os.path.isfile(os.path.join(root, "requirements.txt")):
            lines.append("• Python (requirements.txt)")
        if os.path.isfile(os.path.join(root, "pyproject.toml")):
            lines.append("• Python (pyproject.toml)")
        return lines

    def format(self, data: list[str]) -> str:
        if not data:
            return ""
        return "## Tech Stack\n" + "\n".join(data)
