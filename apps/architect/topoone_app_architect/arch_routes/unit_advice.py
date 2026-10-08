"""W5 单测建议层路由(2610-B1)——缺口建议 + 事实对账(approval 扩展位)。

从 unit_test.py 拆出(行数棘轮纪律); 执行/对话 WS 仍在 unit_test 域。
"""
from fastapi import APIRouter

from ..common import ok
from .. import store

router = APIRouter()

def _advice_pid(root: str, project: str) -> str:
    """root/project → 项目 id(对齐 agents_md 的项目解析口径)。"""
    import os
    rows = store.ProjectsStore.all() or []
    for r in rows:
        if project and r.get("id") == project:
            return str(r.get("id") or "")
        rp = str(r.get("rootPath") or r.get("root_path") or "")
        if not project and root and os.path.normpath(rp) == os.path.normpath(root):
            return str(r.get("id") or "")
    return project or ""


def _advice_config() -> dict:
    """建议层配置(approval 扩展位, D-4 预留: 缺省 mode=none 无任何行为分支)。"""
    raw = store.CollabConfigStore.get("unit_test_advice", "") or ""
    try:
        import json as _json
        cfg = _json.loads(raw) if raw else {}
        return cfg if isinstance(cfg, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


@router.get("/unit-tests/advice")
async def unit_test_advice(root: str = "", project: str = "", top_n: int = 10):
    """缺口建议清单(图加权 Top-N 无测试可达符号)——建议视角, 无强制步骤。

    approval 扩展位缺省 {mode:none}(未来对接人工审批/主控 agent 审批)。
    """
    from ..sem.test_reach import test_reach_gaps
    pid = _advice_pid(root, project)
    if not pid:
        return ok({"items": [], "reason": "no_project", "approval": {"mode": "none"}})
    prow = store.ProjectsStore.get(pid) or {}
    root_path = str(prow.get("rootPath") or prow.get("root_path") or "")
    items = test_reach_gaps(pid, top_n=max(1, min(int(top_n or 10), 50)),
                            root=root_path)
    cfg = _advice_config()
    return ok({"items": items, "projectId": pid, "approval": cfg.get("approval")
               or {"mode": "none"}})


@router.get("/unit-tests/facts")
async def unit_test_facts(root: str = "", project: str = ""):
    """事实层对账状态: 扫描集 × K2 回执主张(claimed_only 挂账待核验, 幂等)。"""
    from ..sem.test_reach import read_test_scan, reconcile_tests
    pid = _advice_pid(root, project)
    if not pid:
        return ok({"reason": "no_project"})
    scan = read_test_scan(pid)
    rec = reconcile_tests(pid)
    return ok({"projectId": pid, "scannedCount": rec["scanned_count"],
               "claimedCount": rec["claimed_count"],
               "claimedOnly": rec["claimed_only"],
               "scannedOnly": rec["scanned_only"],
               "scanAt": rec["scan_at"],
               "diff": scan.get("diff") or {}})


# ── W6: test.advice 工具 + test.strategy 内置技能(首批, W5 建议层的 agent 面) ──

from ..agent.tools.req_agent import register_architect_skill, register_architect_tool


@register_architect_tool(
    "test.advice",
    "测试缺口建议——图加权 Top-N 高风险无测试符号(扇入×类型权重, 附一跳邻域证据)。"
    "用户询问 测试覆盖/该测什么/测试建议 或准备补测试时先调用。",
    params_doc='{"top_n": 10}',
)
def tool_test_advice(top_n: int = 10) -> dict:
    from ..sem.test_reach import test_reach_gaps
    from .. import ctx as _ctx
    pid = _ctx.get_project() or ""
    if not pid:
        return {"ok": False, "error": "no_project"}
    prow = store.ProjectsStore.get(pid) or {}
    root = str(prow.get("rootPath") or prow.get("root_path") or "")
    items = test_reach_gaps(pid, top_n=max(1, min(int(top_n or 10), 50)), root=root)
    return {"ok": True, "items": items, "count": len(items)}


@register_architect_skill(
    "test.strategy",
    "测试策略：先调 test.advice 取缺口建议(高风险无测试符号+邻域证据)，"
    "再按建议组织补测/委派——建议视角，确认由人。",
    steps=2, category="quality",
)
def _skill_test_strategy():
    pass
