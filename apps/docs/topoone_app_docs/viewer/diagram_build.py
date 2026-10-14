"""图构建/校验/IR 文档路由（MS5-V2 自 viewer.py 切分）。"""
import logging
import re

from fastapi import APIRouter, HTTPException, Request

from topoone import service_common as common
import logging
logger = logging.getLogger(__name__)

router = APIRouter()

# ── Diagram Build / Validate Service（供 architect 绘图增强复用） ──

@router.post("/api/diagram/build")
async def diagram_build_service(request: Request):
    """从 IR 生成语法正确的 Mermaid/PlantUML 代码（收敛于统一内核）。

    IR 两种格式均接受：
    - DiagramSchema（新，唯一 IR）：{version, type, nodes, ...} → L1-L4 校验 → 转 legacy → build
    - legacy IR（旧，向后兼容）：{lang, diagram_type, ...} → legacy schema 校验 → build
    供 architect 的 `diagram.build` 工具经薄代理调用——避免在 architect 侧拷贝建图逻辑。
    body: {"ir": {...}}
    """
    try:
        body = await request.json()
        ir = body.get("ir")
        if not isinstance(ir, dict):
            raise HTTPException(400, "ir (object) is required")
        from topoone.diagram import build_from_ir, is_legacy_ir, schema_to_legacy_ir
        from topoone.diagram.validation import validate_schema_document
        from ..diagram_tools._validator import validate_diagram_syntax

        if is_legacy_ir(ir):
            legacy, lang = ir, ir.get("lang", "mermaid")
            from topoone.diagram._ir_schema import validate_ir
            dt = ir.get("diagram_type", "")
            valid_schema, schema_errors = validate_ir(ir, dt) if dt else (True, [])
            if not valid_schema:
                raise HTTPException(422, {"error": f"IR schema validation failed: {schema_errors[:3]}"})
        else:
            report = validate_schema_document(ir)
            if not report["ok"]:
                codes = [e["code"] for e in report["errors"]][:3]
                raise HTTPException(422, {"error": f"DiagramSchema validation failed: {codes}"})
            legacy = schema_to_legacy_ir(ir)
            lang = ir.get("lang") or legacy.get("lang", "mermaid")

        result = build_from_ir(legacy)
        if "error" in result:
            raise HTTPException(422, result)
        validation = validate_diagram_syntax(result["code"], lang)
        return {
            "code": result["code"],
            "type": result["type"],
            "validation": validation,
            "_tool_generated": True,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("POST /api/diagram/build failed")
        raise HTTPException(500, f"Build failed: {e}")


@router.post("/api/diagram/validate")
async def diagram_validate_service(request: Request):
    """校验代码或 IR（收敛于统一内核）。

    body 两种形态：
    - {"schema": {...}} → L1-L4 结构/语义/动画校验（统一内核，DiagramSchema）
    - {"code": str, "lang": "mermaid"|"plantuml"} → 代码语法校验（legacy validator）
    """
    try:
        body = await request.json()
        if body.get("schema") is not None:
            from topoone.diagram.validation import validate_schema_document
            return validate_schema_document(body["schema"])
        code: str = body.get("code", "")
        lang: str = body.get("lang", "mermaid")
        if not code or not code.strip():
            raise HTTPException(400, "code is required")
        from ..diagram_tools._validator import validate_diagram_syntax
        return validate_diagram_syntax(code, lang)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("POST /api/diagram/validate failed")
        raise HTTPException(500, f"Validate failed: {e}")


@router.get("/api/diagram/ir-docs")
async def diagram_ir_docs_service():
    """共享 IR schema 文档（供 architect 绘图增强 prompt 注入，单一起源）。

    返回统一 DiagramSchema IR 说明（overview + 各类型字段 + 示例 + 动画），
    不含 KB 侧工具约束（web_diagram_build 等）——由调用方(architect)以自己的
    工具名(diagram.build)包装。
    """
    try:
        # 统一 IR 文档（topoone.diagram.prompts），chat skill 与 docs 共享
        from topoone.diagram import prompts as _ir_docs
        overview = re.sub(r"构造 IR 后调用 web_diagram_build 生成代码。?",
                          "构造 IR 后交给建图工具生成代码。", _ir_docs.overview_docs())
        return {"docs": "\n\n".join([
            overview,
            _ir_docs.flowchart_example_docs(),
            _ir_docs.sequence_docs(),
            _ir_docs.state_docs(),
            _ir_docs.class_docs(),
            _ir_docs.er_docs(),
            _ir_docs.gantt_docs(),
            _ir_docs.pie_docs(),
            _ir_docs.activity_docs(),
            _ir_docs.animation_docs(),
        ])}
    except Exception as e:
        logger.exception("GET /api/diagram/ir-docs failed")
        raise HTTPException(500, f"IR docs failed: {e}")

