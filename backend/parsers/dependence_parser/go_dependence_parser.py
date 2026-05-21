# parsers/languages/dependence_parser/go_dependence_parser.py
"""
Go 依赖提取器

实现 Go 语言的 import 依赖识别和提取逻辑。

支持的导入语法:
- import "package"
- import alias "package"
- import . "package" (点导入)
- import _ "package" (空白标识符导入)
- import ( "pkg1"; "pkg2" ) (导入块)

系统库判断:
- Go 标准库 (fmt, os, net/http 等)
- 第三方模块 (通过模块路径判断)
"""
from typing import Dict, Any, Optional, List, Tuple, Set
import os
from .extractor_factory import DependencyExtractor, register_dependency_extractor


@register_dependency_extractor('go')
class GoModExtractor(DependencyExtractor):
    """
    Go import 依赖提取器

    支持识别:
    - 标准库导入：import "fmt"
    - 第三方导入：import "github.com/gin-gonic/gin"
    - 相对导入：import "./local"
    - 别名导入：import alias "package"
    - 点导入：import . "package"
    - 空白导入：import _ "package"
    - 模块路径解析：从 go.mod 读取 module path，映射 import 到内部文件
    """

    # 缓存模块路径
    _module_path_cache: str = None
    
    # Go 依赖相关的 AST 节点类型
    DEPENDENCY_NODE_TYPES = [
        "import_declaration",
        "import_spec",
        "imported_package_name",
    ]
    
    # Go 标准库包列表
    STANDARD_LIBRARY_PACKAGES = {
        # 核心库
        'builtin', 'builtins', 'unsafe',
        
        # 常用标准库
        'fmt', 'os', 'io', 'bytes', 'strings', 'strconv',
        'time', 'math', 'rand', 'sort', 'regexp',
        
        # 容器
        'container/list', 'container/ring', 'container/heap',
        
        # 加密
        'crypto', 'crypto/md5', 'crypto/sha1', 'crypto/sha256',
        'crypto/rand', 'crypto/aes', 'crypto/cipher',
        
        # 编码
        'encoding', 'encoding/json', 'encoding/xml', 'encoding/base64',
        'encoding/hex', 'encoding/gob',
        
        # 压缩
        'compress/gzip', 'compress/zlib', 'compress/bzip2',
        'compress/flate',
        
        # 网络
        'net', 'net/http', 'net/url', 'net/mail', 'net/smtp',
        'net/rpc', 'net/http/httptest',
        
        # 并发
        'sync', 'sync/atomic', 'context',
        
        # 反射
        'reflect',
        
        # IO
        'bufio', 'path/filepath', 'archive/tar', 'archive/zip',
        
        # 数据库
        'database/sql', 'database/sql/driver',
        
        # 调试/测试
        'debug', 'runtime', 'runtime/debug', 'runtime/pprof',
        'testing', 'log',
        
        # 其他
        'errors', 'flag', 'image', 'html', 'html/template', 'text/template',
        'go/ast', 'go/parser', 'go/printer', 'go/token',
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
            import_path = node.get("import_path", "")
            
            # 处理 refs 中的导入路径
            for ref in refs:
                if not ref:
                    continue
                
                # 去除引号
                module_path = ref.strip('"\'')
                
                if not module_path:
                    continue
                
                # 判断是否为标准库
                is_stdlib = self._is_standard_library(module_path)
                
                # 判断是否为相对导入
                is_relative = module_path.startswith('.')
                
                dependencies.append({
                    "from_file_id": from_file_id,
                    "target": module_path,
                    "is_angle_bracket": False,
                    "is_stdlib": is_stdlib,
                    "is_relative": is_relative,
                })
                
                if is_stdlib:
                    system_targets.add(module_path)
        
        return dependencies, system_targets

    def _is_standard_library(self, module_path: str) -> bool:
        """
        判断模块是否为 Go 标准库
        
        Args:
            module_path: 模块路径
            
        Returns:
            True 如果是标准库
        """
        # 处理相对导入
        if module_path.startswith('.'):
            return False
        
        # 提取顶级包名
        parts = module_path.split('/')
        if not parts:
            return False
        
        top_package = parts[0]
        
        # 检查是否有域名 (第三方包通常有域名)
        if '.' in top_package:
            return False
        
        # 检查是否在标准库列表中
        if module_path in self.STANDARD_LIBRARY_PACKAGES:
            return True
        
        # 检查顶级包是否在标准库中
        if top_package in self.STANDARD_LIBRARY_PACKAGES:
            return True
        
        # 常见的第三方包域名前缀
        third_party_prefixes = [
            'github.com', 'golang.org', 'google.golang.org',
            'go.opentelemetry.io', 'gopkg.in', 'gitlab.com',
            'bitbucket.org',
        ]
        
        for prefix in third_party_prefixes:
            if module_path.startswith(prefix):
                return False
        
        # 如果没有域名且不是已知的第三方包，可能是标准库
        # Go 标准库的包名通常较短且有意义
        return len(top_package) <= 20 and top_package.isidentifier()

    def is_system_include(self, target: str) -> bool:
        """判断是否为系统库引用"""
        return self._is_standard_library(target)

    def is_internal_dependency(
        self,
        target: str,
        project_files_by_path: Dict[str, List[int]]
    ) -> Tuple[bool, Optional[int]]:
        """判断依赖是否指向项目内部文件

        Go 规则:
        - 相对路径直接解析
        - 绝对模块路径: 启发式检测 module path，strip 后匹配文件路径
        - 支持包目录匹配（import "mymod/pkg" → 匹配 pkg/*.go）
        """
        # 处理相对导入
        if target.startswith('.'):
            norm_target = os.path.normpath(target)
            possible_paths = [norm_target, norm_target + '.go', os.path.join(norm_target, 'main.go')]
            for path in possible_paths:
                if path in project_files_by_path:
                    return True, project_files_by_path[path][0]
            for file_path, file_ids in project_files_by_path.items():
                if file_path.startswith(norm_target + '/') and file_path.endswith('.go'):
                    return True, file_ids[0]
            return False, None

        # 绝对模块路径: 尝试 strip module path 后匹配
        module_path = self._detect_module_path(project_files_by_path)
        if module_path and target.startswith(module_path + '/'):
            rel_path = target[len(module_path) + 1:]
            return self._match_path_to_files(rel_path, project_files_by_path)

        # 直接尝试匹配
        return self._match_path_to_files(target, project_files_by_path)

    def _detect_module_path(self, project_files_by_path: Dict[str, List[int]]) -> Optional[str]:
        """从项目文件路径中启发式检测 module path"""
        if self._module_path_cache is not None:
            return self._module_path_cache

        go_files = [p for p in project_files_by_path.keys() if p.endswith('.go')]
        if len(go_files) >= 2:
            first_dirs = set()
            for f in go_files:
                parts = f.split('/')
                if len(parts) > 1:
                    first_dirs.add(parts[0])
            if len(first_dirs) == 1:
                self._module_path_cache = list(first_dirs)[0]
                return self._module_path_cache

        return None

    def _match_path_to_files(
        self, rel_path: str, project_files_by_path: Dict[str, List[int]]
    ) -> Tuple[bool, Optional[int]]:
        """将包路径匹配到项目文件"""
        # 直接文件匹配: "pkg/sub" → "pkg/sub.go"
        direct_file = rel_path + '.go'
        if direct_file in project_files_by_path:
            return True, project_files_by_path[direct_file][0]

        # 目录匹配: "pkg/sub" → "pkg/sub/*.go"
        prefix = rel_path + '/'
        for file_path, file_ids in project_files_by_path.items():
            if file_path.startswith(prefix) and file_path.endswith('.go'):
                return True, file_ids[0]

        # 精确目录名匹配
        for file_path, file_ids in project_files_by_path.items():
            file_dir = os.path.dirname(file_path)
            if file_dir == rel_path and file_path.endswith('.go'):
                return True, file_ids[0]

        return False, None
