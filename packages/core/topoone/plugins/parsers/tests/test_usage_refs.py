"""标识符使用收集(引用/赋值/传参)单元测试 — walker 通用 refs 扩展。

Run:  cd <repo>/topoone/plugins/parsers && python -m pytest tests/test_usage_refs.py -q

保障点:
  1. 新类别 refs 正确产出(passes/assigns/references)
  2. 既有 calls/instantiates 收集逐条不变(社区分析输入安全保证)
  3. 定义名/形参位/调用名/成员属性位/导入语句不误报
"""
import os
import sys

_here = os.path.dirname(__file__)
sys.path.insert(0, _here)
sys.path.insert(0, os.path.join(_here, "..", "parsers"))

from parsers.core.walker import TreeSitterWalker  # noqa: E402
from parsers.core.node_types import EdgeKind  # noqa: E402
from parsers.languages import EXTRACTORS  # noqa: E402


def _walk(source: str, language: str):
    ex = EXTRACTORS.get(language)
    assert ex is not None, f"no extractor for {language}"
    w = TreeSitterWalker(f"test.{language}", source.encode("utf-8"), language, ex)
    return w.extract()


def _refs_by_kind(table, kind):
    return [(r.reference_name, r.line) for r in table.unresolved_refs
            if r.reference_kind == kind]


# ── Python ────────────────────────────────────────────────────

_PY_SRC = '''
import helper

TOTAL = 0

def compute(x):
    return helper.scale(x)

def run(items):
    total = compute(TOTAL)
    result = helper
    return result
'''


def test_python_new_kinds():
    t = _walk(_PY_SRC, "python")
    passes = _refs_by_kind(t, EdgeKind.PASSES)
    assigns = _refs_by_kind(t, EdgeKind.ASSIGNS)
    references = _refs_by_kind(t, EdgeKind.REFERENCES)
    # 实参(已声明符号): compute(TOTAL) → passes TOTAL；形参名实参被 decl 过滤(设计行为)
    assert ("TOTAL", 10) in passes, f"passes 缺 TOTAL: {passes}"
    # 赋值右侧: result = helper → helper(assigns)
    assert ("helper", 11) in assigns, f"assigns 缺 helper: {assigns}"
    # 普通引用: return result
    assert ("result", 12) in references, f"references 缺 result: {references}"
    # 形参名实参(x/it)不入 refs——decl 过滤挡住
    assert ("x", 7) not in passes


def test_python_no_false_positives():
    t = _walk(_PY_SRC, "python")
    all_refs = [(r.reference_kind, r.reference_name, r.line)
                for r in t.unresolved_refs]
    # 定义名/形参位不产出使用 ref
    for k, name, line in all_refs:
        assert not (name in ("compute", "run", "items", "x") and k == EdgeKind.REFERENCES), \
            f"定义/形参误报: {k} {name}@{line}"
        assert not (name == "TOTAL" and line == 4 and k == EdgeKind.ASSIGNS), "LHS 赋值目标误报"
    # 导入语句内不产出
    assert not any(name == "helper" and line == 2 for _, name, line in all_refs), \
        f"import 行误报: {all_refs}"


def test_python_calls_unchanged():
    """社区分析输入安全保证: calls 收集与基线逐条一致。"""
    t = _walk(_PY_SRC, "python")
    calls = set(_refs_by_kind(t, EdgeKind.CALLS))
    # helper.scale(7) / compute(TOTAL)(10) — 每调用点一条
    assert calls == {("helper.scale", 7), ("compute", 10)}, f"calls 漂移: {calls}"


# ── TypeScript ────────────────────────────────────────────────

_TS_SRC = '''
import { fmt } from './fmt';

export function render(items) {
  const cache = new Map();
  let out = fmt(cache);
  cache.set('k', out);
  return out;
}
'''


def test_ts_new_kinds():
    t = _walk(_TS_SRC, "typescript")
    passes = _refs_by_kind(t, EdgeKind.PASSES)
    references = _refs_by_kind(t, EdgeKind.REFERENCES)
    # 形参名实参被 decl 过滤(设计行为)
    assert ("items", 6) not in passes
    # 已声明符号实参: fmt(cache) / cache.set('k', out)
    assert ("cache", 6) in passes, f"passes 缺 cache: {passes}"
    assert ("out", 7) in passes, f"passes 缺 out(cache.set 实参): {passes}"
    assert ("out", 8) in references, f"references 缺 out: {references}"


def test_ts_calls_unchanged():
    t = _walk(_TS_SRC, "typescript")
    calls = set(_refs_by_kind(t, EdgeKind.CALLS))
    instantiates = set(_refs_by_kind(t, EdgeKind.INSTANTIATES))
    assert ("fmt", 6) in calls, f"calls 缺 fmt: {calls}"
    assert ("cache.set", 7) in calls, f"calls 缺 cache.set: {calls}"
    assert ("Map", 5) in instantiates, f"instantiates 缺 Map: {instantiates}"
    # fmt 调用名不重复产出 references
    for k, name, line in [(r.reference_kind, r.reference_name, r.line)
                          for r in t.unresolved_refs]:
        assert not (name == "fmt" and line == 6 and k == EdgeKind.REFERENCES), \
            "调用名重复收集"
