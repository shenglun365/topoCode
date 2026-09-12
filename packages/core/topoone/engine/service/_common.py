"""kb 引擎公共基础（哈希/后台任务注册表/KB 数据目录）——原 core_service.py 共享区。

由 core_service.py 解构而来（M03 T3.2）。
文件范围忽略配置已随纯 git 视图机制移除：git 是文件清单唯一事实源。
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


