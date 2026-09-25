#!/usr/bin/env python3
"""
MS6 通用 Vue 组件机械抽取管线（W2 管线固化版）。
用法：改底部 CONFIG 后运行。域内逐行原文；跨域标识符自动 D.<域>. 前缀；
类型提升模块级 export；import 按 body 引用随迁（聚合按源，默认导入保原样）。
规则与陷阱详见 docs/refactor/MS6-frontend-components.md §8。
"""
import re, sys, json
from collections import OrderedDict

SRC = sys.argv[1]
OUTDIR = sys.argv[2]
PREFIX = sys.argv[3]        # composable 前缀, 如 useChat
TYPENAME = sys.argv[4]      # WsDeps 类型名, 如 ChatDeps
CONFIG = json.load(open(sys.argv[5]))  # {"domains": {"data": [[a,b],...]}, "keep_tail_from": 1062}

src = open(SRC).read()
lines = src.splitlines(keepends=True)

DOMAINS = {k: [tuple(x) for x in v] for k, v in CONFIG["domains"].items()}
TAIL = CONFIG.get("keep_tail_from")

marker_re = re.compile(r"^(export )?(async )?function |^(const|let) |^interface |^type |^watch\(|^onMounted|^onUnmounted|^onBeforeUnmount|^defineProps|^defineEmits")
def top_defs(a, b):
    names = {}
    for i in range(a, b+1):
        if marker_re.match(lines[i-1]) and not lines[i-1].startswith("/*"):
            mm = re.search(r"(?:function|const|let|interface|type|watch|onMounted|onUnmounted|onBeforeUnmount)\s+\(?(\w+)", lines[i-1])
            if mm: names[mm.group(1)] = i
    return names

defs = {}
for d, rs in DOMAINS.items():
    dd = {}
    for a, b in rs: dd.update(top_defs(a, b))
    defs[d] = dd
name2dom = {n: d for d, dd in defs.items() for n in dd}
TYPE_NAMES = set()
for d, rs in DOMAINS.items():
    for a, b in rs:
        for i in range(a, b+1):
            m = re.match(r"^(?:export )?(?:interface|type) (\w+)", lines[i-1])
            if m: TYPE_NAMES.add(m.group(1))
REWRITE = {n: dm for n, dm in name2dom.items() if n not in TYPE_NAMES}

sfc_imports = OrderedDict()
sfc_default = {}
for l in src.splitlines():
    m = re.match(r"import (type )?\{([^}]*)\} from '([^']+)'", l)
    if m:
        for item in m.group(2).split(","):
            item = item.strip()
            if not item: continue
            if " as " in item: n, a = [x.strip() for x in item.split(" as ")]
            else: n = a = item
            sfc_imports.setdefault(m.group(3), []).append((n, a, bool(m.group(1))))
    else:
        m2 = re.match(r"import (\w+) from '([^']+)'", l)
        if m2: sfc_default[m2.group(2)] = l.rstrip()

def rewrite(seg, d):
    names = sorted([n for n, dm in REWRITE.items() if dm != d], key=len, reverse=True)
    for n in names:
        seg = re.sub(r"(?<![\w.$'\"])"+re.escape(n)+r"\b(?!\s*[:\"?])", f"D.{REWRITE[n]}.{n}", seg)
    return seg

def has_word(body, w):
    return re.search(r"(?<![\w.$'\"])"+re.escape(w)+r"\b", body) is not None

