"""imports 统一解析层(D1) —— 模块说明符 → 项目内文件路径。

数据主权批E2 后 architect 自管图谱的跨文件关联核心：collect_snapshot 的
imports 边 target 从裸模块字符串升级为 `file:<rel>` 真实节点 id（未解析
external 丢弃，KB communityFromGraph 本就丢弃悬空边）。

架构（定稿 docs/architect/data-sovereignty-20261004.md 后续批次）:
- 解析族(family): 语言 → 探测列表互通的等价类(web/JVM/C/py/go/rust/php/dart/cs)。
  族内探测列表含多语言扩展 ⇒ vue↔ts、kt↔java、c↔cpp 天然互通(跨语言依赖);
  族间无静态 import 边 ⇒ 连通分量分离(TS/JS 一起分析、PY 独立)。
- AliasRegistry: 项目级一次性构建的别名映射表(全语言静态配置载体,
  loader 见 alias_registry.py)。
- resolver 链: 相对路径 → AliasRegistry 命中 → 文件探测序 → external 丢弃。

Run: cd <repo> && python -m pytest apps/architect/tests/test_import_resolver.py -q
"""
import json
import os
import re
from typing import Callable, Dict, List, Optional

from .alias_registry import (  # noqa: F401 (re-export)
    FAMILY_EXTS, AliasRegistry, build_alias_registry,
)

# ── 解析族: 语言 → 同探测列表的等价类 ─────────────────────────


_LANG_FAMILY: Dict[str, str] = {}
for fam, exts in FAMILY_EXTS.items():
    for e in exts:
        _LANG_FAMILY[e.lstrip(".")] = fam
# KB _detect_language 产出的语言名(非扩展名) → 族
_LANG_NAME_FAMILY = {
    "typescript": "web", "tsx": "web", "javascript": "web", "jsx": "web",
    "vue": "web", "java": "jvm", "kotlin": "jvm", "scala": "jvm",
    "c": "c", "c_header": "c", "cpp": "c", "cpp_header": "c",
    "python": "py", "go": "go", "rust": "rust", "c_sharp": "cs",
    "php": "php", "dart": "dart", "ruby": "ruby", "lua": "lua", "luau": "lua",
    "objc": "c", "swift": "swift",
}

INDEX_NAMES = ("index", "__init__", "mod", "main")


def lang_family(lang: str) -> str:
    return _LANG_NAME_FAMILY.get((lang or "").strip().lower()) or \
        _LANG_FAMILY.get((lang or "").strip().lower().lstrip("."), "")


# ── AliasRegistry: 项目级别名映射(全语言, 一期静态配置载体) ────

# ── 文件探测序 ────────────────────────────────────────────────

def probe_file(base_rel: str, file_set: set, family: str) -> Optional[str]:
    """base_rel(不含扩展名或字面带后缀) → file_set 中命中的项目相对路径。"""
    base_rel = os.path.normpath(base_rel).replace(os.sep, "/").lstrip("./") or base_rel
    exts = FAMILY_EXTS.get(family) or FAMILY_EXTS["web"]
    # 1) 字面命中(模块串自带后缀, 如 './x.js'/'x.h')
    if base_rel in file_set:
        return base_rel
    stem = base_rel
    # TS 风格 `import './x.js'` 实际源是 x.ts —— 先回映射
    lit_ext = os.path.splitext(stem)[1].lower()
    if lit_ext in (".js", ".mjs", ".cjs"):
        stem = stem[: -len(lit_ext)]
        for e in exts:
            if stem + e in file_set:
                return stem + e
    elif lit_ext in [e for e in exts]:
        stem = stem[: -len(lit_ext)]
    # 2) 扩展序
    for e in exts:
        if stem + e in file_set:
            return stem + e
    # 3) 目录入口(语言惯例): go=包目录任意 .go; rust=crate 根 src/lib|main.rs 或 lib/main/mod
    if family == "go":
        return next((f for f in sorted(file_set)
                     if f.startswith(stem + "/") and f.endswith(".go")), None)
    if family == "rust":
        for nm in ("lib", "main", "mod"):
            for cand in (f"{stem}/src/{nm}.rs", f"{stem}/{nm}.rs"):
                if cand in file_set:
                    return cand
        return None
    for nm in INDEX_NAMES:
        for e in ([".py"] if nm == "__init__" else exts):
            cand = f"{stem}/{nm}{e}"
            if cand in file_set:
                return cand
    return None


# ── 主入口: 模块说明符解析 ────────────────────────────────────

