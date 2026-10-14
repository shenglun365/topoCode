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

SEMANTIC_KINDS = ("entity", "contract", "state", "rule", "process", "decision")
SEMANTIC_LEVELS = ("implementation", "logic", "business")

# 类别轴：静态·定义(是什么) / 动态·处理(发生什么)。
SEMANTIC_CATEGORY = {
    "entity": "static", "contract": "static", "state": "static", "rule": "static",
    "process": "dynamic", "decision": "dynamic",
}
STATIC_KINDS = ("entity", "contract", "state", "rule")
DYNAMIC_KINDS = ("process", "decision")

_KIND_LABEL = {
    "entity": "实体(数据对象/领域实体)",
    "contract": "契约(接口/消息/事件/端点)",
    "state": "状态(生命周期定义/状态集+迁移)",
    "rule": "规则(配置化的约束/策略定义)",
    "process": "过程(输入→处理→输出/流程)",
    "decision": "决策(运行时分支/策略执行)",
}

# 规范分类在各级粒度下的具体形态(供 prompt / 前端标注)。
_LEVEL_KIND_FORM = {
    ("business", "entity"): "business_entity 聚合根/业务概念",
    ("business", "contract"): "business_capability 对外业务能力",
    ("business", "state"): "lifecycle 业务生命周期",
    ("business", "rule"): "business_policy 业务政策/规章",
    ("business", "process"): "business_process 端到端业务过程",
    ("business", "decision"): "business_strategy 业务策略选择",
    ("logic", "entity"): "logical_data 领域实体/规范化关系",
    ("logic", "contract"): "service_contract 服务/接口契约",
    ("logic", "state"): "state_flow 状态机(迁移表)",
    ("logic", "rule"): "configured_rule 配置化规则定义",
    ("logic", "process"): "processing_flow 用例/流程",
    ("logic", "decision"): "control_logic 决策表/分支",
    ("implementation", "entity"): "concrete_type 具体类型(class/struct/enum)",
    ("implementation", "contract"): "message_contract 签名/路由/schema",
    ("implementation", "state"): "enum 枚举/状态字段",
    ("implementation", "rule"): "config_item 配置结构/阈值定义",
    ("implementation", "process"): "call_chain 函数执行序列",
    ("implementation", "decision"): "branch_logic if/switch 分支",
}

# 统一 id 编码规则：sa-{cat_code}-{gran_code}-{kind_code}-{seq}。每段 1 字母码。
_CAT_CODE = {"static": "s", "dynamic": "d"}
_GRAN_CODE = {"implementation": "i", "logic": "l", "business": "b"}
_KIND_CODE = {"entity": "e", "contract": "c", "state": "s", "rule": "r",
              "process": "p", "decision": "d"}


def _id_prefix(level: Optional[str], kind: Optional[str]) -> str:
    """语义资产 id 统一编码前缀: sa-{cat}-{gran}-{kind}。未知取值回落 sa-x-x-x。"""
    cat = _CAT_CODE.get(SEMANTIC_CATEGORY.get(kind or ""), "x")
    return f"sa-{cat}-{_GRAN_CODE.get(level or '', 'x')}-{_KIND_CODE.get(kind or '', 'x')}"

# codegraph node.kind → AstNodeKind
_AST_KIND_MAP = {
    "class": "class", "struct": "class", "interface": "class", "enum": "class",
    "component": "class", "type_alias": "class",
    "method": "method", "constructor": "method",
    "function": "func", "func": "func", "route": "func",
    "field": "field", "property": "field", "variable": "field",
    "constant": "field", "enum_member": "field",
}

_NODE_COLS = (
    "id, kind, name, qualified_name, file_path, start_line, end_line, "
    "start_column, end_column, signature, docstring, return_type"
)

_SCHEMA_KIND_TO_LLM = {k: k for k in SEMANTIC_KINDS}

