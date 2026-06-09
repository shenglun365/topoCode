"""BidirectionalAnalyzer — 双向架构分析器。

基于 AnalysisContext 实现两方向的层次化分析：
  - top-down:   项目 → 社区 → 文件 → 符号，每层关注功能特性和业务目标
  - bottom-up:  符号 → 文件 → 社区 → 项目，底层关注实现细节，上层关注抽象模式

依赖 AnalysisContext 提供数据，LLM 提供自然语言生成。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 默认每层摘要长度上限
_MAX_TOPDOWN_CHARS = 600
_MAX_BOTTOMUP_CHARS = 600


class BidirectionalAnalyzer:
    """双向架构分析器。

    用法:
        analyzer = BidirectionalAnalyzer(ctx, llm_chat_fn)
        result = await analyzer.top_down(["project", "comm-auth"])
        result = await analyzer.bottom_up("authenticate", levels=3)
    """

    def __init__(self, ctx, llm_chat_fn):
        """Args:
            ctx: AnalysisContext 实例
            llm_chat_fn: async callable(messages) -> str, LLM 对话函数
        """
        self._ctx = ctx
        self._llm = llm_chat_fn

    # ═══════════════════════════════════════════
    # 自顶向下
    # ═══════════════════════════════════════════

    async def top_down(self, path: list[str], focus: str = "features") -> dict:
        """自顶向下分析：沿路径逐层生成摘要。

        Args:
            path: 如 ["project", "comm-auth", "src/api/handler.ts"]
            focus: "features" (功能特性) | "business" (业务目标) | "apis" (接口)

        Returns:
            {
                "layers": [
                    {"level": "project", "summary": "...", "role": "..."},
                    {"level": "community", "summary": "...", "role": "..."},
                    ...
                ],
                "overall": "整体描述"
            }
        """
        layers = self._ctx.get_downward_path(path)
        layer_summaries = []

        for i, layer in enumerate(layers):
            desc = await self._summarize_top_down(layer, i, len(layers), focus)
            layer_summaries.append({
                "level": layer.level,
                "name": layer.name,
                "summary": desc.get("summary", ""),
                "role": desc.get("role", ""),
                "key_items": desc.get("key_items", []),
            })

        overall = await self._build_overview(layer_summaries)
        return {"layers": layer_summaries, "overall": overall}

    async def _summarize_top_down(self, layer, depth: int, total: int, focus: str) -> dict:
        """为单层生成自顶向下摘要。"""
        context = self._ctx.format_for_llm([layer], "top-down")

        depth_hint = {
            0: "最高层 —— 描述整体架构目标",
            1: "中层 —— 描述该模块的功能定位和业务职责",
            2: "底层 —— 描述该文件/符号在上层中的角色",
            3: "最底层 —— 描述该符号的功能和接口",
        }.get(depth, "描述该层的功能")

        messages = [
            {
                "role": "system",
                "content": (
                    f"你是架构分析师。用中文进行自顶向下的架构描述。{depth_hint}"
                    f"当前分析焦点: {focus}。保持简洁，不超过 {_MAX_TOPDOWN_CHARS} 字。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"分析以下项目架构数据，生成该层的摘要：\n\n{context}\n\n"
                    f"请输出 JSON 格式: {{\"summary\": \"该层功能摘要\", \"role\": \"在整体中的角色\", \"key_items\": [\"关键项1\", \"关键项2\"]}}"
                ),
            },
        ]

        try:
            result = await self._llm(messages)
            return self._parse_json(result, {"summary": "", "role": "", "key_items": []})
        except Exception as e:
            logger.warning(f"top_down summary failed: {e}")
            return {"summary": layer.what, "role": "", "key_items": []}

    async def _build_overview(self, summaries: list[dict]) -> str:
        """从各层摘要组装整体概述。"""
        if len(summaries) <= 1:
            return summaries[0].get("summary", "") if summaries else ""

        layers_text = "\n".join(
            f"- [{s['level']}层] {s['name']}: {s.get('summary', '')[:200]}"
            for s in summaries
        )
        messages = [
            {
                "role": "system",
                "content": "你是架构分析师。基于各层摘要，用一段话总结整个分析路径的架构认知。不超过 300 字。",
            },
            {
                "role": "user",
                "content": f"各层摘要:\n{layers_text}\n\n请生成整体的架构认知总结。",
            },
        ]

        try:
            return await self._llm(messages)
        except Exception as e:
            logger.warning(f"build_overview failed: {e}")
            return "各层分析已完成，详见各层摘要。"

    # ═══════════════════════════════════════════
    # 自底向上
    # ═══════════════════════════════════════════

    async def bottom_up(self, start_symbol: str, levels: int = 3) -> dict:
        """自底向上分析：从符号出发层层抽象。

        Args:
            start_symbol: 起始符号名
            levels: 向上抽象层数

        Returns:
            {
                "layers": [
                    {"level": "symbol", "implementation": "...", "logic": "..."},
                    {"level": "file", "collaboration": "...", "pattern": "..."},
                    ...
                ],
                "abstraction": "最高层架构抽象"
            }
        """
        layers = self._ctx.get_upward_path(start_symbol)[:levels]
        layer_summaries = []

        for i, layer in enumerate(layers):
            desc = await self._summarize_bottom_up(layer, i)
            layer_summaries.append({
                "level": layer.level,
                "name": layer.name,
                "implementation": desc.get("implementation", ""),
                "logic": desc.get("logic", ""),
                "abstraction": desc.get("abstraction", ""),
            })

        abstraction = await self._build_abstraction(layer_summaries)
        return {"layers": layer_summaries, "abstraction": abstraction}

    async def _summarize_bottom_up(self, layer, depth: int) -> dict:
        """为单层生成自底向上摘要。"""
        context = self._ctx.format_for_llm([layer], "bottom-up")

        hints = {
            0: "最底层 —— 详细描述实现逻辑",
            1: "中层 —— 描述模块内协作方式",
            2: "高层 —— 描述架构模式",
            3: "最高层 —— 抽象为设计原则",
        }
        hint = hints.get(depth, "描述该层")

        messages = [
            {
                "role": "system",
                "content": (
                    f"你是架构分析师。用中文从底层向上做架构抽象。{hint}。"
                    f"保持简洁，不超过 {_MAX_BOTTOMUP_CHARS} 字。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"分析以下代码层数据，从实现角度生成摘要：\n\n{context}\n\n"
                    "请输出 JSON: "
                    '{"implementation": "该层功能实现", '
                    '"logic": "实现逻辑和协作方式", '
                    '"abstraction": "向上层抽象得到的架构认知"}'
                ),
            },
        ]

        try:
            result = await self._llm(messages)
            return self._parse_json(result, {"implementation": "", "logic": "", "abstraction": ""})
        except Exception as e:
            logger.warning(f"bottom_up summary failed: {e}")
            return {"implementation": layer.what, "logic": layer.how, "abstraction": ""}

    async def _build_abstraction(self, summaries: list[dict]) -> str:
        """从各层摘要抽象出最顶层的架构认知。"""
        if len(summaries) <= 1:
            return summaries[0].get("abstraction", "") or summaries[0].get("implementation", "")

        layers_text = "\n".join(
            f"- [{s['level']}层] {s['name']}\n  实现: {s.get('implementation', '')[:150]}\n  抽象: {s.get('abstraction', '')[:150]}"
            for s in summaries
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "你是架构分析师。基于底层实现细节，逐层向上抽象，"
                    "提炼出最高层的架构认知和设计原则。不超过 300 字。"
                ),
            },
            {
                "role": "user",
                "content": f"各层分析:\n{layers_text}\n\n请生成最高层的架构抽象。",
            },
        ]

        try:
            return await self._llm(messages)
        except Exception as e:
            logger.warning(f"build_abstraction failed: {e}")
            return "逐层分析已完成，详见各层摘要。"

    # ═══════════════════════════════════════════
    # 工具
    # ═══════════════════════════════════════════

    @staticmethod
    def _parse_json(text: str, default: dict) -> dict:
        """提取 LLM 输出中的 JSON。"""
        import json as json_mod
        # 尝试提取 JSON 块
        text = text.strip()
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            text = text[start:end].strip()
        elif text.startswith("{"):
            pass  # raw JSON
        else:
            # Find first { and last }
            b = text.find("{")
            e = text.rfind("}")
            if b >= 0 and e > b:
                text = text[b:e + 1]
            else:
                return default

        try:
            result = json_mod.loads(text)
            if isinstance(result, dict):
                return result
        except (json_mod.JSONDecodeError, ValueError):
            pass
        return default
