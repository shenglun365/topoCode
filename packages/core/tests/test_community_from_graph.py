"""analysis.communityFromGraph 端到端测试（数据主权批B）。

喂合成簇型图（3 簇×8 文件星型 imports）→ 断言组件树/文件归属/无状态复现。
小图（<10 节点）会被 HUB/ORPHAN 过滤清零——KB 真实场景为大图，测试用簇型图。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from topoone.engine.task_api.community_from_graph import _run


def _node(nid, path, kind="file", name=""):
    return {"id": nid, "kind": kind, "name": name or nid,
            "file_path": path, "qualified_name": name or nid}


def _cluster_graph(clusters=3, per=8):
    """c 簇×per 文件星型 imports（f0 被同簇其余 import）+ 1 符号调用边。"""
    nodes, edges = [], []
    for c in range(clusters):
        for i in range(per):
            rel = f"mod{c}/f{i}.py"
            nodes.append(_node(f"file:{rel}", rel, name=f"f{i}.py"))
            if i > 0:
                edges.append({"source": f"file:mod{c}/f{i}.py",
                              "target": f"file:mod{c}/f0.py", "kind": "imports"})
    return nodes, edges


class TestCommunityFromGraph:
    def test_empty_graph(self):
        r = _run([], [])
        assert r["components"] == [] and r["levels"] == 0

    def test_cluster_partition(self):
        nodes, edges = _cluster_graph(3, 8)
        nodes.append(_node("s1", "mod0/f1.py", kind="function", name="fa"))
        nodes.append(_node("s2", "mod0/f2.py", kind="function", name="fb"))
        edges.append({"source": "s1", "target": "s2", "kind": "calls"})
        edges.append({"source": "s1", "target": "missing", "kind": "calls"})  # 未解析→丢弃
        edges.append({"source": "file:mod0/f1.py", "target": "file:mod1/f0.py",
                      "kind": "references"})  # 非划分 kind→忽略
        r = _run(nodes, edges)
        assert r["counts"]["usedEdges"] == 22  # 21 星型 imports + 1 calls
        assert r["counts"]["unifiedComponents"] == 3
        comps = [c for c in r["components"] if c["level"] == "L0"]
        assert len(comps) == 3
        for c in comps:
            assert set(c) >= {"commId", "level", "parentId", "files",
                              "nodeCount", "fileCount", "qualityScore"}
            # 簇内文件不跨簇: 所有 files 同属一个 modN
            mods = {f.split("/")[0] for f in c["files"]}
            assert len(mods) == 1, c["files"]
            assert len(c["files"]) == 8
        # 父子链: L0 组件 parentId 可空(单层)
        assert all("parentId" in c for c in comps)

    def test_symbol_calls_aggregate_to_file_level(self):
        """符号级 calls 按 file_path 归并文件级——file_path 丢失的强分辨回归。

        场景: 星型 imports 底座(3 簇) + 独立调用链文件集 f20..f32(仅靠
        跨文件符号 calls 连通, 无 imports; 13 节点 ≥ CALL 线 min_node_cnt)。
        - 正确(文件级): 调用归并为文件链 → 这些文件进入 UNIFIED 组件 files。
        - bug(符号级, _NODE_DEFAULTS 丢 file_path): CALL 社区成员是符号 id
          (无 "/"), files 组装拒收 → f20..f32 从所有组件 files 消失。"""
        nodes, edges = [], []
        for c in range(3):  # imports 底座
            for i in range(8):
                rel = f"mod{c}/f{i}.py"
                nodes.append(_node(f"file:{rel}", rel, name=f"f{i}.py"))
                if i > 0:
                    edges.append({"source": f"file:mod{c}/f{i}.py",
                                  "target": f"file:mod{c}/f0.py", "kind": "imports"})
        chain = [f"call_only/f{k}.py" for k in range(13)]  # 仅符号调用连通的文件集
        for rel in chain:
            nodes.append(_node(f"file:{rel}", rel, name=rel.split("/")[-1]))
        for k in range(12):
            nodes.append(_node(f"sym:{k}", chain[k], kind="function", name=f"fn{k}"))
            nodes.append(_node(f"sym_t:{k}", chain[k + 1], kind="function", name=f"gn{k}"))
            edges.append({"source": f"sym:{k}", "target": f"sym_t:{k}",
                          "kind": "calls", "line": k + 2})
        r = _run(nodes, edges)
        # 决定性信号: CALL 线文件级=链状少量社区; 符号级(丢 file_path)退化为
        # 12 个独立 2 节点分量。实测: 修复态 4 / bug 态 12。
        assert r["counts"]["callCommunities"] == 4, r["counts"]
        assert r["counts"]["unifiedComponents"] >= 1, r["counts"]
        all_files = {f for c in r["components"] for f in c["files"]}
        missing = [rel for rel in chain if rel not in all_files]
        assert not missing, f"调用链文件从组件 files 消失(file_path 归并失效): {missing[:4]}"
