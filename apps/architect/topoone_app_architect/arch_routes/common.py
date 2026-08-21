"""Shared helpers for architect API routes."""
from datetime import datetime, timezone
from fastapi.responses import JSONResponse


def _ts() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _id(prefix: str) -> str:
    return f"{prefix}-{_ts()}"


def ok(data=None):
    return {"code": 0, "message": "ok", "data": data}


def err(code: int, msg: str):
    return JSONResponse(status_code=400, content={"code": code, "message": msg, "data": None})


_MODEL_KEYS = ("components", "erTables", "ormMappings", "entityClasses",
               "executionFlows", "dataFlows")


def empty_architecture_model() -> dict:
    """空架构模型(项目未绑定 KB 基线的降级态——非伪造，接口应提示用户先关联)。"""
    return {k: [] for k in _MODEL_KEYS}


class KbUnavailableError(Exception):
    """KB 调用失败/不可达/能力不足 —— 调用方应转 502 并给出明确提示。"""


def build_architecture_model(root=None, project=None, include_code_mappings: bool = False) -> dict:
    """返回项目真实架构模型。

    正式方案(KB-REQ-17)：项目已关联 KB 且基线可访问时，经 KbGateway 调 KB
    `/zmq/architecture.model` 取真实模型(组件来自分析图社区、依赖走 imports
    边、change 归因到版本差异)。

    语义：
    - 项目未绑定 KB 基线(降级态) → 返回空模型(合法状态，接口带 note 提示关联)；
    - KB 调用失败/不可达/方法缺失 → 抛 KbUnavailableError，路由转 502(不再静默当空)。
    """
    try:
        from . import project as _project_mod
        from .kb_gateway import call_kb
        if _project_mod.kb_degraded(root, project):
            return empty_architecture_model()
        proj = _project_mod._resolve_project(root, project)
        kb_id = (proj or {}).get("kbProjectId") or (proj or {}).get("kb_project_id")
        if not kb_id:
            return empty_architecture_model()
        model = call_kb("architecture.model", projectId=kb_id)
        if model is None:
            raise KbUnavailableError("KB 不可达：architecture.model 调用失败，无法读取组件模型。")
        if not isinstance(model, dict):
            raise KbUnavailableError("KB 能力不足：architecture.model 返回了非模型结构。")
        for k in _MODEL_KEYS:
            model.setdefault(k, [])
        if not include_code_mappings:
            model.pop("codeMappings", None)
        return model
    except KbUnavailableError:
        raise
    except Exception as e:
        raise KbUnavailableError(f"KB 调用失败：{e}")


def build_component_catalog(root=None, project=None) -> dict:
    """组件目录(选择器专用)：经 KB `/zmq/architecture.catalog` 取跨分析类型/层级的组件。

    返回 { components, edgeTypes, levels, taskId }。
    - 项目未绑定 KB 基线(降级态) → 空目录(合法状态，接口提示关联)；
    - KB 调用失败/不可达 → 抛 KbUnavailableError，路由转 502。
    """
    try:
        from . import project as _project_mod
        from .kb_gateway import call_kb
        if _project_mod.kb_degraded(root, project):
            return {"components": [], "edgeTypes": ["INCLUDE", "CALL"], "levels": ["L0", "L1"], "taskId": None}
        proj = _project_mod._resolve_project(root, project)
        kb_id = (proj or {}).get("kbProjectId") or (proj or {}).get("kb_project_id")
        if not kb_id:
            return {"components": [], "edgeTypes": ["INCLUDE", "CALL"], "levels": ["L0", "L1"], "taskId": None}
        catalog = call_kb("architecture.catalog", projectId=kb_id)
        if catalog is None:
            raise KbUnavailableError("KB 不可达：architecture.catalog 调用失败，无法读取组件目录。")
        if not isinstance(catalog, dict):
            raise KbUnavailableError("KB 能力不足：architecture.catalog 返回了非目录结构。")
        catalog.setdefault("components", [])
        catalog.setdefault("edgeTypes", ["INCLUDE", "CALL"])
        catalog.setdefault("levels", ["L0", "L1"])
        catalog.setdefault("taskId", None)
        return catalog
    except KbUnavailableError:
        raise
    except Exception as e:
        raise KbUnavailableError(f"KB 调用失败：{e}")

