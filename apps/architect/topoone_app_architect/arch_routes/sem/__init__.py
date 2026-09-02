"""sem — semantic_assets 内核子包（A1 拆分，纯移动）。

router 实例驻留于此：briefs/impact 等模块的路由随各自逻辑就地注册，
facade(semantic_assets.py) 与 arch_routes/__init__ 经此引用。
"""
from fastapi import APIRouter

router = APIRouter()
