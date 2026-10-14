"""语义资产提取 skill 文档（规约模板 → agent 可执行知识）— plan-C §4.1。

(MS4-W3 整体自 arch_routes/asset_skill.py 迁入——该文件本无路由, 属语义资产域逻辑。)

**按场景加载（防上下文污染）**：`skill_docs(root, project, scenarios)` 只拼接
当前场景相关片段——builtin 规约(按场景切分) + 项目规约库(arch_naming_conventions
按 scenarios 标签过滤)。禁止默认全量注入。

场景：extract(对话式提取) / accept(验收比对) / naming(命名治理) / plan(方案生成) / coding(coding agent 委派) / capability(评估与提炼) / general。
注入点：websocket._build_chat_messages → chat_system_prompt(skill_docs=…)。
"""
import logging
from typing import List, Optional

from ..store import NamingConventionStore

logger = logging.getLogger(__name__)

# ── 内置规约（提取场景；规约正文与 asset_rules/asset_templates 单一语义来源对齐） ──

_BUILTIN_EXTRACT = """## 语义资产提取规约（extract 场景）

### 指令化提取（唯一路径，确定执行）
- 提取由**明确指令**触发：指令携带**组件ID**（形如 `comm-…`）作为**权威范围**——
  由组件资产 UI 按钮自动生成，或设计者在对话手动输入。
- 组件ID 即范围：以其为 scope 直接执行定向提取，**不再提议范围、不等确认**
  （只有 ID 缺失/多义时才需澄清，见下）。
- 提取统一走 `asset.semantic.extract`（规则定死类别 + tAgent 定向 + 锚定代码段 +
  语义解释）——**不要**改用 `code.read_symbols` 手工读码 + `asset.semantic.save` 拼资产。

### 工作流（每次提取必经）
1. 确定组件ID：指令带 `comm-…` ID 直接用；只给组件名 → `kb.asset.search` 取 `id`；
   多义（多个候选）→ **如实报告候选清单请设计者确认**，禁止猜。
2. `asset.semantic.search` 查该组件已有资产（查重/过期判定）——已有且新鲜则提示，不重复提取。
3. `asset.semantic.extract` 以 `{scope:{type:"comm", key:<组件ID>}}` 执行定向提取。
4. 如实汇报：保存几条 / 各类别数 / 是否降级(degraded) / 命名继承(proposedNames) /
   范围未命中时的 error+候选清单；`count=0` 则说明"未提取到任何资产"及原因。
   禁止声称"提取已启动/后台运行/请等待"——你拿到的是同步完成的结果。

### 产出契约（管线保证，你如实转述即可，不自行判断类别）
- 每条资产 = 类别(六类之一，规则定死) + 锚定代码段(astRefs: file/symbol/startLine/endLine)
  + 语义解释(desc 白话 + detail 结构化)；
- 六类：entity 实体 / contract 契约 / state 状态 / rule 规则 / process 过程 / decision 决策；
- 实现层资产必带 astRefs 锚点，无锚点会被幻影拒绝。

### 命名纪律（重要）
- canonicalKey 命中既有资产 → **旧名自动保留**，提议名进 proposedNames 由设计者定夺；
- 新资产沿用历史命名（墓碑）；提取前先 `asset.semantic.search` 查重，避免重复产出。

### 框架值域
- kind/level 必须在当前框架档位值域内，越域会被拒绝（返回 rejected 原因）。
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

### 参数完整示例
- contract.propose: {"items": [{"kind": "…", "level"?: "implementation", "target": {"file"?: "…", "symbol"?: "…"}, "behavior"?: {"steps": [{"order": 1, "semantic": "…"}], "branches": [{"condition": "…", "semantic": "…"}]}, "zAxis"?: [{"category": "…", "text": "…"}], "acceptance"?: {"mode"?: "auto", "criteria"?: "…"}, "origin": {"quote": "设计者原话(必填)"}, "reqId"?: "…"}]}

### 边界
- 你只产**草稿**：确认/打回/通过全由设计者在界面上操作，你不代判；
- 一次提议 1-3 条为宜，逐条可确认；不要为凑数固化模糊期望。
"""


_BUILTIN_CAPABILITY = """## 能力评估与提炼规约（capability 场景）

### capability.evaluate 图文评估
- target=plan：评估会话最新方案(变更足迹×语义资产影响面+关系子图)——方案确认前调用，
  评估结论只作参考意见，通过与否由设计者决定；
- target=execution：评估执行结果(实际 diff 足迹+与方案偏差集)——执行完成后调用；
- 如实转述报告中的机械比对事实与 L3 参考意见，不自行加权下结论；报告内资产卡可联动资产地图。

### capability.mine 能力提炼
- 会话出现可复用模式(命名规约/处理流程/排查技巧/skill 用法)时，可主动提议提炼；
- 提炼产出进待审队列，设计者采纳后才生效(规约入规约库/skill 文档注入)——
  你只提议，不代采纳；一次提炼 1-3 条为宜，不为凑数提炼模糊内容。
"""


