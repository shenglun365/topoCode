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
    """REST 错误响应(错误契约见 docs/architect/error-contract.md)。

    HTTP 状态码与 body.code 一致(历史 bug: 恒 400, 404/500 语义丢失)——
    前端 api-client 只解析 body.code, 状态码修正对前端透明。
    """
    return JSONResponse(status_code=code if 400 <= code < 600 else 400,
                        content={"code": code, "message": msg, "data": None})


_MODEL_KEYS = ("components", "erTables", "ormMappings", "entityClasses",
               "executionFlows", "dataFlows")


def empty_architecture_model() -> dict:
    """空架构模型(项目未绑定 KB 基线的降级态——非伪造，接口应提示用户先关联)。"""
    return {**{k: [] for k in _MODEL_KEYS}, "codeMappings": []}


def _derive_code_mappings(model: dict) -> list:
    """KB 未返回 codeMappings 时，从各组件 owns 首文件推导，保证字段非空可用。"""
    mappings = model.get("codeMappings") or []
    if mappings:
        return mappings
    derived = []
    for c in model.get("components") or []:
        owns = c.get("owns") or []
        derived.append({
            "id": f"cm-{c['id']}", "targetType": "component", "targetId": c["id"],
            "targetName": c.get("name") or c["id"],
            "file": owns[0] if owns else f"app/{c.get('name') or c['id']}",
            "line": "L1", "level": "logical", "note": c.get("desc") or "",
        })
    return derived


class KbUnavailableError(Exception):
    """KB 调用失败/不可达/能力不足 —— 调用方应转 502 并给出明确提示。"""


def normalize_file_ref(v: str, root: str = "") -> str:
    """图谱边端点归一化：剥 file: 前缀 + 绝对路径归一为相对 root 路径。

    采集管线写 file:<绝对路径>，组件 owns 存相对路径——两侧需同一口径
    才能归并出组件级依赖(否则 0 边, 7月批次实测坑)。"""
    v = (v or "").strip()
    if v.startswith("file:"):
        v = v[5:]
    if root and v.startswith(root):
        v = v[len(root):].lstrip("/")
    return v


def _self_components(root=None, project=None) -> list:
    """自管组件目录(数据主权): arch_components 最新 rev + 组件级依赖聚合。

    依赖 = 自管图谱 imports 边(file→file) 按组件 owns 归并(组件级 dependsOn)。
    """
    from .sem.catalog import _fetch_arch_components
    from .sem.symbols import resolve_base_commit
    from .store.graph import GraphStore
    proj = None
    try:
        from .arch_routes import project as _project_mod
        proj = _project_mod.resolve_project(root, project)
    except Exception:  # noqa: BLE001
        proj = None
    pid = (proj or {}).get("id") or (project or "")
    comps = _fetch_arch_components(pid)
    if not comps:
        return []
    file2comp = {}
    for c in comps:
        for f in (c.get("owns") or []):
            file2comp[f] = c["id"]
    deps: dict = {}
    head = resolve_base_commit(root, pid)
    if head:
        # 结构依赖多类归并(汇总抽象为组件级, 不逐条展示): 依赖+调用+继承+实现
        try:
            for kind in ("imports", "calls", "extends", "implements"):
                for e in GraphStore.edges(pid, f"baseline:{head}", kind=kind, limit=100000):
                    s = normalize_file_ref(e.get("source") or "", root)
                    t = normalize_file_ref(e.get("target") or "", root)
                    cs, ct = file2comp.get(s), file2comp.get(t)
                    if cs and ct and cs != ct:
                        deps.setdefault(cs, set()).add(ct)
        except Exception:  # noqa: BLE001
            pass
    return [{
        "id": c["id"], "name": c.get("name") or c["id"],
        "owns": c.get("owns") or [], "parentId": c.get("parentId") or "",
        "level": f"L{c.get('level') or 0}", "edgeType": "UNIFIED",
        "dependsOn": sorted(deps.get(c["id"], set())),
        "desc": c.get("summary") or "",
    } for c in comps]


def build_architecture_model(root=None, project=None, include_code_mappings: bool = False) -> dict:
    """返回项目架构模型(数据主权批E: 自管独立, 不经 KB)。

    组件 = arch_components 最新 rev(社区分组); 依赖 = 自管图谱 imports 边
    按组件归并; 其余分析域(erTables/executionFlows 等)一期为空, 待按新思路
    重建(用户裁决: 切断 KB 联系, architect 独立完成)。
    """
    model = {k: [] for k in _MODEL_KEYS}
    model["components"] = _self_components(root, project)
    if include_code_mappings:
        model["codeMappings"] = _derive_code_mappings(model)
    return model


def build_component_catalog(root=None, project=None) -> dict:
    """组件目录(选择器专用, 数据主权批E: 自管独立, 不经 KB)。"""
    return {
        "components": _self_components(root, project),
        "edgeTypes": ["UNIFIED"], "levels": ["L0", "L1"], "taskId": None,
    }

