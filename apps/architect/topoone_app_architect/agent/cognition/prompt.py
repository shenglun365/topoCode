"""提示词注册表 (Prompt Registry) — 块化 + 单源化 + 分级 + 预算裁剪。

设计:
- 块 = {id, render(ctx), priority, required}; required 块(角色/边界/能力协议)
  永不裁剪, 条件块按 priority 升序淘汰
- 预算 = f(tier) 字符数(t0 宽松 → t4 极简), 由模型能力档案驱动
- 单源化(B4, MS-B3 起唯一模式): capability 块由 _ARCH_TOOLS 注册表渲染
  (brief/params_doc 注册点自声明; 缺省以 derive_params_doc 签名生成兜底)。
  存量迁移表 TOOL_BRIEFS/TOOL_PARAM_DOCS 与 legacy 等价回退通道(_CAPABILITY_DOC)
  已退役——教育面回到注册表单源(契约单源架构, 见
  docs/architect/tool-contract-single-source-2610.md)
- 覆盖通道: arch_collab_config 键 `prompt.overrides`
    {"blocks": {"<id>": "替换文本"}, "budget": {"2": 12000}}
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List


logger = logging.getLogger("arch.prompt_registry")

def _store():
    from ... import store
    return store


_OVERRIDES_KEY = "prompt.overrides"

# tier → system 总字符预算(恒置块之外的条件块裁剪目标; R2.2: 三档刻度对齐,
# 旧 3/4 档键随 2026-09-17 五档收敛移除——读路径已归一, 不会命中)
DEFAULT_BUDGET: Dict[int, int] = {0: 26000, 1: 22000, 2: 16000}


# ── 覆盖配置 ──────────────────────────────────────────────────────────

def _overrides() -> Dict[str, Any]:
    try:
        raw = _store().CollabConfigStore.get(_OVERRIDES_KEY, "")
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
    from ...agent.tools import req_agent as _req_agent_mod
    p = _req_agent_mod.tool_project_ctx(ctx.get("root"), ctx.get("project"))
    mode = "greenfield(从零)" if not ctx.get("project") else "existing(既有)"
    degraded = p.get("degraded", False)
    bound = p.get("bound", False)
    # cv-189 注入层硬控制: 未关联 KB → KB 叙述整句不注入(降级提示也是 KB 话术)
    kb = ("KB 已绑定，可检索资产/基线/依赖图。"
          if bound and not degraded else "")
    return ("你是 TopoCode 架构需求分析 agent(自由对话)。\n"
            f"当前项目：{p.get('name') or '(未绑定)'}，模式：{mode}。{kb}")


_BOUNDARY_TEXT = (
    "## 职责边界(重要)\n"
    "用户明确表达的需求一律受理、不拒做(含与项目关联较弱的脚本/工具/配置类)：照常收敛为"
    "需求规约(req.propose 带 title/requirementMd/**designMd**/acceptanceMd)，关联较弱时"
    "仅在方案中说明「独立于项目核心资产」并收敛 scope，不得以此推诿。"
    "已建需求(RQ 以系统回执为准)继续跟进完善。"
)


def _r_boundary(_ctx: Dict[str, Any]) -> str:
    return _BOUNDARY_TEXT


# GU-3 人格统一(2026-09-22, goal-understanding-2609): 静态判据层——身份唯一,
# 三问定性, 双出口。每回合的具体路线判定由决策表生成的回合指引注入(turns/goal),
# 本块只定义恒定人格与判断标准(防多轮目标转换的人格抖动)。
_POSTURE_TEXT = (
    "## 对话路线(判据)\n"
    "身份唯一：你是需求分析 agent 兼外循环编排者。知识/分析面由你自己承担，"
    "动手实现类能力由 coding subagent(cline/opencode/codex)承担。"
    "收到任何诉求先按三问定性：\n"
    "1) 产出物会**反复使用/多步执行/需要验收**？(项目级功能/环境搭建/初始化/"
    "交付组件) → 开发类需求：收敛为需求规约(req.propose)；方案要点/验收等关键"
    "要素缺失时**先集中提问再立卡**——提问是正当步骤，不是推诿；\n"
    "2) **单命令即时结果**？(查状态/跑个脚本/统计文件数) → task.propose 单次"
    "任务卡(默认保存)，勿绕需求流程；\n"
    "3) 拿不准？→ 先向用户提一个最关键的澄清问题，不落卡。\n"
    "续接规则：已绑定需求(RQ 编号以系统回执为准)的会话，补充/调整走 req.amend "
    "新版本；执行期 subagent 的提问/进展会以消息进入会话，用户回复即转达。\n"
    "回执与卡片(需求卡/任务卡)已自动落流展示——回答中**不要复述**其标题/方案/"
    "验收等内容，一句话确认或只补充增量说明。"
)


def _r_posture(_ctx: Dict[str, Any]) -> str:
    return _POSTURE_TEXT


def posture_text() -> str:
    """posture 判据块公开读取(legacy 等价串/测试用)。"""
    return _POSTURE_TEXT


def _r_capability(ctx: Dict[str, Any]):
    # B4 单源化(MS-B3 起唯一模式); MS-C2: 拆两段——基础契约(本块, 恒置) +
    # 参数文档段(capability_params 块, 可裁剪)——恢复预算防线对能力文档的效力。
    return _render_capability_base(_capability_entries(ctx), ctx)


def _r_capability_params(ctx: Dict[str, Any]):
    # MS-C2: 参数文档段(独立块, priority=46 预算紧张时最先裁——弱模型拿长
    # 参数表遵从率反降, 批丁实证; 面内工具清单保留)。
    return _render_capability_params(_capability_entries(ctx))


# R3.4: 工具面按挡裁剪(toolsurface 消费落地; kb=False → 检索工具同裁)
KB_RETRIEVAL_TOOLS = ("kb.asset.search", "kb.code_mappings", "kb.baseline",
                      "kb.graph")
# cv-187 KB 面(检索四件)——提示面裁剪与执行面拦截共用的单源集合。
# mcp.call 出向代理已退役(2610 MCP 定型: 主 agent 非 MCP 消费者)
KB_FACE_TOOLS = frozenset(KB_RETRIEVAL_TOOLS)
_WRITE_TOOLS = ("asset.semantic.save", "asset.semantic.update",
                "asset.semantic.merge", "asset.semantic.split",
                "asset.upsert", "convention.propose",
                "contract.propose")
_MINIMAL_KEEP = ("kb.asset.search", "project.ctx", "map.overview",
                 "code.read_symbols", "asset.semantic.search",
                 "asset.semantic.detail")


def _filter_tools(entries, tool_surface: str, kb_enabled: bool):
    """R3.4 工具面过滤: full=全量 / reduced=裁 KB 写+MCP 写 / minimal=只读核心;
    kb=False(T0 直通车)叠加裁 kb.* 检索工具。

    ⚠️ 执法边界(审计 B1): 本过滤为**提示级**——只裁能力文档声明面,
    run_arch_tool 执行面不拒绝(弱模型若仍发被裁工具会执行);
    硬执法待 ChatTurn 消费 RunParams 时接线(设计 §12 后续轨道)。"""
    out = []
    for name, entry in entries:
        if not kb_enabled and name in KB_FACE_TOOLS:
            continue
        if tool_surface == "minimal" and name not in _MINIMAL_KEEP:
            continue
        if tool_surface == "reduced" and name in _WRITE_TOOLS:
            continue
        out.append((name, entry))
    return out


def _r_ir_schema(_ctx: Dict[str, Any]) -> str:
    # MS-C1 教育面=执行面: GU 限面不含绘图工具 → IR 结构文档不注入
    # (answer 纯读面曾恒注入 653+ 字, 同 system 自相矛盾审计项)。
    allowed = _ctx.get("gu_allowed")
    if allowed is not None and not (set(allowed) & _DIAGRAM_FACE_TOOLS):
        return ""
    from ...agent.tools import req_agent as _req3
    return _req3._ir_schema_doc()


def _r_diagram_skill(ctx: Dict[str, Any]) -> str:
    if not ctx.get("diagram_skill"):
        return ""
    from ...agent.tools import req_agent as _req4
    return _req4._diagram_skill_doc()


def _r_skill_docs(ctx: Dict[str, Any]) -> str:
    scenarios = ctx.get("skill_scenarios") or []
    if not scenarios:
        return ""
    # MS-C1: 技能文档仅需求分析族面装载(限面回合不教面外方法论)
    if not _req_face_on(ctx):
        return ""
    from ...sem.skill_docs import skill_docs
    return skill_docs(ctx.get("root"), ctx.get("project"), scenarios)


def _r_skill_catalog(ctx: Dict[str, Any]) -> str:
    # W6: 目录+路由(表为真相源覆盖内置, 清表回退); cv-189 同款门消毒 KB 话术
    # MS-C1: 仅需求分析族面装载(propose-task/answer 等限面回合不注入目录)
    if not _req_face_on(ctx):
        return ""
    try:
        from ...sem.skill_catalog import render_skill_catalog
        md = render_skill_catalog(str(ctx.get("project") or ""))
        if md and "KB" in md:
            try:
                from ...arch_routes.project import kb_degraded as _kd
                if _kd(ctx.get("root"), ctx.get("project")):
                    md = md.replace("KB", "知识资产")
            except Exception:  # noqa: BLE001
                pass
        return md
    except Exception:  # noqa: BLE001 — 目录失败不阻塞组装
        return ""


def _register_defaults() -> None:
    # 渲染顺序对齐既有 chat_system_prompt 拼接顺序(header/boundary/capability/
    # ir/diagram/mcp/skill), 等价模式下逐字节一致; 裁剪顺序 ir→diagram→mcp→skill
    register_block(PromptBlock("header", _r_header, order=0, priority=0, required=True))
    register_block(PromptBlock("boundary", _r_boundary, order=5, priority=5, required=True))
    register_block(PromptBlock("posture", _r_posture, order=6, priority=20, required=True))
    register_block(PromptBlock("capability", _r_capability, order=10, priority=10, required=True))
    register_block(PromptBlock("capability_params", _r_capability_params, order=11, priority=46))
    register_block(PromptBlock("ir_schema", _r_ir_schema, order=12, priority=45))
    register_block(PromptBlock("diagram_skill", _r_diagram_skill, order=14, priority=40))
    register_block(PromptBlock("skill_catalog", _r_skill_catalog, order=17, priority=26))
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
    # M1 收编: 裁剪循环经 compensation.providers.budget(逐字等价, R1.1)
    # R3.4: ctx_budget 系数实消费(dossier/工具结果同系数的提示预算面)
    budget = int(budget_for(tier) * float(ctx.get("ctx_budget", 1.0) or 1.0))
    from ..compensation.providers import trim_optional_blocks
    rendered, _ = trim_optional_blocks(rendered, budget, tier, logger)
    rendered.sort(key=lambda r: r[0].order)
    return "\n\n".join(t for _, t in rendered)




# ── 单源渲染: 工具注册表 → 能力文档 ────────────────────────────────────

# 层级概念约定(与 _CAPABILITY_DOC 逐字对齐——单源文档结构完整性)
_TIER_CONVENTION_DOC = (
    "层级概念约定：组件带**图层级**(L0=底层原子社区，L1/L2=逐级聚合，见 map.overview 目录「层级」列)；"
    "语义资产带**抽象粒度** level(business/implementation/logic)。"
    "用户问「L0/L1 模块/组件」指组件图层级(用 map.*)，问资产「粒度/层次」指语义资产 level"
    "(用 asset.semantic.* 的 level 过滤)。"
)

# 图表输出纪律(与 _CAPABILITY_DOC 图表段对齐; IR 结构细节由 ir_schema 块承载)
_DIAGRAM_OUTPUT_DOC = (
    "图表输出能力：当描述语义数据资产(数据结构/处理流程/控制逻辑)、依赖链路、"
    "实现路径或改动影响时，用图直观表达。**优先**输出 ```diagram 围栏，内容为 JSON 图结构"
    "(DiagramSchema)，前端会自动把它确定性地转成 Mermaid/PlantUML 并动画，"
    "避免直接写图语法出错。仅当图极简单(≤2节点)或 IR 无法表达时，"
    "才直接输出 ```mermaid / ```plantuml 代码围栏。"
    "要求：节点精简、命名与代码资产一致；图中不要包含 [TOOL_CALL] 块。"
)


def _tool_brief(name: str, entry: Dict[str, Any]) -> str:
    """能力清单一行简介: 注册点 brief → 描述首句兜底(MS-B3 表退役后单源)。"""
    brief = (entry.get("brief") or "").strip()
    if brief:
        return brief
    desc = (entry.get("description") or "").strip()
    return desc.split("。")[0][:120] if desc else ""


# ── GU 面工具集(MS-C1 教育面=执行面; 块条件数据驱动, 不散落工具名清单) ──
_DIAGRAM_FACE_TOOLS = frozenset({"diagram.build", "diagram.validate"})
_REQ_FACE_TOOLS = frozenset({"req.propose", "req.amend"})


def _req_face_on(ctx: Dict[str, Any]) -> bool:
    """需求分析族面判定: 未限面(True) 或 面含 req 系工具。"""
    allowed = ctx.get("gu_allowed")
    if allowed is None:
        return True
    return bool(set(allowed) & _REQ_FACE_TOOLS)


def _capability_entries(ctx: Dict[str, Any]):
    """面内工具条目收集(W1-1 排序; 空=无能力文档)——base/params 两段共用。"""
    from ...agent.tools import req_agent as _req_agent_mod
    entries = [(n, e) for n, e in _req_agent_mod._ARCH_TOOLS.items()
               if n not in ("diagram.build", "diagram.validate")]
    entries = _filter_tools(entries, ctx.get("tool_surface") or "full",
                            ctx.get("kb_enabled", True))
    allowed = ctx.get("gu_allowed")
    if allowed is not None:
        allowed = set(allowed)
        entries = [(n, e) for n, e in entries if n in allowed]
    if not entries:
        return []
    entries.sort(key=lambda ne: ne[0])   # 注册序随导入路径漂移, prompt 须确定
    return entries


def _render_capability_base(entries, ctx: Dict[str, Any]) -> str:
    """基础契约段(恒置): 工具清单 + 协议(纪律按 req 面门) + 范围 + 图表纪律。"""
    if not entries:
        return ""
    slim = bool(ctx.get("prompt_slim"))
    req_face = _req_face_on(ctx)
    lines = ["你可以使用以下能力(skills/tools)："]
    for name, entry in entries:
        brief = _tool_brief(name, entry)
        lines.append(f"- {name}：{brief}" if brief else f"- {name}")
        if name == "map.graph":
            lines.append(_TIER_CONVENTION_DOC)   # 层级约定锚在地图组之后
    lines.append("")
    lines.append(protocol_doc(slim=slim, req_face=req_face))
    if not slim:
        lines.append(_SCOPE_DOC)
    lines.append(_DIAGRAM_OUTPUT_DOC)
    return "\n".join(lines)


def _render_capability_params(entries) -> str:
    """参数文档段(MS-C2 可裁剪): 面内工具 params_doc 清单。"""
    if not entries:
        return ""
    params = ["各工具的参数："]
    for name, entry in entries:
        pd = _tool_params_doc(name, entry)
        if pd:
            params.append(f"- {name}: {pd}")
    return "\n".join(params) if len(params) > 1 else ""


def _tool_params_doc(name: str, entry: Dict[str, Any]) -> str:
    """参数形状: 注册点 params_doc → 签名自动生成兜底(MS-B1/B3)。"""
    pd = (entry.get("params_doc") or "").strip()
    if pd:
        return pd
    from ...agent.tools.registry import derive_params_doc
    return derive_params_doc(entry.get("handler"))


def capability_doc_from_tools(tool_surface: str = "full",
                              kb_enabled: bool = True,
                              allowed=None, slim: bool = False) -> str:
    """由 _ARCH_TOOLS 注册表渲染能力文档(单源模式; 测试/诊断公共入口)。

    MS-C2 后生产渲染走块拆分(capability + capability_params 两块, 预算独立);
    本函数保留组合语义(base+params)供既有消费面与 golden。
    R3.4: tool_surface/kb_enabled 按挡裁剪; allowed(GU 限定)→面内子集;
    slim(简挡)→省系统面说明段。
    """
    ctx = {"tool_surface": tool_surface, "kb_enabled": kb_enabled,
           "gu_allowed": allowed, "prompt_slim": slim}
    entries = _capability_entries(ctx)
    base = _render_capability_base(entries, ctx)
    if not base:
        return ""
    parts = [base]
    params = _render_capability_params(entries)
    if params:
        parts.append(params)
    return "\n".join(parts)


# ── 工具调用纪律(单源常量) ────────────────────────────────────────────
# 唯一源: chat 面(_PROTOCOL_DOC)与工具面(req_agent 能力文档)共同引用拼接。
# 禁止在任何调用面手工复制这些段落——漂移即事故(cv-177: 两份副本三处不一致)。
# 工具结果回喂包裹(cv-189: 旧文案「知识库工具返回结果」对 project.ctx/
# req.propose 等本地工具也是错话, 且在模型日志里持续制造 KB 叙述)
TOOL_FEED_PREFIX = "以下是工具返回结果，请基于结果直接回答，不再输出工具调用块：\n"


from .envelope import REQUEST_ENVELOPE_DOC, wrap_user_request  # noqa: F401 W1-2 单源再导出



TOOL_PROTOCOL_HEAD = (
    "工具调用协议(重要)：当需要检索项目数据才能回答(例如确认真实资产、组件与边界)时，"
    "先且仅先输出一个工具调用块，格式为：\n"
    '[TOOL_CALL]{"tool":"<工具名>","arguments":{参数}}[/TOOL_CALL]\n'
)
ANTI_FABRICATION = (
    "硬性规则(防编造)：凡是会改数据或有真实执行结果的指令(提取/刷新/保存/委派执行等)，"
    "必须实际调用对应工具拿到同步返回的结果，再如实转述；"
    "严禁不调用工具就输出『已启动/报告/条数/检查结果』等编造结论。\n"
)
# 批丁去重: 原条 1(「只有开发类需求才 req.propose」)与 posture 三问定性重复
# (人格层单源), 本纪律只保留工具面规则(amend/查看/编号管理)。
REQ_CARD_DISCIPLINE = (
    "需求卡纪律：修改既有需求必须用 [TOOL_CALL] 调 req.amend，严禁重复 req.propose；"
    "用户仅要求查看需求卡时直接概述当前绑定内容，严禁 req.amend(查看不是修改)；"
    "RQ/数据编号由系统管理：调用不传 reqId，回复中的编号只来自工具返回，严禁自造。\n"
)
DIRECT_CMD_SYMBOLS = (
    "会话指令符号：/执行 由系统确定性直通(不经你)，不要代用户发出；"
    "/调整 作为普通消息进入对话(由你整理修订内容)。\n"
)
TOOL_TAIL = (
    "输出工具调用块后不要再写其它内容；收到工具结果后才继续回答。"
    "若无需检索即可直接回答，就不要调用工具。"
)

_PROTOCOL_DOC = (
    TOOL_PROTOCOL_HEAD + ANTI_FABRICATION + REQ_CARD_DISCIPLINE
    + REQUEST_ENVELOPE_DOC + DIRECT_CMD_SYMBOLS + TOOL_TAIL
)

def protocol_doc(slim: bool = False, req_face: bool = True) -> str:
    """工具调用协议单源组装(slim=简挡省略系统面说明段; 信封纪律两态恒在)。

    MS-C1: req_face=False(GU 限面不含 req 系工具)→省需求卡纪律段——同 system
    内「教面外工具用法」的自相矛盾消除(propose-task 面不再教 req.amend)。
    """
    discipline = REQ_CARD_DISCIPLINE if req_face else ""
    if slim:
        return (TOOL_PROTOCOL_HEAD + ANTI_FABRICATION
                + discipline + REQUEST_ENVELOPE_DOC + TOOL_TAIL)
    if req_face:
        return _PROTOCOL_DOC
    return (TOOL_PROTOCOL_HEAD + ANTI_FABRICATION
            + REQUEST_ENVELOPE_DOC + DIRECT_CMD_SYMBOLS + TOOL_TAIL)

_SCOPE_DOC = (
    "可处理范围：需求分析/澄清/范围收敛、资产命中与影响评估、设计实现建议、新项目引导；"
    "通用闲聊/外包式实现礼貌引导回需求语境(软拒绝，允许继续提问)。"
    "回复保持简洁、直接、可操作，可输出 Markdown。"
)


def set_overrides(data: Dict[str, Any]) -> None:
    _store().CollabConfigStore.set(_OVERRIDES_KEY, json.dumps(data, ensure_ascii=False))


# ── 分析挡位指引 → 已迁 agent/governance/gears.py(环节十二a 挡位体系,
#    数据驱动 T0-T4; 本文件不再持有二值挡位文本) ─────────────────────
