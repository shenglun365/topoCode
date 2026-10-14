"""稳定符号/边 ID 契约测试 — core/ids.py + TreeSitterWalker 集成。

身份语义(见 parsers/core/ids.py):
1. 行号位移(插入空行/注释/上方代码)不改变符号 ID;
2. 符号内容改名 → ID 变; 父级改名 → 子符号 ID 变(身份传播);
3. 同文件同 kind 同限定名(重载)按源码序 #N 消歧, 无静默覆盖;
4. 边 ID 对同一 (source, target, kind) 确定, 与节点行号无关。

Run:  cd <repo> && python -m pytest plugins/parsers/tests/test_stable_ids.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)
sys.path.insert(0, os.path.join(_repo, "plugins", "parsers"))

from parsers.core.walker import TreeSitterWalker  # noqa: E402
from parsers.core.ids import make_node_id, make_edge_id  # noqa: E402
from parsers.core.node_types import EdgeKind  # noqa: E402
from parsers.languages import EXTRACTORS  # noqa: E402


def _walk(source: str, language: str = "python", file_path: str = "src/mod.py"):
    ex = EXTRACTORS.get(language)
    assert ex is not None, f"no extractor for {language}"
    w = TreeSitterWalker(file_path, source.encode("utf-8"), language, ex)
    return w.extract()


def _ids_by_qn(table):
    return {n.qualified_name: n.id for n in table.nodes}


# ── 1. 行号位移不改 ID ────────────────────────────────────────

_PY_A = '''\
class Service:
    def run(self):
        return 1

    def stop(self):
        return 2
'''

_PY_A_SHIFTED = '''\
# 新增头部注释 使所有行号下移
"""新模块 docstring"""


class Service:
    def run(self):
        return 1

    def stop(self):
        return 2
'''


def test_line_shift_keeps_ids():
    a = _ids_by_qn(_walk(_PY_A))
    b = _ids_by_qn(_walk(_PY_A_SHIFTED))
    common = set(a) & set(b)
    assert common, "应有同名限定名可比"
    for qn in common:
        assert a[qn] == b[qn], f"行号位移不应改变 ID: {qn}"


# ── 2. 身份传播: 改名 → ID 变 ─────────────────────────────────

def test_rename_changes_id():
    a = _ids_by_qn(_walk(_PY_A))
    b = _ids_by_qn(_walk(_PY_A.replace("class Service:", "class ServiceX:")))
    assert a["Service::run"] != b["ServiceX::run"], "父级改名应传播到子符号 ID"
    renamed = _ids_by_qn(_walk(_PY_A.replace("def stop(", "def halt(")))
    assert a["Service::stop"] != renamed["Service::halt"]


# ── 3. 同限定名碰撞消歧(无静默覆盖) ──────────────────────────
# Go 不同 receiver 同名方法: qualified_name 均为裸方法名 → 同文件真实碰撞。

_GO_DUP = '''\
package main

type Circle struct{ r float64 }
type Square struct{ a float64 }

func (c Circle) Area() float64 { return 3.14 * c.r * c.r }
func (s Square) Area() float64 { return s.a * s.a }
'''


def test_same_qualified_name_no_silent_overwrite():
    table = _walk(_GO_DUP, language="go", file_path="src/shape.go")
    dup = [n for n in table.nodes if n.name == "Area"]
    assert len(dup) == 2, f"两个同名方法应都保留, 实际 {len(dup)}"
    ids = [n.id for n in dup]
    assert len(set(ids)) == 2, "碰撞限定名必须 #N 消歧, 不得静默覆盖"
    # 位移行号后二者仍稳定且互异
    shifted = _walk(_GO_DUP.replace("package main\n", "package main\n// c1\n// c2\n"),
                    language="go", file_path="src/shape.go")
    ids2 = sorted(n.id for n in shifted.nodes if n.name == "Area")
    assert sorted(ids) == ids2


def test_collision_ordinal_deterministic():
    id1 = make_node_id("f.go", "method", "Area", 1)
    id2 = make_node_id("f.go", "method", "Area", 2)
    assert id1 != id2
    assert id1 == make_node_id("f.go", "method", "Area", 1)
    assert id2 == make_node_id("f.go", "method", "Area", 2)


# ── 4. ID 不含行号成分(纯函数层) ─────────────────────────────

def test_make_node_id_line_independent():
    # 同 (path, kind, qn): 与历史上任何行号取值都无关 — 契约上无法传行号
    a = make_node_id("f.py", "function", "A::b")
    b = make_node_id("f.py", "function", "A::b")
    assert a == b
    assert len(a) == 16


def test_make_edge_id_deterministic_and_kind_string():
    e1 = make_edge_id("s", "t", EdgeKind.CALLS)
    e2 = make_edge_id("s", "t", "calls")
    assert e1 == e2 == make_edge_id("s", "t", EdgeKind.CALLS)
    assert e1 != make_edge_id("s", "t", EdgeKind.IMPORTS)


# ── 5. contains 边稳定(walker 生成的边引用稳定节点) ───────────

def test_contains_edges_stable_under_shift():
    ta = _walk(_PY_A)
    tb = _walk(_PY_A_SHIFTED)
    ea = {(e.source, e.target) for e in ta.edges}
    eb = {(e.source, e.target) for e in tb.edges}
    assert ea == eb, "contains 边端点应随节点 ID 稳定"
