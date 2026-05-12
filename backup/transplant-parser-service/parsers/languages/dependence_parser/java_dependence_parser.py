# parsers/languages/dependence_parser/java_dependence_parser.py
"""
Java 依赖提取器

实现 Java 语言的 import/package 依赖识别和提取逻辑。

支持的导入语法:
- import package.Class
- import package.* (通配符导入)
- import static package.Class.method (静态导入)
- import static package.Class.* (静态通配符)

系统库判断:
- Java 标准库 (java.*, javax.* 等)
- 第三方库 (通过包名判断)
"""
from typing import Dict, Any, Optional, List, Tuple, Set
import os
from .extractor_factory import DependencyExtractor, register_dependency_extractor


@register_dependency_extractor('java')
class JavaImportExtractor(DependencyExtractor):
    """
    Java import 依赖提取器
    
    支持识别:
    - 普通导入：import java.util.List;
    - 通配符导入：import java.util.*;
    - 静态导入：import static java.lang.Math.PI;
    - 静态通配符：import static java.lang.Math.*;
    """
    
    # Java 依赖相关的 AST 节点类型
    DEPENDENCY_NODE_TYPES = [
        "import_declaration",
        "import_statement",
    ]
    
    # Java 标准库包列表
    STANDARD_LIBRARY_PACKAGES = {
        # 核心库
        'java.lang', 'java.util', 'java.io', 'java.nio', 'java.net',
        'java.time', 'java.math', 'java.text', 'java.applet',
        
        # 并发
        'java.util.concurrent', 'java.util.concurrent.atomic',
        'java.util.concurrent.locks',
        
        # 集合
        'java.util.stream', 'java.util.function', 'java.util.regex',
        
        # IO/NIO
        'java.nio.file', 'java.nio.channels', 'java.nio.charset',
        
        # 网络
        'java.net.http', 'javax.net', 'javax.net.ssl',
        
        # 数据库
        'java.sql', 'javax.sql',
        
        # XML/JSON
        'javax.xml', 'org.w3c.dom', 'org.xml.sax',
        
        # 安全
        'java.security', 'javax.crypto', 'javax.security',
        
        # 图形界面
        'java.awt', 'javax.swing', 'java.beans',
        
        # 反射/注解
        'java.lang.reflect', 'java.lang.annotation',
        
        # 其他
        'java.rmi', 'java.scripting', 'javax.annotation',
    }
    
    def get_required_node_types(self) -> List[str]:
        """获取依赖相关的 AST 节点类型"""
        return self.DEPENDENCY_NODE_TYPES

    def extract_dependencies(self, nodes: List[Dict]) -> Tuple[List[Dict], Set[str]]:
        """
        从 import 节点提取依赖关系
        
        Args:
            nodes: import_declaration 节点列表
            
        Returns:
            (dependencies, system_targets)
        """
        dependencies = []
        system_targets = set()
        
        for node in nodes:
            from_file_id = node.get("file_id")
            refs = node.get("refs", [])
            is_static = node.get("is_static", False)
            is_wildcard = node.get("is_wildcard", False)
            
            for ref in refs:
                if not ref:
                    continue
                
                # 判断是否为系统库
                is_system = self._is_system_package(ref)
                
                dependencies.append({
                    "from_file_id": from_file_id,
                    "target": ref,
                    "is_angle_bracket": False,
                    "is_static": is_static,
                    "is_wildcard": is_wildcard,
                })
                
                if is_system:
                    system_targets.add(ref)
        
        return dependencies, system_targets

    def _is_system_package(self, package_path: str) -> bool:
        """
        判断包是否为标准库
        
        Args:
            package_path: 包路径 (如 java.util.List)
            
        Returns:
            True 如果是标准库
        """
        # 提取包名 (去掉类名)
        parts = package_path.split('.')
        
        # 检查顶级包
        if len(parts) > 0:
            top_package = parts[0]
            
            # java.* 和 javax.* 是标准库
            if top_package in ('java', 'javax', 'org'):
                # 进一步检查完整包路径
                for std_pkg in self.STANDARD_LIBRARY_PACKAGES:
                    if package_path.startswith(std_pkg):
                        return True
                
                # 如果是 java.* 或 javax.* 的子包，默认认为是标准库
                if top_package in ('java', 'javax'):
                    return True
        
        return False

    def is_system_include(self, target: str) -> bool:
        """判断是否为系统库引用"""
        return self._is_system_package(target)

    def is_internal_dependency(
        self,
        target: str,
        project_files_by_basename: Dict[str, List[int]]  # 参数名与基类保持一致
    ) -> Tuple[bool, Optional[int]]:
        """
        判断依赖是否指向项目内部文件

        Java 规则:
        - 将包路径转换为文件路径进行匹配
        - 支持类文件和包目录匹配

        Args:
            target: 包/类路径 (如 com.example.MyClass)
            project_files_by_basename: 项目文件 basename 映射

        Returns:
            (is_internal, matched_file_id)
        """
        # 将包路径转换为可能的文件路径
        package_parts = target.split('.')

        # 可能的路径模式
        possible_paths = [
            '/'.join(package_parts) + '.java',  # com/example/MyClass.java
            '/'.join(package_parts) + '/package-info.java',
        ]

        # 检查可能的路径
        for path in possible_paths:
            if path in project_files_by_basename:
                return True, project_files_by_basename[path][0]

        # 也检查 basename 匹配
        class_name = package_parts[-1]
        for file_path, file_ids in project_files_by_basename.items():
            basename = os.path.basename(file_path)
            if basename == class_name + '.java':
                return True, file_ids[0]

        return False, None
