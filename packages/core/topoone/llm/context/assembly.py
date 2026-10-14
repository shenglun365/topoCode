import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .ingredient import ContextIngredient


@dataclass
class CollectContext:
    """数据收集上下文 — 贯穿所有 ingredient 共享的信息。"""
    db: Any                                              # project_db
    task_id: str
    project_root: str

    # 目标对象
    comm_id: str = ""                                    # 社区 ID（组件/架构分析用）
    file_paths: set = field(default_factory=set)         # 相关文件路径

    # 全局预加载缓存（避免重复查询）
    fp_map: dict = field(default_factory=dict)           # file_path → [symbols]
    edge_list: list = field(default_factory=list)        # 边关系列表
    all_fp_map: dict = field(default_factory=dict)       # 全局文件→符号映射（架构分析用）
    existing_results: dict = field(default_factory=dict) # comm_id → {name, summary}

    # 单文件摘要用
    file_path: str = ""
    # 社区元数据（由调用方传入，供 ingredient 消费）
    _comm_meta: dict = field(default_factory=dict)

    @property
    def rel_paths(self) -> list[str]:
        return sorted(
            os.path.relpath(fp, self.project_root) if self.project_root and os.path.isabs(fp) else fp
            for fp in self.file_paths
        )

    def resolve_path(self, fp: str) -> str:
        return os.path.relpath(fp, self.project_root) if self.project_root and os.path.isabs(fp) else fp


class ContextAssembler:
    """按 recipe 组合 ingredient，产出最终 LLM 上下文文本。"""

    def __init__(self):
        self._ingredients: dict[str, ContextIngredient] = {}

    def register(self, ing: ContextIngredient):
        self._ingredients[ing.name] = ing

    def assemble(self, recipe: list[str], ctx: CollectContext) -> str:
        parts = []
        for name in recipe:
            ing = self._ingredients.get(name)
            if ing is None:
                continue
            try:
                data = ing.collect(ctx)
                text = ing.format(data)
                if text:
                    parts.append(text)
            except Exception:
                pass
        return "\n".join(parts)
