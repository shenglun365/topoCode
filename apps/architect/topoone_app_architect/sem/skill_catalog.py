"""W6 技能目录解析（2610-B1，D-1 表为真相源）——arch_assets(kind=skill) 覆盖内置。

同名技能以表为准（清表即回退内置注册表，天然回退位）；payload.route_hint
承载"何时选我"的路由描述（学 Roomote initial_routing 协议），child_registry
承载父子技能引用（协议最小承载）。目录渲染进 system prompt 的 skill_catalog
块（强制选择语义，见 prompt.py）。
"""
from __future__ import annotations

from typing import Any, Dict, List


def skill_catalog(project_id: str) -> List[Dict[str, Any]]:
    """内置 _ARCH_SKILLS ∪ arch_assets(kind=skill, 项目∪全局)，同名表覆盖。"""
    from ..agent.tools.registry import architect_skills
    out: Dict[str, Dict[str, Any]] = {}
    for s in architect_skills():
        out[str(s.get("name"))] = {
            "name": s.get("name"), "description": s.get("description") or "",
            "route_hint": "", "child_registry": [], "source": "builtin",
        }
    try:
        from .. import store as _store
        for a in _store.ArchAssetsStore.all(kind="skill",
                                            project_id=project_id or ""):
            if not a.get("enabled"):
                continue
            p = a.get("payload") or {}
            out[str(a.get("name"))] = {
                "name": a.get("name"), "id": a.get("id"),
                "description": a.get("description") or "",
                "route_hint": str(p.get("route_hint") or ""),
                "child_registry": list(p.get("child_registry") or []),
                "source": "asset",
            }
    except Exception:  # noqa: BLE001 — 表不可用时回退内置目录
        pass
    return sorted(out.values(), key=lambda s: str(s.get("name")))


def render_skill_catalog(project_id: str) -> str:
    """目录 + 强制路由指令（N 选 1 语义的 architect 化；受块预算裁剪）。"""
    catalog = skill_catalog(project_id)
    if not catalog:
        return ""
    lines = ["## 技能目录(skills)",
             "按任务类型从下列技能中选择执行路线（无匹配才自由作答，不得绕过可用技能）："]
    for s in catalog:
        hint = f"｜何时选: {s['route_hint']}" if s.get("route_hint") else ""
        lines.append(f"- {s['name']}：{s['description']}{hint}")
    return "\n".join(lines)
