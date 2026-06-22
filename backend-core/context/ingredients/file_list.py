from typing import Any

from ..ingredient import ContextIngredient


class FileListIngredient(ContextIngredient):
    name = "file_list"

    def collect(self, ctx) -> list[str]:
        return ctx.rel_paths

    def format(self, data: list[str]) -> str:
        if not data:
            return ""
        return f"文件列表 ({len(data)}): {', '.join(data)}"
