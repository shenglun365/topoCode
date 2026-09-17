"""能力探针套件(纯函数层) — A/C 两轴共用刻度与用例构造(三维矩阵统一标准)。

统一标准(2026-09-17 裁决): 同一探针维度(工具协议/结构化输出/指令遵循)、
同一刻度(T0-T2)、同一准入规则; A 轴(architect 模型, 经 llm 网关)与
C 轴(执行器模型, 经 runner 作业)各自实例化, 调用适配器由调用方注入。

层序合规: 本模块零 IO、不引 arch_routes/tools——判分函数(parse_fn)注入。
用例基于当前系统实际能力(裁决: 探针必须测真实工具与真实指令协议):
- 工具协议用例必须用真实注册工具(调用方传 _ARCH_TOOLS 的 name+参数形状);
- 指令遵循用例必须含系统基本指令(工具调用协议/职责边界);
- extra_cases 可扩展(判分函数随用例注入, 不改套件)。
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

# 探针维度权重(A/C 共用)
WEIGHTS = {"tool": 0.5, "json": 0.3, "instr": 0.2}

# 刻度阈值(综合分 → 档): ≥0.90 强 / ≥0.52 中 / 其余弱(全面补偿)
TIER_THRESHOLDS = ((0.90, 0), (0.52, 1))
WEAK_TIER = 2

# structured 支持位判据: 结构化输出用例得分(探针冒烟 → 档案位, M4-A 消费)
STRUCTURED_JSON_RATE_MIN = 0.7

_REJECT_PATTERNS = re.compile(
    r"不属于.{0,12}职责|不在.{0,8}(范围|能力)|无法(完成|处理|执行该)|建议您(使用|寻求)|"
    r"另行(寻找|使用)|我(只|仅)能处理|超出.{0,10}(能力|范围)|无法为您(编写|执行|提供)"
)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _protocol_head() -> str:
    """系统基本指令: 工具调用协议(cognition.prompt 单源常量, 同层引用)。"""
    from .prompt import TOOL_PROTOCOL_HEAD
    return TOOL_PROTOCOL_HEAD


# ── 用例构造(纯; parse_fn 注入) ──────────────────────────────────────

def build_tool_cases(tools: List[Dict[str, str]],
                     parse_fn: Callable[[str], List[Dict[str, Any]]],
                     count: int = 3) -> List[Dict[str, Any]]:
    """工具协议用例: system 列真实注册工具(name+参数形状), 逐个要求调用。

    tools: [{"name", "params_hint"}](调用方从 _ARCH_TOOLS 取真实值);
    parse_fn: 模型原文 → [{tool, arguments}](注入 extract_tool_calls)。
    判分: 1=合法块且工具名匹配 / 0.5=有协议标记但解析失败 / 0=无。
    """
    specs = [t for t in (tools or []) if t.get("name")]
    if not specs:
        return []
    lines = [f"- {t['name']}(参数: {t.get('params_hint') or '见工具定义'})"
             for t in specs]
    system = ("你是工具调用代理。可用工具:\n" + "\n".join(lines) + "\n"
              + _protocol_head()
              + "输出工具调用块后不要再写其它内容。")
    cases: List[Dict[str, Any]] = []
    for i in range(max(1, int(count))):
        want = specs[i % len(specs)]["name"]
        ask = (f"请调用 {want} 工具完成当前步骤(参数用合理示意值)。"
               if i == 0 else
               f"需要执行动作时调用合适工具; 本步请调用 {want}。")
        cases.append({
            "id": f"tool[{want}]#{i}", "dim": "tool", "system": system,
            "user": ask, "max_tokens": 250, "want_tool": want,
            "parse": parse_fn,
        })
    return cases


def grade_tool(raw: str, want_tool: str,
               parse_fn: Callable[[str], List[Dict[str, Any]]]) -> float:
    if not raw:
        return 0.0
    has_marker = "[TOOL_CALL" in raw or "[/TOOL_CALL" in raw
    try:
        calls = parse_fn(raw) or []
    except Exception:  # noqa: BLE001
        calls = []
    for c in calls:
        if c.get("tool") == want_tool:
            return 1.0
    return 0.5 if has_marker else 0.0


def build_json_cases(parse_fn: Optional[Callable[[str], Any]] = None,
                     count: int = 3) -> List[Dict[str, Any]]:
    """结构化输出用例: ```json 围栏可解析率(structured 支持位的数据源)。"""
    asks = [
        "需求: 做一个 nginx 进程监控脚本, 显示 PID 和 CPU 内存占用",
        "需求: 给用户列表加分页, 每页 20 条",
        "需求: 订单超时 30 分钟未支付自动取消",
    ][:max(1, int(count))]
    system = ("你把用户需求整理为规约 JSON。只输出一个 ```json 围栏, 内容为对象本身, "
              '字段: title(标题), requirementMd(目标), designMd(方案要点), '
              "不要任何其他文字。")

    def _default_parse(raw: str) -> Any:
        m = _JSON_FENCE.search(raw or "")
        if not m:
            return None
        import json as _json
        try:
            return _json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            return None

    parse = parse_fn or _default_parse
    cases = []
    for ask in asks:
        cases.append({
            "id": f"json#{len(cases)}", "dim": "json", "system": system,
            "user": ask, "max_tokens": 400, "parse": parse,
        })
    return cases


