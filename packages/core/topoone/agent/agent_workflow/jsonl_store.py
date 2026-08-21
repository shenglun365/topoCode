"""
JSONL 追加写入工具。

用于 .topocode/architecture/ 下的 versions.jsonl / communities.jsonl / deltas.jsonl。

设计原则:
  - 追加写入 (append-only)，永不覆盖
  - 每行一个 JSON 对象
  - 使用文件锁避免并发写入冲突
  - 自动创建目录结构
"""

import json
import os
import threading
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# In-process file lock — all JSONL writes happen within a single Python process,
# so threading.Lock provides sufficient concurrency protection across all platforms.
_jsonl_lock = threading.Lock()


def ensure_arch_dir(project_root: str) -> str:
    """确保 .topocode/architecture/ 目录存在，返回绝对路径"""
    arch_dir = os.path.join(os.path.abspath(project_root), ".topocode", "architecture")
    os.makedirs(arch_dir, exist_ok=True)
    return arch_dir


def append_jsonl(project_root: str, filename: str, entry: dict) -> bool:
    """
    追加一条 JSONL 记录到指定文件。

    Args:
        project_root: 项目根目录
        filename: JSONL 文件名 (versions.jsonl / communities.jsonl / deltas.jsonl)
        entry: 要追加的 dict

    Returns:
        True 成功, False 失败
    """
    try:
        arch_dir = ensure_arch_dir(project_root)
        filepath = os.path.join(arch_dir, filename)
        line = json.dumps(entry, ensure_ascii=False) + "\n"

        with _jsonl_lock:
            with open(filepath, "a") as f:
                f.write(line)
                f.flush()

        return True
    except Exception as e:
        logger.warning(f"[JSONL] append failed: {filepath} — {e}")
        return False


def read_jsonl(project_root: str, filename: str, limit: Optional[int] = None) -> list[dict]:
    """
    读取 JSONL 文件中的所有记录。

    Args:
        project_root: 项目根目录
        filename: JSONL 文件名
        limit: 最多返回条数 (None = 全部)

    Returns:
        list[dict]
    """
    try:
        arch_dir = ensure_arch_dir(project_root)
        filepath = os.path.join(arch_dir, filename)
        if not os.path.exists(filepath):
            return []

        entries = []
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning(f"[JSONL] malformed line in {filename}")
                if limit and len(entries) >= limit:
                    break
        return entries
    except Exception as e:
        logger.warning(f"[JSONL] read failed: {filepath} — {e}")
        return []


def get_latest_version(project_root: str) -> Optional[dict]:
    """获取最新的版本记录"""
    versions = read_jsonl(project_root, "versions.jsonl")
    if not versions:
        return None
    return versions[-1]


def get_version_count(project_root: str) -> int:
    """获取版本总数"""
    arch_dir = ensure_arch_dir(project_root)
    filepath = os.path.join(arch_dir, "versions.jsonl")
    if not os.path.exists(filepath):
        return 0
    count = 0
    try:
        with open(filepath, "r") as f:
            for line in f:
                if line.strip():
                    count += 1
    except Exception:
        pass
    return count
