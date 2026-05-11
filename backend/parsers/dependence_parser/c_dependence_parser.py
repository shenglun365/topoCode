# parsers/languages/dependence_parser/c_dependence_parser.py
"""
C/C++ 依赖提取器

实现 C/C++ 语言的 #include 依赖识别和提取逻辑。
"""
from typing import Dict, Any, Optional, List, Tuple, Set
import os
from .extractor_factory import DependencyExtractor, register_dependency_extractor


@register_dependency_extractor('c')
@register_dependency_extractor('cpp')
class CIncludeExtractor(DependencyExtractor):
    """
    C/C++ 的 #include 依赖提取器

    支持识别:
    - 系统库引用：#include <stdio.h>
    - 本地头文件：#include "myheader.h"
    - 相对路径：#include "../common/utils.h"
    """

    # C/C++ 依赖相关的 AST 节点类型
    DEPENDENCY_NODE_TYPES = ["preproc_include"]
    
    # 常见系统库名称（用于判断是否为系统库）
    SYSTEM_LIBS = {
        'stdio.h', 'stdlib.h', 'string.h', 'strings.h',
        'unistd.h', 'fcntl.h', 'errno.h', 'ctype.h',
        'time.h', 'sys/types.h', 'sys/stat.h',
        'inttypes.h', 'stdint.h', 'stdbool.h',
        'malloc.h', 'memory.h', 'pthread.h',
    }

    def get_required_node_types(self) -> List[str]:
        """获取依赖相关的 AST 节点类型"""
        return self.DEPENDENCY_NODE_TYPES

    def extract_dependencies(self, nodes: List[Dict]) -> Tuple[List[Dict], Set[str]]:
        """
        从 #include 节点提取依赖关系

        Args:
            nodes: preproc_include 节点列表

        Returns:
            (dependencies, system_targets)
            - dependencies: 依赖列表
            - system_targets: 系统库目标集合（这里返回空集，由主流程判断）
        """
        dependencies = []

        for node in nodes:
            from_file_id = node["file_id"]
            refs = node.get("refs", [])

            for inc in refs:
                inc = inc.strip()

                # 跳过空引用
                if not inc:
                    continue

                # refs 中的值已经是清理过引号/尖括号的文件名
                # 判断是系统库（含/）还是本地头文件
                is_angle_bracket = '/' in inc or inc in self.SYSTEM_LIBS
                
                dependencies.append({
                    "from_file_id": from_file_id,
                    "target": inc,
                    "is_angle_bracket": is_angle_bracket
                })

        # system_includes 先返回空集，后续由主流程根据 resolve 结果收集
        return dependencies, set()

    def is_system_include(self, target: str) -> bool:
        """
        判断是否为系统库引用（已废弃）
        
        C 语言规则：
        - 标准库路径：/usr/include, /usr/local/include 等
        - 常见系统库前缀：stdio, stdlib, string, unistd 等
        """
        # 常见系统库路径前缀
        system_paths = [
            '/usr/include',
            '/usr/local/include',
            '/opt/',
        ]
        
        # 常见系统库名称
        system_libs = {
            'stdio.h', 'stdlib.h', 'string.h', 'strings.h',
            'unistd.h', 'fcntl.h', 'errno.h', 'ctype.h',
            'time.h', 'sys/types.h', 'sys/stat.h',
            'inttypes.h', 'stdint.h', 'stdbool.h',
            'malloc.h', 'memory.h', 'pthread.h',
        }
        
        # 检查是否为系统库
        if target in system_libs:
            return True
        
        # 检查路径前缀
        for prefix in system_paths:
            if target.startswith(prefix):
                return True
        
        return False

    def is_internal_dependency(
        self,
        target: str,
        project_files_by_basename: Dict[str, List[int]]
    ) -> Tuple[bool, Optional[int]]:
        """
        判断依赖是否指向项目内部文件
        
        C 语言规则：
        - 只要项目中有同名文件（无论用 "..." 或 <...>），就是 internal
        - 支持相对路径解析
        """
        # 提取 basename 进行匹配
        basename = os.path.basename(target)
        matched_ids = project_files_by_basename.get(basename, [])
        
        if matched_ids:
            return True, matched_ids[0]
        
        return False, None
    
    def resolve_relative_path(
        self,
        target: str,
        from_file_path: str,
        project_files_by_path: Dict[str, int]
    ) -> Optional[int]:
        """
        解析相对路径依赖
        
        Args:
            target: 依赖目标（如 "../common/utils.h"）
            from_file_path: 源文件路径
            project_files_by_path: 项目文件路径映射
            
        Returns:
            匹配的文件 ID，如果找不到则返回 None
        """
        # 计算解析后的路径
        from_dir = os.path.dirname(from_file_path)
        resolved_path = os.path.normpath(os.path.join(from_dir, target))
        
        # 尝试匹配
        if resolved_path in project_files_by_path:
            return project_files_by_path[resolved_path]
        
        # 尝试 basename 匹配（回退策略）
        basename = os.path.basename(target)
        for path, file_id in project_files_by_path.items():
            if os.path.basename(path) == basename:
                return file_id
        
        return None