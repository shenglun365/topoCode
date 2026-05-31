# parsers/languages/code_parser/lang_parser_conf.py
"""
语言检测和解析器配置模块

提供多语言检测功能，支持：
1. 基于文件扩展名的检测（主要方式）
2. 基于 shebang 的检测（用于无扩展名脚本文件）
3. 基于文件内容特征的检测（辅助方式）

架构:
- LANGUAGE_EXTENSIONS: 文件扩展名到语言的映射
- SHEBANG_PATTERNS: shebang 到语言的映射
- CONTENT_PATTERNS: 内容特征到语言的映射
- LANGUAGES: tree-sitter 语言对象映射
- PARSERS: tree-sitter 解析器缓存
"""
import re
import logging
from typing import Optional, Dict, Set
from tree_sitter import Language, Parser

logger = logging.getLogger(__name__)


# ==================== 文件扩展名映射 ====================
LANGUAGE_EXTENSIONS: Dict[str, Set[str]] = {
    # C 系列
    'c': {'.c', '.h'},
    'cpp': {'.cpp', '.cc', '.cxx', '.hpp', '.hh', '.hxx'},
    'objective-c': {'.m'},
    'objective-c++': {'.mm'},
    
    # Java 系列
    'java': {'.java'},
    'kotlin': {'.kt', '.kts'},
    'scala': {'.scala'},
    
    # Python 系列
    'python': {'.py', '.pyw', '.pyi'},
    
    # JavaScript 系列
    'javascript': {'.js', '.jsx', '.mjs', '.es6'},
    'typescript': {'.ts', '.cts', '.mts'},
    'tsx': {'.tsx'},
    
    # Web 开发
    'php': {'.php', '.phtml'},
    'ruby': {'.rb', '.rbw'},
    'csharp': {'.cs'},
    'swift': {'.swift'},
    'go': {'.go'},
    'rust': {'.rs'},
    'r': {'.r', '.R'},
    
    # 脚本语言
    'bash': {'.sh', '.bash', '.zsh', '.ksh'},
    'perl': {'.pl', '.pm', '.t'},
    'lua': {'.lua'},
    'powershell': {'.ps1', '.psm1', '.psd1'},
    
    # 其他语言
    'sql': {'.sql'},
    'html': {'.html', '.htm', '.xhtml'},
    'css': {'.css', '.scss', '.sass', '.less'},
    'yaml': {'.yaml', '.yml'},
    'json': {'.json'},
    'xml': {'.xml'},
    'markdown': {'.md', '.markdown'},
    'makefile': {'Makefile', 'makefile', 'GNUmakefile'},
    'dockerfile': {'Dockerfile'},
    'cmake': {'CMakeLists.txt'},
    
    # 配置文件
    'toml': {'.toml'},
    'ini': {'.ini', '.cfg', '.conf'},
    'properties': {'.properties'},
}


# ==================== Shebang 模式映射 ====================
# 用于检测无扩展名的脚本文件
SHEBANG_PATTERNS: Dict[str, str] = {
    # Python
    r'#!/.*python(\d+(\.\d+)?)?(\s|$)': 'python',
    r'#!/usr/bin/env python(\d+(\.\d+)?)?(\s|$)': 'python',
    
    # Bash/Shell
    r'#!/.*bash(\s|$)': 'bash',
    r'#!/.*sh(\s|$)': 'bash',
    r'#!/bin/sh(\s|$)': 'bash',
    r'#!/usr/bin/env bash(\s|$)': 'bash',
    r'#!/usr/bin/env sh(\s|$)': 'bash',
    
    # Perl
    r'#!/.*perl(\d+(\.\d+)?)?(\s|$)': 'perl',
    r'#!/usr/bin/env perl(\s|$)': 'perl',
    
    # Ruby
    r'#!/.*ruby(\d+(\.\d+)?)?(\s|$)': 'ruby',
    r'#!/usr/bin/env ruby(\s|$)': 'ruby',
    
    # PHP
    r'#!/.*php(\s|$)': 'php',
    r'#!/usr/bin/env php(\s|$)': 'php',
    
    # Node.js
    r'#!/.*node(\s|$)': 'javascript',
    r'#!/usr/bin/env node(\s|$)': 'javascript',
    
    # Lua
    r'#!/.*lua(\d+(\.\d+)?)?(\s|$)': 'lua',
    r'#!/usr/bin/env lua(\s|$)': 'lua',
}


