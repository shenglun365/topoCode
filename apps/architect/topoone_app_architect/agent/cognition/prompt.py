"""提示词注册表 (Prompt Registry) — 块化 + 单源化 + 分级 + 预算裁剪。

设计:
- 块 = {id, render(ctx), priority, required}; required 块(角色/边界/能力协议)
  永不裁剪, 条件块按 priority 升序淘汰
- 预算 = f(tier) 字符数(t0 宽松 → t4 极简), 由模型能力档案驱动
- 单源化(B4 默认): capability 块由 _ARCH_TOOLS 注册表 brief+params_doc 渲染
  (存量迁移表 TOOL_BRIEFS/TOOL_PARAM_DOCS 承载原文); 配置 `single_source: false`
  可回退等价模式(_CAPABILITY_DOC 原文, 行为等价基线)
- 覆盖通道: arch_collab_config 键 `prompt.overrides`
    {"blocks": {"<id>": "替换文本"}, "single_source": true, "budget": {"2": 12000}}
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


def _r_capability(ctx: Dict[str, Any]) -> str:
    # B4 单源化默认开(双轨漂移消灭); `single_source: false` 覆盖可回退等价模式
    if _overrides().get("single_source", True):
        doc = capability_doc_from_tools(
            tool_surface=ctx.get("tool_surface") or "full",
            kb_enabled=ctx.get("kb_enabled", True),
            allowed=ctx.get("gu_allowed"),
            slim=bool(ctx.get("prompt_slim")))
        if doc:
            return doc
    return _legacy_capability_doc()


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


def _legacy_capability_doc() -> str:
    from ...agent.tools import req_agent as _req2
    return _req2._CAPABILITY_DOC


def _r_ir_schema(_ctx: Dict[str, Any]) -> str:
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
    from ...sem.skill_docs import skill_docs
    return skill_docs(ctx.get("root"), ctx.get("project"), scenarios)


def _r_skill_catalog(ctx: Dict[str, Any]) -> str:
    # W6: 目录+强制路由(表为真相源覆盖内置, 清表回退); cv-189 同款门消毒 KB 话术
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



# ── B4 工具文档迁移表(与 _CAPABILITY_DOC 逐字对齐; 单源渲染的存量数据源) ──
# brief: 能力清单行(`- name：brief`); params_doc: 参数形状行(`- name: {…}`)。
# 属提示词内容故归本模块(层序: cognition 不得反向依赖 tools);
# 新增工具优先在注册装饰器直接传 params_doc/brief, 本表只承载存量迁移。

TOOL_BRIEFS: Dict[str, str] = {
    "kb.asset.search":
        "全文检索知识库架构资产(组件/ER/实体/流程)，按关键词命中并按相关度排序",
    "kb.code_mappings": "查询资产对应的代码映射(文件/行号)，锁定「改哪里」",
    "kb.baseline": "读取当前项目 KB 基线(git 表示：分支/提交/基线版本)",
    "kb.graph": "遍历组件依赖图(依赖/被调用)，判断需求改动的影响链路",
    "map.overview":
        "资产地图总览——组件目录(含图层级 L0/L1/文件数/依赖)+资产统计；穷举/统计/层级类提问先看",
    "map.component": "组件档案——单组件的层级/文件/依赖出入/组件内语义资产",
    "map.assets":
        "语义资产表列检索——kind/level 过滤+关键词，Markdown 表格浏览清单",
    "map.rules": "项目规约全集(架构+编码+命名规约+词汇表，编码/评估必须遵守)",
    "map.graph": "关系图(mermaid)——component 组件依赖图 / semantic 语义关系图",
    "asset.semantic.search":
        "检索已提取的语义数据资产(数据结构/处理流程/控制逻辑，比组件更细、锚定 AST 节点；"
        "支持 kind/level 过滤；includeGlobal=true 时合并主库全局层通用资产)",
    "asset.semantic.stats": "语义资产统计(总量/按类别/按粒度/状态)",
    "asset.semantic.extract":
        "按指令从最新代码提取语义数据资产并落库(指令化唯一入口：comm 时 key=组件ID 为权威范围，确定执行)",
    "asset.semantic.detail": "读取单个语义资产的完整描述/结构化细节/AST 锚点",
    "asset.semantic.mappings": "查询语义资产对应的代码映射(文件/行号)，锁定「改哪里」",
    "asset.semantic.reconcile": "校验资产新鲜度，标记因文件变更/新增文件影响而过期的资产(需更新后使用)",
    "asset.semantic.refresh": "更新过期资产(增量重提；失败软删并重新生成)",
    "code.read_symbols": "读取项目源码片段(按文件/符号)，对话式提取前先看真实代码",
    "asset.semantic.save":
        "对话式提取落库(按规约产出资产 → 框架值域校验/名称继承/墓碑承接)",
    "asset.semantic.update":
        "认知层编辑既有资产(改名/描述；旧名自动入历史，overlay 留痕)",
    "asset.semantic.merge":
        "合并资产(intoId 吸收 targetIds 锚点；目标留痕 mergedInto)",
    "asset.semantic.split":
        "拆分资产(按 anchorKeys 锚点组拆出新资产；原资产留痕 splitInto)",
    "convention.propose":
        "把观察到的命名重复模式固化为命名规约提案(pending，待设计者确认/忽略)",
    "contract.propose":
        "把对话中讨论出的期望固化为契约条目草稿(待设计者逐条确认；kind/level 按框架值域校验)",
    "req.propose":
        "需求提案(新建或幂等更新)——**开发类需求**(要写代码/改代码/交付组件)时调用，"
        "创建需求卡即 ready(designMd=选型与结构)；分析/问答类请求不要产卡。"
        "用户要求 编写脚本/工具/程序 时**必须先调本工具**，由 /执行 链路产出代码——"
        "**严禁直接输出成品代码**(python/bash 等)替代需求收敛",
    "req.amend":
        "需求修订(通用)——用户对既有需求 补充/完善/调整 时调用，追加新 draft "
        "版本(append-only)。reqId 勿传(系统自动取会话绑定需求)",
    "ctx.search":
        "跨会话检索历史上下文(单元/消息/备案文档)——回答涉及历史讨论/已有结论时先检索，避免重复讨论",
    "ctx.get": "读取指定会话的上下文包(摘要+关键单元+备案文档清单)",
    "ctx.summarize": "生成/刷新会话摘要",
    "probe.run":
        "方案草图(probe)——调 coding agent 在代码快照上产出改动思路与伪 diff，供用户预览确认后再正式执行",
    "capability.evaluate":
        "图文评估——target=plan 评估会话最新方案(变更足迹×语义资产影响面+关系子图图)；"
        "target=execution 评估执行结果(实际 diff 足迹 + 与方案的偏差集)。"
        "报告内资产卡可点击联动资产地图。方案确认前/执行完成后调用",
    "capability.mine":
        "能力提炼——扫描会话(消息+方案/回执单元)提炼 规约/流程/技巧/skill 提案入待审队列, "
        "设计者采纳后生效(规约入规约库/skill 文档注入能力文档)。会话出现可复用模式时主动提议",
}

TOOL_PARAM_DOCS: Dict[str, str] = {
    "kb.asset.search": '{"text": "检索关键词", "preferred": ["资产ID(可选)"]}',
    "kb.code_mappings": '{"asset_ids": ["资产ID"]}',
    "kb.baseline": "{}",
    "kb.graph": '{"comp_ids": ["组件ID"]}',
    "project.ctx": "{}",
    "asset.semantic.search":
        '{"text": "关键词", "kind": "entity|contract|state|rule|process|decision(可选)", '
        '"level": "business|implementation|logic(可选)", "limit": 20, "offset": 0, '
        '"scopes": ["comm-…(可选)"]}',
    "map.overview": "{}",
    "map.component": '{"name": "组件名或id"}',
    "map.assets": '{"query": "关键词", "kind": "类别(可选)", "level": "粒度(可选)", "limit": 30}',
    "map.rules": "{}",
    "map.graph": '{"kind": "component|semantic"}',
    "asset.semantic.stats": "{}",
    "asset.semantic.extract":
        '{"scope": {"type": "comm|files|symbols|project", "key"?, "files"?, "symbols"?}, "kinds"?}'
        "(工作流见 extract 技能)",
    "asset.semantic.detail": '{"asset_id": "sa-xxx"}',
    "asset.semantic.mappings": '{"asset_ids": ["sa-xxx"]}',
    "asset.semantic.reconcile": "{}",
    "asset.semantic.refresh": '{"asset_id": "sa-xxx"}',
    "code.read_symbols":
        '{"file": "相对路径", "symbol"?: "符号名", "startLine"?: 行, "endLine"?: 行}',
    "asset.semantic.save":
        '{"assets": [{"name", "kind", "level"?, "desc"?, "detail"?, '
        '"astRefs"[{file,symbol,startLine,endLine}]}]}',
    "asset.semantic.update": '{"assetId": "sa-xxx", "patch": {"name"?: "新名", "desc"?: "新描述"}}',
    "asset.semantic.merge":
        '{"intoId": "sa-xxx", "targetIds": ["sa-yyy"], "targetName"?: "合并后名称"}',
    "asset.semantic.split":
        '{"assetId": "sa-xxx", "parts": [{"name": "…", "anchorKeys": ["file:symbol"], "desc"?: "…"}]}',
    "convention.propose":
        '{"ruleText": "服务以 XxxService 结尾", "scenarios": ["naming"], "appliesKinds"?: ["process"]}',
    "contract.propose":
        '{"items": [{kind, level?, target{file?,symbol?}, behavior{steps,branches?}, zAxis?, '
        "acceptance?, origin{quote 必填}, reqId?}]}(构造纪律见 contract 技能, 🧾)",
    "req.propose":
        '{"title": "需求标题(必填)", "requirementMd": "需求目标(全文)", '
        '"designMd": "选型与结构方案", "priority": "P1", "estMin": 30, '
        '"acceptanceMd": "验收条目(md)", "newRequirement": false(同会话已建卡时'
        '强制新建才传)} —— reqId 勿传',  # noqa: E501
    "req.amend": '{"requirementMd": "修订后需求目标(全文, 可选)", '
                 '"designMd": "修订后方案(可选)", '
                 '"acceptance": ["验收条目"], "allowedScope": ["目录"], '
                 '"forbiddenScope": ["目录"], "reasoning": "原因"} —— 只传要调整的'
                 '字段; 标题修订用 {"title": "新标题"}(reqId 勿传, 自动取会话绑定)',  # noqa: E501
    "capability.evaluate": '{"target": "plan|execution"}',
    "capability.mine": '{"conversation"?: "cv-…(缺省当前会话)}',
}

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
    """能力清单一行简介: 注册点 brief → 迁移表 → 描述首句兜底。"""
    brief = (entry.get("brief") or "").strip() \
        or TOOL_BRIEFS.get(name, "")
    if brief:
        return brief
    desc = (entry.get("description") or "").strip()
    return desc.split("。")[0][:120] if desc else ""


def _tool_params_doc(name: str, entry: Dict[str, Any]) -> str:
    return (entry.get("params_doc") or "").strip() \
        or TOOL_PARAM_DOCS.get(name, "")


def capability_doc_from_tools(tool_surface: str = "full",
                              kb_enabled: bool = True,
                              allowed=None, slim: bool = False) -> str:
    """由 _ARCH_TOOLS 注册表渲染能力文档(单源模式, B4 默认)。

    结构对齐 _CAPABILITY_DOC: 工具清单(brief 单源) + 层级约定 + 工具调用协议 +
    硬性规则(防编造) + 需求落库纪律 + 会话指令符号 + 参数表(params_doc 单源) +
    可处理范围 + 图表输出纪律。无注册工具时返回空串(调用方回退等价模式)。
    R3.4: tool_surface/kb_enabled 按挡裁剪工具面(缺省 full/True 行为不变)。
    批丁: allowed(GU 路线限定, 具体名单)→工具面收敛为本轮子集; slim(简挡)→
    省略系统面说明段(指令符号/可处理范围——挡位系统已确定性处理, 无需模型知)。
    """
    from ...agent.tools import req_agent as _req_agent_mod
    entries = [(n, e) for n, e in _req_agent_mod._ARCH_TOOLS.items()
               if n not in ("diagram.build", "diagram.validate")]
    entries = _filter_tools(entries, tool_surface, kb_enabled)
    if allowed is not None:
        allowed = set(allowed)
        entries = [(n, e) for n, e in entries if n in allowed]
    if not entries:
        return ""
    # W1-1: 按名排序——注册序随导入路径漂移(实测), prompt 须确定(可缓存/快照)
    entries.sort(key=lambda ne: ne[0])
    lines = ["你可以使用以下能力(skills/tools)："]
    params = ["各工具的参数："]
    for name, entry in entries:
        brief = _tool_brief(name, entry)
        lines.append(f"- {name}：{brief}" if brief else f"- {name}")
        if name == "map.graph":
            lines.append(_TIER_CONVENTION_DOC)   # 层级约定锚在地图组之后(对齐原文位置)
        pd = _tool_params_doc(name, entry)
        if pd:
            params.append(f"- {name}: {pd}")
    lines.append("")
    lines.append(protocol_doc(slim=slim))
    if len(params) > 1:
        lines.append("\n".join(params))
    if not slim:
        lines.append(_SCOPE_DOC)
    lines.append(_DIAGRAM_OUTPUT_DOC)
    return "\n".join(lines)


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

def protocol_doc(slim: bool = False) -> str:
    """工具调用协议单源组装(slim=简挡省略系统面说明段; 信封纪律两态恒在)。"""
    if slim:
        return (TOOL_PROTOCOL_HEAD + ANTI_FABRICATION
                + REQ_CARD_DISCIPLINE + REQUEST_ENVELOPE_DOC + TOOL_TAIL)
    return _PROTOCOL_DOC

_SCOPE_DOC = (
    "可处理范围：需求分析/澄清/范围收敛、资产命中与影响评估、设计实现建议、新项目引导；"
    "通用闲聊/外包式实现礼貌引导回需求语境(软拒绝，允许继续提问)。"
    "回复保持简洁、直接、可操作，可输出 Markdown。"
)


def set_overrides(data: Dict[str, Any]) -> None:
    _store().CollabConfigStore.set(_OVERRIDES_KEY, json.dumps(data, ensure_ascii=False))


# ── 分析挡位指引 → 已迁 agent/governance/gears.py(环节十二a 挡位体系,
#    数据驱动 T0-T4; 本文件不再持有二值挡位文本) ─────────────────────
