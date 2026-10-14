"""relation_index —— 资产关系 target 解析索引(KB 同款口径, 单源)。

自 engine.py 迁移(§ 函数移动, 非复制): id / name / nameAlias / 锚点符号 →
资产 id。语义图谱(semantic_graph)与图谱范围提纲(graph_outline)等所有
消费资产间 relations 的入口统一走此索引——图上怎么连, 下游就怎么连。
"""
from __future__ import annotations

from typing import Dict, List, Tuple


def relation_target_index(assets: List[dict]) -> Dict[str, str]:
    """关系目标解析索引：id / name / nameAlias / 锚点符号 → 资产 id。

    基于**全部**资产(非过滤子集)建索引，使按粒度/类别/范围筛选时，
    指向其它层级/范围的边仍能解析为稳定 id(是否渲染由前端按节点集决定)。
    """
    idx: Dict[str, str] = {}
    for a in assets:
        aid = a.get("id") or ""
        if not aid:
            continue
        idx.setdefault(aid, aid)
        nm = (a.get("name") or "").strip()
        if nm:
            idx.setdefault(nm, aid)
        for al in (a.get("nameAlias") or []) if isinstance(a.get("nameAlias"), list) else []:
            if isinstance(al, str) and al.strip():
                idx.setdefault(al.strip(), aid)
        for r in (a.get("astRefs") or []):
            s = (r.get("symbol") or "").strip()
            if s:
                idx.setdefault(s, aid)
    return idx


def resolve_relation_target(t: str, idx: Dict[str, str]) -> Tuple[str, bool]:
    t = (t or "").strip()
    if not t:
        return "", False
    aid = idx.get(t)
    return (aid, True) if aid else (t, False)
