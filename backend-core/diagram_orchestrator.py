"""DiagramOrchestrator — 图生成编排器。

将文本分析和图生成分离为独立的 LLM 会话回合：
  Step 1: 文本分析 session → 生成结构化摘要（禁止输出图）
  Step 2: 基于摘要并行生成 Mermaid + PlantUML（独立 session，各聚焦一种格式）
  Step 3: 验证 + 自动修正（最多 2 轮）

用法:
    orch = DiagramOrchestrator(ctx, llm_chat_fn)
    result = await orch.generate(["project", "comm-auth"])
    # => {"summary": "...", "mermaid": "...", "plantuml": "..."}
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Mermaid 样式指南
MERMAID_STYLE_GUIDE = """
Mermaid 样式规则:
- 使用 graph LR 做依赖图，graph TD 做调用图
- 节点名用英文，标签用中文
- Hub 节点加粗边框 style X stroke-width:3px
- 社区边界用 subgraph 标注
- 避免交叉连线，必要时用 linkStyle 调整
"""

# PlantUML 样式指南
PLANTUML_STYLE_GUIDE = """
PlantUML 样式规则:
- 使用 component diagram: 顶层用 package，组件用 component
- 接口用 interface，数据库用 database
- 颜色: 核心组件 #LightBlue，基础设施 #LightGray
- 注释用 note right of X
- 必须包含 @startuml 和 @enduml
"""


class DiagramOrchestrator:
    """图生成编排器。"""

    def __init__(self, ctx, llm_chat_fn):
        self._ctx = ctx
        self._llm = llm_chat_fn
        self._summary: Optional[str] = None

    async def generate(self, scope: list[str], include_plantuml: bool = True) -> dict:
        """主流程: 文本摘要 → 并行图生成 → 验证修正。

        Args:
            scope: 层级路径，如 ["project", "comm-auth"]
            include_plantuml: 是否同时生成 PlantUML

        Returns:
            {"summary": str, "mermaid": str, "plantuml": str | None}
        """
        # Step 1: 文本摘要
        self._summary = await self._generate_text_summary(scope)

        # Step 2: 并行图生成
        tasks = [self._generate_mermaid(scope)]
        if include_plantuml:
            tasks.append(self._generate_plantuml(scope))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        mermaid = results[0] if not isinstance(results[0], Exception) else ""
        plantuml = (
            results[1] if len(results) > 1 and not isinstance(results[1], Exception) else None
        )

        # Step 3: 验证修正
        if mermaid:
            mermaid = await self._validate_and_fix("mermaid", mermaid)
        if plantuml:
            plantuml = await self._validate_and_fix("plantuml", plantuml)

        return {"summary": self._summary, "mermaid": mermaid, "plantuml": plantuml}

    async def generate_mermaid_only(self, scope: list[str]) -> str:
        """仅生成 Mermaid 图。"""
        if not self._summary:
            self._summary = await self._generate_text_summary(scope)
        code = await self._generate_mermaid(scope)
        return await self._validate_and_fix("mermaid", code)

    async def generate_plantuml_only(self, scope: list[str]) -> str:
        """仅生成 PlantUML 图。"""
        if not self._summary:
            self._summary = await self._generate_text_summary(scope)
        code = await self._generate_plantuml(scope)
        return await self._validate_and_fix("plantuml", code)

    # ═══════════════════════════════════════════
    # 文本摘要
    # ═══════════════════════════════════════════

    async def _generate_text_summary(self, scope: list[str]) -> str:
        """文本摘要 session —— 禁止输出图代码。"""
        layers = self._ctx.get_downward_path(scope)
        context = self._ctx.format_for_llm(layers, "top-down")

        messages = [
            {
                "role": "system",
                "content": (
                    "你是架构分析师。根据项目架构数据生成结构化文本摘要。"
                    "严格禁止输出任何 Mermaid、PlantUML 或其他图表代码块。"
                    "只输出纯文本描述。不超过 800 字。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"项目架构数据:\n\n{context}\n\n"
                    "请生成结构化的文本摘要，包含：\n"
                    "1. 整体架构概述\n"
                    "2. 关键模块和角色\n"
                    "3. 主要依赖关系走向\n"
                ),
            },
        ]

        try:
            result = await self._llm(messages)
            return result or "架构摘要生成失败。"
        except Exception as e:
            logger.warning(f"text summary failed: {e}")
            layers = self._ctx.get_downward_path(scope)
            return "\n".join(l.what for l in layers) if layers else ""

    # ═══════════════════════════════════════════
    # 图生成
    # ═══════════════════════════════════════════

    async def _generate_mermaid(self, scope: list[str]) -> str:
        """Mermaid 图生成 session。"""
        layers = self._ctx.get_downward_path(scope)
        context = self._ctx.format_for_llm(layers, "top-down")

        messages = [
            {
                "role": "system",
                "content": (
                    "你是 Mermaid 图表专家。基于架构摘要和原始数据生成 Mermaid 图。"
                    f"确保摘要中提到的所有模块都出现在图中。\n{MERMAID_STYLE_GUIDE}"
                    "只输出 Mermaid 代码，放在 ```mermaid ... ``` 块中。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"架构摘要:\n{self._summary}\n\n"
                    f"原始数据:\n{context}\n\n"
                    "请生成 Mermaid 架构图。"
                ),
            },
        ]

        try:
            result = await self._llm(messages)
            return self._extract_code(result, "mermaid")
        except Exception as e:
            logger.warning(f"mermaid generation failed: {e}")
            return ""

    async def _generate_plantuml(self, scope: list[str]) -> str:
        """PlantUML 图生成 session。"""
        layers = self._ctx.get_downward_path(scope)
        context = self._ctx.format_for_llm(layers, "top-down")

        messages = [
            {
                "role": "system",
                "content": (
                    "你是 PlantUML 专家。基于架构摘要生成 PlantUML component diagram。\n"
                    f"{PLANTUML_STYLE_GUIDE}"
                    "只输出 PlantUML 代码，放在 ```plantuml ... ``` 块中。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"架构摘要:\n{self._summary}\n\n"
                    f"原始数据:\n{context}\n\n"
                    "请生成 PlantUML 组件图。"
                ),
            },
        ]

        try:
            result = await self._llm(messages)
            return self._extract_code(result, "plantuml")
        except Exception as e:
            logger.warning(f"plantuml generation failed: {e}")
            return ""

    # ═══════════════════════════════════════════
    # 验证与修正
    # ═══════════════════════════════════════════

    async def _validate_and_fix(self, diagram_type: str, code: str) -> str:
        """验证 + 自动修正，最多 2 轮。"""
        if not code or not code.strip():
            return ""

        for attempt in range(2):
            errors = self._validate(diagram_type, code)
            if not errors:
                return code

            logger.info(
                f"diagram {diagram_type} fix attempt {attempt + 1}: {len(errors)} errors"
            )

            messages = [
                {
                    "role": "system",
                    "content": (
                        f"你是 {diagram_type} 语法修正专家。修复代码中的语法错误。"
                        "保持原始结构和节点不变，只修正语法。"
                        f"只输出修正后的 {diagram_type} 代码块。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"需要修正的 {diagram_type} 代码:\n```\n{code}\n```\n\n"
                        f"发现的错误:\n{self._format_errors(errors)}\n\n"
                        f"原始架构摘要（用于验证节点完整性）:\n{self._summary or ''}\n\n"
                        "请输出修正后的代码。"
                    ),
                },
            ]

            try:
                result = await self._llm(messages)
                code = self._extract_code(result, diagram_type) or code
            except Exception as e:
                logger.warning(f"diagram fix failed: {e}")
                break

        return code

    @staticmethod
    def _validate(diagram_type: str, code: str) -> list[dict]:
        """验证图代码。"""
        errors = []

        if diagram_type == "mermaid":
            # 基础语法检查
            if "```" in code:
                pass  # 提取后的代码不含 ``` 是正常的
            if "graph" not in code.lower() and "flowchart" not in code.lower():
                errors.append({
                    "type": "syntax",
                    "message": "缺少 graph/flowchart 声明，请检查图类型关键字"
                })
            if "subgraph" in code.lower() and "end" not in code.lower():
                errors.append({
                    "type": "syntax",
                    "message": "subgraph 未闭合，需要 end 关键字"
                })

        elif diagram_type == "plantuml":
            if not code.strip().startswith("@startuml"):
                errors.append({
                    "type": "syntax",
                    "message": "缺少 @startuml 声明"
                })
            if "@enduml" not in code:
                errors.append({
                    "type": "syntax",
                    "message": "缺少 @enduml 声明"
                })

        return errors

    @staticmethod
    def _format_errors(errors: list[dict]) -> str:
        return "\n".join(f"- [{e.get('type','unknown')}] {e.get('message','')}" for e in errors)

    @staticmethod
    def _extract_code(text: str, code_type: str = "mermaid") -> str:
        """从 LLM 输出中提取代码块。"""
        if not text:
            return ""
        text = text.strip()

        # 提取 fenced code block
        fence = f"```{code_type}"
        if fence in text:
            start = text.index(fence) + len(fence)
            end = text.index("```", start)
            return text[start:end].strip()

        # 任意 fenced block
        if "```" in text:
            start = text.index("```") + 3
            # 跳过语言标识
            nl = text.find("\n", start)
            if nl > start:
                start = nl + 1
            end = text.index("```", start)
            return text[start:end].strip()

        # 如果文本以 @startuml 开头 → PlantUML
        if text.startswith("@startuml"):
            return text

        return text
