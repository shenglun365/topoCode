"""Path validation — prevent directory traversal attacks."""

from pathlib import Path
from typing import Optional


class PathValidator:
    """Validate file paths are within the project root directory."""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()

    def validate(self, file_path: str) -> Optional[str]:
        """Validate and resolve a file path.

        Args:
            file_path: Absolute or project-relative file path.

        Returns:
            Resolved absolute path if valid, None if outside project root.
        """
        p = Path(file_path)
        if not p.is_absolute():
            p = self.project_root / p
        resolved = p.resolve()
        try:
            resolved.relative_to(self.project_root)
            return str(resolved)
        except ValueError:
            return None

    def assert_valid(self, file_path: str) -> str:
        """Validate and return resolved path, or raise ValueError."""
        resolved = self.validate(file_path)
        if resolved is None:
            raise ValueError(
                f"Access denied: {file_path} is outside project root "
                f"({self.project_root})"
            )
        return resolved
