"""幻影引用扫描门禁(cv-157 教训固化): 全文件从未绑定即 Load = 红。

9-13 重构曾一次产生 5 处幻影(_ws_send/run_arch_tool/_srow_to_api/target/logger
+_req_chat_stream 函数体丢失), 测试全绿两天——静态扫描零成本拦截此类事故。

扫描口径(保守, 控误报):
  - 绑定集 = 模块内全部 def/class 名 + import 名 + 所有 Name-Store + except as +
    arg 参数(任意层级)——跨函数共享同一集合, 因此函数局部变量被其他函数引用
    这类「作用域错误」不在此测试射程(交给运行时/集成测试);
  - 只报「全文件无任何绑定就被 Load」——恰是重构丢行/改名漏改的形状;
  - 注解字符串白名单: `from __future__ import annotations` 下 Optional/Dict 等
    运行时不求值; typing 名单硬编码豁免。

Run: cd <repo> && python -m pytest apps/architect/tests/test_no_phantom_names.py -q
"""
import ast
import builtins
import os

import pytest

_PKG_ROOT = os.path.join(os.path.dirname(__file__), "..", "topoone_app_architect")

# 注解字符串豁免(annotations 导入下运行时不求值; 手写新误报可加行)
_ANNOTATION_NAMES = {
    "Optional", "Dict", "List", "Any", "Union", "Tuple", "Callable", "Set",
    "Literal", "Final", "ClassVar", "Type", "Sequence", "Mapping", "Iterable",
}
_KNOWN = set(dir(builtins)) | {"__name__", "__file__", "__doc__", "self", "cls",
                               "__all__", "__version__"}


def _py_files(root: str):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


def _phantoms(path: str):
    """返回 [(lineno, name)]; 见模块 docstring 的保守口径。"""
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except SyntaxError as e:
        return [(e.lineno or 0, f"<SyntaxError: {e.msg}>")]
    bound = set()
    loads = {}
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


def test_no_phantom_names_architect_package():
    bad = []
    for p in _py_files(_PKG_ROOT):
        for ln, n in _phantoms(p):
            bad.append(f"{os.path.relpath(p)}:{ln}: 未绑定引用 {n!r}")
    assert not bad, (
        "存在幻影引用(重构丢行/改名漏改; 若为注解字符串误报请在 "
        "_ANNOTATION_NAMES 豁免):\n" + "\n".join(bad))


def test_scan_covers_hotspot_files():
    """扫描器自身健康检查: 热点文件必须在扫描范围内(cv-157 事故文件)。"""
    hotspots = [
        os.path.join(_PKG_ROOT, "agent", "orchestrator.py"),
        os.path.join(_PKG_ROOT, "arch_routes", "exec_bridge.py"),
        os.path.join(_PKG_ROOT, "arch_routes", "req_agent.py"),
    ]
    for h in hotspots:
        assert os.path.isfile(h), h
        # 烟囱验证: 人为注入幻影必须被抓到
        assert _phantoms(h) is not None


def test_scanner_catches_injected_phantom(tmp_path):
    """扫描器自检: 注入 _ws_send 式幻影的文件必须报红(防扫描器腐化)。"""
    f = tmp_path / "mod.py"
    f.write_text(
        "def ok_fn(send):\n"
        "    await send({'a': 1})\n"
        "\n"
        "def broken_fn(request_id):\n"
        "    await _ws_send({'rid': request_id})\n",   # 幻影: _ws_send 从未绑定
        encoding="utf-8")
    phantoms = _phantoms(str(f))
    names = {n for _, n in phantoms}
    assert "_ws_send" in names, phantoms
    # 注解豁免仍生效
    f2 = tmp_path / "anno.py"
    f2.write_text(
        "from __future__ import annotations\n"
        "def f(x) -> Optional[dict]:\n"
        "    return x\n", encoding="utf-8")
    assert _phantoms(str(f2)) == []
