from typing import Any, Optional


class ContextIngredient:
    """单一数据源：收集 + 格式化。
    
    每个子类负责从 DB/文件系统收集一种数据并格式化为 LLM-ready 文本。
    子类只需实现 collect() 和 format()。
    """
    name: str = ""

    def collect(self, ctx: "CollectContext") -> Optional[Any]:
        raise NotImplementedError

    def format(self, data: Any) -> str:
        raise NotImplementedError
