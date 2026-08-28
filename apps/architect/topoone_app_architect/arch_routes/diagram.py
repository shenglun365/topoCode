"""Diagram render routes — 绘图增强(IR→代码)服务代理。

绘图增强(build/validate/ir-docs)：与 KB chat 的 `diagram_editor` skill 能力对齐，
但**不拷贝建图逻辑**——architect 以薄代理转发到 reports(3456) 的 `diagram_tools` 服务，
保证单一起源、统一迭代：
  - POST /diagram/build      → reports /api/diagram/build（IR → 语法正确的代码）
  - POST /diagram/validate   → reports /api/diagram/validate（代码语法校验）
  - GET  /diagram/ir-docs    → reports /api/diagram/ir-docs（共享 IR schema 文档）

PlantUML 渲染已收敛到前端内核（/api/topo，sidecar→本地 jar→远程兜底），
原 /diagram/plantuml 端点已移除。
服务地址：`ARCH_REPORTS_URL` 环境变量，默认 `http://127.0.0.1:3456`。
"""
import json
import logging
import os
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException
from fastapi import Request, Response

logger = logging.getLogger(__name__)

router = APIRouter()


def _reports_base() -> str:
    return (os.environ.get("ARCH_REPORTS_URL") or "http://127.0.0.1:3456").rstrip("/")


def _auth_headers() -> dict:
    """reports(经网关) 需鉴权：转发本地数据目录的 token(architect 与网关同源)。"""
    try:
        from . import ctx
        tok_path = os.path.join(ctx.data_dir(), "token")
        with open(tok_path, "r", encoding="utf-8") as f:
            tok = f.read().strip()
        if tok:
            return {"Authorization": f"Bearer {tok}"}
    except Exception:
        pass
    return {}


def _forward(method: str, path: str, body: bytes, timeout: float = 20.0):
    """转发到 reports 服务；业务错误(HTTP 4xx/5xx)映射为 HTTPException。"""
    url = f"{_reports_base()}{path}"
    headers = {"Content-Type": "application/json", **_auth_headers()}
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = str(e)
        try:
            detail = json.loads(e.read().decode())
        except Exception:
            pass
        logger.warning("[diagram] %s %s -> HTTP %s: %s", method, url, e.code, detail)
        raise HTTPException(e.code, detail)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        logger.warning("[diagram] %s %s unreachable: %s", method, url, e)
        raise HTTPException(502, f"绘图增强服务不可达({url})：{e}")


@router.post("/diagram/build")
async def diagram_build(request: Request):
    """IR → 语法正确的 Mermaid/PlantUML 代码（转发 reports build 服务）。"""
    body = await request.body()
    if not body or not body.strip():
        raise HTTPException(400, "Empty body")
    return _forward("POST", "/api/diagram/build", body)


@router.post("/diagram/validate")
async def diagram_validate(request: Request):
    """校验 Mermaid/PlantUML 代码语法（转发 reports validate 服务）。"""
    body = await request.body()
    if not body or not body.strip():
        raise HTTPException(400, "Empty body")
    return _forward("POST", "/api/diagram/validate", body)


@router.get("/diagram/ir-docs")
async def diagram_ir_docs():
    """共享 IR schema 文档（供绘图增强 prompt 注入，单一起源）。"""
    return _forward("GET", "/api/diagram/ir-docs", b"")


def call_build(ir: dict) -> dict:
    """agent 工具入口：IR → 图代码。失败返回 {error}（工具降级用）。"""
    try:
        return _forward("POST", "/api/diagram/build", json.dumps({"ir": ir}).encode())
    except HTTPException as e:
        return {"error": f"diagram.build 失败: {e.detail}"}
    except Exception as e:
        return {"error": f"diagram.build 失败: {e}"}


def call_validate(code: str, lang: str) -> dict:
    """agent 工具入口：代码语法校验。失败返回 {valid:False, errors:[...]}。"""
    try:
        return _forward("POST", "/api/diagram/validate",
                        json.dumps({"code": code, "lang": lang}).encode())
    except HTTPException as e:
        return {"valid": False, "errors": [f"diagram.validate 失败: {e.detail}"]}
    except Exception as e:
        return {"valid": False, "errors": [f"diagram.validate 失败: {e}"]}


_ir_docs_cache: str = ""


def fetch_ir_docs() -> str:
    """拉取共享 IR schema 文档（带进程内缓存，供绘图增强 prompt 注入）。"""
    global _ir_docs_cache
    if _ir_docs_cache:
        return _ir_docs_cache
    try:
        data = _forward("GET", "/api/diagram/ir-docs", b"", timeout=10.0)
        docs = (data or {}).get("docs", "")
        if docs:
            _ir_docs_cache = docs
        return docs
    except Exception as e:
        logger.warning("[diagram] fetch ir-docs failed: %s", e)
        return ""
