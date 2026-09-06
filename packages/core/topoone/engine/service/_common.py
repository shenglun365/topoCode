"""kb 引擎公共基础（.gitignore 解析/导入配置/哈希/后台导入注册表）——原 core_service.py 共享区。

由 core_service.py 解构而来（M03 T3.2）。
"""
"""Core Service - 方法注册 + 业务逻辑 (多数据库架构)"""

import asyncio
import time
import fnmatch
import hashlib
import json
import logging
import os

import re
import shutil
import uuid
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from topoone.db.manager import SQLiteContext, MultiDBManager
from topoone.rpc.zmq_server import ZMQServer
from topoone.engine.report_tree_service import save_overall_doc as _save_overall_doc

from topoone.engine.task_manager import (
    detect_git_info as _tm_detect_git_info,
    save_git_info as _tm_save_git_info,
    get_git_info as _tm_get_git_info,
    check_import_status as _tm_check_import_status,
    save_positions as _tm_save_positions,
    load_positions as _tm_load_positions,
    clear_positions as _tm_clear_positions,
    list_position_keys as _tm_list_position_keys,
)

# 后台导入任务注册表：requestId -> {status, progress, phase, projectId, error}
# project.import 改为后台执行后，前端据此轮询进度（进度事件仍走 WS）。
_IMPORT_JOBS: dict = {}
_DELETE_JOBS: dict = {}



# ==================== .gitignore 解析器 ====================

class GitIgnoreParser:
    """完整的 .gitignore 语法解析器"""

    def __init__(self):
        self.patterns: list[tuple[str, bool]] = []  # (pattern, negated)

    def load_file(self, filepath: str) -> 'GitIgnoreParser':
        """从文件加载规则"""
        if not os.path.exists(filepath):
            return self
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                self.add_pattern(line.strip())
        return self

    def add_pattern(self, pattern: str):
        """添加单个规则"""
        if not pattern or pattern.startswith('#'):
            return
        negated = pattern.startswith('!')
        if negated:
            pattern = pattern[1:]
        # 处理尾随斜杠 (目录匹配)
        is_dir_only = pattern.endswith('/')
        if is_dir_only:
            pattern = pattern[:-1]
        # 转义通配符
        if is_dir_only:
            pattern = pattern + '/'
        self.patterns.append((pattern, negated))

    def is_ignored(self, path: str, is_dir: bool = False) -> bool:
        """检查路径是否被忽略（git 语义：按文件顺序，最后一条匹配的规则生效）"""
        # 规范化路径
        path = path.lstrip('/')
        parts = path.split('/')

        ignored = False
        for pattern, negated in self.patterns:
            if self._match_pattern(pattern, path, parts, is_dir):
                ignored = not negated

        return ignored

    def _match_pattern(self, pattern: str, path: str, parts: list[str], is_dir: bool) -> bool:
        """匹配单个模式（git 语义：锚定路径逐段匹配，* 不跨越路径分隔符）"""
        # 目录专用模式
        if pattern.endswith('/'):
            if not is_dir:
                # 文件也匹配父目录模式
                dir_pattern = pattern[:-1]
                for i in range(len(parts)):
                    subpath = '/'.join(parts[:i + 1])
                    if fnmatch.fnmatch(subpath, dir_pattern):
                        return True
                return False
            else:
                pattern = pattern[:-1]

        anchored = pattern.startswith('/')
        if anchored:
            pattern = pattern[1:]

        # 锚定模式（/ 开头，或含 /）：整条路径逐段匹配，* 不跨 /
        if anchored or '/' in pattern:
            return self._match_anchored(pattern, parts)

        # 否则匹配 basename 或任何路径段
        basename = parts[-1]
        if fnmatch.fnmatch(basename, pattern):
            return True
        for i in range(len(parts)):
            subpath = '/'.join(parts[i:])
            if fnmatch.fnmatch(subpath, pattern):
                return True

        return False

    @staticmethod
    def _match_anchored(pattern: str, parts: list[str]) -> bool:
        """锚定路径匹配：长度一致且逐段 fnmatch（* 不跨越 /）"""
        pat_parts = pattern.split('/')
        if len(pat_parts) != len(parts):
            return False
        for p, s in zip(pat_parts, parts):
            if not fnmatch.fnmatch(s, p):
                return False
        return True


