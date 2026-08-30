"""主 KB 对接 API 层（A2' 预留；plan-C §5.4/§5.6）。

**主 KB** = architect 侧多用户共享权威库（本期=architect.db 共享层；"在场"=项目已关联
`kbProjectId`）。KB 解析构建服务(core engine kb :3459)全程无感知、零改动。

A2' 仅**预留对接 API 层**（不实现"单机→主 KB 晋升"本体）：
- GET  /mainkb/status   对接状态查询（standalone / main-kb 授权策略开关 + 深链 + 晋升预留位）；
- POST /mainkb/promote  单机→主 KB 晋升——**预留未实现**（501，明确返回，后续独立服务化）。

单机（无主 KB）：直走本地，就地认知编辑由本人授权（见 semantic_assets._check_main_kb_policy）。
主 KB 在场：认知层编辑收口主 KB 界面（就地编辑被拒→深链），本层只报状态、不做旁路。
"""
import logging
from typing import Optional

from fastapi import APIRouter

from .common import err, ok
from .store import ProjectsStore

logger = logging.getLogger(__name__)

router = APIRouter()


def _pid_from(root: Optional[str], project: Optional[str]) -> str:
    from .semantic_assets import project_id_for
    return project_id_for(root, project) or ""


def mainkb_status(pid: str) -> dict:
    """主 KB 对接状态：授权策略开关（standalone / main-kb）+ 深链 + 晋升预留位。"""
    proj = ProjectsStore.get(pid) if pid else None
    kb_pid = (proj or {}).get("kbProjectId") or (proj or {}).get("kb_project_id") or ""
    if kb_pid:
        mode = "main-kb"
        deep_link = f"/kb/{kb_pid}/assets"
    else:
        mode = "standalone"
        deep_link = ""
    return {
        "projectId": pid or (proj or {}).get("id") or "",
        "mode": mode,
        "associated": bool(kb_pid),
        "kbProjectId": kb_pid,
        "deepLink": deep_link,
        # 单机→主 KB 晋升：预留未实现（A2' 仅预留 API 层；本体后续独立服务化，仍不改 KB engine）
        "promotion": {
            "implemented": False,
            "reserved": True,
            "note": "单机→主 KB 晋升（用户命名整体晋升为初始权威）预留未实现；"
                    "接入主 KB 时命名继承语义见 plan-C §5.6",
        },
    }


@router.get("/mainkb/status")
async def api_mainkb_status(root: Optional[str] = None,
                            project: Optional[str] = None):
    """主 KB 对接状态查询（授权策略开关 + 深链 + 晋升预留位）。"""
    pid = _pid_from(root, project)
    return ok(mainkb_status(pid))


@router.post("/mainkb/promote")
async def api_mainkb_promote():
    """单机→主 KB 晋升——**预留未实现**（A2'）。明确返回 501，不静默降级。

    设计（plan-C §5.6）：接入主 KB 时，单机积累的用户命名整体晋升为初始权威命名
    （不被重新生成覆盖）。本体为独立服务化能力，届时立项实现；本端点仅预留接口面。
    """
    return err(501, "单机→主 KB 晋升预留未实现（A2'：仅预留对接 API 层；"
                    "本体将独立服务化，仍不改 KB engine）")
