"""CallTurn — 单项调用统一入口(S 轴, 整体设计 §4; R3.1 链 3 收编 D7-①)。

三要素(R3.1): 按 (purpose, tier) 注入补偿脚手架(§5.4 矩阵) + 按挡 RetryPolicy
(nudge 次数单源 gears.RETRY_NUDGES) + 确定性兜底(由调用方提供)。
横切: llm_dataset 遥测带 {tier, purpose, axis, attempt}(D5 实效面数据基座)。
本模块为 llm_sync 唯一白名单调用方(D12 门禁; 其余链 3 调用点随 D7 批次迁入)。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from ..compensation.carriers import RetryPolicy
from ..compensation.ctx import Purpose
from ..governance.gears import DEFAULT_TIER_ID, RETRY_NUDGES, WEAKEST_TIER

logger = logging.getLogger(__name__)


# ── 分目的弱档脚手架(需求规格 §5.4 矩阵落地; 仅最弱挡追加, 强/中挡行为等价) ──

_SCAFFOLDS: Dict[str, str] = {
    Purpose.CLARIFY.value:
        "\n\n【弱模型补偿·问题槽位】返回 3-5 个问题, 且必须覆盖以下槽位"
        "(每槽至少 1 问, 已明确的不必再问):\n"
        "1. 目标——要达成什么(需求目标不清时问);\n"
        "2. 边界——涉及/禁止改动哪些文件或模块(范围不清时问);\n"
        "3. 验收——如何算完成(标准缺失时问)。\n"
        '格式: [{"key": "goal|scope|acceptance|...", "label": "...", '
        '"type": "text", "hint": "..."}]。只输出 JSON 数组, 不要解释。',
    Purpose.COLLECT.value:
        "\n\n【弱模型补偿·字段逐项】输出 JSON 对象, 六个必填字段逐项核对:\n"
        "1. functionalScope: 功能目标列表(来自用户作答/对话, 不新增推断);\n"
        "2. entityBoundary: 实体边界列表;\n"
        "3. assetScope: 资产范围, **只能从下方目录与命中清单中选择**, 禁止臆造;\n"
        "4. estMin: 预估分钟数(整数);\n"
        "5. implementationPath: 实现路径(一段话);\n"
        "6. assessmentSummary: 评估结论(一段话)。\n"
        "只输出一个 JSON 对象, 不要解释。",
    Purpose.EXTRACTION.value:
        "\n\n【弱模型补偿·逐项要求】结构化输出六字段, 逐项核对:\n"
        "1. title: 需求短标题(≤24字), 必填;\n"
        "2. requirementMd: 需求目标(要达成什么), 必填;\n"
        "3. designMd: 技术方案要点(怎么做)——对话中讨论过才写, 没有就留空字符串;\n"
        "4. allowedScopeMd: 允许改动的文件/目录, 逐行一条;\n"
        "5. forbiddenScopeMd: 禁止改动的部分, 逐行一条;\n"
        "6. acceptanceMd: 验收标准, 逐行一条。\n"
        "字段示例: {\"title\": \"连通性探测脚本\", \"requirementMd\": \"实现...\", "
        "\"allowedScopeMd\": \"scripts/\\nsrc/probe/\"}\n"
        "对话记录中没有的约束**留空, 禁止编造**; 只输出 JSON, 不要解释。",
    Purpose.SPLIT.value:
        "\n\n【弱模型补偿·步骤模板】每个步骤按「文件+动作+验证」三要素写 instruction:\n"
        "例: {\"title\": \"扩展配置解析\", \"instruction\": \"在 src/config.py 中增加"
        " timeout 字段解析(动作); 涉及 src/config.py(文件); 运行单测验证解析正确(验证)\"}\n"
        "约束: 2-5 步; 每步只动一个模块, **禁止跨模块**; 步骤间只写必要依赖。"
        "只输出 JSON, 不要解释。",
    Purpose.PROBE.value:
        "\n\n【弱模型补偿·输出示例】每个文件必须带 source 标注, 逐条输出:\n"
        "例: {\"files\": [{\"path\": \"src/http/server.py\", \"source\": \"tree\"}, "
        "{\"path\": \"src/db/\", \"source\": \"history\"}]}\n"
        "source 只能取: tree=文件树中真实存在 / history=历史需求边界出现过 / "
        "kb=资产线索 / inference=你的推断(尽量少)。只输出 JSON, 不要解释。",
}


def scaffold_for(purpose: Purpose, tier: str) -> str:
    """分目的弱档脚手架(仅最弱挡追加; 其余挡位返回空串——基线提示不动)。"""
    if tier != WEAKEST_TIER:
        return ""
    return _SCAFFOLDS.get(purpose.value, "")


def retry_for(tier: str) -> RetryPolicy:
    """按挡重试策略(nudge 次数单源 gears.RETRY_NUDGES; 兜底由调用方注入)。"""
    return RetryPolicy(max_nudges=RETRY_NUDGES.get(tier, 1))


def _telemetry(event: str, **data: Any) -> None:
    try:
        from ..reflection import dataset as _lds
        _lds.record(event, **data)
    except Exception:  # noqa: BLE001 — 遥测失败不阻塞主链
        pass


def call(purpose: Purpose, messages: List[Dict[str, str]], *, tier: str = DEFAULT_TIER_ID,
         model_id: Optional[str] = None, schema: Optional[dict] = None,
         max_tokens: int = 2048,
         validate: Optional[Callable[[Any], tuple]] = None,
         fallback: Optional[Callable[[], Any]] = None,
         runner: bool = False, root: Optional[str] = None,
         project: Optional[str] = None) -> Dict[str, Any]:
    """单项调用(S 轴): 脚手架注入 → 按挡重试 → 确定性兜底。

    validate(payload) -> (ok, reason); 缺省 = payload 为非空产出即通过。
    fallback() -> 兜底产出(返回 None = 无兜底); 兜底产出按 ok=True/degraded=True
    返回(R2.3/§5.4: extraction→澄清问询, split→单卡 None, probe→ok False)。
    runner=True: 走 run_tools_loop 通道(带工具面/结构化; harness clarify/collect
    等需要 KB 工具面的调用点), 否则 llm_sync 直连。
    返回 {ok, output, content, attempts, degraded, modelId}。
    """
    from ...agent.tools import req_agent as _ra   # 调用期解析(测试打桩接缝)
    msgs = list(messages)
    scaffold = scaffold_for(purpose, tier)
    if scaffold:
        msgs.append({"role": "user", "content": scaffold})
    policy = retry_for(tier)
    attempts = 0
    last_reason = ""
    while True:
        try:
            if runner:
                res = _ra.run_tools_loop(
                    msgs, root=root, project=project,
                    mode="structured" if schema else "chat",
                    output_schema=schema, max_tokens=max_tokens,
                    model_id=model_id) or {}
                res = {"output": res.get("output"),
                       "content": res.get("content", ""),
                       "modelId": res.get("modelId", "")}
            else:
                res = _ra.llm_sync(
                    msgs, mode="structured" if schema else "chat",
                    output_schema=schema, max_tokens=max_tokens,
                    model_id=model_id or None)
        except Exception as e:  # noqa: BLE001 — llm 不可用按失败尝试计
            logger.info("[call-turn] %s llm 不可用: %s", purpose.value, e)
            res = {}
            last_reason = f"llm 不可用: {str(e)[:120]}"
        # 无 schema 通道产出在 content(纯文本, runner/直连同规); 结构化在 output
        if not schema:
            payload = (res or {}).get("content")
        else:
            payload = (res or {}).get("output")
        if validate is None:
            ok, reason = bool(payload), ("" if payload else "输出为空")
        else:
            ok, reason = validate(payload)
        if ok:
            _telemetry("llm_call_turn", ok=True, purpose=purpose.value,
                       tier=tier, axis="S", attempts=attempts + 1)
            return {"ok": True, "output": payload,
                    "content": str((res or {}).get("content") or ""),
                    "modelId": (res or {}).get("modelId") or "",
                    "attempts": attempts + 1, "degraded": False}
        last_reason = reason or last_reason
        if attempts >= policy.max_nudges:
            break
        attempts += 1
        msgs.append({"role": "user", "content":
                     f"上一次结构化输出未通过校验({str(last_reason)[:160]})。"
                     "请严格按字段要求重新输出完整 JSON, 不要解释、不要输出多余文本。"})
    # 重试耗尽: 遥测 + 确定性兜底
    _telemetry("llm_call_turn", ok=False, purpose=purpose.value,
               tier=tier, axis="S", attempts=attempts + 1)
    if fallback is not None:
        fb = fallback()
        if fb is not None:
            return {"ok": True, "output": fb, "content": "",
                    "modelId": "", "attempts": attempts + 1, "degraded": True}
    return {"ok": False, "output": None, "content": "",
            "modelId": "", "attempts": attempts + 1, "degraded": False}
