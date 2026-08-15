"""框架 API 路由提取(单文件、只读) — path/methods/handler/framework 元数据。

补充符号级解析: 识别各 Web 框架的路由声明(装饰器/注解/调用/文件约定)，
产出路由元数据，供 architect 实现层 contract(message_contract) 资产精确锚定
「哪个端点、什么方法、handler 是谁」。

返回 [{path, methods, handler, framework, line}]，line 为 1-based 声明行。

设计:
  - 行级正则扫描(路由声明形态稳定，AST 化收益低)；
  - 框架判定优先用 table.imports / import 行，其次用全文标记兜底；
  - handler 尽力解析(取声明后最近的函数定义名)，失败留空不臆造。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from ..core.symbol_model import FileSymbolTable

logger = logging.getLogger(__name__)

_VERBS = ("get", "post", "put", "delete", "patch", "options", "head")
_VERB_METHODS = {v: v.upper() for v in _VERBS}
_METHODS_ARG_RE = re.compile(r"methods\s*=\s*\[([^\]]*)\]")
_SKIP_LINE_PREFIXES = ("#", "//", "/*", "*", "@", "///")


def _imports(table: Optional[FileSymbolTable]) -> list[str]:
    if table is not None and table.imports:
        return [str(m).lower() for m in table.imports]
    return []


# 框架标识子串(小写): 在 import 模块名与全文中检索。
_FW_TEXT_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("fastapi", ("fastapi",)),
    ("flask", ("flask",)),
    ("django", ("django",)),
    ("gin", ("gin-gonic/gin",)),
    ("echo", ("labstack/echo",)),
    ("chi", ("go-chi/chi",)),
    ("net-http", ("net/http",)),
    ("express", ("express",)),
    ("nestjs", ("@nestjs",)),
    ("spring", ("springframework",)),
    ("actix", ("actix_web", "actix-web")),
    ("axum", ("axum",)),
    ("ktor", ("ktor",)),
    ("vapor", ("vapor",)),
    ("laravel", ("illuminate", "laravel")),
    ("symfony", ("symfony",)),
    ("rails", ("rails",)),
    ("sinatra", ("sinatra",)),
    ("shelf", ("shelf",)),
)
_IMPORT_LINE_RE = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.,\s()]+)|"
    r"require\(\s*(['\"])([\w./@-]+)\3"
    r"|import\s+.*?from\s+(['\"])([\w./@-]+)\5"
    r"|import\s+(['\"])([\w./-]+)\7)")


def _imports_from_text(text: str) -> list[str]:
    """从源码 import/require 行提取模块名(小写)，供框架判定。"""
    out: list[str] = []
    for m in _IMPORT_LINE_RE.finditer(text):
        mod = m.group(1) or m.group(4) or m.group(6) or m.group(8)
        if mod:
            out.append(mod.lower())
            continue
        for part in (m.group(2) or "").replace(",", " ").split():
            if part and part not in ("import", "from", "as"):
                out.append(part.rstrip(".").lower())
    return out


def _detect_frameworks(text: str, table: Optional[FileSymbolTable]) -> list[str]:
    """框架判定: table.imports + import 行优先，全文标记兜底，合并去重。"""
    found: list[str] = []
    imps = _imports(table) + _imports_from_text(text)
    for fw, markers in _FW_TEXT_MARKERS:
        if any(mk in x for x in imps for mk in markers):
            found.append(fw)
    low = (text or "").lower()
    for fw, markers in _FW_TEXT_MARKERS:
        if fw not in found and any(mk in low for mk in markers):
            found.append(fw)
    return list(dict.fromkeys(found))


def _next_def(lines: list[str], start: int, lang: str, max_lines: int = 6) -> str:
    """声明行之后最近的函数定义名(best-effort)。"""
    pats = _DEF_PATTERNS.get(lang)
    if pats is None:
        pats = (re.compile(r"([A-Za-z_]\w*)\s*\("),)
    for j in range(start, min(start + max_lines, len(lines))):
        ln = lines[j].strip()
        if not ln or ln.startswith(_SKIP_LINE_PREFIXES) or ln.startswith('"""'):
            continue
        for p in pats:
            m = p.search(ln)
            if not m:
                continue
            name = m.group(m.lastindex) if m.lastindex else m.group(1)
            if name in ("if", "for", "while", "switch", "return", "new",
                        "throw", "else", "do", "catch", "assert", "require"):
                continue
            return name
    return ""


