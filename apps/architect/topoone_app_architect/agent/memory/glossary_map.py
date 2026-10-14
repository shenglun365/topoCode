"""词典检索侧映射(P2) — 纯函数, 零 IO/零 arch_routes 依赖(R1 干净)。

设计裁决(2026-09-17): 词典约束走**外围映射/独立循环**——不注入提示词,
不增加主模型处理负担。落点=检索读侧: ctx.search 查询词经 glossary
(term/alias 命中)扩展同义/规范词, 合并检索(命中带 via 溯源)。
沉淀侧映射与更强的显性约束留待后续酌情启用。
"""
from __future__ import annotations

from typing import Any, Dict, List


def expand_query(query: str, glossary_rows: List[Dict[str, Any]],
                 max_extra: int = 4) -> List[str]:
    """查询词扩展(纯): query 子串命中词条(term 或 alias) → 追加该词条其余变体。

    - 大小写不敏感; query 本身已包含的变体不重复返回;
    - 每词条最多贡献一组变体, 总数封顶 max_extra(控制检索放大倍数);
    - glossary_rows 为 GlossaryStore.list 输出形状({term, alias[]}), 坏行跳过。
    """
    q = (query or "").strip().lower()
    if not q:
        return []
    extras: List[str] = []
    seen: List[str] = [e.lower() for e in extras]
    for row in glossary_rows or []:
        if not isinstance(row, dict):
            continue
        term = str(row.get("term") or "").strip()
        if not term:
            continue
        variants = [term] + [str(a).strip() for a in (row.get("alias") or [])
                             if str(a).strip()]
        hit = next((v for v in variants if v and v.lower() in q), None)
        if not hit:
            continue
        for v in variants:
            vl = v.lower()
            if v and vl != hit.lower() and vl not in q and vl not in seen:
                extras.append(v)
                seen.append(vl)
                if len(extras) >= max_extra:
                    return extras
    return extras