_BUILTIN_PLAN = """## 方案生成规约（plan 场景）

### 何时产出方案
- 触发：设计者要求 生成方案/方案生成/提炼方案/提炼待执行方案/转入执行，
  或使用「方案生成」按钮预填的指令；讨论自然收敛出明确改进/新增需求时，
  也可先简述方案骨架征得同意后再产出。

### 提案产出（req.propose）
- 完整方案以 designMd 为核心：必要的逻辑表达与实现细节——技术路径、关键改动点、
  涉及组件与文件、数据流向、边界条件，按需求复杂度充分展开；禁止标题式罗列；
- 约束框架四项按对话实际给出，未讨论或设计者明确同意为空时留空，不编造：
  ① requirementMd 需求目标；
  ② allowedScopeMd 允许增删改的模块/文件/数据资产节点（每行一项）；
  ③ forbiddenScopeMd 一定不能动的模块/文件/数据资产节点（每行一项）；
  ④ acceptanceMd 最终验收标准（每行一条可判定）——中间自测单测由 coding agent
  按模型能力自行处理，不列入提案任务；
- assessmentMd 给收益/风险/estMin(分钟)；priority 按影响面定 P0/P1/P2；
- 范围与细节优先引用对话中讨论到的真实资产/文件
  （不确定时先 asset.semantic.search / code.read_symbols 取证，再落笔）。

### 产出通道（推荐围栏）
- 首选：把提案写成 ```proposal 围栏(JSON，字段同 req.propose 参数：title/requirementMd/
  designMd/allowedScopeMd/forbiddenScopeMd/acceptanceMd/assessmentMd/estMin/priority)，
  系统自动解析落库并出方案卡——生成类动作无需 [TOOL_CALL]；
- 备选：输出 [TOOL_CALL] 调用 req.propose；
- 只选其一，落库成功以系统返回的 RQ 编号为准。

### 产出纪律（防编造，重要）
- 需求提案必须**实际调用 req.propose** 落库——工具结果返回 requirementId(RQ-…) 才算产出；
  严禁在回复里手写提案 JSON、或声称『已生成提案』——没有工具结果就没有提案；
- 工具边界：需求提案用 req.propose(进规划组/任务管理)；
  contract.propose 是 🧾 期望固化(契约条目草稿)，不要用它替代需求提案。

### 确认与执行（边界）
- 提案落库(req.propose/req.amend)即生成**需求卡(ready)**，无需任何确认步骤
  (req.finalize 已退役)；用户确认存入后，需求卡自带「一键建卡执行」；
- 用户发送 `/执行`（系统直通建任务卡），或你调 task.propose 建卡；
  用户在任务卡上确认后由 coding subagent 在隔离分支执行，进展/提问以
  消息回到本会话，用户直接回复即转达；
- 你不代判验收、不在对话里口头宣布『完成』。
"""


_BUILTIN_LINENOTE = """## 代码逐行解读规约（linenote 场景）

### 目标
- 对给定带行号源码**逐行**给出代码级用途说明（≤40 字/行），读者不看实现也能懂每行在做什么；
- 说明必须贴合真实代码：只解释源码中可见的逻辑，禁止臆造不存在的分支/调用/参数。

### 按需取证（工具辅助：先查证，再作答）
- 行内调用了看不懂的符号/函数 → `code.read_symbols` 读其真实实现后再解释，
  不要凭名字猜测行为；
- 涉及其它语义资产（实体/契约/状态/规则）→ `asset.semantic.search` 检索、
  `asset.semantic.detail` 读完整定义，在说明中点出业务含义与关联；
- 信息已足够时立即作答，不要为取证而取证。

### 输出纪律
- 只输出 JSON：{"notes":[{"line":<行号>,"note":"<说明>"}]}，不要输出其它内容；
- 每行一条，行号必须来自输入清单；空行/纯括号等结构行不必解释；
- 说明里可引用行内真实的标识符名（帮助定位），但不复述整行代码。
"""


def _builtin_for(scenario: str) -> str:
    return {
        "extract": _BUILTIN_EXTRACT,
        "accept": _BUILTIN_ACCEPT,
        "naming": _BUILTIN_NAMING,
        "contract": _BUILTIN_CONTRACT,
        "linenote": _BUILTIN_LINENOTE,
        "plan": _BUILTIN_PLAN,
        # coding 场景 v1 委派规约已移除: v2 契约(挡位指引+capability 单源)覆盖,
        # 场景标签保留兼容前端注入(变 no-op, 防上下文污染)。
        "capability": _BUILTIN_CAPABILITY,
    }.get(scenario, "")


