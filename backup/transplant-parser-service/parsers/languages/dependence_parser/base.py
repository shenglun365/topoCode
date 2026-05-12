# parsers/languages/dependence_parser/base.py

import os
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Set, Tuple, Optional

class DependencyExtractor(ABC):
    """
    抽象基类：定义依赖提取接口
    """

    @abstractmethod
    def get_required_node_types(self) -> List[str]:
        pass

    @abstractmethod
    def extract_dependencies(self, nodes: List[Dict]) -> Tuple[List[Dict], Set[str]]:
        pass

    @abstractmethod
    def is_system_include(self, target: str) -> bool:
        pass

    # === 新增：用于语言自定义 internal 判断（默认回退到 basename 匹配）===
    def is_internal_dependency(
        self,
        target: str,
        project_files_by_basename: Dict[str, List[int]]
    ) -> Tuple[bool, Optional[int]]:
        """
        判断该依赖是否指向项目内部文件。
        默认实现：按 basename 匹配（适用于 C/C++）。
        子类可重写以支持其他语言（如 Python 按模块路径）。
        
        返回: (is_internal: bool, matched_file_id: int or None)
        """
        basename = os.path.basename(target)
        matched_ids = project_files_by_basename.get(basename, [])
        if matched_ids:
            return True, matched_ids[0]  # 取第一个匹配
        return False, None