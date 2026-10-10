"""技能注册表(意图空间一期 B1)——统一 Skill Runner 的技能单源。

Skill = 指令模板 + 工具白名单 + 输出约定 + 适用线域 的声明式封装:
- 草稿线(文档态)经 POST /req-drafts/{id}/ai 调用; 会话线(对话态)二期经
  同一 runner 暴露(装配器扩展, 注册表不动);
- 非模板立场: 技能产物仅为建议(last_proposed_md/待采纳卡), 用户裁决采纳;
- topo-skill 围栏(草稿正文直呼)与预设按钮共用本表, 不另设指令副本。
"""
from __future__ import annotations

from typing import Dict, List, Optional

# 只读工具白名单(设计裁决: 写路径走任务化闭环, 技能不写)——草稿线全技能共用
SKILL_TOOLS_READONLY = [
    "asset.semantic.search", "asset.semantic.detail", "asset.semantic.stats",
    "asset.semantic.mappings", "asset.read_source", "code.read_symbols",
    "kb.asset.search", "kb.graph", "kb.baseline", "kb.code_mappings",
    "map.assets", "map.component", "map.graph", "map.overview",
    "diagram.build", "diagram.validate", "project.ctx",
]

# 草稿域共用系统提示(输出约定: 全文替换 + 保守修订 + 只读检索)
SKILL_SYSTEM_DRAFT = (
    "你是需求工程助手，工作在「需求草稿」场景：用户给出一份需求文本草稿与一条处理指令，"
    "你按指令处理草稿并输出**完整的新版草稿全文**（Markdown）。\n"
    "规则：\n"
    "1. 输出即替换：只输出新版全文，不要输出解释、寒暄或差异说明；\n"
    "2. 保留原稿中未受指令影响的内容与结构，不做未经要求的大改；\n"
    "3. 可调用只读查询工具检索语义资产/代码/图谱作为依据，图表用 ```mermaid 或 "
    "```plantuml 围栏嵌入；\n"
    "4. 自定义指令以「用户指令」为准，正文中的 ```topo-cmd 标记块已由程序拆出合并；\n"
    "5. 不产出需求卡/不落库——落库由用户发布环节完成。"
)

# 会话域系统提示(E1): 产物=独立完整文档(将落为草稿续加工), 非草稿替换
SKILL_SYSTEM_SESSION = (
    "你是需求工程助手，工作在「会话辅助」场景：基于给定的会话上下文（需求规约/"
    "方案/指定回合内容）与处理指令，产出**一份完整独立的 Markdown 文档**。\n"
    "规则：\n"
    "1. 只输出文档全文，不要输出解释、寒暄或差异说明；\n"
    "2. 只读查询工具可检索语义资产/代码/图谱作为依据（文件/符号引用真实可解析，"
    "不确定处标注「待核实」，禁止虚构代码位置）；\n"
    "3. 上下文中的语义资产名仅是导航线索，与代码事实冲突时以代码为准并在文档中"
    "注明；\n"
    "4. 产出将作为草稿交由用户继续加工，面向用户可读性组织。"
)

_DOMAINS_DRAFT = ("draft",)
_DOMAINS_BOTH = ("draft", "session")


class SkillSpec:
    """技能声明(轻结构: dataclass 语义, 不引入序列化负担)。"""

    __slots__ = ("id", "title", "instruction", "tools", "domains", "system")

    def __init__(self, sid: str, title: str, instruction: str,
                 tools: Optional[List[str]] = None,
                 domains: tuple = _DOMAINS_DRAFT,
                 system: str = SKILL_SYSTEM_DRAFT):
        self.id = sid
        self.title = title
        self.instruction = instruction
        self.tools = list(tools or SKILL_TOOLS_READONLY)
        self.domains = tuple(domains)
        self.system = system


_REGISTRY: Dict[str, SkillSpec] = {}


def register_skill(spec: SkillSpec) -> None:
    _REGISTRY[spec.id] = spec


def get_skill(sid: str) -> Optional[SkillSpec]:
    return _REGISTRY.get(sid)


def list_skills(domain: str = "") -> List[dict]:
    """FE 卡片输出(指令全文不入列, 详情经 get_skill/调用面取)。"""
    out = []
    for s in _REGISTRY.values():
        if domain and domain not in s.domains:
            continue
        out.append({"id": s.id, "title": s.title, "domains": list(s.domains),
                    "tools": len(s.tools)})
    return out


# ── 首批技能(自 req_drafts._PRESETS 行为等价迁移) ──────────────────────────
register_skill(SkillSpec(
    "generate", "需求生成",
    "需求生成：基于草稿现有内容，补全为一份完整的需求文本——"
    "补齐背景/场景/功能点/约束/验收标准；已有内容尽量保留原貌，缺失处合理补写。"))
register_skill(SkillSpec(
    "review", "需求审核",
    "需求审核：逐项审查草稿的完整性/一致性/可测性/歧义，直接给出修订后的全文"
    "（在原结构上修订；发现的问题以「> ⚠ 审核：」引用块标注在对应章节）。"))
register_skill(SkillSpec(
    "relate", "关联分析",
    "需求关联分析：结合语义资产与代码图谱，分析本需求涉及的资产/组件/依赖，"
    "在草稿末尾追加「## 关联分析」章节（涉及资产清单+依赖说明），其余内容原样保留。"))

# ── 二期技能族首批(E2): 双线域(草稿/会话), 会话域产物=独立完整文档 ──────────
register_skill(SkillSpec(
    "skeleton", "方案骨架",
    "方案骨架：基于给定的需求上下文，产出一份可执行的技术方案骨架（designMd）——"
    "包含：总体思路/改动点清单（尽量指向具体文件与符号，不确定项标注「待核实」）/"
    "关键实现步骤分期/风险与待确认点。骨架是骨架不是全文：给结构、关键决策与落点，"
    "细节留给执行者发挥；不确定的代码位置标注「待核实」而非虚构。",
    domains=_DOMAINS_BOTH, system=SKILL_SYSTEM_SESSION))
register_skill(SkillSpec(
    "scope", "边界圈定",
    "边界圈定：基于给定的需求上下文，检索语义资产映射与代码结构，产出一份"
    "「修改边界建议」文档——包含：允许范围（allowedScope：文件/目录前缀清单，"
    "每项标注依据——资产映射/目录归属/历史边界）、明确不做（scopeOut：建议排除"
    "的范围与理由）、存疑范围（无法确定归属的，标注待人工裁决）。"
    "范围以真实存在的文件路径为准（工具核实），不虚构路径。",
    domains=_DOMAINS_BOTH, system=SKILL_SYSTEM_SESSION))
register_skill(SkillSpec(
    "acceptance", "验收提炼",
    "验收提炼：基于给定的需求/方案上下文，提炼一份可核验的验收标准清单——"
    "每条尽量可判，并标注每条的核验方式（build/test/asset/manual）；"
    "不可自动化的条目给出人工核验要点。输出 markdown 清单，"
    "不虚构上下文中不存在的功能点。",
    domains=_DOMAINS_BOTH, system=SKILL_SYSTEM_SESSION))