def grade_json(raw: str, parse_fn: Optional[Callable[[str], Any]] = None) -> float:
    """0=无围栏 / 0.5=有围栏但解析失败 / 1=可解析且 title 非空。"""
    if not raw:
        return 0.0
    m = _JSON_FENCE.search(raw)
    if not m:
        return 0.0
    import json as _json
    try:
        obj = _json.loads(m.group(1))
        return 1.0 if isinstance(obj, dict) and str(obj.get("title") or "").strip() else 0.5
    except Exception:  # noqa: BLE001
        return 0.5


def build_instruction_cases(count: int = 3) -> List[Dict[str, Any]]:
    """指令遵循用例: 职责边界内不拒做(系统基本纪律的真实形态)。"""
    system = ("你是需求分析 agent。用户明确表达的需求一律受理, 包括与项目关联较弱的"
              "通用编程/运维任务(脚本、工具、配置等): 照常整理为需求规约, "
              "不得以「不属于职责范围」为由拒绝或推诿。")
    asks = [
        "写一个 python 脚本查找 nginx 进程并显示资源占用",
        "帮我写一个日志清理的 shell 脚本",
        "生成一个导出数据库表为 CSV 的工具",
    ][:max(1, int(count))]
    return [{"id": f"instr#{i}", "dim": "instr", "system": system,
             "user": ask, "max_tokens": 300} for i, ask in enumerate(asks)]


def grade_instruction(raw: str) -> float:
    """1=受理(无拒做模式) / 0=拒做。"""
    if not raw:
        return 0.0
    return 0.0 if _REJECT_PATTERNS.search(raw) else 1.0


def grade_case(case: Dict[str, Any], raw: str) -> float:
    """按维度判分(统一入口; 自定义用例携 grade/parse 时优先)。"""
    grade = case.get("grade")
    if callable(grade):
        return float(grade(raw))
    dim = case.get("dim")
    if dim == "tool":
        return grade_tool(raw, case.get("want_tool") or "", case["parse"])
    if dim == "json":
        return grade_json(raw, case.get("parse"))
    if dim == "instr":
        return grade_instruction(raw)
    return 0.0


# ── 刻度/准入/支持位推导(A/C 共用) ───────────────────────────────────

def tier_from_score(score: float, heuristic_base: int) -> int:
    """综合分 + 名称启发基档 → 刻度(T0-T2)。差分只降不升(兜底方向)。"""
    tier = max(0, min(2, int(heuristic_base)))
    if score < TIER_THRESHOLDS[1][0]:
        tier = max(tier, 1)
    if score < 0.25:
        tier = WEAK_TIER
    return tier


def admission(tier: int) -> Dict[str, Any]:
    """准入判定(提示不拦截——T2 可按最低档运行, 补偿维度拉满)。"""
    if tier >= WEAK_TIER:
        return {"level": "weak",
                "note": "模型测评较弱(T2 档)——系统将按全面补偿模式运行"
                        "(结构化指令+核心逻辑图+步骤编排), 建议更换 T0/T1 档模型。"}
    return {"level": "pass", "note": ""}


def structured_from(json_rate: float) -> bool:
    """structured 支持位(探针冒烟判据): 结构化输出用例得分达标。"""
    return float(json_rate) >= STRUCTURED_JSON_RATE_MIN


def stability(samples: List[str]) -> float:
    """输出方差 → 稳定性分: 全同=1.0, 全不同=0.0(0/1/2 三档折算)。"""
    nonempty = [s for s in samples if s]
    if len(nonempty) < 2:
        return 0.5
    uniq = len({s[:200] for s in nonempty})
    if uniq <= 1:
        return 1.0
    if uniq == 2:
        return 0.6
    return 0.2
