"""KB analysis.buildGraph(API-157) 客户端(数据主权批E)。

主路径采集: 与 KB 分析管线同构的全节点/全边(ResolutionEngine 跨文件
符号级边+文件依赖+框架+合成), 组件划分喂图与 KB 完全一致。
自 graph_collect 拆分(行数门禁软上限)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_graph_collect.py -q
"""
import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


def collect_via_buildgraph(root: str, files: List[str]) -> Optional[Tuple[List[dict], List[dict], dict]]:
    """主路径(数据主权批E): KB analysis.buildGraph——与 KB 分析管线同构的
    全节点/全边(含 ResolutionEngine 跨文件符号级边/文件依赖边/框架/合成)。

    组件划分严格采用 KB 算法(用户裁决): 喂 communityFromGraph 的图与 KB
    自身分析完全一致。KB 不可达/失败返回 None(降级逐文件路径)。"""
    try:
        from ..kb_gateway import call_kb
        res = call_kb("analysis.buildGraph", projectRoot=root, files=files)
        if not isinstance(res, dict) or res.get("error") or not res.get("nodes"):
            return None
        nodes = res.get("nodes") or []
        edges = res.get("edges") or []
        st = res.get("stats") or {}
        # 统一列名(依赖边 source_file/target_file → 已在 dict source/target ✓)
        for e in edges:
            e.setdefault("line", 0)
            e.setdefault("col", 0)
        stats = {"parsed": int(st.get("parsed") or 0), "cached": 0,
                 "failed": int(st.get("failed") or 0) + int(st.get("skipped") or 0),
                 "source": "buildgraph",
                 "contains": int(st.get("contains") or 0),
                 "resolved": int(st.get("resolved") or 0),
                 "imports": int(st.get("imports") or 0),
                 "framework": int(st.get("framework") or 0),
                 "synthetic": int(st.get("synthetic") or 0)}
        return nodes, edges, stats
    except Exception as e:  # noqa: BLE001
        logger.warning("[graph-collect] buildGraph 不可用, 降级逐文件路径: %s", e)
        return None


def _prune_old_snapshots(pid: str, keep: int = 2) -> None:
    """采集完成即修剪旧快照: 组件三表+图节点/边只留最近 keep 个 rev
    (当前+上一版 DIFF 基准), 更旧快照清理(用户裁决: 刷新后不留陈旧组件信息)。"""
    try:
        from ..store.graph import ComponentStore, GraphStore
        n1 = ComponentStore.prune_old_revs(pid, keep=keep)
        n2 = GraphStore.prune_old_revs(pid, keep=keep)
        if n1 or n2:
            logger.info("[graph-collect] 修剪旧快照: 组件行 -%s, 图 rev -%s", n1, n2)
    except Exception as e:  # noqa: BLE001
        logger.warning("[graph-collect] 快照修剪失败(不阻塞): %s", e)
