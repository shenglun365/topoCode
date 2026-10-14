"""dossier 装配(记忆层) — 前置上下文构造(裁决3)。

收集→裁剪→装配 dossier 并落 execution_brief 单元:
  会话摘要/标签 → 备案文档 → 高优上下文单元 → 需求三段 → 项目规约,
  整体受 _DOSSIER_BUDGET 预算约束(逐段截断)。

P4 自 context_registry.py(今 units.py)拆出。
"""
from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


def _store():
    from ... import store
    return store


def _arch_ts():
    from ...common import _ts
    return _arch_ts()


_DOSSIER_BUDGET = 24000   # 字符预算(本地模型 256K 窗口留足余量)


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "\n…(截断)"


def assemble_dossier(conv_id: str, reqs: Optional[list] = None,
                     root: str = "", project_id: str = "",
                     persist: bool = True) -> Optional[str]:
    """前置上下文构造(裁决3): 收集→裁剪→装配 dossier，并落 execution_brief 单元。

    收集源: 会话摘要/标签 → 备案文档 → 高优上下文单元(方案草图/决策/执行回执)
    → 需求三段 → 项目规约。整体受 _DOSSIER_BUDGET 预算约束(逐段截断)。
    """
    conv = _store().ConversationsStore.get(conv_id)
    if not conv:
        return None
    pid = project_id or (conv.get("projectId") or "")
    from .units import _conv_tags
    tags = _conv_tags(conv)
    sections: List[tuple] = []   # (标题, 正文)

    # 1) 会话基础
    sections.append(("会话", (
        f"{conv.get('title') or '-'}（类型 {conv.get('kind')}，模块: "
        f"{', '.join(tags['modules']) or '-'}）\n"
        f"摘要: {(conv.get('summary') or '').strip() or '(未生成)'}")))

    # 2) 备案文档(需求/方案定型快照)
    docs = _store().DocsStore.all(conversation_id=conv_id, limit=5)
    for d in docs[:3]:
        sections.append((f"备案文档: {d.get('title') or '-'}",
                         _clip(d.get("contentMd") or "", 6000)))

    # 3) 高优上下文单元(方案草图/决策/摘要/回执；工具轨迹排除)
    units = _store().ContextUnitsStore.all(conversation_id=conv_id, limit=100)
    picked = [u for u in units
              if (u.get("importance") or 0) >= 1 and u.get("type") != "execution_brief"]
    picked.sort(key=lambda u: (-(u.get("importance") or 0), -(u.get("createdAt") or 0)))
    for u in picked[:6]:
        sections.append((f"[{u.get('type')}] {u.get('title') or '-'}",
                         _clip(u.get("content") or "", 3000)))

    # 4) 需求三段(正式需求实体——执行的对象)
    for r in (reqs or [])[:4]:
        if r and r.get("desc"):
            sections.append((f"需求: {r.get('title') or r.get('id')}",
                             _clip(r.get("desc") or "", 5000)))

    # 5) 项目规约(编码必须遵守)
    if root or pid:
        try:
            from ...sem.map_tools import run_tool
            rules = run_tool("map.rules", {"project": pid or None})
            sections.append(("项目规约(编码必须遵守)", _clip(rules, 4000)))
        except Exception as e:  # noqa: BLE001
            logger.warning("[dossier] 规约装配失败: %s", e)

    # 装配(预算内逐段保留)
    out = ["# 执行 dossier(前置上下文构造)", ""]
    used = 0
    for title, body in sections:
        body = (body or "").strip()
        if not body:
            continue
        block = f"## {title}\n\n{body}\n\n"
        if used + len(block) > _DOSSIER_BUDGET:
            block = block[: max(0, _DOSSIER_BUDGET - used)] + "\n…(预算截断)\n\n"
        out.append(block)
        used += len(block)
        if used >= _DOSSIER_BUDGET:
            break
    dossier = "".join(out)
    if not persist:
        return dossier
    try:
        _store().ContextUnitsStore.create({
            "conversationId": conv_id, "projectId": pid,
            "type": "execution_brief",
            "title": f"执行 dossier({len(dossier)} 字符)",
            "content": dossier[:4000] + ("…(完整版见执行上下文)" if len(dossier) > 4000 else ""),
            "refs": {"modules": tags.get("modules") or []},
            "importance": 1,
        })
    except Exception as e:  # noqa: BLE001
        logger.warning("[dossier] execution_brief 单元写入失败: %s", e)
    return dossier
