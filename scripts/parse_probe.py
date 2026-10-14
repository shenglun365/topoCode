#!/usr/bin/env python3
"""parse_probe — 多语言解析缺口离线探测(不走服务/不落库)

对 soft 下所有项目抽样源码, 用生产同款 TreeSitterWalker 离线解析, 对照
源码 grep 实数(探针)产出 语言×形态 缺口矩阵。用于定位 extractor 缺口,
修复后仍需对代表项目跑全量分析做端到端确认。

用法: python3 scripts/parse_probe.py [root]        # 默认 /home/cuser/soft
      python3 scripts/parse_probe.py <单个项目目录>
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "packages", "core"))

from topoone.plugins.parsers.parsers.core.walker import TreeSitterWalker, _detect_language
from topoone.plugins.parsers.parsers.language_loader import detect_header_language
from topoone.plugins.parsers.parsers.languages import EXTRACTORS
from topoone.plugins.parsers.parsers.language_loader import get_parser

SAMPLE_PER_LANG = 40          # 每(项目,语言)抽样文件上限
KIND_TOP = 8                  # 输出 kind 分布 top N
GAP_RATIO = 0.40              # 探针实然/应然低于此值报缺口
WARN_MIN_SHOULD = 8           # 探针应然值太小时不判缺口(噪声)

# 探针: kind → 源码行锚定正则(估算应然值, 允许量级噪声)
PROBES = {
    "python": {
        "function": r"^\s*(async\s+)?def\s+\w",
        "class": r"^\s*class\s+\w",
    },
    "javascript": {
        "function": r"^\s*(export\s+)?(default\s+)?(async\s+)?function\s*\*?\s+\w",
        "class": r"^\s*(export\s+)?(default\s+)?(abstract\s+)?class\s+\w",
        # 对象/类方法 shorthand: 排除 for/if/while/switch/catch 等控制流首词
        "method": r"^\s+(static\s+)?(async\s+)?(?!for\b|if\b|while\b|switch\b|catch\b|else\b|return\b|do\b|try\b|function\b)\w+\s*\([^()]*\)\s*\{\s*$",
    },
    "typescript": {
        "function": r"^\s*(export\s+)?(default\s+)?(async\s+)?function\s*\*?\s+\w",
        "class": r"^\s*(export\s+)?(default\s+)?(abstract\s+)?class\s+\w",
        "interface": r"^\s*(export\s+)?interface\s+\w",
        "method": r"^\s+(public\s+|private\s+|protected\s+)?(static\s+)?(async\s+)?(?!for\b|if\b|while\b|switch\b|catch\b|else\b|return\b|do\b|try\b)\w+\s*\([^()]*\)\s*:\s*\w+[^;]*\{\s*$",
    },
    "go": {
        "function": r"^func\s+\w",
        "method": r"^func\s+\([^)]+\)\s+\w",
        "struct": r"^type\s+\w+\s+struct\s*\{",
        "interface": r"^type\s+\w+\s+interface\s*\{",
    },
    "rust": {
        "function": r"^\s*(pub(\(\w+\))?\s+)?(const\s+)?(async\s+)?(unsafe\s+)?(extern\s+\"[^\"]*\"\s+)?fn\s+\w",
        "struct": r"^\s*(pub(\(\w+\))?\s+)?struct\s+\w",
        "impl": r"^\s*impl\b",
        "trait": r"^\s*(pub(\(\w+\))?\s+)?trait\s+\w",
    },
    "java": {
        "class": r"^\s*(public\s+|private\s+|protected\s+)?(static\s+)?(final\s+|abstract\s+)*class\s+\w",
        "interface": r"^\s*(public\s+)?interface\s+\w",
        "method": r"^\s+(public\s+|private\s+|protected\s+|static\s+|final\s+|synchronized\s+)+[\w<>\[\],\s]+\s+\w+\s*\([^;)]*\)\s*(throws\s+[\w,\s]+)?\{\s*$",
    },
    "php": {
        "class": r"^\s*(abstract\s+|final\s+)?class\s+\w",
        "function": r"^\s*function\s+\w",
        "method": r"^\s+(public\s+|private\s+|protected\s+|static\s+)+function\s+\w",
    },
    "c": {
        "struct": r"^\s*typedef\s+struct\b|^\s*struct\s+\w+\s*\{",
        "enum": r"^\s*typedef\s+enum\b|^\s*enum\s+\w+\s*\{",
    },
    "cpp": {
        "class": r"^\s*(template\s*<[^>]*>\s*)?(class|struct)\s+\w",
        "function": r"^\s*[\w:<>,\s\*&~]+\s+\w+\s*\([^;]*\)\s*(const\s*)?\{",
    },
    "c_sharp": {
        "class": r"^\s*(public\s+|private\s+|internal\s+|protected\s+)?(static\s+|sealed\s+|abstract\s+|partial\s+)*class\s+\w",
        "interface": r"^\s*(public\s+)?interface\s+\w",
        "method": r"^\s+(public\s+|private\s+|protected\s+|internal\s+|static\s+|async\s+|override\s+|virtual\s+)+[\w<>\[\],\s?]+\s+\w+\s*\([^;)]*\)\s*\{\s*$",
    },
    "ruby": {
        "class": r"^\s*(class\s+\w)",
        "method": r"^\s*def\s+\w",
    },
    "kotlin": {
        "class": r"^\s*(public\s+|private\s+|internal\s+)?(open\s+|abstract\s+|final\s+|data\s+|sealed\s+)*(class\s+\w)",
        "function": r"^\s*(public\s+|private\s+|internal\s+|protected\s+)?(open\s+|override\s+|suspend\s+|inline\s+|private\s+)*fun\s+\w",
    },
    "swift": {
        "class": r"^\s*(public\s+|private\s+|open\s+|final\s+)?(class|struct)\s+\w",
        "function": r"^\s*(public\s+|private\s+|open\s+|internal\s+)?(static\s+)?(func\s+\w)",
    },
    "scala": {
        "class": r"^\s*(final\s+|abstract\s+|case\s+)*class\s+\w",
        "trait": r"^\s*(sealed\s+|private\s+)?trait\s+\w",
    },
    "lua": {
        "function": r"^\s*(local\s+)?function\s+\w",
    },
    "objc": {
        "interface": r"^\s*@interface\s+\w",
        "implementation": r"^\s*@implementation\s+\w",
    },
    "dart": {
        "class": r"^\s*(abstract\s+)?class\s+\w",
        "function": r"^\s*(Future<[^>]*>|void|int|String|bool|double|var)\s+\w+\s*\(",
    },
    "vue": {
        "function": r"^\s*(export\s+)?(default\s+)?(async\s+)?function\s*\*?\s+\w",
        "class": r"^\s*(export\s+)?(default\s+)?(abstract\s+)?class\s+\w",
    },
}

# 解析 kind → 探针 kind 对齐(探针名与 NodeKind 值不一致时映射)
KIND_ALIAS = {
    "impl": "method",            # rust impl 块数≈方法载体, 对比 method+function 之和
}


def should_kind(kind: str) -> str:
    return KIND_ALIAS.get(kind, kind)


def iter_source_files(root: str):
    """项目内源码文件 → {lang: [abs_path]}"""
    by_lang = defaultdict(list)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (
            ".git", "node_modules", "__pycache__", ".codegraph", ".topocode",
            "dist", "build", "target", "vendor", ".venv", "venv")]
        for fn in filenames:
            lang = _detect_language(fn)
            if lang:
                by_lang[lang].append(os.path.join(dirpath, fn))
    return by_lang


def sample(files: list, cap: int = SAMPLE_PER_LANG):
    """均匀步进采样(排序后), 保证目录分散"""
    files = sorted(files)
    if len(files) <= cap:
        return files
    step = len(files) / cap
    return [files[min(int(i * step), len(files) - 1)] for i in range(cap)]


def probe_source(lines: list, lang: str) -> dict:
    """源码探针: {kind: 应然值}"""
    out = {}
    pats = PROBES.get(lang, {})
    compiled = {k: re.compile(p) for k, p in pats.items()}
    for ln in lines:
        for kind, rx in compiled.items():
            if rx.match(ln):
                out[kind] = out.get(kind, 0) + 1
    return out


def probe_project(path: str) -> dict:
    by_lang = iter_source_files(path)
    result = {"project": os.path.basename(path.rstrip("/")), "languages": {}}
    for lang, files in sorted(by_lang.items()):
        try:
            has_parser = get_parser(lang) is not None
        except Exception as e:
            result["languages"][lang] = {"error": f"parser broken: {e}", "files_total": len(files)}
            continue
        if lang not in EXTRACTORS or not has_parser:
            result["languages"][lang] = {"error": "no extractor/parser", "files_total": len(files)}
            continue
        picked = sample(files)
        kind_cnt = Counter()
        ok = err = 0
        src_bytes_total = 0
        unresolved = Counter()          # 未解析调用名
        calls_total = 0
        probe_should = Counter()        # 探针应然(全量行扫, 不止抽样文件——抽样文件行即可)
        probe_got = Counter()          # 探针实然(抽样文件解析结果)
        for fp in picked:
            try:
                with open(fp, "rb") as fh:
                    raw = fh.read()
            except OSError:
                continue
            if len(raw) > 500 * 1024:
                continue
            lang_key = lang
            if lang == "c" and fp.endswith((".h", ".hh")):
                lang_key = detect_header_language(raw)
            try:
                w = TreeSitterWalker(fp, raw, lang_key, EXTRACTORS[lang_key])
                table = w.extract()
            except Exception:
                err += 1
                continue
            ok += 1
            src_bytes_total += len(raw)
            for n in table.nodes:
                kind_cnt[n.kind.value] += 1
            lines = raw.decode("utf-8", errors="replace").splitlines()
            for kind, cnt in probe_source(lines, lang_key).items():
                probe_should[kind] += cnt
            for ref in table.unresolved_refs:
                if ref.reference_kind.value == "calls":
                    calls_total += 1
                    unresolved[ref.reference_name] += 1
        # 探针对齐: 实然从解析 kind 取(口径: 分类归并后对比)
        for kind in probe_should:
            target = should_kind(kind)
            got = kind_cnt.get(target, 0)
            if kind == "impl":
                got = kind_cnt.get("method", 0) + kind_cnt.get("function", 0)
            # python def 总数对比 function+method(类方法记 method);
            # js/ts method(含对象字面量方法)对比 method+function(对象方法记 function)
            if kind == "function" and lang_key == "python" or kind == "method" and lang_key in ("javascript", "typescript", "tsx", "vue"):
                got += kind_cnt.get("method" if kind == "function" else "function", 0)
            probe_got[kind] = got
        cov = {}
        for kind, should in probe_should.items():
            if should >= WARN_MIN_SHOULD:
                cov[kind] = round(probe_got.get(kind, 0) / should, 2)
        result["languages"][lang] = {
            "files_total": len(files), "files_parsed": ok, "files_error": err,
            "src_kb": round(src_bytes_total / 1024),
            "symbols": sum(v for k, v in kind_cnt.items() if k != "file"),
            "density_per_kb": round(sum(v for k, v in kind_cnt.items() if k != "file") / max(src_bytes_total / 1024, 1), 1),
            "kinds": dict(kind_cnt.most_common(KIND_TOP)),
            "calls": calls_total,
            "calls_unresolved_top": dict(unresolved.most_common(5)),
            "probe_coverage": cov,
            "probe_raw": {"should": dict(probe_should), "got": dict(probe_got)},
        }
    return result


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "/home/cuser/soft"
    projects = [root] if os.path.isfile(os.path.join(root, ".git")) or not os.path.isdir(root) else \
               [os.path.join(root, d) for d in sorted(os.listdir(root))
                if os.path.isdir(os.path.join(root, d)) and not d.startswith(".")]
    results = []
    for p in projects:
        r = probe_project(p)
        if r["languages"]:
            results.append(r)
            brief = ", ".join(f"{lg}:{v.get('symbols', v.get('error','?'))}" for lg, v in r["languages"].items())
            print(f"  [scan] {r['project']}: {brief}", flush=True)

    # ── 汇总输出 ──
    print(f"\n{'='*100}\n缺口矩阵(覆盖率 < {GAP_RATIO} 且应然 ≥ {WARN_MIN_SHOULD} 才报)\n{'='*100}")
    gaps = []
    for r in results:
        for lang, v in r["languages"].items():
            if "error" in v:
                gaps.append((r["project"], lang, "EXTRACTOR", v.get("files_total"), v["error"]))
                continue
            for kind, c in v["probe_coverage"].items():
                if c < GAP_RATIO:
                    gaps.append((r["project"], lang, kind, v["probe_raw"]["should"].get(kind, 0), f"覆盖 {c:.0%}"))
    if gaps:
        for proj, lang, kind, should, note in gaps:
            print(f"  {proj:<28} {lang:<12} {kind:<12} 应然≈{should:<6} {note}")
    else:
        print("  (无缺口)")

    print(f"\n{'='*100}\n语言汇总(各项目同语言合并)\n{'='*100}")
    agg = defaultdict(lambda: {"files": 0, "symbols": 0, "kb": 0, "calls": 0})
    for r in results:
        for lang, v in r["languages"].items():
            if "error" in v:
                continue
            a = agg[lang]
            a["files"] += v["files_parsed"]
            a["symbols"] += v["symbols"]
            a["kb"] += v["src_kb"]
            a["calls"] += v["calls"]
    for lang, a in sorted(agg.items()):
        print(f"  {lang:<12} 文件{a['files']:>6}  符号{a['symbols']:>7}  {a['kb']:>7}KB  "
              f"密度{a['symbols']/max(a['kb'],1):.1f}/KB  calls{a['calls']:>6}")

    print(f"\n{'='*100}\n未解析调用 top(全局, 每语言)\n{'='*100}")
    for r in results:
        for lang, v in r["languages"].items():
            top = v.get("calls_unresolved_top") or {}
            if top:
                names = ", ".join(f"{k}({n})" for k, n in list(top.items())[:5])
                print(f"  {r['project']:<28} {lang:<12} {names}")

    out_path = "/tmp/opencode/parse_probe.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)
    print(f"\n明细 JSON: {out_path}")


if __name__ == "__main__":
    main()
