"""runner REST 面契约守护（R1; 与 runner-events-baseline 同模式）。

单源 = packages/core/topoone/plugins/runner/server.py 的 FastAPI app
（含 implement.register 全量 /api/implement* 路由）的 OpenAPI paths；
基线 = packages/core/runner-openapi-baseline.json。

锁定面：路径/方法集冻结——外部宿主（architect RunnerClient / 远端 worker /
潜在第 4 执行器接入方）依赖此面稳定。新增端点 = 追加（向后兼容）；
改名/删除 = 破坏性变更。

Run: cd <repo> && python -m pytest packages/core/tests/test_runner_api_surface.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "topoone"))

from topoone.plugins.runner import implement, server  # noqa: E402

BASELINE_PATH = os.path.join(os.path.dirname(__file__), "..", "runner-openapi-baseline.json")


def _actual_paths() -> dict:
    implement.register(server.app)          # 重复注册幂等(同 path+method 覆盖)
    spec = server.app.openapi()
    return {path: sorted(methods.keys())
            for path, methods in spec.get("paths", {}).items()}


def test_api_surface_matches_baseline():
    """REST 面漂移守卫：实际 paths 必须与基线完全一致。"""
    with open(BASELINE_PATH, encoding="utf-8") as f:
        expected = json.load(f)["paths"]
    actual = _actual_paths()
    assert actual == expected, (
        "runner REST 面与基线不一致。\n"
        "新增端点(向后兼容)或破坏性变更(改名/删除)？\n"
        "处理：1) 运行 python3 scripts/runner-api-baseline.py 重生成；"
        "2) PR 描述标注 runner 破坏面；3) 同步 RunnerClient"
        "（apps/architect agent/execution/runner_client.py）与消费面测试。\n"
        "基线={}, 实际={}".format(
            json.dumps(expected, sort_keys=True), json.dumps(actual, sort_keys=True)))


def test_implement_plane_anchored():
    """锚点断言：实施作业面核心路径在位（基线对账之外的语义保险）。"""
    paths = _actual_paths()
    assert "/api/implement" in paths and "post" in paths["/api/implement"]
    assert "/api/implement/{job_id}" in paths and "get" in paths["/api/implement/{job_id}"]
    for tail, method in (("input", "post"), ("finish", "post"), ("approval", "post"),
                         ("diff", "get")):
        p = f"/api/implement/{{job_id}}/{tail}"
        assert p in paths and method in paths[p], f"实施面缺 {method.upper()} {p}"


def test_events_ws_route_registered():
    """WS 订阅面不走 OpenAPI（websocket 路由），单独锁定其在 app 上注册。"""
    from starlette.routing import WebSocketRoute
    ws_paths = {getattr(r, "path", "") for r in server.app.routes
                if isinstance(r, WebSocketRoute)}
    assert "/api/implement/{job_id}/events" in ws_paths, f"WS 事件面丢失: {ws_paths}"