# ==================== 内容特征模式映射 ====================
# 用于辅助语言检测（当扩展名不明确时）
CONTENT_PATTERNS: Dict[str, list] = {
    'python': [
        (r'^import\s+\w+', 1),           # import statement
        (r'^from\s+\w+\s+import', 1),    # from...import
        (r'^def\s+\w+\s*\(', 2),         # function definition
        (r'^class\s+\w+', 2),            # class definition
        (r'^print\s*\(', 1),             # print function
    ],
    'javascript': [
        (r'^import\s+.*\s+from', 1),     # ES6 import
        (r'^export\s+(default|const|function|class)', 1),
        (r'^const\s+\w+\s*=', 1),
        (r'^function\s+\w+\s*\(', 1),
        (r'^\s*require\s*\(', 1),        # CommonJS require
    ],
    'typescript': [
        (r'^import\s+.*\s+from', 1),
        (r'^export\s+(default|const|function|class|interface|type)', 1),
        (r'^interface\s+\w+', 2),
        (r'^type\s+\w+\s*=', 2),
        (r':\s*(string|number|boolean|any)\b', 1),
    ],
    'java': [
        (r'^package\s+\w+', 2),
        (r'^import\s+\w+', 1),
        (r'^public\s+class\s+\w+', 2),
        (r'^public\s+static\s+void\s+main', 2),
        (r'^\s*System\.out\.print', 1),
    ],
    'go': [
        (r'^package\s+\w+', 2),
        (r'^import\s+\(', 1),
        (r'^func\s+\w+\s*\(', 2),
        (r'^func\s+main\s*\(', 2),
        (r'^\s*fmt\.\w+\(', 1),
    ],
    'rust': [
        (r'^use\s+\w+', 1),
        (r'^fn\s+\w+\s*\(', 2),
        (r'^fn\s+main\s*\(', 2),
        (r'^let\s+mut\s+\w+', 1),
        (r'^println!\s*\(', 1),
    ],
    'c': [
        (r'^#include\s*[<"]', 2),
        (r'^int\s+main\s*\(', 2),
        (r'^void\s+\w+\s*\(', 1),
        (r'^\s*printf\s*\(', 1),
        (r'^struct\s+\w+', 1),
    ],
    'cpp': [
        (r'^#include\s*[<"]', 1),
        (r'^using\s+namespace\s+\w+', 2),
        (r'^int\s+main\s*\(', 2),
        (r'^std::', 2),
        (r'^class\s+\w+', 1),
    ],
    'php': [
        (r'^<\?php', 3),
        (r'^<\?', 2),
        (r'^\s*echo\s+', 1),
        (r'^\s*\$\w+\s*=', 1),
    ],
    'ruby': [
        (r'^require\s+[\'"]', 1),
        (r'^def\s+\w+', 1),
        (r'^class\s+\w+', 1),
        (r'^\s*puts\s+', 1),
        (r'^\s*end\s*$', 1),
    ],
}


def detect_language(filename: str, file_content: bytes = None) -> Optional[str]:
    """
    检测文件的编程语言
    
    检测策略（按优先级）:
    1. 文件扩展名匹配（最快，最可靠）
    2. Shebang 匹配（用于无扩展名脚本）
    3. 内容特征匹配（辅助方式，用于确认）
    
    Args:
        filename: 文件名（包含路径）
        file_content: 文件内容（可选，用于 shebang 和内容检测）
        
    Returns:
        语言名称，如果无法检测则返回 None
    """
    import os
    
    # === Step 1: 扩展名检测 ===
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    
    for lang, extensions in LANGUAGE_EXTENSIONS.items():
        if ext in extensions:
            return lang
    
    # 特殊处理：Makefile, Dockerfile 等无扩展名文件
    basename = os.path.basename(filename)
    if basename in LANGUAGE_EXTENSIONS.get('makefile', set()):
        return 'makefile'
    if basename in LANGUAGE_EXTENSIONS.get('dockerfile', set()):
        return 'dockerfile'
    if basename in LANGUAGE_EXTENSIONS.get('cmake', set()):
        return 'cmake'
    
    # === Step 2: Shebang 检测（需要文件内容）===
    if file_content:
        lang = _detect_by_shebang(file_content)
        if lang:
            return lang
    
    # === Step 3: 内容特征检测（需要文件内容）===
    if file_content:
        lang = _detect_by_content(file_content)
        if lang:
            return lang
    
    logger.debug(f"Unknown language for file: {filename}")
    return None


