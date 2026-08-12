"""Architect API routes — 独立服务(plugins/architect)。

所有路由挂 `/api/architect/*` 前缀。数据经 `ctx`(architect.db + KbGateway)，
不再触碰 reports 全局。由 `plugins/architect/server.py` 提供服务。
"""

from fastapi import APIRouter

from . import project, knowledge, requirements, execution, arch_change, mcp_collab, unit_test, agent, websocket, git, greenfield, tags, overview, dirs, agent_config, docs, semantic_assets, diagram

router = APIRouter(prefix="/api/architect")
router.include_router(project.router)
router.include_router(knowledge.router)
router.include_router(requirements.router)
router.include_router(execution.router)
router.include_router(arch_change.router)
router.include_router(mcp_collab.router)
router.include_router(unit_test.router)
router.include_router(agent.router)
router.include_router(agent_config.router)
router.include_router(websocket.router)
router.include_router(git.router)
router.include_router(greenfield.router)
router.include_router(tags.router)
router.include_router(overview.router)
router.include_router(dirs.router)
router.include_router(docs.router)
router.include_router(semantic_assets.router)
router.include_router(diagram.router)
