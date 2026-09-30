"""semantic_assets 拆分模块（A1 修正：纯移动，逻辑零改动）。

原 semantic_assets.py 5555 行 god-file 按段拆出；本模块由构建脚本生成段内容，
跨模块引用为显式 import。每步拆分均跑 28 个后端测试文件保护。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from .. import store
from ..common import _ts, err, ok  # noqa: F401

logger = logging.getLogger(__name__)

_AST_CACHE_VERSION = "v2"
# implDetails 解析逻辑变更时 bump → 全部旧缓存行失效重取(防脏数据长期命中)。


def _cache_content_hash(root: str, rel: str) -> str:
    """ast 缓存比对哈希 = 版本盐 + 文件 md5。"""
    return f"{_AST_CACHE_VERSION}-{_file_md5(root, rel)}"


def _file_md5(root: str, rel: str) -> str:
    """文件内容哈希签名(对应要求①：AST 节点 ↔ 文件哈希)。"""
    if not root or not rel:
        return ""
    full = os.path.join(root, rel.lstrip("/").replace("/", os.sep))
    try:
        with open(full, "rb") as fh:
            return hashlib.md5(fh.read()).hexdigest()[:16]
    except Exception:
        return ""


def _anchor_hashes(root: str, ast_refs: List[dict]) -> Dict[str, str]:
    """资产锚定文件的哈希签名表(去重)。"""
    files = list(dict.fromkeys(r.get("file") or "" for r in ast_refs if r.get("file")))
    return {f: _file_md5(root, f) for f in files if f}


def _canonical_key(kind: str, level: str, ast_refs: List[dict],
                   name: str = "", scope_type: str = "", scope_key: str = "",
                   rev: str = "") -> str:
    """稳定规范标识 canonicalKey：逻辑类型 + 抽象粒度 + 代码锚点(文件:符号) + 锚点视角 的确定性指纹。

    资产身份 = 代码(锚点) + rev 视角(批1-1)：同一符号在基线/head/工作区视角下
    是不同资产行(语义增强可分别进行)；rev 空字符串与旧口径指纹兼容(legacy 行)。
    kind+level 纳入指纹，避免同一锚点在行为/规则与 high/medium/low 间误合并。
    无 AST 锚点的资产(纯语义/合成，如 H 级聚合)退化为名称派生 key(scope 仅作碰撞消解)。
    """
    anchors = sorted({
        f"{r.get('file', '')}:{r.get('symbol', '')}"
        for r in ast_refs if r.get("file")
    })
    if anchors:
        seed = f"{kind}|{level}|{'|'.join(anchors)}|{rev}"
    else:
        seed = f"{kind}|{level}|{scope_type}|{scope_key}|name:{name}|{rev}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:24]