ret_all = []
order = list(DOMAINS.keys())
for d in order:
    body = "".join("".join(lines[a-1:b]) for a, b in DOMAINS[d])
    body = rewrite(body, d)
    ret_vals = [n for n in sorted(defs[d]) if n not in TYPE_NAMES]
    ret_all += ret_vals
    own = set(defs[d])
    groups = OrderedDict()
    for source, items in sfc_imports.items():
        need = []
        for (n, a, istype) in items:
            if n in own or n in TYPE_NAMES: continue
            if has_word(body, a): need.append((n, a, istype))
        if need: groups[source] = need
    imp_lines = []
    for source, need in groups.items():
        if source in sfc_default:
            name = list(sfc_default.keys()) and [k for k, v in sfc_default.items() if k == source][0]
            if has_word(body, re.match(r"import (\w+) from", sfc_default[source]).group(1)):
                imp_lines.append(sfc_default[source])
            continue
        istype_all = all(t for (_, _, t) in need)
        kw = "import type " if istype_all else "import "
        names = ", ".join((n if n == a else f"{n} as {a}") for (n, a, _) in need)
        imp_lines.append(f"{kw}{{ {names} }} from '{source}'")
    use_i18n = re.search(r"(?<![\w.$'\"])t\(", body) is not None
    if use_i18n and not any("vue-i18n" in l for l in imp_lines):
        imp_lines.append("import { useI18n } from 'vue-i18n'")
    out = "/**\n * %s · %s 域（MS6-W3 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。\n */\n" % (PREFIX, d)
    out += "\n".join(imp_lines) + "\n"
    out += f"\nimport type {{ {TYPENAME} }} from './chatTypes'\n"
    hoisted = []
    def grab(mo):
        hoisted.append(mo.group(0)); return ""
    body2 = re.sub(r"^(?:export )?(interface \w+[^{]*\{[^}]*?\n\}|type \w+ = [^\n]+)\n", grab, body, flags=re.M)
    if hoisted:
        out += "\n" + "\n".join(h.lstrip() for h in hoisted).replace("\ninterface ", "\nexport interface ").replace("\ntype ", "\nexport type ") + "\n"
    out += f"\nexport function {PREFIX}{d.capitalize()}(D: {TYPENAME}) {{\n"
    if use_i18n: out += "  const { t } = useI18n()\n"
    if re.search(r"\bprops\.", body): out += "  const props = D.props\n"
    if re.search(r"\bemit\(", body): out += "  const emit = D.emit\n"
    out += "\n" + body2.rstrip() + "\n\n  return {\n    " + ",\n    ".join(ret_vals) + ",\n  }\n}\n"
    open(f"{OUTDIR}/{PREFIX}{d.capitalize()}.ts", "w").write(out)
    print(d, len(out.splitlines()), "lines,", len(ret_vals), "returns,", len(imp_lines), "imports")

open(f"{OUTDIR}/chatTypes.ts", "w").write(f"""/**
 * {PREFIX} · 跨域依赖袋（MS6-W3 机械抽取）。
 * 刻意宽松(any)：各域按声明顺序惰性互引(computed 天然惰性)。
 */
export interface {TYPENAME} {{ [k: string]: any }}
""")

# SFC 手术
cuts = []
for d, rs in DOMAINS.items(): cuts.extend(rs)
for a, b in sorted(cuts, reverse=True):
    lines[a-1:b] = []
src2 = "".join(lines)
join_names = ",\n  ".join(sorted(set(ret_all))) + ","
wiring = "\n".join(["",
f"// ---- MS6-W3: 逻辑层{len(DOMAINS)}域({OUTDIR.split('/')[-1]}/)——本文件保留 props/emit/模板 ----",
f"const D: {TYPENAME} = {{ props, emit }}"] +
[f"D.{d} = {PREFIX}{d.capitalize()}(D)" for d in order] +
["const ws = Object.assign({}, " + ", ".join(f"D.{d}" for d in order) + ")",
"provide(WS_KEY, ws)",
"const {",
"  " + join_names,
"} = ws",
""])
# 锚点: 唯一字符串定位(切割后行号会漂移——W3 教训)
ANCHOR = CONFIG.get("anchor", "onUnmounted((")
idx = src2.index(ANCHOR)
src2 = src2[:idx] + wiring + "\n" + src2[idx:]
imp_parts = []
for d in order:
    imp_parts.append("import { %s%s } from './%s/%s%s'" % (PREFIX, d.capitalize(), OUTDIR.split('/')[-1], PREFIX, d.capitalize()))
imp_parts.append("import type { %s } from './%s/chatTypes'" % (TYPENAME, OUTDIR.split('/')[-1]))
imp_parts.append("import { provide } from 'vue'")
imp_parts.append("import { WS_KEY } from './%s/key'" % OUTDIR.split('/')[-1])
imp = chr(10).join(imp_parts)
open(SRC, "w").write(src2)
print("SFC", len(src2.splitlines()), "lines;", len(set(ret_all)), "destructured")
