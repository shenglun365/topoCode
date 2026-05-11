# parsers/languages/dependence_parser/rust_dependence_parser.py
"""
Rust 依赖提取器

实现 Rust 语言的 use/mod 依赖识别和提取逻辑。

支持的导入语法:
- use crate::module (crate 内导入)
- use std::module (标准库导入)
- use external_crate::module (外部 crate 导入)
- use self::module (当前模块导入)
- use super::module (父模块导入)
- mod module (模块声明)
- pub use ... (重新导出)

系统库判断:
- Rust 标准库 (std, core, alloc, proc_macro)
- 外部 crate (通过 Cargo.toml 判断)
"""
from typing import Dict, Any, Optional, List, Tuple, Set
import os
from .extractor_factory import DependencyExtractor, register_dependency_extractor


@register_dependency_extractor('rust')
class RustModExtractor(DependencyExtractor):
    """
    Rust use/mod 依赖提取器
    
    支持识别:
    - 标准库导入：use std::collections::HashMap;
    - crate 内导入：use crate::module;
    - 外部 crate：use serde::Serialize;
    - 当前模块：use self::module;
    - 父模块：use super::parent;
    - 模块声明：mod module;
    """
    
    # Rust 依赖相关的 AST 节点类型
    DEPENDENCY_NODE_TYPES = [
        "use_declaration",
        "use_tree",
        "mod_item",
        "extern_crate",
    ]
    
    # Rust 标准库包列表
    STANDARD_LIBRARY_CRATES = {
        'std',          # 标准库
        'core',         # 核心库 (no_std 环境)
        'alloc',        # 分配库
        'proc_macro',   # 过程宏库
        'test',         # 测试库 (不稳定)
    }
    
    def get_required_node_types(self) -> List[str]:
        """获取依赖相关的 AST 节点类型"""
        return self.DEPENDENCY_NODE_TYPES

    def extract_dependencies(self, nodes: List[Dict]) -> Tuple[List[Dict], Set[str]]:
        """
        从 use/mod 节点提取依赖关系
        
        Args:
            nodes: use_declaration 或 mod_item 节点列表
            
        Returns:
            (dependencies, system_targets)
        """
        dependencies = []
        system_targets = set()
        
        for node in nodes:
            from_file_id = node.get("file_id")
            node_type = node.get("type")
            refs = node.get("refs", [])
            
            if node_type == "use_declaration":
                deps, sys_targets = self._extract_use_declaration(from_file_id, refs, node)
            elif node_type == "mod_item":
                deps, sys_targets = self._extract_mod_item(from_file_id, refs, node)
            elif node_type == "extern_crate":
                deps, sys_targets = self._extract_extern_crate(from_file_id, refs, node)
            else:
                continue
            
            dependencies.extend(deps)
            system_targets.update(sys_targets)
        
        return dependencies, system_targets

    def _extract_use_declaration(
        self,
        from_file_id: int,
        refs: List[str],
        node: Dict
    ) -> Tuple[List[Dict], Set[str]]:
        """
        提取 use declaration 的依赖
        """
        dependencies = []
        system_targets = set()
        
        for ref in refs:
            if not ref:
                continue
            
            # 解析路径
            path_parts = ref.split('::')
            if not path_parts:
                continue
            
            root = path_parts[0]
            
            # 判断路径类型
            path_type = self._get_path_type(root)
            
            # 判断是否为标准库
            is_stdlib = self._is_standard_library(ref)
            
            dependencies.append({
                "from_file_id": from_file_id,
                "target": ref,
                "is_angle_bracket": False,
                "path_type": path_type,  # std, crate, self, super, external
                "is_stdlib": is_stdlib,
            })
            
            if is_stdlib:
                system_targets.add(ref)
        
        return dependencies, system_targets

    def _extract_mod_item(
        self,
        from_file_id: int,
        refs: List[str],
        node: Dict
    ) -> Tuple[List[Dict], Set[str]]:
        """
        提取 mod item 的依赖
        """
        dependencies = []
        system_targets = set()
        
        module_name = node.get("name", "")
        if not module_name and refs:
            module_name = refs[0]
        
        if module_name:
            # mod 声明的是 crate 内模块
            dependencies.append({
                "from_file_id": from_file_id,
                "target": f"crate::{module_name}",
                "is_angle_bracket": False,
                "path_type": "crate",
                "is_stdlib": False,
            })
        
        return dependencies, system_targets

    def _extract_extern_crate(
        self,
        from_file_id: int,
        refs: List[str],
        node: Dict
    ) -> Tuple[List[Dict], Set[str]]:
        """
        提取 extern crate 的依赖
        """
        dependencies = []
        system_targets = set()
        
        for ref in refs:
            if not ref:
                continue
            
            is_stdlib = self._is_standard_library(ref)
            
            dependencies.append({
                "from_file_id": from_file_id,
                "target": ref,
                "is_angle_bracket": False,
                "path_type": "extern",
                "is_stdlib": is_stdlib,
            })
            
            if is_stdlib:
                system_targets.add(ref)
        
        return dependencies, system_targets

    def _get_path_type(self, root: str) -> str:
        """
        判断路径类型
        
        Args:
            root: 路径根节点
            
        Returns:
            路径类型：std, crate, self, super, external
        """
        if root == 'std' or root in self.STANDARD_LIBRARY_CRATES:
            return 'std'
        elif root == 'crate':
            return 'crate'
        elif root == 'self':
            return 'self'
        elif root == 'super':
            return 'super'
        elif root.startswith('crate::') or root.startswith('self::') or root.startswith('super::'):
            return 'internal'
        else:
            return 'external'

    def _is_standard_library(self, path: str) -> bool:
        """
        判断路径是否指向标准库
        
        Args:
            path: 完整路径 (如 std::collections::HashMap)
            
        Returns:
            True 如果是标准库
        """
        if not path:
            return False
        
        # 提取根路径
        root = path.split('::')[0]
        
        return root in self.STANDARD_LIBRARY_CRATES

    def is_system_include(self, target: str) -> bool:
        """判断是否为系统库引用"""
        return self._is_standard_library(target)

    def is_internal_dependency(
        self,
        target: str,
        project_files_by_path: Dict[str, List[int]]
    ) -> Tuple[bool, Optional[int]]:
        """
        判断依赖是否指向项目内部文件
        
        Rust 规则:
        - crate:: 路径解析为 crate 根目录
        - self:: 路径解析为当前模块目录
        - super:: 路径解析为父模块目录
        - mod 声明解析为同级目录或文件
        
        Args:
            target: 模块路径
            project_files_by_path: 项目文件路径映射
            
        Returns:
            (is_internal, matched_file_id)
        """
        # 处理 crate:: 路径
        if target.startswith('crate::'):
            module_path = target[7:]  # 去掉 'crate::'
            return self._resolve_module_path(module_path, project_files_by_path)
        
        # 处理 self:: 路径
        if target.startswith('self::'):
            module_path = target[6:]  # 去掉 'self::'
            return self._resolve_module_path(module_path, project_files_by_path)
        
        # 处理 super:: 路径
        if target.startswith('super::'):
            # 需要知道当前文件位置，暂时简化处理
            module_path = target[7:]
            return self._resolve_module_path(module_path, project_files_by_path)
        
        # 外部 crate 不是内部依赖
        if '::' in target and not target.startswith('crate::') and not target.startswith('self::'):
            root = target.split('::')[0]
            if root not in self.STANDARD_LIBRARY_CRATES:
                return False, None
        
        return False, None

    def _resolve_module_path(
        self,
        module_path: str,
        project_files_by_path: Dict[str, List[int]]
    ) -> Tuple[bool, Optional[int]]:
        """
        解析模块路径为文件路径
        
        Args:
            module_path: 模块路径 (如 foo::bar)
            project_files_by_path: 项目文件路径映射
            
        Returns:
            (is_internal, matched_file_id)
        """
        # 将 :: 转换为路径分隔符
        path_parts = module_path.split('::')
        
        # 可能的路径模式
        possible_paths = [
            '/'.join(path_parts) + '.rs',  # foo/bar.rs
            '/'.join(path_parts) + '/mod.rs',  # foo/bar/mod.rs
            '/'.join(path_parts) + '/lib.rs',  # foo/bar/lib.rs
            '/'.join(path_parts) + '/main.rs',  # foo/bar/main.rs
        ]
        
        # 检查可能的路径
        for path in possible_paths:
            if path in project_files_by_path:
                return True, project_files_by_path[path][0]
        
        # basename 匹配
        module_name = path_parts[-1]
        for file_path, file_ids in project_files_by_path.items():
            basename = os.path.basename(file_path)
            if basename == module_name + '.rs' or basename == 'mod.rs':
                return True, file_ids[0]
        
        return False, None