# 默认忽略模式
# ==================== 默认忽略模式 ====================

DEFAULT_IGNORE_PATTERNS = [
    # topoCode 自身数据
    '.topocode/', '.topocode-archive', '.codegraph/',
    # 忽略文件自身
    '.gitignore', '.dockerignore', '.npmignore', '.ignore',
    '.prettierignore', '.eslintignore',
    # 构建产物
    'node_modules/', 'dist/', 'build/', '.next/', '.nuxt/',
    '__pycache__/', '*.pyc', '*.pyo', '*.pyd', '.Python/',
    'env/', 'venv/', '.venv/',
    'target/', 'out/', 'bin/', 'obj/',
    '*.o', '*.a', '*.so', '*.dylib', '*.dll', '*.exe',
    # 包管理器 / 依赖目录
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    'poetry.lock', 'Cargo.lock', 'Go.sum', 'Gopkg.lock',
    '*.egg-info/', '*.egg', '.eggs/', 'eggs/',
    'vendor/', 'bower_components/', 'third_party/', 'deps/',
    'Pods/', '.build/', 'DerivedData/',
    '.gradle/', 'gradle/', 'mvnw/', 'mvnw.cmd',
    'go/pkg/', '.go_build/',
    '.tox/', '*.whl', 'MANIFEST.in',
    '.dart_tool/', '.pub-cache/', '.packages/', '.pub/',
    # IDE / 编辑器
    '.idea/', '.vscode/', '*.swp', '*.swo', '*~',
    '.DS_Store', 'Thumbs.db',
    # 版本控制
    '.git/', '.svn/', '.hg/',
    # 日志 / 调试
    '*.log', 'npm-debug.log*', 'yarn-debug.log*',
    # 临时文件
    'tmp/', 'temp/', '.cache/',
    # 云 / 基础设施
    '.terraform/', 'terraform.tfstate*', 'terraform.tfvars',
    '.serverless/', 'cdk.out/',
    # 测试产物
    'artifacts/', 'coverage/', '.nyc_output/', '.coverage/',
    # 其他编译中间产物
    '*.tsbuildinfo', '*.js.map', '*.d.ts.map',
]

# 各生态额外 ignore 文件名，按优先级排列
IGNORE_FILE_PRIORITY = [
    '.gitignore',
    '.ignore',
    '.dockerignore',
    '.npmignore',
    '.prettierignore',
    '.eslintignore',
]


class MultiIgnoreParser:
    """多 ignore 文件合并解析器，支持 .gitignore/.dockerignore/.npmignore 等"""

    def __init__(self):
        self.parsers: list[GitIgnoreParser] = []

    def load_files(self, root_path: str, filenames: list[str] | None = None) -> 'MultiIgnoreParser':
        """从根目录加载多个 ignore 文件，后者优先级高于前者"""
        if filenames is None:
            filenames = IGNORE_FILE_PRIORITY
        for fname in filenames:
            fp = os.path.join(root_path, fname)
            parser = GitIgnoreParser().load_file(fp)
            if parser.patterns:
                self.parsers.append(parser)
        return self

    def is_ignored(self, rel_path: str, is_dir: bool = False) -> bool:
        """按优先级检查：任一 ignore 文件匹配则忽略"""
        for parser in self.parsers:
            if parser.is_ignored(rel_path, is_dir):
                return True
        return False


