# parsers/languages/dependence_parser/python_dependence_parser.py
"""
Python 依赖提取器

实现 Python 语言的 import/from...import 依赖识别和提取逻辑。

支持的导入语法:
- import module
- import module as alias
- from module import name
- from module import name as alias
- from module import *
- from . import module (相对导入)
- from ..module import name (相对导入)

系统库判断:
- Python 标准库 (sys, os, json 等)
- 第三方库 (通过模块路径判断)
"""
from typing import Dict, Any, Optional, List, Tuple, Set
import os
from .extractor_factory import DependencyExtractor, register_dependency_extractor


@register_dependency_extractor('python')
class PythonImportExtractor(DependencyExtractor):
    """
    Python import 依赖提取器
    
    支持识别:
    - 绝对导入：import os, from json import loads
    - 相对导入：from . import module, from ..utils import func
    - 星号导入：from module import *
    """
    
    # Python 依赖相关的 AST 节点类型
    DEPENDENCY_NODE_TYPES = [
        "import_statement",
        "import_from_statement",
        "import_clause",
    ]
    
    # Python 标准库模块列表 (常用)
    STANDARD_LIBRARY_MODULES = {
        # 内置模块
        'sys', 'os', 'io', 'time', 'datetime', 'math', 'random',
        're', 'string', 'collections', 'itertools', 'functools',
        'operator', 'copy', 'pprint', 'reprlib', 'enum', 'graphlib',
        
        # 文件和目录访问
        'pathlib', 'glob', 'fnmatch', 'tempfile', 'shutil', 'fileinput',
        
        # 数据序列化
        'json', 'csv', 'xml', 'html', 'pickle', 'shelve', 'marshal',
        
        # 网络和 IPC
        'socket', 'ssl', 'select', 'asyncio', 'http', 'urllib', 'ftplib',
        
        # 并发执行
        'threading', 'multiprocessing', 'concurrent', 'queue', 'subprocess',
        
        # 测试和调试
        'unittest', 'doctest', 'logging', 'warnings', 'traceback',
        
        # 包管理
        'importlib', 'pkgutil', 'modulefinder',
        
        # 其他常用
        'typing', 'abc', 'contextlib', 'dataclasses', 'decimal',
        'hashlib', 'hmac', 'secrets', 'zlib', 'gzip', 'bz2',
    }
    
    def get_required_node_types(self) -> List[str]:
        """获取依赖相关的 AST 节点类型"""
        return self.DEPENDENCY_NODE_TYPES

    def extract_dependencies(self, nodes: List[Dict]) -> Tuple[List[Dict], Set[str]]:
        """
        从 import 节点提取依赖关系
        
        Args:
            nodes: import_statement 或 import_from_statement 节点列表
            
        Returns:
            (dependencies, system_targets)
            - dependencies: 依赖列表
            - system_targets: 系统库/第三方库目标集合
        """
        dependencies = []
        system_targets = set()
        
        for node in nodes:
            from_file_id = node.get("file_id")
            node_type = node.get("type")
            refs = node.get("refs", [])
            
            if node_type == "import_statement":
                # 处理 import module 语法
                deps, sys_targets = self._extract_import_statement(from_file_id, refs)
            elif node_type == "import_from_statement":
                # 处理 from module import name 语法
                deps, sys_targets = self._extract_import_from_statement(from_file_id, refs, node)
            else:
                continue
            
            dependencies.extend(deps)
            system_targets.update(sys_targets)
        
        return dependencies, system_targets

    def _extract_import_statement(
        self,
        from_file_id: int,
        refs: List[str]
    ) -> Tuple[List[Dict], Set[str]]:
        """
        提取 import statement 的依赖
        
        例如：import os, import numpy as np
        """
        dependencies = []
        system_targets = set()
        
        for ref in refs:
            if not ref:
                continue
            
            # 提取模块名 (处理 import a.b.c 的情况)
            module_name = ref.split('.')[0]
            full_module_path = ref
            
            # 判断是否为系统库
            is_system = self._is_system_module(module_name)
            
            dependencies.append({
                "from_file_id": from_file_id,
                "target": full_module_path,
                "is_angle_bracket": False,  # Python 没有 <> 语法
                "is_relative": False,
                "level": 0,  # 相对导入层级
            })
            
            if is_system:
                system_targets.add(full_module_path)
        
        return dependencies, system_targets

    def _extract_import_from_statement(
        self,
        from_file_id: int,
        refs: List[str],
        node: Dict
    ) -> Tuple[List[Dict], Set[str]]:
        """
        提取 import from statement 的依赖
        
        例如：from os import path, from .utils import func
        """
        dependencies = []
        system_targets = set()
        
        # 获取模块名
        module_name = node.get("module_name", "")
        if not module_name and refs:
            # 从 refs 中提取模块名 (第一个通常是模块名)
            module_name = refs[0] if len(refs) > 0 else ""
        
        # 检查是否是相对导入
        level = node.get("level", 0)  # 相对导入层级
        is_relative = level > 0
        
        if module_name:
            # 判断是否为系统库
            base_module = module_name.split('.')[0]
            is_system = self._is_system_module(base_module) and not is_relative
            
            dependencies.append({
                "from_file_id": from_file_id,
                "target": module_name,
                "is_angle_bracket": False,
                "is_relative": is_relative,
                "level": level,
            })
            
            if is_system and not is_relative:
                system_targets.add(module_name)
        
        return dependencies, system_targets

    def _is_system_module(self, module_name: str) -> bool:
        """
        判断模块是否为标准库
        
        Args:
            module_name: 模块名
            
        Returns:
            True 如果是标准库
        """
        # 检查是否在标准库列表中
        if module_name in self.STANDARD_LIBRARY_MODULES:
            return True
        
        # 常见的第三方库前缀 (不是系统库)
        third_party_prefixes = [
            'numpy', 'pandas', 'scipy', 'sklearn', 'tensorflow', 'torch',
            'flask', 'django', 'fastapi', 'requests', 'aiohttp',
            'pytest', 'setuptools', 'pip',
        ]
        
        for prefix in third_party_prefixes:
            if module_name.startswith(prefix):
                return False
        
        # 默认判断：如果没有明确的第三方标记，且名称较短，可能是标准库
        # 这是一个简化的判断，实际可能需要更复杂的逻辑
        return len(module_name) <= 15 and module_name.isidentifier()

    def is_system_include(self, target: str) -> bool:
        """
        判断是否为系统库引用
        
        Args:
            target: 依赖目标字符串
            
        Returns:
            True 如果是系统库
        """
        module_name = target.split('.')[0]
        return self._is_system_module(module_name)

    def is_internal_dependency(
        self,
        target: str,
        project_files_by_path: Dict[str, List[int]]
    ) -> Tuple[bool, Optional[int]]:
        """
        判断依赖是否指向项目内部文件
        
        Python 规则:
        - 将模块路径转换为文件路径进行匹配
        - 支持包 (目录) 和模块 (文件) 匹配
        
        Args:
            target: 模块路径 (如 mypackage.mymodule)
            project_files_by_path: 项目文件路径映射 {path: [file_id]}
            
        Returns:
            (is_internal: bool, matched_file_id: int or None)
        """
        # 将模块路径转换为可能的文件路径
        module_parts = target.split('.')
        
        # 可能的路径模式
        possible_paths = [
            '/'.join(module_parts) + '.py',      # mypackage/mymodule.py
            '/'.join(module_parts) + '/__init__.py',  # mypackage/__init__.py
        ]
        
        # 也检查 basename 匹配
        module_name = module_parts[-1]
        
        for path in possible_paths:
            if path in project_files_by_path:
                return True, project_files_by_path[path][0]
        
        # basename 匹配
        for file_path, file_ids in project_files_by_path.items():
            basename = os.path.basename(file_path)
            if basename == module_name + '.py' or basename == '__init__.py':
                return True, file_ids[0]
        
        return False, None
