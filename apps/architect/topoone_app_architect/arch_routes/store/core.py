"""store 拆分模块（A1-T3：纯移动）。"""
from __future__ import annotations

from .base import _all, _db, _delete, _fetchall_routed, _get, _insert, _row_to_api, _update

class ProjectsStore:
    TABLE = "arch_projects"

    @classmethod
    def all(cls):
        return _all(cls.TABLE)

    @classmethod
    def get(cls, project_id: str):
        return _get(cls.TABLE, project_id)

    @classmethod
    def get_active(cls) -> Optional[dict]:
        row = _db().fetchone(
            f"SELECT * FROM {cls.TABLE} WHERE active = 1 ORDER BY updated_at DESC LIMIT 1"
        )
        return _row_to_api(row) if row else None

    @classmethod
    def get_by_root(cls, root: str) -> Optional[dict]:
        """按工作目录(root_path)查项目(URL ?root= 解析)。"""
        row = _db().fetchone(
            f"SELECT * FROM {cls.TABLE} WHERE root_path = ? ORDER BY updated_at DESC LIMIT 1",
            (root,),
        )
        return _row_to_api(row) if row else None

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def upsert(cls, project_id: str, data: dict) -> dict:
        """按 id 存在则更新、否则插入(URL 绑定登记用，避免重复绑定 UNIQUE 冲突)。"""
        existing = _get(cls.TABLE, project_id)
        if existing:
            _update(cls.TABLE, project_id, data)
            return {**existing, **data}
        _insert(cls.TABLE, {**data, "id": project_id})
        return {**data, "id": project_id}

    @classmethod
    def update(cls, project_id: str, data: dict) -> Optional[dict]:
        return _update(cls.TABLE, project_id, data)

    @classmethod
    def delete(cls, project_id: str) -> bool:
        return _delete(cls.TABLE, project_id)




class RequirementsStore:
    TABLE = "arch_requirements"

    @classmethod
    def all(cls):
        return _all(cls.TABLE, order_by="updated_at DESC")

    @classmethod
    def get(cls, req_id: str):
        return _get(cls.TABLE, req_id)

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def update(cls, req_id: str, data: dict) -> Optional[dict]:
        return _update(cls.TABLE, req_id, data)




class PlansStore:
    TABLE = "arch_plans"

    @classmethod
    def all(cls):
        return _all(cls.TABLE, order_by="updated_at DESC")

    @classmethod
    def get(cls, plan_id: str):
        return _get(cls.TABLE, plan_id)

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def update(cls, plan_id: str, data: dict) -> Optional[dict]:
        return _update(cls.TABLE, plan_id, data)




class TaskTreesStore:
    TABLE = "arch_task_trees"

    @classmethod
    def get(cls, tree_id: str):
        return _get(cls.TABLE, tree_id)

    @classmethod
    def get_by_plan(cls, plan_id: str) -> Optional[dict]:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE plan_id = ? ORDER BY revision DESC",
            (plan_id,),
        )
        return _row_to_api(rows[0]) if rows else None

    @classmethod
    def upsert(cls, tree_id: str, data: dict) -> None:
        existing = _get(cls.TABLE, tree_id)
        if existing:
            _update(cls.TABLE, tree_id, data)
        else:
            _insert(cls.TABLE, data)




class ExecutionTasksStore:
    TABLE = "arch_execution_tasks"

    @classmethod
    def all(cls):
        return _all(cls.TABLE, order_by="created_at DESC")

    @classmethod
    def get(cls, task_id: str):
        return _get(cls.TABLE, task_id)

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def update(cls, task_id: str, data: dict) -> Optional[dict]:
        return _update(cls.TABLE, task_id, data)



