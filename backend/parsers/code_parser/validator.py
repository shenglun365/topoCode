# parsers/languages/code_parser/validator.py
"""
语言配置验证工具

用于验证各语言配置的正确性和完整性。
可在开发阶段和 CI/CD 流程中运行。

使用方法:
    python -m parsers.code_parser.validator
    
或:
    from parsers.code_parser.validator import validate_all_configs
    validate_all_configs()
"""
import logging
from typing import Dict, List, Set, Tuple, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """验证结果"""
    language: str
    passed: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    info: List[str] = field(default_factory=list)
    
    def __str__(self) -> str:
        status = "✅ PASS" if self.passed else "❌ FAIL"
        return f"{status} {self.language}: {len(self.errors)} errors, {len(self.warnings)} warnings"


class LanguageConfigValidator:
    """语言配置验证器"""
    
    # 必需的配置属性
    REQUIRED_ATTRIBUTES = {
        'important_node_types': set,
        'is_name_node_types': set,
        'scope_creating_types': set,
        'defining_context_types': set,
        'node_type_to_op': dict,
    }
    
    # 推荐包含的节点类型（每种语言都应考虑）
    RECOMMENDED_NODE_TYPES = {
        # 函数相关
        'function_definition', 'function_declaration', 'method_declaration',
        # 类/结构体相关
        'class_declaration', 'class_definition', 'struct_specifier',
        # 变量相关
        'declaration', 'assignment', 'variable_declaration',
        # 控制流
        'if_statement', 'for_statement', 'while_statement', 'return_statement',
        # 表达式
        'call_expression', 'call', 'binary_expression',
        # 标识符
        'identifier',
        # 顶层结构
        'translation_unit', 'program', 'module', 'source_file',
    }
    
    # 必需的名称节点类型
    REQUIRED_NAME_NODE_TYPES = {'identifier'}
    
    # 必需的作用域创建类型
    REQUIRED_SCOPE_TYPES = set()  # 因语言而异
    
    # 必需的定义上下文类型
    REQUIRED_DEFINING_TYPES = set()  # 因语言而异
    
    def __init__(self):
        self.results: List[ValidationResult] = []
    
    def validate_config(self, lang: str, config: Any) -> ValidationResult:
        """
        验证单个语言配置
        
        Args:
            lang: 语言名称
            config: LanguageConfig 实例
            
        Returns:
            ValidationResult
        """
        result = ValidationResult(language=lang, passed=True)
        
        # === 检查 1: 配置对象是否存在 ===
        if config is None:
            result.passed = False
            result.errors.append(f"Configuration for '{lang}' is None")
            return result
        
        # === 检查 2: 必需属性是否存在且类型正确 ===
        for attr_name, expected_type in self.REQUIRED_ATTRIBUTES.items():
            if not hasattr(config, attr_name):
                result.passed = False
                result.errors.append(f"Missing required attribute: {attr_name}")
            else:
                attr_value = getattr(config, attr_name)
                if not isinstance(attr_value, expected_type):
                    result.passed = False
                    result.errors.append(
                        f"Attribute '{attr_name}' should be {expected_type.__name__}, "
                        f"got {type(attr_value).__name__}"
                    )
        
        # 如果有错误，提前返回
        if result.errors:
            return result
        
        # === 检查 3: 集合非空检查 ===
        set_attrs = ['important_node_types', 'is_name_node_types', 
                     'scope_creating_types', 'defining_context_types']
        
        for attr_name in set_attrs:
            attr_value = getattr(config, attr_name)
            if not attr_value:
                result.warnings.append(f"Attribute '{attr_name}' is empty")
        
        # === 检查 4: node_type_to_op 的值是否有效 ===
        valid_ops = {
            'def', 'import', 'export', 'include', 'call', 'assign',
            'arith', 'logic', 'compare', 'bitwise', 'cast', 'type',
            'control', 'return', 'throw', 'try', 'catch', 'cond',
            'lambda', 'yield', 'await', 'async', 'sync', 'with',
            'send', 'recv', 'select', 'macro', 'assert', 'include',
            'sizeof', 'typeid', 'instanceof', 'deref', 'ref', 'unpack',
            'destructure', 'goroutine', 'defer', 'unsafe'
        }
        
        node_type_to_op = getattr(config, 'node_type_to_op')
        for node_type, op in node_type_to_op.items():
            if op not in valid_ops:
                result.warnings.append(
                    f"Unknown operation '{op}' for node type '{node_type}'"
                )
        
        # === 检查 5: 推荐节点类型检查 ===
        important_types = getattr(config, 'important_node_types')
        missing_recommended = self.RECOMMENDED_NODE_TYPES - set(important_types)
        
        if missing_recommended:
            # 这不是错误，只是建议
            result.info.append(
                f"Missing recommended node types: {missing_recommended}"
            )
        
        # === 检查 6: 名称节点类型检查 ===
        name_types = getattr(config, 'is_name_node_types')
        missing_required_name = self.REQUIRED_NAME_NODE_TYPES - set(name_types)
        
        if missing_required_name:
            result.warnings.append(
                f"Missing required name node types: {missing_required_name}"
            )
        
        # === 检查 7: 作用域和定义上下文一致性检查 ===
        scope_types = getattr(config, 'scope_creating_types')
        defining_types = getattr(config, 'defining_context_types')
        
        # 检查是否有类型同时出现在两个集合中（通常不应该）
        overlap = set(scope_types) & set(defining_types)
        if overlap:
            result.info.append(
                f"Types in both scope_creating_types and defining_context_types: {overlap}"
            )
        
        # === 检查 8: 节点类型命名规范检查 ===
        all_types = (set(important_types) | set(name_types) | 
                     set(scope_types) | set(defining_types))
        
        invalid_names = []
        for type_name in all_types:
            if not isinstance(type_name, str):
                invalid_names.append(f"{type_name} (not a string)")
            elif not type_name:
                invalid_names.append("(empty string)")
        
        if invalid_names:
            result.warnings.append(f"Invalid node type names: {invalid_names}")
        
        # === 检查 9: 统计信息 ===
        result.info.append(
            f"Statistics: "
            f"{len(important_types)} important types, "
            f"{len(name_types)} name types, "
            f"{len(scope_types)} scope types, "
            f"{len(defining_types)} defining types, "
            f"{len(node_type_to_op)} op mappings"
        )
        
        return result
    
    def validate_language_module(self, lang: str, module_path: str) -> ValidationResult:
        """
        验证语言模块
        
        Args:
            lang: 语言名称
            module_path: 模块导入路径 (如 'parsers.code_parser.lang_python')
            
        Returns:
            ValidationResult
        """
        try:
            import importlib
            module = importlib.import_module(module_path)
            
            if not hasattr(module, 'CONFIG'):
                result = ValidationResult(
                    language=lang,
                    passed=False,
                    errors=[f"Module {module_path} does not export CONFIG"]
                )
                return result
            
            return self.validate_config(lang, module.CONFIG)
            
        except ImportError as e:
            return ValidationResult(
                language=lang,
                passed=False,
                errors=[f"Failed to import module {module_path}: {e}"]
            )
        except Exception as e:
            return ValidationResult(
                language=lang,
                passed=False,
                errors=[f"Unexpected error validating {lang}: {e}"]
            )


