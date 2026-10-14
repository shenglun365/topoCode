"""viewer 路由子包（MS5-V2 自单文件拆分；路由路径与方法零变化）。

聚合顺序 = 原单文件声明顺序；apps/docs/tests 的 G0 路由数守卫（26/10）为安全锁。
"""
from fastapi import APIRouter

from topoone_app_docs.viewer import (  # noqa: F401
    pages, community, plantuml, diagram_build, diagram_editor, layout,
)

router = APIRouter()
for _m in (pages, community, plantuml, diagram_build, diagram_editor, layout):
    router.include_router(_m.router)
