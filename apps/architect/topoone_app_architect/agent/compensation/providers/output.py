"""输出契约与图门禁 Provider — structured_output / logic_diagram 消费者(R1.2)。

- StructuredOutputProvider: structured_output=True → 收尾按 JSON 块契约解析
  (R3.3 正式语义随 DispatchTurn(M4) 接线; M2 提供确定性解析函数 + 消费位);
- LogicDiagramGateProvider: logic_diagram="uml" → ArtifactGate 确定性校验
  (R3.2: 图围栏存在且边≥3; 下发前校验随 DispatchTurn(M4) 接线)。
runner 侧契约零变更(D4/CONV-04)。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Tuple

from ..carriers import GateResult, PromptPiece
from ..ctx import CompensationCtx

_JSON_BLOCK = re.compile(r"```json\s*\n?(\{.*?\})\s*```", re.DOTALL)
# 图围栏(标准语法, 非渲染 IR): mermaid/plantuml/activity 等标注
_DIAGRAM_FENCE = re.compile(
    r"```(?:mermaid|plantuml|uml|activity|sequence)\w*\s*\n", re.IGNORECASE)
_EDGE_HINT = re.compile(r"(->|-->)|(-\->[^\n]*)|(^\s*(?:->|–>|=>)\s*)", re.MULTILINE)


def parse_json_block(text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """R3.3 双轨解析: JSON 块优先 → (payload|None, "json"|"text")。

    无合法 JSON 块 → (None, "text")——调用方回落文本固定行解析(兼容降级)。"""
    m = _JSON_BLOCK.search(text or "")
    if not m:
        return None, "text"
    try:
        d = json.loads(m.group(1))
        return (d if isinstance(d, dict) else None), "json"
    except Exception:  # noqa: BLE001
        return None, "text"


def validate_logic_diagram(text: str) -> GateResult:
    """R3.2 确定性校验: 核心逻辑图围栏存在, 且边表达≥3(->/--> 箭头计数)。"""
    if not _DIAGRAM_FENCE.search(text or ""):
        return GateResult(passed=False, note="缺少核心逻辑图围栏(```mermaid/plantuml)")
    edges = len(re.findall(r"-->|->|=>", text))
    if edges < 3:
        return GateResult(passed=False, note=f"逻辑图边数不足({edges}<3)")
    return GateResult(passed=True, note=f"逻辑图校验通过(边={edges})")


class StructuredOutputProvider:
    name = "structured_output"
    purposes = frozenset()
    consumes = frozenset({"structured_output"})

    def assemble(self, ctx: CompensationCtx, prompt) -> None:
        if getattr(ctx.gear, "structured_output", False):
            prompt.pieces.append(PromptPiece(
                placement="scaffold", key="output_contract_decl",
                text="[输出契约] 里程碑/完成报告优先以 ```json 块给出"
                     "(changed_files/verify/next); 无法结构化时用固定三行文本。",
                priority=60))

    def conclude(self, ctx: CompensationCtx, output):
        if not getattr(ctx.gear, "structured_output", False):
            return None
        payload, track = parse_json_block(getattr(output, "text", "") or "")
        note = "输出契约: json 块" if track == "json" and payload else \
            "输出契约: 文本协议(兼容降级)"
        from ..pipeline import Verdict
        return Verdict(ok=True, text=getattr(output, "text", ""),
                       gate_notes=[note])


class LogicDiagramGateProvider:
    name = "logic_diagram_gate"
    purposes = frozenset()
    consumes = frozenset({"logic_diagram"})

    def assemble(self, ctx: CompensationCtx, prompt) -> None:
        if str(getattr(ctx.gear, "logic_diagram", "") or "") == "uml":
            prompt.pieces.append(PromptPiece(
                placement="scaffold", key="logic_diagram_req",
                text="[图门禁] 任务指令须附核心逻辑图(PlantUML/Mermaid 标准语法,"
                     " activity/sequence 类), 下发前将做确定性校验。",
                priority=60))

    def conclude(self, ctx: CompensationCtx, output):
        if str(getattr(ctx.gear, "logic_diagram", "") or "") != "uml":
            return None
        gate = validate_logic_diagram(getattr(output, "text", "") or "")
        from ..pipeline import Verdict
        return Verdict(ok=gate.passed, text=getattr(output, "text", ""),
                       gate_notes=[f"图门禁: {gate.note}"])