def validate_all_configs() -> List[ValidationResult]:
    """
    验证所有语言配置
    
    Returns:
        验证结果列表
    """
    validator = LanguageConfigValidator()
    results = []
    
    # 定义所有语言模块
    language_modules = [
        ('c', 'parsers.code_parser.lang_c'),
        ('cpp', 'parsers.code_parser.lang_cpp'),
        ('java', 'parsers.code_parser.lang_java'),
        ('python', 'parsers.code_parser.lang_python'),
        ('javascript', 'parsers.code_parser.lang_js'),
        ('typescript', 'parsers.code_parser.lang_ts'),
        ('go', 'parsers.code_parser.lang_go'),
        ('rust', 'parsers.code_parser.lang_rust'),
        # 可以添加更多语言
    ]
    
    print("=" * 60)
    print("语言配置验证")
    print("=" * 60)
    
    for lang, module_path in language_modules:
        print(f"\n验证 {lang}...")
        result = validator.validate_language_module(lang, module_path)
        results.append(result)
        
        print(f"  {result}")
        
        if result.errors:
            for error in result.errors:
                print(f"    ❌ {error}")
        
        if result.warnings:
            for warning in result.warnings:
                print(f"    ⚠️  {warning}")
        
        if result.info:
            for info in result.info:
                print(f"    ℹ️  {info}")
    
    # 汇总
    print("\n" + "=" * 60)
    print("验证汇总")
    print("=" * 60)
    
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    total_errors = sum(len(r.errors) for r in results)
    total_warnings = sum(len(r.warnings) for r in results)
    
    print(f"总计：{len(results)} 个语言配置")
    print(f"通过：{passed}")
    print(f"失败：{failed}")
    print(f"错误：{total_errors}")
    print(f"警告：{total_warnings}")
    
    if failed == 0:
        print("\n✅ 所有配置验证通过!")
    else:
        print(f"\n❌ {failed} 个配置验证失败")
    
    return results


def validate_config_file(config_path: str) -> ValidationResult:
    """
    验证单个配置文件
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        ValidationResult
    """
    import sys
    import importlib.util
    
    path = Path(config_path)
    if not path.exists():
        return ValidationResult(
            language=path.stem,
            passed=False,
            errors=[f"File not found: {config_path}"]
        )
    
    # 动态加载模块
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    
    if not hasattr(module, 'CONFIG'):
        return ValidationResult(
            language=path.stem,
            passed=False,
            errors=[f"Module does not export CONFIG"]
        )
    
    validator = LanguageConfigValidator()
    return validator.validate_config(path.stem, module.CONFIG)


if __name__ == '__main__':
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) > 1:
        # 验证单个文件
        config_path = sys.argv[1]
        result = validate_config_file(config_path)
        print(result)
        if result.errors:
            for error in result.errors:
                print(f"  ❌ {error}")
        sys.exit(0 if result.passed else 1)
    else:
        # 验证所有配置
        results = validate_all_configs()
        sys.exit(0 if all(r.passed for r in results) else 1)