def _detect_by_shebang(content: bytes) -> Optional[str]:
    """
    通过 shebang 检测语言
    
    Args:
        content: 文件内容（字节）
        
    Returns:
        语言名称，如果未检测到则返回 None
    """
    try:
        # 只读取前 2 行（shebang 通常在第一行）
        text = content.decode('utf-8', errors='ignore')
        lines = text.split('\n')[:2]
        
        for line in lines:
            line = line.strip()
            if line.startswith('#!'):
                for pattern, lang in SHEBANG_PATTERNS.items():
                    if re.match(pattern, line, re.IGNORECASE):
                        logger.debug(f"Detected language '{lang}' by shebang: {line[:50]}")
                        return lang
    except Exception as e:
        logger.debug(f"Shebang detection failed: {e}")
    
    return None


def _detect_by_content(content: bytes) -> Optional[str]:
    """
    通过内容特征检测语言
    
    算法:
    1. 读取前 100 行内容
    2. 对每种语言的每个模式进行匹配
    3. 计算各语言的得分
    4. 返回得分最高的语言
    
    Args:
        content: 文件内容（字节）
        
    Returns:
        语言名称，如果无法检测则返回 None
    """
    try:
        text = content.decode('utf-8', errors='ignore')
        lines = text.split('\n')[:100]  # 只检查前 100 行
        
        scores: Dict[str, int] = {}
        
        for lang, patterns in CONTENT_PATTERNS.items():
            score = 0
            for pattern, weight in patterns:
                for line in lines:
                    if re.search(pattern, line, re.MULTILINE):
                        score += weight
                        if score >= 5:  # 提前终止
                            break
                if score >= 5:
                    break
            scores[lang] = score
        
        if not scores:
            return None
        
        # 返回得分最高的语言
        best_lang, best_score = max(scores.items(), key=lambda x: x[1])
        
        if best_score >= 3:  # 最低阈值
            logger.debug(f"Detected language '{best_lang}' by content (score={best_score})")
            return best_lang
            
    except Exception as e:
        logger.debug(f"Content detection failed: {e}")
    
    return None


def get_language_extensions(lang: str) -> Optional[Set[str]]:
    """
    获取语言支持的文件扩展名
    
    Args:
        lang: 语言名称
        
    Returns:
        扩展名集合，如果语言不支持则返回 None
    """
    return LANGUAGE_EXTENSIONS.get(lang)


def is_supported_language(lang: str) -> bool:
    """
    检查语言是否支持
    
    Args:
        lang: 语言名称
        
    Returns:
        True 如果语言支持
    """
    return lang in LANGUAGE_EXTENSIONS


# ==================== Tree-sitter 语言包加载 ====================

# 导入各语言的语法模块（需先 pip install 对应包）
try:
    import tree_sitter_c as tsc
except ImportError:
    tsc = None

try:
    import tree_sitter_cpp as tscpp
except ImportError:
    tscpp = None

try:
    import tree_sitter_python as tspy
except ImportError:
    tspy = None

try:
    import tree_sitter_javascript as tsjs
except ImportError:
    tsjs = None

try:
    import tree_sitter_typescript as tsts
except ImportError:
    tsts = None

try:
    import tree_sitter_java as tsjava
except ImportError:
    tsjava = None

try:
    import tree_sitter_go as tsgo
except ImportError:
    tsgo = None

try:
    import tree_sitter_rust as tsrs
except ImportError:
    tsrs = None

try:
    import tree_sitter_bash as tsbash
except ImportError:
    tsbash = None

try:
    import tree_sitter_php as tsphp
    # 检查是否有 language 属性（某些版本没有）
    if not hasattr(tsphp, 'language'):
        logger.warning("tree_sitter_php installed but has no 'language' attribute, disabling")
        tsphp = None