def _merge_global_conventions(convs: list, pid: str, scenario: str) -> list:
    """WS8-S4: 合并主库全局桶规约(场景匹配, 归一文本去重, 全局行缀后)。"""
    try:
        from .store.base import GLOBAL_PID, _db, _row_to_api
        rows = _db().fetchall(
            "SELECT * FROM arch_naming_conventions WHERE project_id = ? "
            "AND status = 'active' AND scenarios LIKE ? ORDER BY updated_at DESC LIMIT 50",
            (GLOBAL_PID, f'%"{scenario}"%'))
    except Exception:
        return convs
    import re as _re

    def _norm(x):
        return _re.sub(r"[\s\W_]+", "", (x or "").lower())
    seen = {_norm(c.get("ruleText")) for c in convs}
    for r in rows:
        d = _row_to_api(r)
        if _norm(d.get("ruleText")) in seen:
            continue
        convs.append(d)
    return convs


def skill_docs(root: Optional[str], project: Optional[str],
               scenarios: List[str]) -> str:
    """按场景拼接 skill 文档：builtin 规约 + 项目规约库（按场景标签过滤）。

    无匹配场景 → 返回空串（不注入，防上下文污染）。
    """
    if not scenarios:
        return ""
    # cv-189 注入层硬控制: 未关联 KB → skill 文档不得出现 kb.* 查询指引,
    # 组件 ID 定位改走本地资产检索(extract 场景其余内容与 KB 无关, 保留)。
    degraded = False
    try:
        from ..arch_routes.project import kb_degraded as _kd
        degraded = _kd(root, project)
    except Exception:  # noqa: BLE001
        degraded = True
    parts: List[str] = []
    for sc in scenarios:
        b = _builtin_for(sc)
        if not b:
            continue
        if degraded:
            b = b.replace(
                "只给组件名 → `kb.asset.search` 取 `id`",
                "只给组件名 → `asset.semantic.search`(关键词=组件名) 或 "
                "`map.assets` 查得 `id`(scope.key)")
        parts.append(b)
    # 项目规约（按场景标签过滤——R7 禁全量注入）
    try:
        from ..arch_routes.semantic_assets import project_id_for
        pid = project_id_for(root, project)
        if "extract" in scenarios or "naming" in scenarios:
            convs = NamingConventionStore.list(pid, scenario="extract")
            convs = _merge_global_conventions(convs, pid, "extract")
            if convs:
                lines = ["### 项目命名规约（设计者固化）"]
                for c in convs:
                    tag = "（全局）" if str(c.get("id", "")).startswith("g-") else ""
                    lines.append(f"- {c.get('ruleText')}{tag}")
                parts.append("\n".join(lines))
        # A1 经验回写：验收场景注入历史打回归纳出的经验规约（防同类失败复发）
        if "accept" in scenarios:
            convs = NamingConventionStore.list(pid, scenario="accept")
            convs = _merge_global_conventions(convs, pid, "accept")
            if convs:
                lines = ["### 验收经验规约（来自历史打回，设计者固化）"]
                for c in convs:
                    tag = "（全局）" if str(c.get("id", "")).startswith("g-") else ""
                    lines.append(f"- {c.get('ruleText')}{tag}")
                parts.append("\n".join(lines))
        # WS7 能力闭环: 已采纳提案(流程/技巧/skill)按场景标签注入(静态注册→可增长)
        try:
            from .store import CapabilityProposalStore
            accepted = CapabilityProposalStore.list(pid, status="accepted", limit=200)

            def _scene_list(p):
                raw = p.get("scenarios")
                if isinstance(raw, list):
                    return raw
                try:
                    import json as _json
                    parsed = _json.loads(raw or "[]")
                    return parsed if isinstance(parsed, list) else []
                except Exception:
                    return []
            hits = [p for p in accepted
                    if any(s in _scene_list(p) for s in scenarios)]
            if hits:
                lines = [f"### 提炼能力（设计者采纳, {len(hits)} 条）"]
                for p in hits[:8]:
                    lines.append(f"\n**[{p.get('type')}] {p.get('title')}**\n{p.get('content', '')[:600]}")
                parts.append("\n".join(lines))
        except Exception as e:  # noqa: BLE001
            logger.warning("[asset-skill] 提炼能力注入失败: %s", e)
    except Exception as e:
        logger.warning("[asset-skill] 项目规约加载失败: %s", e)
    if not parts:
        return ""
    return "\n\n# 语义资产技能（按场景注入）\n\n" + "\n\n".join(parts)
