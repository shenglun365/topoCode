"""Architect API routes — 独立服务(plugins/architect)。

所有路由挂 `/api/architect/*` 前缀。数据经 `ctx`(architect.db + KbGateway)，
不再触碰 reports 全局。由 `plugins/architect/server.py` 提供服务。
"""

from fastapi import APIRouter

from . import project, knowledge, requirements, execution, arch_change, mcp_collab, unit_test, websocket, git, greenfield, tags, overview, dirs, docs, semantic_assets, diagram, design
from . import sessions
from . import session_docs
from . import dev_digest
from . import asset_framework
from . import agent_executors
from . import cline_engines
from . import exec_cline
from . import agent_roles
from . import contracts
from . import acceptance
from . import naming
from . import mainkb
from . import capability_mining
from . import llm_dataset
from . import flow_policy
from . import tracking

router = APIRouter(prefix="/api/architect")
router.include_router(project.router)
router.include_router(knowledge.router)
router.include_router(requirements.router)
router.include_router(sessions.router)
router.include_router(session_docs.router)
router.include_router(dev_digest.router)
router.include_router(arch_change.router)
router.include_router(mcp_collab.router)
router.include_router(unit_test.router)
router.include_router(websocket.router)
router.include_router(git.router)
router.include_router(greenfield.router)
router.include_router(tags.router)
router.include_router(overview.router)
router.include_router(llm_dataset.router)
router.include_router(flow_policy.router)
router.include_router(dirs.router)
router.include_router(docs.router)
router.include_router(semantic_assets.router)
router.include_router(agent_executors.router)
router.include_router(cline_engines.router)
router.include_router(exec_cline.router)
router.include_router(asset_framework.router)
router.include_router(agent_roles.router)
router.include_router(contracts.router)
router.include_router(acceptance.router)
router.include_router(naming.router)
router.include_router(mainkb.router)
router.include_router(capability_mining.router)
router.include_router(diagram.router)
router.include_router(design.router)
router.include_router(tracking.router)
