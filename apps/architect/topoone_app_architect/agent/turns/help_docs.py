"""产品使用指南/帮助手册内容单源(批戊补) — 帮助意图(help kind)的内容供给面。

裁决(2026-09-22 用户): 所有指南/帮助信息**非最终版**——随迭代逐步更新。因此:
- 内容 = 结构化 topics 缺省表(本模块, 纯数据); 支持 flow_policy.goal.helpTopics
  全量覆盖(与 strategies 同款配置基座: 改一条帮助内容 = PUT /flow-policy 零发版);
- 每条 topic 带 updated 日期; lookup 返回附「内容可能滞后于当前版本」提示
  (防模型把文档当永久事实), provide-help 指引文案同款提醒;
- 意图面: match_help(确定性正则, 构建标记排除) → GU kind=help → 决策表
  provide-help → tools=[help.lookup](读类)。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# 帮助意图线索(产品使用咨询; 命中即候选)
_HELP_HINT_RE = re.compile(
    r"(帮助|使用指南|使用手册|帮助手册|怎么用|如何使用|使用说明|操作指南|"
    r"功能介绍|新手|入门|怎么开始|如何配置|怎么配置|怎么创建|如何创建|"
    r"怎么建卡|如何建卡|文档)")
# 构建标记排除: 「帮我写个使用手册」是开发诉求(需求路线), 不是产品咨询
_BUILD_MARK_RE = re.compile(
    r"(做一个|做个|写个|写一个|开发|实现|封装|新建|新增|加一个|添加|搭一个)")


def match_help(question: str) -> bool:
    """帮助意图判定(确定性): 使用咨询线索命中 且 无构建标记。"""
    t = (question or "").strip()
    if not t:
        return False
    if not _HELP_HINT_RE.search(t):
        return False
    if _BUILD_MARK_RE.search(t):
        return False
    return True


DEFAULT_HELP_TOPICS: List[Dict[str, Any]] = [
    {"key": "getting-started", "title": "会话基本流", "updated": "2026-09-22",
     "kws": ["开始", "入门", "基本流", "怎么开始", "流程"],
     "body": ("1. 直接用自然语言描述诉求(开发类/工具类均可)——系统自动判别路线。\n"
              "2. 明确诉求 → 生成需求卡(ready)；要素不全 → 系统先按推断默认值集中提问。\n"
              "3. 需求卡就绪后回复「执行」或点卡片「开始执行」→ 建任务卡 → 确认后 coding "
              "subagent 动手。\n"
              "4. 多步需求自动拆成任务计划，逐步预填、逐步确认。\n"
              "提示：卡片是操作入口（开始执行/忽略），文字确认语（确认/继续执行）等效。")},
    {"key": "commands", "title": "指令与确认语", "updated": "2026-09-22",
     "kws": ["指令", "命令", "斜杠", "确认", "继续", "重试", "提取需求", "执行"],
     "body": ("整条消息恰为以下内容时确定性触发(可带 @执行器 前缀指定引擎)：\n"
              "- `/提取需求`：从对话历史提取需求卡\n"
              "- `/执行`：绑定需求 → 生成任务计划/单卡\n"
              "- `确认 / 开始执行 / ok / 好的`：启动待确认的任务卡\n"
              "- `继续执行 / 继续`：就近推进当前焦点(预填步骤/待确认卡)\n"
              "- `重试`：重发最近失败的步骤\n"
              "带正文的消息(如「确认一下这个方案」)是普通对话，不触发直通。")},
    {"key": "requirement-card", "title": "需求卡与五要素澄清", "updated": "2026-09-22",
     "kws": ["需求卡", "澄清", "五要素", "规约", "要素"],
     "body": ("需求卡五要素：①目标 ②方案要点 ③允许范围 ④禁止改动 ⑤验收标准。\n"
              "系统按「澄清挡位」工作：auto(有缺口才问)/forced(每需求回合先问)。\n"
              "提问均带推断默认值——回复序号确认或直接修改即可。\n"
              "修订既有需求：对话中直接说明调整内容(系统走 req.amend 新版本)。")},
    {"key": "task-plan", "title": "任务计划与多步执行", "updated": "2026-09-22",
     "kws": ["计划", "多步", "步骤", "拆步", "进度"],
     "body": ("/执行 时较复杂的需求自动拆成 2-5 步计划(带依赖关系)。\n"
              "计划卡是**进度锚**：每步完成/预填时原位更新(✅ 完成 / ➡️ 待确认 / "
              "❌ 失败 / ⬚ 待就绪)。\n"
              "每步完成自动预填下一步(待确认执行)；全部完成后出汇总。\n"
              "步骤卡尾注为「待确认执行」——点卡片或回复「确认/继续执行」启动。")},
    {"key": "executors", "title": "执行器配置", "updated": "2026-09-22",
     "kws": ["执行器", "cline", "opencode", "codex", "引擎", "配置执行器"],
     "body": ("执行器 = 真正动手的 coding subagent(如 cline-sdk)。\n"
              "配置入口：设置面板「执行器配置」(注册表管理 id/类型/参数)。\n"
              "指定方式：任务卡上切换，或消息前缀 `@执行器id`(如 `@cline /执行`)。\n"
              "架构师(architect)只做理解/编排，动手实现一律由执行器承担。")},
    {"key": "gears", "title": "分析挡位", "updated": "2026-09-22",
     "kws": ["挡位", "strict", "quick", "分析模式", "预算"],
     "body": ("会话级 analysisMode 决定分析深度：strict(标准, 默认)/quick(快速简挡)。\n"
              "挡位影响：拆步与否、工具面宽窄、提示预算、重试策略。\n"
              "切换入口：会话设置「分析模式」。")},
    {"key": "sessions", "title": "会话管理与项目隔离", "updated": "2026-09-22",
     "kws": ["会话", "项目", "分组", "过滤", "隔离", "列表"],
     "body": ("会话按项目硬隔离：列表只显示当前项目的会话(无跨项目访问)。\n"
              "管理能力：分组/模块标签、时间与状态过滤、归档。\n"
              "左侧对话栏与会话列表左右联动；删除会话会同步清除打开状态。")},
    {"key": "failure-recovery", "title": "失败重试与中断恢复", "updated": "2026-09-22",
     "kws": ["失败", "重试", "中断", "恢复", "异常"],
     "body": ("步骤失败：计划锚显示 ❌——回复「重试」重发该步(不问 LLM 直接建卡)。\n"
              "会话异常中断：进入 interrupted 相位，新任务下发被拦；用工具栏"
              "「恢复」核对执行器实际状态，或「停止」终态化保留 worktree。\n"
              "完成回执未消化：会话处于 reviewing，验收(合并/已阅)后自然流转。")},
    {"key": "faq-safety", "title": "常见问题：范围保护与占位拦截", "updated": "2026-09-22",
     "kws": ["faq", "常见问题", "范围", "保护", "占位", "互斥"],
     "body": ("需求未声明 allowedScope：执行时自动运行范围探针补全；补全失败则"
              "本次执行无互斥保护(卡上有 ⚠️ 提示)。\n"
              "需求正文含省略号/「待补充」等占位符会被拒绝(占位卡无执行价值)——"
              "请给出完整内容或先回答澄清问题。\n"
              "纯寒暄/咨询回合不会落卡(零写面)；表达开发诉求后下一回合才建卡。")},
]


def load_topics(rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """帮助主题单源(纯函数, rows 注入——R1: 本模块零 arch_routes 依赖)。

    rows=flow_policy.goal.helpTopics(配置全量覆盖缺省表, 与 strategies 同款
    基座; 由调用方读取传入)。坏值回落缺省(fail-soft)。"""
    out = [dict(r) for r in (rows or [])
           if isinstance(r, dict) and str(r.get("key") or "")]
    return out or [dict(r) for r in DEFAULT_HELP_TOPICS]


def lookup_topics(query: str = "",
                  rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """关键词检索帮助主题: 命中返回全文; 空查询返回主题清单; 未命中给引导。"""
    q = (query or "").strip().lower()
    topics = load_topics(rows)
    if not q:
        return {"topics": [{"key": t["key"], "title": t["title"],
                            "updated": t.get("updated", "")} for t in topics],
                "hint": "指定关键词(如: 执行器/需求卡/计划/确认)获取全文。"}
    scored = []
    for t in topics:
        score = sum(1 for kw in (t.get("kws") or []) if kw and kw in q)
        if not score and (q in str(t.get("title") or "").lower()
                          or q in t["key"]):
            score = 1
        if score:
            scored.append((score, t))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return {"topics": [{"key": t["key"], "title": t["title"]} for t in topics],
                "hint": "未命中主题——可从上述清单指定关键词重查。"}
    return {"topics": [{"key": t["key"], "title": t["title"],
                        "updated": t.get("updated", ""),
                        "body": t.get("body") or ""} for _, t in scored[:3]],
            "hint": "内容可能滞后于当前版本，以系统实际行为为准。"}