def resolve_import(mod: str, from_file: str, file_set: set,
                   registry: AliasRegistry) -> Optional[str]:
    """模块字符串 → 项目内文件相对路径; external/未命中返回 None。

    mod: imports 边原始 target(来自 KB walker); from_file: 导入方相对路径。
    """
    mod = (mod or "").strip().replace("\\", "/")
    if not mod:
        return None
    # python 相对导入(保留点号形态: walker 产出 'x' 或 '.x' 或 '..x')
    if from_file.endswith(".py"):
        return _resolve_py(mod, from_file, file_set)
    family = lang_family(os.path.splitext(from_file)[1].lstrip(".")) or "web"
    if mod.startswith("."):
        base_dir = os.path.dirname(from_file)
        return probe_file(os.path.normpath(os.path.join(base_dir, mod)).replace(os.sep, "/"),
                          file_set, family)
    # dart: package:name/path —— name/lib/x(dart 约定) 优先, 裸路径兜底
    if mod.startswith("package:"):
        m2 = re.match(r"package:([^/]+)/(.*)", mod)
        if m2:
            tgt = registry.resolve(f"package:{m2.group(1)}")
            if tgt:
                return probe_file(f"{tgt}/lib/{m2.group(2)}", file_set, "dart") or \
                    probe_file(f"{tgt}/{m2.group(2)}", file_set, "dart")
        return None
    # rust crate:: / self:: / super::
    if mod.startswith(("crate::", "self::", "super::")):
        return _resolve_rust(mod, from_file, file_set, registry)
    # 别名注册表
    hit = registry.resolve(mod)
    if hit:
        return probe_file(hit, file_set, family)
    # C 族: 引号 include 无 ./ 前缀(已由 walker 归一为 'ngx_config.h')——
    # 同目录 → include_dirs(CMake) → 项目内全局文件名匹配兜底
    if family == "c":
        base_dir = os.path.dirname(from_file)
        cand = os.path.normpath(os.path.join(base_dir, mod)).replace(os.sep, "/")
        got = probe_file(cand, file_set, family)
        if got:
            return got
        for d in registry.include_dirs:   # CMake include_directories
            got = probe_file(f"{d}/{mod}", file_set, family)
            if got:
                return got
        matches = [f for f in file_set if f.endswith("/" + mod) or f == mod]
        if len(matches) == 1:
            return matches[0]
        return None
    # JVM: FQCN(com.x.Y) —— 由调用方的包根索引处理(见 resolve_imports_batch);
    # 单条解析退化为别名表(模块坐标)命中。
    return None


def _resolve_py(mod: str, from_file: str, file_set: set) -> Optional[str]:
    """python: 相对导入点号层级 + 绝对包路径(顶级包=项目根)。"""
    m = re.match(r"^(\.*)(.*)$", mod)
    dots, rest = m.group(1), m.group(2)
    base_dir = os.path.dirname(from_file)
    for _ in range(len(dots) - 1):  # 1 个点=当前包
        base_dir = os.path.dirname(base_dir) or "."
    if not dots:
        base_dir = ""  # 绝对导入从项目根解析
    if rest:
        parts = rest.split(".")
        cand = "/".join(parts)
        for tail in (f"{cand}.py", f"{cand}/__init__.py"):
            full = os.path.normpath(os.path.join(base_dir, tail)).replace(os.sep, "/")
            if full in file_set:
                return full
    else:
        full = os.path.normpath(os.path.join(base_dir, "__init__.py")).replace(os.sep, "/")
        if full in file_set:
            return full
    return None


def _resolve_rust(mod: str, from_file: str, file_set: set,
                  registry: AliasRegistry) -> Optional[str]:
    """rust 路径: crate::a::b → 逐级回退探测最长命中前缀文件。

    模块路径每段可对应 <stem>.rs 或 <stem>/mod.rs; 深路径(a::b)找不到
    b 文件时回退到 a(声明 b 的父模块文件)——文件级边取最近命中层。
    """
    base_dir = os.path.dirname(from_file)
    if mod.startswith("crate::"):
        parts = mod.split("::")[1:]
        crate_root = "src"
        if "/src/" in from_file:
            crate_root = from_file.split("/src/")[0] + "/src"
        segments = [crate_root] + parts
    elif mod.startswith(("self::", "super::")):
        up = 2 if mod.startswith("super::") else 0
        parts = mod.split("::")[up:]
        d = base_dir
        for _ in range(up - 1 if up else 0):
            d = os.path.dirname(d)
        segments = ([d] if d else []) + parts
    else:
        return None
    # 逐级回退: 全路径 → 砍末段 → …
    for i in range(len(segments), 0, -1):
        stem = "/".join(segments[:i])
        for tail in (f"{stem}.rs", f"{stem}/mod.rs"):
            if tail in file_set:
                return tail
    return None


# ── 批量入口: imports 边改写 ──────────────────────────────────

def resolve_imports_batch(edges: List[dict], file_set: set,
                          registry: AliasRegistry,
                          jvm_package_dirs: Optional[dict] = None) -> tuple:
    """collect_snapshot imports 边批量改写。

    jvm_package_dirs: {fqcn_prefix: rel_dir}(由调用方扫描 package 声明构建;
    一期在 collect_graph 内扫描, 见 graph_collect._jvm_package_roots)。
    返回 (resolved_edges, stats): 悬空/external 丢弃。
    """
    out: List[dict] = []
    stats = {"resolved": 0, "external": 0}
    jvm = jvm_package_dirs or {}
    for e in edges or []:
        if e.get("kind") != "imports":
            out.append(e)
            continue
        src, mod = e.get("source") or "", (e.get("target") or "").strip()
        from_file = src[5:] if src.startswith("file:") else ""
        tgt = resolve_import(mod, from_file, file_set, registry)
        if tgt is None and jvm:
            for prefix, d in jvm.items():
                if mod == prefix or mod.startswith(prefix + "."):
                    parts = mod[len(prefix):].lstrip(".").split(".")
                    stem = "/".join([d] + parts)
                    hit = probe_file(stem, file_set, "jvm")
                    if hit:
                        tgt = hit
                        break
        if tgt is None:
            stats["external"] += 1
            continue
        stats["resolved"] += 1
        ne = dict(e)
        ne["target"] = f"file:{tgt}"
        out.append(ne)
    return out, stats
