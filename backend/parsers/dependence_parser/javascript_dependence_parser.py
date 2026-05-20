# parsers/languages/dependence_parser/javascript_dependence_parser.py
"""
JavaScript 依赖提取器

实现 JavaScript 语言的 import/require 依赖识别和提取逻辑。

支持的导入语法:
- import x from 'module' (ES6)
- import { x, y } from 'module' (ES6 命名导入)
- import * as x from 'module' (ES6 命名空间导入)
- require('module') (CommonJS)
- require.resolve('module')
- import('module') (动态导入)
- export ... from 'module' (重新导出)

系统库判断:
- Node.js 内置模块 (fs, path, http 等)
- npm 第三方包
- 相对路径本地模块
"""
from typing import Dict, Any, Optional, List, Tuple, Set
import os
from .extractor_factory import DependencyExtractor, register_dependency_extractor


@register_dependency_extractor('javascript')
@register_dependency_extractor('typescript')
class JavaScriptRequireExtractor(DependencyExtractor):
    """
    JavaScript/TypeScript import/require 依赖提取器
    
    支持识别:
    - ES6 导入：import x from 'module'
    - CommonJS 导入：require('module')
    - 动态导入：import('module')
    - 重新导出：export { x } from 'module'
    """
    
    # JavaScript 依赖相关的 AST 节点类型
    # 注意：require() 和 import() 在 tree-sitter 中被解析为 call_expression
    # 需要在 extract_dependencies 中特殊处理
    DEPENDENCY_NODE_TYPES = [
        "import_statement",
        "import_clause",
        "named_imports",
        "import_specifier",
        "export_statement",
        "call_expression",  # 用于识别 require() 和动态 import()
    ]
    
    # Node.js 内置模块列表
    BUILTIN_MODULES = {
        # 核心模块
        'fs', 'path', 'http', 'https', 'net', 'tls', 'os', 'events',
        'stream', 'util', 'buffer', 'querystring', 'url', 'crypto',
        'zlib', 'readline', 'repl', 'vm', 'child_process', 'cluster',
        'dgram', 'dns', 'domain', 'assert', 'tty', 'v8', 'process',
        'console', 'timers', 'module', 'worker_threads', 'perf_hooks',
        'async_hooks', 'trace_events', 'inspector', 'wasi',
        
        # 较新的模块
        'node:fs', 'node:path', 'node:http', 'node:https',
    }
    
    def get_required_node_types(self) -> List[str]:
        """获取依赖相关的 AST 节点类型"""
        return self.DEPENDENCY_NODE_TYPES

    def extract_dependencies(self, nodes: List[Dict]) -> Tuple[List[Dict], Set[str]]:
        """
        从 import/require 节点提取依赖关系

        Args:
            nodes: import_statement, call_expression (require/import) 节点列表

        Returns:
            (dependencies, system_targets)
        """
        dependencies = []
        system_targets = set()

        for node in nodes:
            from_file_id = node.get("file_id")
            node_type = node.get("type")
            refs = node.get("refs", [])
            name = node.get("name")  # 获取 name 字段（字符串字面量）

            # 处理 call_expression (require() 和动态 import())
            if node_type == "call_expression":
                # 检查是否是 require() 或 import() 调用
                if refs and refs[0] in ['require', 'import']:
                    # 从 name 字段获取模块路径（AST 解析时已提取）
                    if name:
                        self._add_dependency(
                            dependencies, system_targets,
                            from_file_id, name, node_type
                        )
                    elif len(refs) >= 2:
                        # 回退：从 refs 中提取第二个元素（模块名）
                        module_name = refs[1]
                        if module_name:
                            self._add_dependency(
                                dependencies, system_targets,
                                from_file_id, module_name, node_type
                            )
                continue

            # 处理 import_statement, import_clause, named_imports, import_specifier
            if node_type in ["import_statement", "import_clause", "named_imports", "import_specifier"]:
                # 优先使用 name 字段（模块路径）
                if name:
                    self._add_dependency(
                        dependencies, system_targets,
                        from_file_id, name, node_type
                    )
                else:
                    # 回退：从 refs 中提取包含 / 或 . 的路径（过滤 / 和 . 单独出现）
                    for ref in refs:
                        if not ref or ref in ('/', '.', '..'):
                            continue
                        if '/' in ref or ref.startswith('.'):
                            self._add_dependency(
                                dependencies, system_targets,
                                from_file_id, ref, node_type
                            )
                continue

            # 处理 export_statement
            if node_type == "export_statement":
                # 优先使用 name 字段
                if name:
                    self._add_dependency(
                        dependencies, system_targets,
                        from_file_id, name, node_type
                    )
                else:
                    # 回退：从 refs 中提取路径（过滤 / 和 . 单独出现）
                    for ref in refs:
                        if not ref or ref in ('/', '.', '..'):
                            continue
                        if '/' in ref or ref.startswith('.'):
                            self._add_dependency(
                                dependencies, system_targets,
                                from_file_id, ref, node_type
                            )
                continue

        return dependencies, system_targets

    def _add_dependency(
        self,
        dependencies: List[Dict],
        system_targets: Set[str],
        from_file_id: int,
        target: str,
        node_type: str
    ):
        """添加依赖关系"""
        if not target:
            return

        # 清理 target（去除引号和空白）
        target = target.strip().strip('"').strip("'")
        if not target:
            return

        # 判断是否为相对导入
        is_relative = target.startswith('.') or target.startswith('/')

        # 判断是否为系统/内置模块
        is_builtin = self._is_builtin_module(target)

        dependencies.append({
            "from_file_id": from_file_id,
            "target": target,
            "is_angle_bracket": False,
            "is_relative": is_relative,
            "is_builtin": is_builtin,
            "node_type": node_type,
        })

        if is_builtin:
            system_targets.add(target)

    def _is_builtin_module(self, module_path: str) -> bool:
        """
        判断模块是否为 Node.js 内置模块
        
        Args:
            module_path: 模块路径
            
        Returns:
            True 如果是内置模块
        """
        # 处理 node: 前缀
        if module_path.startswith('node:'):
            return True
        
        # 提取模块名 (处理 scoped packages 如 @scope/package)
        if module_path.startswith('@'):
            # Scoped package: @scope/package/subpath
            parts = module_path.split('/')
            if len(parts) >= 2:
                module_name = f"{parts[0]}/{parts[1]}"
            else:
                module_name = module_path
        else:
            # Regular package: package/subpath
            module_name = module_path.split('/')[0]
        
        return module_name in self.BUILTIN_MODULES

    def is_system_include(self, target: str) -> bool:
        """判断是否为系统库引用"""
        return self._is_builtin_module(target)

    def is_internal_dependency(
        self,
        target: str,
        project_files_by_path: Dict[str, List[int]]
    ) -> Tuple[bool, Optional[int]]:
        """
        判断依赖是否指向项目内部文件
        
        JavaScript 规则:
        - 相对路径直接解析
        - 支持 .js, .jsx, .ts, .tsx, .mjs 等扩展名
        - 支持 index 文件解析
        
        Args:
            target: 模块路径
            project_files_by_path: 项目文件路径映射
            
        Returns:
            (is_internal, matched_file_id)
        """
        # 只处理相对路径
        if not (target.startswith('.') or target.startswith('/')):
            return False, None
        
        # 可能的扩展名
        extensions = ['.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.json']
        
        # 生成可能的文件路径
        possible_paths = [target]  # 原始路径
        
        # 添加扩展名
        for ext in extensions:
            possible_paths.append(target + ext)
        
        # 添加 index 文件
        possible_paths.append(os.path.join(target, 'index.js'))
        possible_paths.append(os.path.join(target, 'index.ts'))
        possible_paths.append(os.path.join(target, 'index.jsx'))
        
        # 检查可能的路径
        for path in possible_paths:
            # 规范化路径
            normalized = os.path.normpath(path)
            if normalized in project_files_by_path:
                return True, project_files_by_path[normalized][0]
        
        # basename 匹配
        basename = os.path.basename(target)
        for file_path, file_ids in project_files_by_path.items():
            file_basename = os.path.basename(file_path)
            # 去掉扩展名比较
            name_without_ext = os.path.splitext(file_basename)[0]
            if name_without_ext == basename or file_basename == basename:
                return True, file_ids[0]
        
        return False, None
