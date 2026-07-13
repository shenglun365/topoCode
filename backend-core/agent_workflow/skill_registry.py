"""
Skill Registry — 技能注册装饰器 + 启动时同步到 DB。

使用方式:
    @register_skill(name="skill_generate_arch_overview", description="...", steps=3, category="analysis")
    class MyTool(AgentTool):
        ...

启动时调用 sync_skills_to_db(multi_db) 将注册的技能写入 skill_configs 表。
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 模块级注册表: 存储所有通过 @register_skill 注册的技能元数据
_registry: List[Dict[str, Any]] = []


def register_skill(
    name: str,
    description: str = "",
    steps: int = 1,
    category: str = "general",
) -> callable:
    """类装饰器: 将技能元数据注册到模块级注册表。"""
    def decorator(cls):
        _registry.append({
            "name": name,
            "description": description,
            "steps": steps,
            "category": category,
        })
        logger.debug(
            "[SkillRegistry] registered skill %s from %s", name, cls.__name__
        )
        return cls
    return decorator


def get_registered_skills() -> List[Dict[str, Any]]:
    """返回当前已注册的所有技能元数据（去重，按 name）。"""
    seen: set = set()
    result: List[Dict[str, Any]] = []
    for s in _registry:
        if s["name"] not in seen:
            seen.add(s["name"])
            result.append(s)
    return result


def sync_skills_to_db(multi_db, locale: Optional[str] = None):
    """启动时调用: 将注册表的技能写入 skill_configs 表，清理遗留旧技能。"""
    from prompt_manager import _now
    main_db = multi_db.main_db
    skills = get_registered_skills()
    imported = 0

    # 获取所有已注册的 skill name，用于清理遗留数据
    registered_names = {s["name"] for s in skills}

    for s in skills:
        existing = main_db.fetchone(
            "SELECT id FROM skill_configs WHERE name = ?", (s["name"],)
        )
        if not existing:
            import uuid
            sid = uuid.uuid4().hex[:12]
            main_db.execute(
                """INSERT INTO skill_configs (id, name, description, category, enabled, config, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 1, '{}', ?, ?)""",
                (sid, s["name"], s["description"], s["category"], _now(), _now()),
            )
            imported += 1

    # 清理遗留旧 skill（不在注册表中的 seed 数据）
    all_rows = main_db.execute(
        "SELECT name FROM skill_configs"
    ).fetchall()
    deleted = 0
    for row in all_rows:
        name = row["name"] if isinstance(row, dict) else row[0]
        if name not in registered_names:
            main_db.execute("DELETE FROM skill_configs WHERE name = ?", (name,))
            deleted += 1

    if imported or deleted:
        main_db.commit()
        if imported:
            logger.info("[SkillRegistry] synced %d new skills to DB", imported)
        if deleted:
            logger.info("[SkillRegistry] cleaned %d legacy skills from DB", deleted)