_DEF_PATTERNS: dict[str, tuple[re.Pattern, ...]] = {
    "python": (re.compile(r"\bdef\s+([A-Za-z_]\w*)\s*\("),),
    "go": (re.compile(r"\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\("),),
    "javascript": (re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\("),
                   re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*="),
                   re.compile(r"^\s*([A-Za-z_$][\w$]*)\s*\(")),
    "typescript": (re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\("),
                   re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*="),
                   re.compile(r"^\s*([A-Za-z_$][\w$]*)\s*\(")),
    "java": (re.compile(r"([A-Za-z_]\w*)\s*\("),),
    "kotlin": (re.compile(r"\bfun\s+([A-Za-z_]\w*)\s*\("),
               re.compile(r"([A-Za-z_]\w*)\s*\(")),
    "c_sharp": (re.compile(r"([A-Za-z_]\w*)\s*\("),),
    "rust": (re.compile(r"\bfn\s+([A-Za-z_]\w*)\s*\("),),
    "swift": (re.compile(r"\bfunc\s+([A-Za-z_]\w*)\s*\("),),
    "php": (re.compile(r"\bfunction\s+([A-Za-z_]\w*)\s*\("),),
    "ruby": (re.compile(r"\bdef\s+([A-Za-z_]\w*)\s*\("),),
    "dart": (re.compile(r"([A-Za-z_]\w*)\s*\("),),
}


def _route(path: str, methods: list[str], handler: str, framework: str,
           line: int) -> dict:
    if path and not path.startswith("/"):
        path = "/" + path
    return {"path": path, "methods": methods or ["GET"], "handler": handler,
            "framework": framework, "line": line}


# ── Python: FastAPI / Flask / Django ─────────────────────────

_PY_DEC_RE = re.compile(
    r"^\s*@(?:[\w.]+\.)?(get|post|put|delete|patch|options|head|route|api_route)"
    r"\(\s*(['\"])([^'\"]+)\2")
_DJ_URL_RE = re.compile(
    r"\b(?:path|re_path)\(\s*r?(['\"])([^'\"]+)\1\s*,\s*([A-Za-z_][\w.]*)")
_ADD_API_ROUTE_RE = re.compile(
    r"\.add_api_route\(\s*(['\"])([^'\"]+)\1\s*,\s*([A-Za-z_][\w.]*)")


def _py_routes(lines: list[str], fws: list[str]) -> list[dict]:
    out: list[dict] = []
    has_fw = any(k in fws for k in ("fastapi", "flask", "django"))
    for i, ln in enumerate(lines):
        m = _PY_DEC_RE.match(ln)
        if m:
            verb, _q, path = m.groups()
            if verb in _VERBS:
                methods = [_VERB_METHODS[verb]]
                fw = ("flask" if "flask" in fws
                      else "fastapi" if "fastapi" in fws else "python-web")
            else:  # route / api_route
                blob = "\n".join(lines[i:i + 3])
                mm = _METHODS_ARG_RE.search(blob)
                methods = ([x.strip().strip("'\"").upper() for x in mm.group(1).split(",")
                            if x.strip()] if mm else ["GET", "POST"])
                fw = ("flask" if re.match(r"\s*@app\.route", ln) or "flask" in fws
                      else "fastapi")
            out.append(_route(path, methods, _next_def(lines, i + 1, "python"),
                              fw, i + 1))
            continue
        dm = _DJ_URL_RE.search(ln)
        if dm and "django" in fws:
            out.append(_route(dm.group(2), ["GET", "POST"], dm.group(3),
                              "django", i + 1))
            continue
        am = _ADD_API_ROUTE_RE.search(ln)
        if am:
            blob = "\n".join(lines[i:i + 3])
            mm = _METHODS_ARG_RE.search(blob)
            methods = ([x.strip().strip("'\"").upper() for x in mm.group(1).split(",")
                        if x.strip()] if mm else ["GET", "POST"])
            out.append(_route(am.group(2), methods, am.group(3), "fastapi", i + 1))
    if not out and not has_fw:
        return []
    return out


# ── Go: gin / echo / chi / net-http ──────────────────────────

_GO_RE = re.compile(
    r"\b(\w+)\.(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD|Any|HandleFunc)\("
    r"\s*(['\"])([^'\"]+)\3\s*,\s*([A-Za-z_][\w.]*)")


def _go_routes(lines: list[str], fws: list[str]) -> list[dict]:
    has_web = any(k in fws for k in ("gin", "echo", "chi", "net-http"))
    if not has_web and not any(_GO_RE.search(ln) for ln in lines):
        return []
    fw = ("gin" if "gin" in fws else
          "echo" if "echo" in fws else
          "chi" if "chi" in fws else "net-http")
    out: list[dict] = []
    for i, ln in enumerate(lines):
        m = _GO_RE.search(ln)
        if m:
            verb, path, handler = m.group(2), m.group(4), m.group(5)
            methods = (["GET", "POST", "PUT", "DELETE", "PATCH"]
                       if verb in ("Any", "HandleFunc") else [verb.upper()])
            out.append(_route(path, methods, handler.split(".")[-1], fw, i + 1))
    return out


# ── JS/TS: Express / NestJS / Next.js 文件约定 ────────────────

_EXPRESS_RE = re.compile(
    r"\b(\w+)\.(get|post|put|delete|patch|all)\(\s*(['\"])([^'\"]+)\3"
    r"\s*(?:,\s*([A-Za-z_$][\w$]*))?")
_CTRL_RE = re.compile(r"@Controller\(\s*(['\"])([^'\"]*)\1\s*\)")
_NEST_VERB_RE = re.compile(
    r"@(Get|Post|Put|Delete|Patch|Options|Head)"
    r"(?:\(\s*(?:['\"])([^'\"]*)['\"]\s*\))?")
_NEXT_EXPORT_RE = re.compile(
    r"\bexport\s+(?:async\s+)?(?:function|const)\s+"
    r"(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\b")


def _js_routes(lines: list[str], file_path: str, fws: list[str]) -> list[dict]:
    out: list[dict] = []
    # Next.js 文件约定: app/api/**/route.(ts|js) 或 pages/api/x.(ts|js)
    norm = (file_path or "").replace("\\", "/")
    m_next = re.search(r"(?:^|/)(?:app|pages)/api/(.+)/route\.(?:ts|tsx|js|jsx)$", norm)
    m_pages = re.search(r"(?:^|/)pages/api/(.+)\.(?:ts|tsx|js|jsx)$", norm)
    if m_next or m_pages:
        seg = (m_next or m_pages).group(1).replace("/", "/")
        path = "/api/" + seg
        methods = [m2.group(1) for m2 in (_NEXT_EXPORT_RE.search(ln) for ln in lines) if m2]
        out.append(_route(path, methods or ["GET"], "", "nextjs", 1))
    ctrl_prefix = ""
    has_express = "express" in fws or "nestjs" in fws
    for i, ln in enumerate(lines):
        cm = _CTRL_RE.search(ln)
        if cm:
            ctrl_prefix = cm.group(2).strip("/")
            continue
        vm = _NEST_VERB_RE.search(ln)
        if vm:
            verb = vm.group(1)
            sub = (vm.group(2) or "").strip("/")
            path = "/" + "/".join(x for x in (ctrl_prefix, sub) if x)
            out.append(_route(path, [verb.upper()],
                              _next_def(lines, i + 1, "typescript"), "nestjs", i + 1))
            continue
        em = _EXPRESS_RE.search(ln)
        if em:
            verb, path = em.group(2), em.group(4)
            methods = ["GET", "POST", "PUT", "DELETE", "PATCH"] if verb == "all" \
                else [verb.upper()]
            handler = em.group(5) or _next_def(lines, i + 1, "javascript")
            out.append(_route(path, methods, handler, "express", i + 1))
    if not out and not has_express:
        return []
    return out


# ── Java: Spring / Quarkus ───────────────────────────────────

_J_PREFIX_RE = re.compile(
    r"@RequestMapping\(\s*(?:value\s*=\s*|path\s*=\s*)?(['\"])([^'\"]*)\1")
_J_VERB_RE = re.compile(
    r"@(Get|Post|Put|Delete|Patch|Options|Head)Mapping"
    r"(?:\s*\(\s*(?:(?:value|path)\s*=\s*)?(['\"])([^'\"]*)\2\s*\))?")


def _java_routes(lines: list[str], fws: list[str]) -> list[dict]:
    has_spring = "spring" in fws
    if not has_spring and not any("@RequestMapping" in ln or "@GetMapping" in ln
                                  for ln in lines):
        return []
    fw = "spring"
    out: list[dict] = []
    class_prefix = ""
    for i, ln in enumerate(lines):
        m = _J_VERB_RE.search(ln)
        if m:
            path = "/" + "/".join(
                x for x in (class_prefix, (m.group(3) or "").strip("/")) if x)
            out.append(_route(path, [m.group(1).upper()],
                              _next_def(lines, i + 1, "java"), fw, i + 1))
            continue
        pm = _J_PREFIX_RE.search(ln)
        if pm:
            # 其后 3 行出现 class → 类前缀；否则方法级无 verb 映射
            tail = "\n".join(lines[i + 1:i + 4])
            if re.search(r"\bclass\s+\w+", tail):
                class_prefix = pm.group(2).strip("/")
            else:
                path = "/" + "/".join(
                    x for x in (class_prefix, pm.group(2).strip("/")) if x)
                out.append(_route(path, ["GET", "POST"],
                                  _next_def(lines, i + 1, "java"), fw, i + 1))
    return out


# ── C#: ASP.NET Core ─────────────────────────────────────────

_CS_ROUTE_RE = re.compile(r"\[Route\(\s*(['\"])([^'\"]*)\1\s*[,)\]]")
_CS_VERB_RE = re.compile(
    r"\[Http(Get|Post|Put|Delete|Patch|Options|Head)"
    r"(?:\(\s*(['\"])([^'\"]*)\2\s*\))?\]")
_CS_MAP_RE = re.compile(r"\bapp\.Map(Get|Post|Put|Delete|Patch)\(\s*(['\"])([^'\"]+)\2")
_CS_ANN_RE = re.compile(r"\[(?:Route|Http\w+)\s*[\(\]]")


def _cs_routes(lines: list[str], fws: list[str]) -> list[dict]:
    if not any(_CS_ANN_RE.search(ln) for ln in lines):
        return []
    out: list[dict] = []
    class_prefix = ""
    for i, ln in enumerate(lines):
        vm = _CS_VERB_RE.search(ln)
        if vm:
            verb, path = vm.group(1), vm.group(3) or ""
            full = "/" + "/".join(x for x in (class_prefix, path.strip("/")) if x)
            out.append(_route(full, [verb.upper()], _next_def(lines, i + 1, "c_sharp"),
                              "aspnet", i + 1))
            continue
        rm = _CS_ROUTE_RE.search(ln)
        if rm:
            tail = "\n".join(lines[i + 1:i + 4])
            if re.search(r"\bclass\s+\w+", tail):
                class_prefix = rm.group(2).strip("/")
            else:
                full = "/" + "/".join(x for x in (class_prefix, rm.group(2).strip("/")) if x)
                out.append(_route(full, ["GET", "POST"],
                                  _next_def(lines, i + 1, "c_sharp"), "aspnet", i + 1))
            continue
        mm = _CS_MAP_RE.search(ln)
        if mm:
            out.append(_route(mm.group(3), [mm.group(1).upper()], "", "aspnet", i + 1))
    return out


# ── Rust: actix-web / axum ───────────────────────────────────

_RS_ACTIX_RE = re.compile(
    r"#\[(get|post|put|delete|patch|head|options)\(\s*(['\"])([^'\"]+)\2\s*\)\]")
_RS_AXUM_RE = re.compile(
    r"\.route\(\s*(['\"])([^'\"]+)\1\s*,\s*(get|post|put|delete|patch)\s*\(?\s*([A-Za-z_:]*)")


def _rs_routes(lines: list[str], fws: list[str]) -> list[dict]:
    has_fw = any(k in fws for k in ("actix", "axum"))
    out: list[dict] = []
    for i, ln in enumerate(lines):
        am = _RS_ACTIX_RE.search(ln)
        if am:
            out.append(_route(am.group(3), [am.group(1).upper()],
                              _next_def(lines, i + 1, "rust"), "actix", i + 1))
            continue
        xm = _RS_AXUM_RE.search(ln)
        if xm:
            out.append(_route(xm.group(2), [xm.group(3).upper()], xm.group(4),
                              "axum", i + 1))
    if not out and not has_fw:
        return []
    return out


# ── Kotlin: Spring 注解 / Ktor ───────────────────────────────

_KTOR_RE = re.compile(
    r"^\s*(get|post|put|delete|patch|options|head)\(\s*(['\"])([^'\"]+)\2")


def _kt_routes(lines: list[str], fws: list[str]) -> list[dict]:
    out = _java_routes(lines, fws)
    if "ktor" in fws:
        for i, ln in enumerate(lines):
            m = _KTOR_RE.match(ln)
            if m and not ln.strip().startswith("@"):
                out.append(_route(m.group(3), [m.group(1).upper()], "", "ktor", i + 1))
    return out


# ── Ruby: Rails routes / Sinatra ─────────────────────────────

_RB_TO_RE = re.compile(
    r"^\s*(get|post|put|delete|patch)\s+(['\"])([^'\"]+)\2\s*,\s*to:\s*(['\"])([^'\"]+)\4")
_RB_BARE_RE = re.compile(r"^\s*(get|post|put|delete|patch)\s+(['\"])([^'\"]+)\2")


def _rb_routes(lines: list[str], file_path: str, fws: list[str]) -> list[dict]:
    fname = os.path.basename(file_path or "")
    out: list[dict] = []
    for i, ln in enumerate(lines):
        m = _RB_TO_RE.match(ln)
        if m:
            out.append(_route(m.group(3), [m.group(1).upper()], m.group(5),
                              "rails" if fname == "routes.rb" else "sinatra", i + 1))
            continue
        if fname != "routes.rb" and "sinatra" in fws:
            b = _RB_BARE_RE.match(ln)
            if b:
                out.append(_route(b.group(3), [b.group(1).upper()], "", "sinatra", i + 1))
    return out


# ── PHP: Laravel / Symfony ───────────────────────────────────

_PH_LARAVEL_RE = re.compile(
    r"\bRoute::(get|post|put|delete|patch|options|head)\(\s*(['\"])([^'\"]+)\2\s*,\s*([^)]+)\)")
_PH_SYMFONY_RE = re.compile(
    r"#\[(Route|Get|Post|Put|Delete|Patch)\(\s*(?:path\s*=\s*)?(['\"])([^'\"]*)\2")


def _ph_routes(lines: list[str], fws: list[str]) -> list[dict]:
    out: list[dict] = []
    for i, ln in enumerate(lines):
        m = _PH_LARAVEL_RE.search(ln)
        if m:
            arg = m.group(4).strip()
            mm = re.search(r"(\w+)::class\s*,\s*['\"](\w+)['\"]", arg)
            handler = f"{mm.group(1)}::{mm.group(2)}" if mm else \
                (arg.strip("'\" ") if "@" in arg else "")
            out.append(_route(m.group(3), [m.group(1).upper()], handler, "laravel", i + 1))
            continue
        sm = _PH_SYMFONY_RE.search(ln)
        if sm:
            verb = sm.group(1)
            methods = ["GET", "POST"] if verb == "Route" else [verb.upper()]
            out.append(_route(sm.group(3) or "/", methods,
                              _next_def(lines, i + 1, "php"), "symfony", i + 1))
    return out


# ── Swift: Vapor ─────────────────────────────────────────────

_SW_RE = re.compile(r"\broutes\.(get|post|put|delete|patch)\(\s*(['\"])([^'\"]+)\2")


def _sw_routes(lines: list[str], fws: list[str]) -> list[dict]:
    out: list[dict] = []
    for i, ln in enumerate(lines):
        m = _SW_RE.search(ln)
        if m:
            out.append(_route(m.group(3), [m.group(1).upper()], "", "vapor", i + 1))
    return out


# ── Scala: Play routes 文件 ──────────────────────────────────

_PLAY_RE = re.compile(r"^(GET|POST|PUT|DELETE|PATCH)\s+(/\S*)\s+([\w.]+)\.(\w+)")


def _scala_routes(lines: list[str], file_path: str) -> list[dict]:
    fname = os.path.basename(file_path or "")
    if fname != "routes" and not any(_PLAY_RE.match(ln) for ln in lines[:5]):
        return []
    out: list[dict] = []
    for i, ln in enumerate(lines):
        m = _PLAY_RE.match(ln.strip())
        if m:
            out.append(_route(m.group(2), [m.group(1)], f"{m.group(3)}.{m.group(4)}",
                              "play", i + 1))
    return out


# ── Dart: shelf 路由 ─────────────────────────────────────────

_DART_RE = re.compile(r"\b(\w+)\.(get|post|put|delete|patch)\(\s*(['\"])([^'\"]+)\3")


def _dart_routes(lines: list[str], fws: list[str]) -> list[dict]:
    out: list[dict] = []
    for i, ln in enumerate(lines):
        m = _DART_RE.search(ln)
        if m:
            out.append(_route(m.group(4), [m.group(2).upper()], "", "shelf", i + 1))
    return out


# ── 统一入口 ─────────────────────────────────────────────────

def extract_routes(language: str, file_path: str, source_text: str,
                   table: Optional[FileSymbolTable] = None) -> list[dict]:
    """单文件框架路由提取。language 用 walker 语言名(c_sharp 等)。"""
    lang = (language or "").lower()
    if lang == "vue":
        lang = "typescript"
    text = source_text or ""
    if not text:
        return []
    lines = text.split("\n")
    fws = _detect_frameworks(text, table)
    try:
        if lang == "python":
            out = _py_routes(lines, fws)
        elif lang == "go":
            out = _go_routes(lines, fws)
        elif lang in ("javascript", "typescript", "tsx", "jsx"):
            out = _js_routes(lines, file_path, fws)
        elif lang == "java":
            out = _java_routes(lines, fws)
        elif lang in ("c_sharp", "csharp"):
            out = _cs_routes(lines, fws)
        elif lang == "rust":
            out = _rs_routes(lines, fws)
        elif lang == "kotlin":
            out = _kt_routes(lines, fws)
        elif lang == "ruby":
            out = _rb_routes(lines, file_path, fws)
        elif lang == "php":
            out = _ph_routes(lines, fws)
        elif lang == "swift":
            out = _sw_routes(lines, fws)
        elif lang == "scala":
            out = _scala_routes(lines, file_path)
        elif lang == "dart":
            out = _dart_routes(lines, fws)
        else:
            out = []
    except Exception as e:
        logger.warning("routes extract failed for %s: %s", file_path, e)
        out = []
    # 去重(同 path+methods+line)
    seen: set = set()
    dedup = []
    for r in out:
        key = (r["path"], tuple(r["methods"]), r["line"])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)
    return dedup
