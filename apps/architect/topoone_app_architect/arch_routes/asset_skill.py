"""语义资产提取 skill 文档（规约模板 → agent 可执行知识）— plan-C §4.1。

**按场景加载（防上下文污染）**：`skill_docs(root, project, scenarios)` 只拼接
当前场景相关片段——builtin 规约(按场景切分) + 项目规约库(arch_naming_conventions
按 scenarios 标签过滤)。禁止默认全量注入。

场景：extract(对话式提取) / accept(验收比对) / naming(命名治理) / general。
注入点：websocket._build_chat_messages → chat_system_prompt(skill_docs=…)。
"""
import logging
from typing import List, Optional

from .store import NamingConventionStore

logger = logging.getLogger(__name__)

# ── 内置规约（提取场景；规约正文与 asset_rules/asset_templates 单一语义来源对齐） ──

_BUILTIN_EXTRACT = """## 语义资产提取规约（extract 场景）

### 工作流（提议制，每次提取必经）
1. `asset.semantic.search` 查已有资产（查重/过期判定）——已有且新鲜则不重复提取；
2. `code.read_symbols` 读真实源码（禁止凭空产出）；
3. 按下方本体规约构造资产 JSON，经 `asset.semantic.save` 落库；
4. 汇报结果：保存了几条 / 被拒原因（值域越界等）/ 命名继承情况（proposedNames）。

### 本体判定（六类，X 轴）
- **entity 实体**：承载业务状态的数据结构（类/结构体/枚举），锚 class/struct/enum；
- **contract 契约**：跨边界交互接口（HTTP 路由/RPC/对外函数签名），锚 route/func；
- **state 状态**：显式状态机（枚举+合法转移），锚 class/enum；低配框架无此类；
- **rule 规则**：配置化业务规则（校验/阈值/白名单），锚 func/field；
- **process 过程**：有步骤序列的处理流程（函数/方法），锚 func/method/route；
- **decision 决策**：分支判定逻辑（if/switch 链），锚 func。

### detail 结构规约
- process：`steps:[{order,semantic,condition?}]`（**按源码行号顺序重建**，含调用与分支）；
- entity：`fields:[{name,type?,semantic?}]`；decision：`branches:[{condition,semantic}]`；
- state：`states`+`transitions`；契约：`relations:[{target,type,semantic?}]`。

### desc 白话规范
- 一句话讲清"这是什么、做什么"（代码级白话，禁止空模板话术）；
- 格式：「实体「X」：…N 字段（a, b…）」/「过程「X」：N 步（a→b→c），M 分支」；
- 命名与代码一致；源码 docstring 优先作为语义来源。

### 命名纪律（重要）
- canonicalKey 命中既有资产 → **旧名自动保留**，你的提议名进 proposedNames 由设计者定夺，不要反复改名；
- 新资产先查参考池（墓碑）——同名符号有历史命名则沿用；
- 提取前先 `asset.semantic.search` 查重，避免重复产出。

### 框架值域
- kind/level 必须在当前框架档位值域内，越域会被拒绝（返回 rejected 原因）；
- 实现层资产必须带 astRefs 锚点（file/symbol/startLine/endLine），无锚点会被幻影拒绝。
"""

_BUILTIN_ACCEPT = """## 验收比对规约（accept 场景）
- 严 profile 提取（规则+LLM 互证，带置信度）；
- L1 覆盖性/L2 行为符合性机械比对为**事实**；L3 语义判断仅**参考意见**（带来源/置信度/证据）；
- 不做判定——通过/打回由设计者决定；修复指令只起草。
"""

_BUILTIN_NAMING = """## 命名治理规约（naming 场景）
- 名称继承优先级：用户手改名 > 历史名 > 规约生成名；
- 发现用户改名重复模式 → 在回复中提议固化为命名规约（设计者在项目规约页确认，
  你可按场景规约生成建议文本）；
- 术语表是词典（纯参考），不做强制校验。
"""

_BUILTIN_CONTRACT = """## 期望固化规约（contract 场景，🧾 开启时）

### 何时提议
- 设计者在方案讨论中表达**具体、可验证的期望**（"订单创建前必须校验库存"、
  "支付回调要幂等"）→ 用 `contract.propose` 固化为契约条目草稿；
- 只是泛泛讨论/未决方向 → 不固化，继续澄清。

### 条目构造纪律
- `origin.quote` **必填**：引用设计者原话（≤200 字）——证据链锚点，无原话不得固化；
- `target.file/symbol`：能从代码定位就给锚点；给不出 → 留空（自动标意图级，
  如实呈现，不要编造路径）；
- `behavior.steps` 按讨论出的处理序列写（order 递增、semantic 白话）；
  branches/fields/relations 只在讨论明确提及时写；
- `zAxis` 仅当讨论涉及可观测/韧性/配置/安全约束时写（category 四选一）；
- `acceptance.criteria`：把期望写成可判定的标准（Given/When/Then 或自由文本）；
- kind/level 必须在当前框架值域内（越域会被拒绝并返回原因）。

### 边界
- 你只产**草稿**：确认/打回/通过全由设计者在界面上操作，你不代判；
- 一次提议 1-3 条为宜，逐条可确认；不要为凑数固化模糊期望。
"""


def _builtin_for(scenario: str) -> str:
    return {
        "extract": _BUILTIN_EXTRACT,
        "accept": _BUILTIN_ACCEPT,
        "naming": _BUILTIN_NAMING,
        "contract": _BUILTIN_CONTRACT,
    }.get(scenario, "")


def skill_docs(root: Optional[str], project: Optional[str],
               scenarios: List[str]) -> str:
    """按场景拼接 skill 文档：builtin 规约 + 项目规约库（按场景标签过滤）。

    无匹配场景 → 返回空串（不注入，防上下文污染）。
    """
    if not scenarios:
        return ""
    parts: List[str] = []
    for sc in scenarios:
        b = _builtin_for(sc)
        if b:
            parts.append(b)
    # 项目规约（按场景标签过滤——R7 禁全量注入）
    try:
        from .semantic_assets import project_id_for
        pid = project_id_for(root, project)
        if "extract" in scenarios or "naming" in scenarios:
            convs = NamingConventionStore.list(pid, scenario="extract")
            if convs:
                lines = ["### 项目命名规约（设计者固化）"]
                for c in convs:
                    lines.append(f"- {c.get('ruleText')}")
                parts.append("\n".join(lines))
        # A1 经验回写：验收场景注入历史打回归纳出的经验规约（防同类失败复发）
        if "accept" in scenarios:
            convs = NamingConventionStore.list(pid, scenario="accept")
            if convs:
                lines = ["### 验收经验规约（来自历史打回，设计者固化）"]
                for c in convs:
                    lines.append(f"- {c.get('ruleText')}")
                parts.append("\n".join(lines))
    except Exception as e:
        logger.warning("[asset-skill] 项目规约加载失败: %s", e)
    if not parts:
        return ""
    return "\n\n# 语义资产技能（按场景注入）\n\n" + "\n\n".join(parts)