def _load_import_config(main_db) -> dict:
    """从 app_config 表加载导入配置"""
    config = {
        "ignore_mode": "strict",
        "extra_ignore_files": [],
        "custom_patterns": [],
    }
    try:
        rows = main_db.fetchall("SELECT key, value FROM app_config WHERE key LIKE 'import_%'")
        for row in rows:
            key = row["key"]
            val = row["value"]
            if key == "import_ignore_mode":
                config["ignore_mode"] = val
            elif key == "import_extra_ignore_files":
                config["extra_ignore_files"] = json.loads(val) if val else []
            elif key == "import_custom_patterns":
                config["custom_patterns"] = json.loads(val) if val else []
    except Exception:
        pass
    return config


def build_effective_ignore_patterns(config: dict) -> list[str]:
    """根据配置构建有效的忽略模式列表"""
    mode = config.get("ignore_mode", "standard")
    custom = config.get("custom_patterns", [])

    if mode == "minimal":
        base = [p for p in DEFAULT_IGNORE_PATTERNS if any(
            kw in p for kw in ['node_modules', '__pycache__', '.git/', '.DS_Store',
                               '*.pyc', '*.log', '.idea/', '.vscode/']
        )]
    elif mode == "strict":
        base = list(DEFAULT_IGNORE_PATTERNS)
        base.extend([
            'test/', 'tests/', '__tests__/', 'spec/', 'e2e/',
            'docs/', 'doc/', 'examples/', 'example/',
            '*.md', '*.txt', '*.rst',
            '*.svg', '*.png', '*.jpg', '*.jpeg', '*.gif', '*.ico',
            '.github/', '.gitlab/',
        ])
    else:
        base = list(DEFAULT_IGNORE_PATTERNS)

    seen = set(base)
    for p in custom:
        if p not in seen:
            base.append(p)
            seen.add(p)
    if '.topocode/' not in seen:
        base.append('.topocode/')
        seen.add('.topocode/')
    if '.codegraph/' not in seen:
        base.append('.codegraph/')
        seen.add('.codegraph/')
    return base


def should_ignore_file(rel_path: str,
                       gitignore_parser: GitIgnoreParser | MultiIgnoreParser | None = None,
                       is_dir: bool = False,
                       extra_patterns: list[str] | None = None) -> bool:
    """检查文件是否应该被忽略"""
    # 检查 ignore 文件
    if gitignore_parser:
        if gitignore_parser.is_ignored(rel_path, is_dir):
            return True

    # 检查默认 + 自定义忽略模式
    patterns = extra_patterns or DEFAULT_IGNORE_PATTERNS
    for pattern in patterns:
        # 目录模式('xx/')：gitignore 语义——目录自身或其下任意层级的文件都忽略
        if pattern.endswith('/'):
            dirname = pattern[:-1]
            if dirname and (rel_path == dirname or rel_path.startswith(pattern)
                            or f'/{dirname}/' in f'/{rel_path}/'):
                return True
            continue
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        if fnmatch.fnmatch(os.path.basename(rel_path), pattern):
            return True

    return False


# topoCode 自身数据目录：导入/分析时不得识别为项目代码
TOPOCODE_DATA_DIRS = ('.topocode/', '.codegraph/')


def _ensure_topocode_dirs_in_gitignore(root_path: str):
    """Ensure topoCode data dirs (.topocode/.codegraph) are listed in the project's .gitignore."""
    gitignore_path = os.path.join(root_path, '.gitignore')
    try:
        if os.path.exists(gitignore_path):
            with open(gitignore_path, 'r', encoding='utf-8') as f:
                normalized = [l.strip() for l in f.readlines()]
            missing = [e for e in TOPOCODE_DATA_DIRS
                       if e not in normalized and e.rstrip('/') not in normalized]
            if not missing:
                return
            with open(gitignore_path, 'a', encoding='utf-8') as f:
                f.write('\n' + '\n'.join(missing) + '\n')
        else:
            with open(gitignore_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(TOPOCODE_DATA_DIRS) + '\n')
    except Exception as e:
        logger.warning(f'[import] failed to update .gitignore: {e}')


# ==================== 项目管理方法 ====================



def _simple_hash(path: str) -> str:
    """简单哈希"""
    import hashlib
    return hashlib.md5(path.encode()).hexdigest()[:12]


