"""需求澄清引擎(cv-190) — 策略库/缺口矩阵/显式指令判定, 全确定性规则。

裁决(2026-09-20):
- 澄清为会话**挡位按钮**: auto(自动, 有缺口才问) | forced(强制, 每需求回合先问);
- 策略库按**具体目标**切分(环境搭建/脚本工具/UI组件/缺陷修复/接口服务/重构优化/
  数据分析), 命中 → 用切合目标的标准化问题集; **未命中 → 模型自由提问**(五要素
  框架兜底, 不强行套库);
- **明确指令免澄清**(如「按钮UI 修改为 xxx」)——正则判定, 强制挡同样跳过;
- 全部规则零 LLM 依赖; 精度边界: 自动挡在需求卡未建时仍靠模型路由判断。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ── 策略库(按目标切分; kws 命中计分, questions 即该目标的澄清问题集) ──

STRATEGIES: List[Dict[str, Any]] = [
    {"key": "env_setup", "label": "开发环境搭建",
     "kws": ("环境", "搭建", "安装", "编译", "构建", "工具链", "依赖",
             "sdk", "toolchain", "初始化", "脚手架", "monorepo", "workspace"),
     "questions": [
         ("方案要点", "语言/运行时与版本？(如 Node 20 / Python 3.10)"),
         ("方案要点", "包管理与依赖清单？(pnpm/npm/pip/poetry…)"),
         ("允许范围", "目标平台与 OS 边界？(仅 Linux？含 Windows/macOS？)"),
         ("验收标准", "怎样算搭建完成？(编译通过 / 冒烟运行 / 测试通过)"),
     ]},
    {"key": "script_tool", "label": "脚本/工具",
     "kws": ("脚本", "工具", "命令行", "cli", "批处理", "自动化", "爬取", "转换"),
     "questions": [
         ("方案要点", "输入是什么、输出要什么形式？"),
         ("方案要点", "运行环境与语言偏好？(python/node/bash)"),
         ("允许范围", "允许改动/新建哪些目录？"),
         ("验收标准", "给一个真实输入→期望输出的例子？"),
     ]},
    {"key": "ui_component", "label": "UI/组件封装",
     "kws": ("组件", "ui", "按钮", "弹窗", "表单", "页面", "样式", "css",
             "vue", "react", "前端", "交互"),
     "questions": [
         ("方案要点", "目标框架与版本？(Vue3/React18…)"),
         ("方案要点", "交互与状态怎么定？(受控/非受控、事件回调)"),
         ("允许范围", "兼容范围？(浏览器/分辨率/主题)"),
         ("验收标准", "视觉与交互怎样算符合预期？"),
     ]},
    {"key": "bug_fix", "label": "缺陷修复",
     "kws": ("修复", "报错", "bug", "异常", "崩溃", "不生效", "失效",
             "错误", "fix", "回归"),
     "questions": [
         ("方案要点", "复现步骤是什么？"),
         ("方案要点", "期望行为 vs 实际行为？"),
         ("允许范围", "允许改动的模块/文件边界？"),
         ("验收标准", "用什么方式验证已修复且无回归？"),
     ]},
    {"key": "api_service", "label": "接口/服务",
     "kws": ("接口", "api", "服务", "端点", "rest", "grpc", "鉴权",
             "webhook", "后端"),
     "questions": [
         ("方案要点", "协议与端点清单？(method/path)"),
         ("方案要点", "请求/响应数据契约示例？"),
         ("方案要点", "鉴权与错误码约定？"),
         ("验收标准", "怎样验收？(curl 用例 / 集成测试)"),
     ]},
    {"key": "refactor", "label": "重构/优化",
     "kws": ("重构", "优化", "性能", "抽离", "迁移", "升级", "清理",
             "refactor", "解耦"),
     "questions": [
         ("方案要点", "动机与量化指标？(耗时/行数/耦合度)"),
         ("允许范围", "禁止改动的部分？(对外接口/序列化格式)"),
         ("方案要点", "兼容性要求？(行为完全等价 or 允许变化)"),
         ("验收标准", "用什么基准验证不回退？"),
     ]},
    {"key": "data_analysis", "label": "数据/统计",
     "kws": ("数据", "统计", "分析", "报表", "指标", "聚合", "看板"),
     "questions": [
         ("方案要点", "数据源在哪里？(库表/文件/API)"),
         ("方案要点", "统计口径与输出形式？"),
         ("允许范围", "只读还是允许落库/写文件？"),
         ("验收标准", "给一组已知输入→期望数字？"),
     ]},
]

# 融合形态: 动作+连接词一体(改为/改成/换成/设为…), 后接宾语
_EXPLICIT_FUSED_RE = re.compile(
    r"(修改为|更改为|改为|改成|换成|更新为|设置为|设为|换到|迁移到)[^。！？;；]{0,40}\S")
# 纯动作形态: 整句短指令(删除 X / 新增 X), 无疑问/开放式目标词
_EXPLICIT_ACTION_RE = re.compile(r"^(删除|移除|去掉|新增|添加|加上|更名|重命名)\s*\S.{0,27}$")
# 明确指令兜底形态: 「X 改为 Y」「删除 X」「新增 X」——动作 + 具体宾语, 无开放式目标词
_OPEN_GOAL_RE = re.compile(
    r"(搭建|开发|设计|实现|做一个|建一个|封装|规划|方案|怎么|如何|建议)")


def is_explicit_instruction(text: str) -> bool:
    """明确指令判定(确定性): 修改类动作 + 明确目标值(为/成 X) → True。

    例: 「按钮UI 修改为 xxx」✓ /「标题改成 XX」✓ /「删除导出按钮」✓;
    「搭建开发环境」✗(开放式目标词)。
    """
    t = (text or "").strip()
    if not t:
        return False
    if _OPEN_GOAL_RE.search(t):
        return False
    if _EXPLICIT_FUSED_RE.search(t):
        return True
    if len(t) <= 30 and _EXPLICIT_ACTION_RE.match(t):
        return True
    return False


def match_strategy(text: str) -> Optional[Dict[str, Any]]:
    """按目标关键词命中策略(确定性计分: 命中词数最多且 ≥1)。未命中 → None。"""
    t = (text or "").lower()
    best, best_score = None, 0
    for s in STRATEGIES:
        score = sum(1 for kw in s["kws"] if kw in t)
        if score > best_score:
            best, best_score = s, score
    return best


def gap_matrix(snapshot: Dict[str, Any]) -> List[str]:
    """要素缺口矩阵(确定性): 五要素缺失/单薄判定, 返回缺口要素名列表。

    判据: 验收标准空 / 方案要点(designMd) <30 字 / 允许范围空 /
    需求目标(functionalScope)空 / 需求目标正文(desc) <15 字。
    """
    a = snapshot or {}
    gaps: List[str] = []
    if not (a.get("desc") or "").strip() or len(str(a.get("desc") or "")) < 15:
        gaps.append("①目标(需求正文)")
    if len(str(a.get("designMd") or "")) < 30:
        gaps.append("②方案要点")
    if not (a.get("allowedScope") or []):
        gaps.append("③允许范围")
    if not (a.get("functionalScope") or []):
        gaps.append("④需求目标清单")
    if not (a.get("acceptance") or []):
        gaps.append("⑤验收标准")
    return gaps


def clarify_directive(mode: str, question: str,
                      req_snapshot: Optional[Dict[str, Any]] = None) -> str:
    """生成会话内澄清指令段(系统消息; 空串=本回合不注入)。

    - 明确指令(任意挡) → ""(免澄清);
    - forced: 命中策略 → 策略问题集集中提问; 未命中 → 模型自由提问(五要素框架);
      用户答复前不落需求卡;
    - auto: 仅当已绑定需求且缺口矩阵非空 → 按缺口集中一次提问补齐。
    """
    if is_explicit_instruction(question):
        return ""
    if mode == "forced" and not req_snapshot:
        strat = match_strategy(question)
        if strat:
            qs = "\n".join(f"  {i+1}. [{el}] {q}"
                           for i, (el, q) in enumerate(strat["questions"]))
            return (f"【需求澄清(强制挡 · {strat['label']})】本回合先澄清后落卡——"
                    f"按以下切合该目标的问题集中编号提问, 每问先给出你基于上下文的"
                    f"推断默认值请用户确认或补全, 禁止开放式泛问:\n{qs}\n"
                    "用户答复后用 req.propose/req.amend 回填再建卡; 首轮禁止直接落需求卡。")
        return ("【需求澄清(强制挡)】本回合先澄清后落卡——该目标不在策略库覆盖内, "
                "由你自行组织澄清问题: 按五要素框架(①目标 ②方案要点 ③允许范围 "
                "④禁止改动 ⑤验收标准)逐项给出推断默认值请用户确认, 禁止开放式泛问; "
                "用户答复后 req.propose/req.amend 回填再建卡, 首轮禁止直接落需求卡。")
    if req_snapshot:
        # 强制挡在需求已建后同样走缺口驱动(状态无关, 自然收敛: 答复→amend
        # 回填→缺口缩→不再问), 防止"先澄清"指令对答复回合无限重放。
        gaps = gap_matrix(req_snapshot)
        if gaps:
            gl = "、".join(gaps)
            tag = "强制挡" if mode == "forced" else "自动"
            return (f"【需求澄清({tag})】当前规约缺口: {gl}——请集中一次提问补齐"
                    "(每项给出推断默认值请用户确认), 用户答复后 req.amend 回填; "
                    "要素齐了再提示可建卡。")
    return ""
