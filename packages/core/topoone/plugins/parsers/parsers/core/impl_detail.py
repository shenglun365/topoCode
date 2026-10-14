"""实现细节提取 — 语句级 / 框架路由 / 值级数据(单文件、只读、不落库)。

补充符号级 FileSymbolTable 的三类数据，供 architect 实现层语义资产提取消费：

  - statements: if/switch/case/try/loop 语句节点 + condition 原文 + 行区间 + 所属函数
  - routes:     框架 API 路由元数据(path/methods/handler/framework/line)
  - constants:  常量/变量/字段/枚举成员的赋值文本(值级数据)
  - configKeys: 配置文件(yaml/json/env/toml)键值对

设计:
  - 复用 language_loader 的 tree-sitter parser 缓存与 languages 注册表
    (所属函数判定与 LanguageExtractor.function_types/method_types 同源，
    保证语句归属与符号节点一致)。
  - 语句归属函数采用「行区间包含」(最小包含区间)，无需维护 scope 栈。
  - 全部 best-effort: 语言无 parser / 解析失败 → 对应列表为空，不抛异常。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from ..language_loader import get_parser
from ..languages import EXTRACTORS
from .symbol_model import FileSymbolTable

logger = logging.getLogger(__name__)

MAX_STATEMENTS_PER_FILE = 400
MAX_CONDITION_CHARS = 300
MAX_CONSTANTS_PER_FILE = 200
MAX_CONST_VALUE_CHARS = 120
MAX_CONFIG_KEYS_PER_FILE = 500
MAX_CONFIG_VALUE_CHARS = 200

# ── 语句节点类型矩阵(tree-sitter 节点类型 → 语句类别) ─────────
# 类型不存在于某语言语法时永不匹配，多列无害；按 T1/T2/T3 语言分层维护。

STMT_SPECS: dict[str, dict[str, tuple[str, ...]]] = {
    "python": {
        "if": ("if_statement", "elif_clause"),
        "switch": ("match_statement",),
        "case": ("match_case", "case_clause"),
        "try": ("try_statement",),
        "loop": ("for_statement", "while_statement"),
    },
    "javascript": {
        "if": ("if_statement",),
        "switch": ("switch_statement",),
        "case": ("switch_case", "switch_default"),
        "try": ("try_statement",),
        "loop": ("for_statement", "for_in_statement", "for_of_statement",
                 "while_statement", "do_statement"),
    },
    "typescript": {
        "if": ("if_statement",),
        "switch": ("switch_statement",),
        "case": ("switch_case", "switch_default"),
        "try": ("try_statement",),
        "loop": ("for_statement", "for_in_statement", "for_of_statement",
                 "while_statement", "do_statement"),
    },
    "go": {
        "if": ("if_statement",),
        "switch": ("expression_switch_statement", "type_switch_statement",
                   "select_statement"),
        "case": ("expression_case", "type_case", "default_case"),
        "try": (),
        "loop": ("for_statement",),
    },
    "java": {
        "if": ("if_statement",),
        "switch": ("switch_expression", "switch_statement"),
        "case": ("switch_label",),
        "try": ("try_statement",),
        "loop": ("for_statement", "enhanced_for_statement", "while_statement"),
    },
    "c": {
        "if": ("if_statement",),
        "switch": ("switch_statement",),
        "case": ("case_statement", "default_statement"),
        "try": (),
        "loop": ("for_statement", "while_statement", "do_statement"),
    },
    "cpp": {
        "if": ("if_statement",),
        "switch": ("switch_statement",),
        "case": ("case_statement", "default_statement"),
        "try": ("try_statement",),
        "loop": ("for_statement", "for_range_loop", "while_statement", "do_statement"),
    },
    "c_sharp": {
        "if": ("if_statement",),
        "switch": ("switch_statement",),
        "case": ("switch_section",),
        "try": ("try_statement",),
        "loop": ("for_statement", "for_each_statement", "while_statement", "do_statement"),
    },
    "rust": {
        "if": ("if_expression",),
        "switch": ("match_expression",),
        "case": ("match_arm",),
        "try": (),
        "loop": ("loop_expression", "for_expression", "while_expression"),
    },
    "kotlin": {
        "if": ("if_expression",),
        "switch": ("when_expression",),
        "case": ("when_entry",),
        "try": ("try_expression",),
        "loop": ("for_expression", "while_expression"),
    },
    "swift": {
        "if": ("if_statement", "guard_statement"),
        "switch": ("switch_statement",),
        "case": ("case_item",),
        "try": ("do_statement"),
        "loop": ("for_statement", "while_statement", "repeat_statement"),
    },
    "ruby": {
        "if": ("if_node", "unless_node"),
        "switch": ("case_node",),
        "case": ("when_node",),
        "try": (),
        "loop": ("while_node", "until_node", "for_node"),
    },
    "php": {
        "if": ("if_statement",),
        "switch": ("switch_statement",),
        "case": ("case_statement", "default_statement"),
        "try": ("try_statement",),
        "loop": ("for_statement", "foreach_statement", "while_statement", "do_statement"),
    },
    "dart": {
        "if": ("if_statement",),
        "switch": ("switch_statement",),
        "case": ("switch_pattern_case", "case_pattern", "default_pattern"),
        "try": ("try_statement",),
        "loop": ("for_statement", "while_statement"),
    },
    "scala": {
        "if": ("if_expression",),
        "switch": ("match",),
        "case": ("case_clause",),
        "try": ("try_expression",),
        "loop": ("for_expression", "while_expression"),
    },
    "lua": {
        "if": ("if_statement",),
        "switch": (),
        "case": (),
        "try": (),
        "loop": ("while_statement", "repeat_statement", "for_statement", "numeric_for"),
    },
    "luau": {
        "if": ("if_statement",),
        "switch": (),
        "case": (),
        "try": (),
        "loop": ("while_statement", "repeat_statement", "for_statement", "numeric_for"),
    },
    "objc": {
        "if": ("if_statement",),
        "switch": ("switch_statement",),
        "case": ("case_statement", "default_statement"),
        "try": (),
        "loop": ("for_statement", "while_statement", "do_statement"),
    },
}

# 条件原文提取: 语句类别 → 候选 tree-sitter field 名(按序尝试)。
# 均命中失败时回退「关键字后 → 首个 {/(/: 前」的头部切片。
_CONDITION_FIELDS: dict[str, tuple[str, ...]] = {
    "if": ("condition",),
    "switch": ("value", "tag", "argument", "subject", "condition"),
    "case": ("value", "pattern", "condition"),
    "try": (),
    "loop": ("condition",),
}

_STRIP_KEYWORDS = {
    "if": ("else if", "elif", "guard", "if", "unless"),
    "switch": ("switch", "match", "when"),
    "case": ("case", "when", "default"),
    "try": ("try",),
    "loop": ("for", "while", "do", "repeat"),
}


def _node_text(node, source) -> str:
    """节点文本。source 应为解析所用的 bytes(节点偏移是字节偏移)；
    传 str 仅在纯 ASCII 时安全(中文等多字节会错位)，故优先支持 bytes。"""
    try:
        raw = source[node.start_byte:node.end_byte]
        if isinstance(raw, (bytes, bytearray)):
            return raw.decode("utf-8", errors="replace")
        return raw
    except Exception:
        return ""


def _strip_header(text: str, keywords: tuple[str, ...]) -> str:
    """去掉语句头部的类型关键字(如 `if`/`switch (x)` → 条件部分)。"""
    t = (text or "").strip()
    changed = True
    while changed:
        changed = False
        for kw in keywords:
            if t.startswith(kw):
                t = t[len(kw):].strip(" \t:(")
                changed = True
    if t.endswith(")") and "(" not in t:
        t = t[:-1].strip()
    t = t.rstrip(":").strip()
    return t


def _strip_outer_parens(text: str) -> str:
    """`(a > 0)` / `(r.count() > 0)` → 去掉最外层成对括号(平衡检查)。"""
    t = (text or "").strip()
    if not (len(t) >= 2 and t[0] == "(" and t[-1] == ")"):
        return t
    depth = 0
    for i, ch in enumerate(t):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return t[1:-1].strip() if i == len(t) - 1 else t
    return t


def _condition_from_node(node, typ: str, text: str, lang: str) -> str:
    """提取 condition 原文(≤MAX_CONDITION_CHARS)。"""
    if typ == "case" and lang == "rust":
        # match_arm: `=>` 之前为 pattern(含可选 guard)
        raw = _node_text(node, text)
        i = raw.find("=>")
        cond = raw[:i].strip() if i >= 0 else ""
    else:
        cond = ""
        for f in _CONDITION_FIELDS.get(typ, ()):
            c = node.child_by_field_name(f)
            if c is not None:
                cond = _node_text(c, text)
                break
        if not cond:
            # 回退: 语句头部 = 到第一个 '{' 或换行(取更早者)之前
            raw = _node_text(node, text)
            cuts = [i for i in (raw.find("{"), raw.find("\n")) if i >= 0]
            head = raw[:min(cuts)] if cuts else raw
            cond = _strip_header(head, _STRIP_KEYWORDS.get(typ, ()))
    cond = re.sub(r"\s+", " ", (cond or "")).strip()
    return _strip_outer_parens(cond)[:MAX_CONDITION_CHARS]


def _function_types_for(lang: str) -> set[str]:
    ex = EXTRACTORS.get(lang)
    if ex is None:
        return set()
    return set(ex.function_types) | set(ex.method_types)


def _function_name(node, text: str) -> str:
    try:
        c = node.child_by_field_name("name")
        if c is not None:
            return _node_text(c, text).strip()
    except Exception:
        pass
    # 回退: 第一个 identifier 类型子节点
    for child in node.children:
        if child.type in ("identifier", "simple_identifier", "type_identifier",
                          "property_identifier"):
            return _node_text(child, text).strip()
    return ""


def extract_statements(root_node, source: str, language: str) -> list[dict]:
    """语句级提取: 返回 [{type, condition, startLine, endLine, enclosing}]。

    两趟: ① 迭代遍历收集函数行区间与语句节点(条件原文同步切片)；
          ② 按「最小包含行区间」为语句归属最内层函数。
    """
    spec = STMT_SPECS.get(language)
    if not spec or root_node is None:
        return []
    type_of: dict[str, str] = {}
    for st, types in spec.items():
        for t in types:
            type_of[t] = st
    fn_types = _function_types_for(language)

    functions: list[tuple[int, int, str]] = []   # (start, end, name)
    statements: list[dict] = []

    stack = [root_node]
    while stack:
        node = stack.pop()
        ntype = node.type
        if ntype in type_of:
            if len(statements) < MAX_STATEMENTS_PER_FILE:
                statements.append({
                    "type": type_of[ntype],
                    "condition": _condition_from_node(node, type_of[ntype], source, language),
                    "startLine": node.start_point[0] + 1,
                    "endLine": node.end_point[0] + 1,
                    "enclosing": "",
                })
        elif ntype in fn_types:
            name = _function_name(node, source)
            if name:
                functions.append((node.start_point[0] + 1, node.end_point[0] + 1, name))
        # 继续下钻(函数体内也需收集语句)
        for child in reversed(node.children):
            stack.append(child)

    # 语句 → 最内层函数(最小包含区间)
    for s in statements:
        best: Optional[tuple[int, str]] = None
        sl, el = s["startLine"], s["endLine"]
        for (fs, fe, fn) in functions:
            if fs <= sl <= fe:
                width = fe - fs
                if best is None or width < best[0]:
                    best = (width, fn)
        s["enclosing"] = best[1] if best else ""
    return statements


# ── 常量/值级数据 ────────────────────────────────────────────

_CONST_VALUE_KINDS = frozenset({"constant", "variable", "field", "property", "enum_member"})
_ASSIGN_RE = re.compile(r"(?:^|[\s(])=([^=].*)$")      # 优先赋值 `= value`
_ANNOT_RE = re.compile(r":\s*([^\s=].+?)\s*(?:#.*)?$")  # 回退注解 `: type`


def _first_assignment_value(lines: list[str]) -> str:
    for idx, ln in enumerate(lines):
        m = _ASSIGN_RE.search(ln)
        if m:
            v = m.group(1).strip().rstrip(";").strip()
        else:
            m2 = _ANNOT_RE.search(ln)
            if not m2:
                continue
            v = m2.group(1).strip()
        # 去掉行尾注释
        v = re.split(r"\s+#\s", v, 1)[0].strip()
        v = re.sub(r"\s*//.*$", "", v).strip()
        if not v:
            continue
        # 多行容器字面量(dict/list)：补齐后续行直至括号配平(有上限)
        while (v.count("{") + v.count("[")) > (v.count("}") + v.count("]")) \
                and idx + 1 < len(lines):
            idx += 1
            nxt = lines[idx].strip()
            if nxt.startswith("#"):
                continue  # 纯注释行跳过
            v = (v + " " + nxt).rstrip()
        return v[:MAX_CONST_VALUE_CHARS]
    return ""


def extract_constant_values(table: FileSymbolTable, source: str) -> list[dict]:
    """常量/变量/字段/枚举成员 → 赋值文本。返回 [{name, value, line}]。"""
    out: list[dict] = []
    if table is None:
        return out
    lines = source.split("\n")
    for n in table.nodes:
        kind = getattr(n.kind, "value", str(n.kind))
        if kind not in _CONST_VALUE_KINDS:
            continue
        s0 = int(getattr(n, "start_line", 0) or 0)
        s1 = int(getattr(n, "end_line", 0) or s0)
        if s0 < 1 or s1 < s0:
            continue
        # 多给几行，让多行容器字面量(如 dict)能补齐到括号配平
        body = lines[s0 - 1:min(s1, s0 + 24)]
        value = _first_assignment_value(body)
        if not value:
            continue
        out.append({"name": n.name, "value": value, "line": s0})
        if len(out) >= MAX_CONSTANTS_PER_FILE:
            break
    return out


# ── 统一入口 ─────────────────────────────────────────────────

_CONFIG_EXTS = frozenset({".yaml", ".yml", ".json", ".env", ".toml", ".ini", ".properties"})


def _file_ext(file_path: str) -> str:
    base = os.path.basename(file_path or "")
    ext = os.path.splitext(base)[1].lower()
    if not ext and len(base) > 1 and base.startswith("."):
        ext = base  # .env 等隐藏文件: 整体作为类型
    return ext


def extract_impl_details(file_path: str, source: bytes, language: str,
                         table: Optional[FileSymbolTable] = None) -> dict:
    """单文件实现细节提取(只读)。

    返回 {"statements": [...], "routes": [...], "constants": [...],
          "configKeys": [...], "language": str}
    """
    result: dict = {"statements": [], "routes": [], "constants": [],
                    "configKeys": [], "language": language}
    text = source.decode("utf-8", errors="replace")
    ext = _file_ext(file_path)
    if ext in _CONFIG_EXTS or (language or "").lower() in ("yaml", "json"):
        from .config_files import parse_config_file
        result["configKeys"] = parse_config_file(file_path or "", text)
        return result

    lang = language or ""
    line_offset = 0
    if lang == "vue":
        # 与 TreeSitterWalker 一致的 <script> 块预处理(行偏移回补)
        m = re.search(r"<script\b[^>]*>(.*?)</script>", text, re.DOTALL | re.IGNORECASE)
        if m:
            line_offset = text[:m.start(1)].count("\n")
            text = m.group(1)
            lang = "typescript"
        else:
            logger.warning("impl_detail: no script block in vue file %s", file_path)
            return result

    parser = get_parser(lang)
    if parser is not None:
        try:
            # 节点偏移是字节偏移：必须与解析所用字节一致(中文多字节文件传 str 会错位)。
            parse_bytes = text.encode("utf-8") if lang == "typescript" else source
            tree = parser.parse(parse_bytes)
            if tree and tree.root_node is not None:
                stmts = extract_statements(tree.root_node, parse_bytes, lang)
                if line_offset:
                    for s in stmts:
                        s["startLine"] += line_offset
                        s["endLine"] += line_offset
                result["statements"] = stmts
            if hasattr(tree, "delete"):
                tree.delete()
        except Exception as e:
            logger.warning("impl_detail: statement extract failed for %s: %s", file_path, e)

    result["constants"] = extract_constant_values(table, text)

    # 框架路由(延迟导入避免循环依赖)
    try:
        from ..frameworks.routes import extract_routes
        result["routes"] = extract_routes(lang, file_path, text, table)
    except Exception as e:
        logger.warning("impl_detail: route extract failed for %s: %s", file_path, e)
    return result
