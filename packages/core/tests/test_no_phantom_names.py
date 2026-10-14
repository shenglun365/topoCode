"""幻影引用扫描门禁(core 包, cv-157 教训固化)——口径同
apps/architect/tests/test_no_phantom_names.py 的模块 docstring。

Run: cd <repo> && python -m pytest packages/core/tests/test_no_phantom_names.py -q
"""
import ast
import builtins
import os

_KNOWN = set(dir(builtins)) | {"__name__", "__file__", "__doc__", "self", "cls"}
_ANNOTATION_NAMES = {
    "Optional", "Dict", "List", "Any", "Union", "Tuple", "Callable", "Set",
    "Literal", "Final", "ClassVar", "Type", "Sequence", "Mapping", "Iterable",
}


def _phantoms(path: str):
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except SyntaxError as e:
        return [(e.lineno or 0, f"<SyntaxError: {e.msg}>")]
    bound, loads = set(), {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                bound.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.Import):
            for a in node.names:
                bound.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            loads.setdefault(node.id, node.lineno)
    return [(ln, n) for n, ln in sorted(loads.items(), key=lambda x: x[1])
            if n not in bound and n not in _KNOWN and n not in _ANNOTATION_NAMES]


def test_no_phantom_names_core_hotspots():
    """扫描范围 = 本流程热点路径(plugins/runner + agent)。

    core 其余历史子包(engine/supervisor/tests 等)存在大量存量幻影/动态导入
    模式, 不在本测试射程——热点路径零容忍, 历史欠债单列。"""
    roots = [
        os.path.join(os.path.dirname(__file__), "..", "topoone", "plugins", "runner"),
        os.path.join(os.path.dirname(__file__), "..", "topoone", "agent"),
    ]
    bad = []
    for root in roots:
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if f.endswith(".py"):
                    p = os.path.join(dirpath, f)
                    for ln, n in _phantoms(p):
                        bad.append(f"{os.path.relpath(p)}:{ln}: 未绑定引用 {n!r}")
    assert not bad, (
        "存在幻影引用(重构丢行/改名漏改; 注解字符串误报在 _ANNOTATION_NAMES 豁免):\n"
        + "\n".join(bad))
