"""C/C++ 头文件-实现配对适配特征测试(KB 社区分组)。

契约：_inject_stem_pairs 为同名 stem 的 header↔impl 注入虚拟边(仅 INCLUDE,
双侧存在才注入)；assign_files 后处理接管——头文件跟随同名实现所在组件,
公共头(无同名实现)不受影响。
"""
from topoone.plugins.community.community_analysis import _inject_stem_pairs
from topoone.plugins.community.unified_merge import assign_files


def _graph(edges):
    from collections import defaultdict
    g = defaultdict(set)
    for a, b in edges:
        g[a].add(b)
        g[b].add(a)
    return g


class TestInjectStemPairs:
    NODES = {
        "src/core/nginx.c", "src/core/nginx.h",          # 同名对
        "src/app/foo.cpp", "src/app/foo.hpp",            # 同名对(cpp/hpp)
        "src/util/util.h", "src/util/helper.c",          # 异 stem
        "src/orphan/lonely.h",                           # 头无实现
    }

    def test_injects_same_stem_pairs_include_only(self):
        g = _graph([("src/core/nginx.c", "src/util/util.h")])
        n = _inject_stem_pairs(g, self.NODES, "INCLUDE")
        assert n == 2                       # nginx.c↔nginx.h + foo.cpp↔foo.hpp
        assert "src/core/nginx.h" in g["src/core/nginx.c"]
        assert "src/app/foo.hpp" in g["src/app/foo.cpp"]

    def test_no_inject_for_call_graph(self):
        g = _graph([])
        n = _inject_stem_pairs(g, self.NODES, "CALL")
        assert n == 0

    def test_no_inject_when_one_side_missing(self):
        nodes = {"src/orphan/lonely.h"}     # 无同名实现
        g = _graph([])
        assert _inject_stem_pairs(g, nodes, "INCLUDE") == 0

    def test_no_inject_for_non_c_project(self):
        nodes = {"pkg/mod.py", "pkg/__init__.py"}
        g = _graph([])
        assert _inject_stem_pairs(g, nodes, "INCLUDE") == 0


class TestAssignFilesStemTakeover:
    COMPS = [
        {"members": {"src/core/nginx.c", "src/core/ngx_crc.c"}, "evidence": "BOTH", "kind": "normal"},
        {"members": {"src/core/nginx.h", "src/core/ngx_module.h"}, "evidence": "INCLUDE", "kind": "normal"},
    ]

    def test_header_follows_impl_component(self):
        # nginx.h 被社区划进头文件簇(组件2), 但同名实现 nginx.c 在组件1 → 接管
        assignment, unassigned = assign_files(self.COMPS, [], set(), set(), force=True)
        assert assignment["src/core/nginx.c"] == 0
        assert assignment["src/core/nginx.h"] == 0        # 跟随同名实现
        assert "src/core/nginx.h" not in unassigned

    def test_public_header_without_impl_untouched(self):
        # 公共头(ngx_config.h 无同名 .c)不受 stem 规则影响——走原有归属
        comps = [
            {"members": {"src/core/nginx.c"}, "evidence": "BOTH", "kind": "normal"},
            {"members": {"src/core/ngx_config.h"}, "evidence": "INCLUDE", "kind": "normal"},
        ]
        assignment, _ = assign_files(comps, [], set(), set(), force=True)
        assert assignment["src/core/ngx_config.h"] == 1

    def test_pool_header_still_goes_through_f3(self):
        # 头文件无组件声明、仅在仲裁池 → 走既有 F3 池归入(邻接), stem 不凭空注入
        comps = [{"members": {"src/core/nginx.c"}, "evidence": "BOTH", "kind": "normal"}]
        assignment, unassigned = assign_files(comps, ["src/core/nginx.h"], set(), set(), force=True)
        assert assignment.get("src/core/nginx.h") == 0   # F3 归入唯一邻接组件
