"""提示词注册表 (Prompt Registry) — 块化 + 单源化 + 分级 + 预算裁剪。

设计:
- 块 = {id, render(ctx), priority, required}; required 块(角色/边界/能力协议)
  永不裁剪, 条件块按 priority 升序淘汰
- 预算 = f(tier) 字符数(t0 宽松 → t4 极简), 由模型能力档案驱动
- 单源化: capability 块支持双模式——
    等价模式(默认): 沿用 _CAPABILITY_DOC 原文(行为等价, 快照回归基线)
    单源模式(配置开): 由 _ARCH_TOOLS 注册表 description+params_doc 渲染,
      消除工具文档双份漂移; P3 实测调优时切换
- 覆盖通道: arch_collab_config 键 `prompt.overrides`
    {"blocks": {"<id>": "替换文本"}, "single_source": true, "budget": {"2": 12000}}
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from . import store

logger = logging.getLogger("arch.prompt_registry")

_OVERRIDES_KEY = "prompt.overrides"

# tier → system 总字符预算(恒置块之外的条件块裁剪目标)
DEFAULT_BUDGET: Dict[int, int] = {0: 26000, 1: 22000, 2: 16000, 3: 10000, 4: 6000}


# ── 覆盖配置 ──────────────────────────────────────────────────────────

def _overrides() -> Dict[str, Any]:
    try:
        raw = store.CollabConfigStore.get(_OVERRIDES_KEY, "")
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def budget_for(tier: int) -> int:
    ov = _overrides().get("budget") or {}
    try:
        return int(ov.get(str(tier)) or ov.get(tier) or DEFAULT_BUDGET.get(tier, 16000))
    except (TypeError, ValueError):
        return DEFAULT_BUDGET.get(tier, 16000)


# ── 块注册表 ──────────────────────────────────────────────────────────

@dataclass
class PromptBlock:
    block_id: str
    render: Callable[[Dict[str, Any]], str]   # ctx → 文本(空串=本回合不注入)
    order: int = 50                            # 渲染顺序(升序)
    priority: int = 50                         # 裁剪优先级: 数值大先淘汰
    required: bool = False                     # 恒置块, 永不裁剪
    tier_range: tuple = (0, 4)                # 适用档位(闭区间)


_REGISTRY: Dict[str, PromptBlock] = {}


def register_block(block: PromptBlock) -> None:
    _REGISTRY[block.block_id] = block


def _r_header(ctx: Dict[str, Any]) -> str:
    from .req_agent import tool_project_ctx
    p = tool_project_ctx(ctx.get("root"), ctx.get("project"))
    mode = "greenfield(从零)" if not ctx.get("project") else "existing(既有)"
    degraded = p.get("degraded", False)
    bound = p.get("bound", False)
    kb = ("KB 已绑定，可检索资产/基线/依赖图。" if bound and not degraded
          else "KB 降级(无资产检索)，仅能基于需求描述给出规划建议，建议先关联知识库。")
    return ("你是 TopoCode 架构需求分析 agent(自由对话)。\n"
            f"当前项目：{p.get('name') or '(未绑定)'}，模式：{mode}。{kb}")


_BOUNDARY_TEXT = (
    "## 职责边界(重要)\n"
    "用户明确表达的需求**一律受理**，不拒做、不引导用户另找工具——包括与当前项目"
    "关联较弱的通用编程/运维任务(脚本、工具、配置等)：照常收敛为需求规约"
    "(req.propose 带 title/requirementMd/**designMd**/acceptanceMd)，后续同样可 /定稿 + /执行。"
    "关联较弱时仅在方案中说明「独立于项目核心资产」并收敛 scope，**不得以此为由拒绝或推诿**。"
    "已创建需求(RQ 编号以系统回执为准)后继续跟进完善，不得再声明该任务不属于职责范围。"
)


def _r_boundary(_ctx: Dict[str, Any]) -> str:
    return _BOUNDARY_TEXT


def _r_capability(ctx: Dict[str, Any]) -> str:
    if _overrides().get("single_source"):
        doc = capability_doc_from_tools()
        return doc or _legacy_capability_doc()
    return _legacy_capability_doc()


def _legacy_capability_doc() -> str:
    from .req_agent import _CAPABILITY_DOC
    return _CAPABILITY_DOC


def _r_ir_schema(_ctx: Dict[str, Any]) -> str:
    from .req_agent import _ir_schema_doc
    return _ir_schema_doc()


def _r_diagram_skill(ctx: Dict[str, Any]) -> str:
    if not ctx.get("diagram_skill"):
        return ""
    from .req_agent import _diagram_skill_doc
    return _diagram_skill_doc()


def _r_mcp(_ctx: Dict[str, Any]) -> str:
    from .req_agent import _mcp_doc
    return _mcp_doc()


def _r_skill_docs(ctx: Dict[str, Any]) -> str:
    scenarios = ctx.get("skill_scenarios") or []
    if not scenarios:
        return ""
    from .asset_skill import skill_docs
    return skill_docs(ctx.get("root"), ctx.get("project"), scenarios)


def _register_defaults() -> None:
    # 渲染顺序对齐既有 chat_system_prompt 拼接顺序(header/boundary/capability/
    # ir/diagram/mcp/skill), 等价模式下逐字节一致; 裁剪顺序 ir→diagram→mcp→skill
    register_block(PromptBlock("header", _r_header, order=0, priority=0, required=True))
    register_block(PromptBlock("boundary", _r_boundary, order=5, priority=5, required=True))
    register_block(PromptBlock("capability", _r_capability, order=10, priority=10, required=True))
    register_block(PromptBlock("ir_schema", _r_ir_schema, order=12, priority=45))
    register_block(PromptBlock("diagram_skill", _r_diagram_skill, order=14, priority=40))
    register_block(PromptBlock("mcp", _r_mcp, order=16, priority=30))
    register_block(PromptBlock("skill_docs", _r_skill_docs, order=18, priority=22))


_register_defaults()


# ── 组装器 ────────────────────────────────────────────────────────────

def render_system(ctx: Dict[str, Any]) -> str:
    """按档案 tier 组装 system: 块渲染 → 覆盖替换 → 预算裁剪。

    ctx: {root, project, diagram_skill, skill_scenarios, tier, model_id}
    """
    tier = int(ctx.get("tier") if isinstance(ctx.get("tier"), int) else 1)
    ov_blocks = (_overrides().get("blocks") or {})
    parts: List[str] = []
    # 渲染全部非空块
    rendered: List[tuple] = []   # (block, text)
    for blk in _REGISTRY.values():
        if not (blk.tier_range[0] <= tier <= blk.tier_range[1]):
            continue
        try:
            text = (ov_blocks.get(blk.block_id) or blk.render(ctx) or "").strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("[prompt-registry] 块 %s 渲染失败: %s", blk.block_id, e)
            continue
        if text:
            rendered.append((blk, text))
    # 预算裁剪: 条件块按 priority 降序淘汰直到达标(恒置块保留)
    budget = budget_for(tier)
    total = sum(len(t) for _, t in rendered)
    optional = sorted([r for r in rendered if not r[0].required],
                      key=lambda r: -r[0].priority)
    dropped = []
    for blk, text in optional:
        if total <= budget:
            break
        total -= len(text) + 2
        rendered.remove((blk, text))
        dropped.append(blk.block_id)
    if dropped:
        logger.info("[prompt-registry] tier=%s 预算 %s 裁剪块: %s", tier, budget, dropped)
    rendered.sort(key=lambda r: r[0].order)
    return "\n\n".join(t for _, t in rendered)


# ── 单源渲染: 工具注册表 → 能力文档 ────────────────────────────────────

def capability_doc_from_tools() -> str:
    """由 _ARCH_TOOLS 注册表渲染能力文档(单源模式)。

    结构对齐 _CAPABILITY_DOC: 工具清单(description 单源) + 工具调用协议 +
    硬性规则(防编造) + 需求落库纪律 + 会话指令符号 + 参数表(params_doc) +
    可处理范围 + 图表输出。
    """
    from .req_agent import _ARCH_TOOLS
    lines = ["你可以使用以下能力(skills/tools)："]
    params = ["各工具的参数："]
    for name, entry in _ARCH_TOOLS.items():
        desc = (entry.get("description") or "").strip()
        lines.append(f"- {name}：{desc}" if desc else f"- {name}")
        pd = (entry.get("params_doc") or "").strip()
        if pd:
            params.append(f"- {name}: {pd}")
    lines.append("")
    lines.append(_PROTOCOL_DOC)
    if len(params) > 1:
        lines.append("\n".join(params))
    lines.append(_SCOPE_DOC)
    return "\n".join(lines)


_PROTOCOL_DOC = (
    "工具调用协议(重要)：当需要检索知识库/项目数据才能回答(例如确认真实资产、基线、依赖链路)时，"
    "先且仅先输出一个工具调用块，格式为：\n"
    '[TOOL_CALL]{"tool":"<工具名>","arguments":{参数}}[/TOOL_CALL]\n'
    "硬性规则(防编造)：凡是会改数据或有真实执行结果的指令(提取/刷新/保存/定稿/委派执行等)，"
    "必须实际调用对应工具拿到同步返回的结果，再如实转述；"
    "严禁不调用工具就输出『已启动/报告/条数/检查结果』等编造结论。\n"
    "需求落库纪律(必须遵守)：\n"
    "1. 修改既有需求(用户确认后补充约束/调整方案/完善规约) → 必须用 [TOOL_CALL] 调 "
    "req.amend，严禁重新 req.propose 或输出裸 JSON 围栏当作工具调用；\n"
    "2. RQ 编号/数据 ID 一律由系统管理：工具调用不传 reqId(系统自动取会话绑定)，"
    "回复中的编号只来自工具返回，严禁自造编号(会被系统守卫拦截)；\n"
    "3. 确认(draft→ready)由用户指令 `/定稿` 发起(系统直通)；修订(req.amend)时不要顺带调用 req.finalize。\n"
    "会话指令符号(系统处理，与模型无关)：用户消息以 / 开头(/执行 /定稿 /继续 /diff /调整)时"
    "由系统直接执行确定性动作——模型不会收到这类消息，也不要在回复中代用户发出指令。\n"
    "输出工具调用块后不要再写其它内容；收到工具结果后才继续回答。"
    "若无需检索即可直接回答，就不要调用工具。"
)

_SCOPE_DOC = (
    "可处理范围：\n"
    "1. 需求分析/澄清/范围收敛、资产命中与影响评估；\n"
    "2. 产品设计、软件开发实现建议(非文档化的帮助性建议)；\n"
    "3. 新项目引导(从零建立开发环境/确立目标)、未关联 KB 的已有项目建立 KB 的引导(非强制)。\n"
    "越界处理(软拒绝)：对与需求分析无关的通用闲聊/外包式实现请求，礼貌说明能力范围并引导回"
    "需求分析语境，不深入执行，但允许用户继续提问。\n"
    "回复保持简洁、直接、可操作，可输出 Markdown。"
)


def set_overrides(data: Dict[str, Any]) -> None:
    store.CollabConfigStore.set(_OVERRIDES_KEY, json.dumps(data, ensure_ascii=False))