except (ImportError, AttributeError):
    tsphp = None

try:
    import tree_sitter_ruby as tsruby
except ImportError:
    tsruby = None

try:
    import tree_sitter_lua as tslua
except ImportError:
    tslua = None


# 构建语言映射
LANGUAGES: Dict[str, Language] = {}

# 安全地构建语言映射（检查 language 属性）
if tsc and hasattr(tsc, 'language'):
    try:
        LANGUAGES["c"] = Language(tsc.language())
    except Exception as e:
        logger.warning(f"Failed to load C language: {e}")

if tscpp and hasattr(tscpp, 'language'):
    try:
        LANGUAGES["cpp"] = Language(tscpp.language())
    except Exception as e:
        logger.warning(f"Failed to load C++ language: {e}")

if tspy and hasattr(tspy, 'language'):
    try:
        LANGUAGES["python"] = Language(tspy.language())
    except Exception as e:
        logger.warning(f"Failed to load Python language: {e}")

if tsjs and hasattr(tsjs, 'language'):
    try:
        LANGUAGES["javascript"] = Language(tsjs.language())
    except Exception as e:
        logger.warning(f"Failed to load JavaScript language: {e}")

if tsts and hasattr(tsts, 'language_typescript'):
    try:
        LANGUAGES["typescript"] = Language(tsts.language_typescript())
        LANGUAGES["tsx"] = Language(tsts.language_tsx())
    except Exception as e:
        logger.warning(f"Failed to load TypeScript language: {e}")

if tsjava and hasattr(tsjava, 'language'):
    try:
        LANGUAGES["java"] = Language(tsjava.language())
    except Exception as e:
        logger.warning(f"Failed to load Java language: {e}")

if tsgo and hasattr(tsgo, 'language'):
    try:
        LANGUAGES["go"] = Language(tsgo.language())
    except Exception as e:
        logger.warning(f"Failed to load Go language: {e}")

if tsrs and hasattr(tsrs, 'language'):
    try:
        LANGUAGES["rust"] = Language(tsrs.language())
    except Exception as e:
        logger.warning(f"Failed to load Rust language: {e}")

if tsbash and hasattr(tsbash, 'language'):
    try:
        LANGUAGES["bash"] = Language(tsbash.language())
    except Exception as e:
        logger.warning(f"Failed to load Bash language: {e}")

if tsphp and hasattr(tsphp, 'language'):
    try:
        LANGUAGES["php"] = Language(tsphp.language())
    except Exception as e:
        logger.warning(f"Failed to load PHP language: {e}")

if tsruby and hasattr(tsruby, 'language'):
    try:
        LANGUAGES["ruby"] = Language(tsruby.language())
    except Exception as e:
        logger.warning(f"Failed to load Ruby language: {e}")

if tslua and hasattr(tslua, 'language'):
    try:
        LANGUAGES["lua"] = Language(tslua.language())
    except Exception as e:
        logger.warning(f"Failed to load Lua language: {e}")

logger.info(f"Loaded {len(LANGUAGES)} tree-sitter languages: {list(LANGUAGES.keys())}")


# 解析器缓存
PARSERS: Dict[str, Parser] = {}


def get_parser(lang_name: str) -> Optional[Parser]:
    """
    获取语言对应的 tree-sitter 解析器
    
    使用缓存机制，每个语言只创建一次解析器
    
    Args:
        lang_name: 语言名称
        
    Returns:
        Parser 实例，如果语言不支持则返回 None
    """
    if lang_name in PARSERS:
        return PARSERS[lang_name]
    
    if lang_name not in LANGUAGES:
        logger.debug(f"Language '{lang_name}' not available in tree-sitter")
        return None
    
    parser = Parser(LANGUAGES[lang_name])
    PARSERS[lang_name] = parser
    logger.info(f"Created parser for language: {lang_name}")
    
    return parser


def get_available_languages() -> list:
    """
    获取所有可用的 tree-sitter 语言列表
    
    Returns:
        语言名称列表
    """
    return list(LANGUAGES.keys())


# 便捷函数
def get_supported_languages() -> list:
    """获取所有支持的语言列表（包括扩展名检测和 tree-sitter 支持）"""
    return list(LANGUAGE_EXTENSIONS.keys())
