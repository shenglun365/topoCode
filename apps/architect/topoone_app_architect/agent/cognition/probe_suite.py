"""能力探针套件(纯函数层) — A/C 两轴共用刻度与用例构造(三维矩阵统一标准)。

统一标准(2026-09-17 裁决): 同一探针维度(工具协议/结构化输出/指令遵循)、
同一刻度(T0-T2)、同一准入规则; A 轴(architect 模型, 经 llm 网关)与
C 轴(执行器模型, 经 runner 作业)各自实例化, 调用适配器由调用方注入。

层序合规: 本模块零 IO、不引 arch_routes/tools——判分函数(parse_fn)注入。
用例基于当前系统实际能力(裁决: 探针必须测真实工具与真实指令协议):
- 工具协议用例必须用真实注册工具(调用方传 _ARCH_TOOLS 的 name+参数形状),
  问法三态覆盖真实输入形态(直接点名/场景转述/带噪声上下文);
- 结构化输出用例取 architect 真实场景池(规约生成), 跨领域覆盖
  (业务流程/权限/前端/检索/网关/数据), 含一例长规约(1200 tokens)
  专门压测小模型「JSON 写一半被截断」的高频失败模式;
- 指令遵循用例取通用工程任务池(运维脚本/前端/数据库/DevOps/算法/测试),
  不绑定具体项目(nginx-src 等), 以实际交付规约产物为据(空壳受理 0.5 分);
- 设计三维(需求分析/架构设计/模块设计): 模糊需求澄清定界 / 模块分解依赖选型 /
  接口契约边界步骤——产物验收, 轻权重参与判档(2026-09-18 裁决);
- extra_cases 可扩展(判分函数随用例注入, 不改套件)。
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

# 探针维度权重(A/C 共用; 2026-09-18 裁决: 设计三维参与判档, 轻权重)
WEIGHTS = {"tool": 0.30, "json": 0.15, "instr": 0.10,
           "requirement": 0.10, "architecture": 0.05, "module": 0.05,
           "inquiry": 0.15, "routing": 0.10}

# 刻度阈值(综合分 → 档): ≥0.90 强 / ≥0.52 中 / 其余弱(全面补偿)
TIER_THRESHOLDS = ((0.90, 0), (0.52, 1))
WEAK_TIER = 2

# ── 胜任容量分层(2026-09-18 裁决) ─────────────────────────────────────
# 探测输出预算按模型参数规模给足: 思考型模型 reasoning 同样占用输出容量,
# 预算不足会导致「无法输出」而误判低分(nex-n2.5-mini 截断教训的机制化)。
# 仅影响测试预算, 不影响评分与判档(判档纯用例结果)。
_BUDGET_UNKNOWN = 8192   # 参数规模未知 → 中档默认

_B_PARAM_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*b(?![a-z0-9])", re.IGNORECASE)


def guess_params_b(model_name: str) -> Optional[float]:
    """模型名 → 参数规模(billion)。如 qwen3-8b→8.0, Qwen2.5-72B→72.0, 0.5b→0.5。"""
    for m in _B_PARAM_RE.finditer(model_name or ""):
        try:
            return float(m.group(1))
        except ValueError:  # pragma: no cover
            continue
    return None


def output_budget(model_name: str) -> int:
    """胜任容量 → 单用例输出预算(max_tokens):
    1~5B → 4K / 6~15B → 8K / 15B+ → 16K / 未知 → 8K(中档默认)。"""
    b = guess_params_b(model_name)
    if b is None:
        return _BUDGET_UNKNOWN
    if b < 6:
        return 4096
    if b < 16:
        return 8192
    return 16384

# structured 支持位判据: 结构化输出用例得分(探针冒烟 → 档案位, M4-A 消费)
STRUCTURED_JSON_RATE_MIN = 0.7

# 结构化输出默认输出上限(实测: 规整模型规约常 500-800 tokens, 400 会截断致围栏
# 不闭合被误判 0 分——nex-n2.5-mini 生产回归); 长规约用例单独放大(截断压力测试)
_JSON_MAX_TOKENS = 900
_JSON_LONG_MAX_TOKENS = 1200
# 设计三维(需求/架构/模块)产物更长, 统一放宽
_DESIGN_MAX_TOKENS = 1200

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
# 截断容错: 围栏开了没收口(max_tokens 截断)——有产物但不完整, 不应记 0
_JSON_FENCE_OPEN = re.compile(r"```(?:json)?\s*\{")


def _parse_fence_obj(raw: str):
    """围栏 JSON 解析(截断容错): 返回 (obj|None, truncated)。
    truncated=True = 围栏开了没闭合(产物被 max_tokens 截断, 部分分)。"""
    raw = raw or ""
    m = _JSON_FENCE.search(raw)
    if m:
        import json as _json
        try:
            obj = _json.loads(m.group(1))
            return (obj if isinstance(obj, dict) else None), False
        except Exception:  # noqa: BLE001
            return None, False
    if _JSON_FENCE_OPEN.search(raw):
        return None, True
    return None, False


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
    问法三态(轮转): 直接点名 / 场景转述 / 带噪声上下文——覆盖真实输入形态。
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
    asks = [
        "请调用 {want} 工具完成当前步骤(参数用合理示意值)。",
        "结合当前进展, 需要落库/检索/汇总时调用合适工具; 本步请调用 {want}。",
        "[用户补充] 这条需求比较急, 先把数据找齐。(与工具选择无关的背景噪声)"
        "本步必须调用 {want}。",
    ]
    cases: List[Dict[str, Any]] = []
    for i in range(max(1, int(count))):
        want = specs[i % len(specs)]["name"]
        cases.append({
            "id": f"tool[{want}]#{i}", "dim": "tool", "system": system,
            "user": asks[i % len(asks)].format(want=want),
            "max_tokens": 250, "want_tool": want,
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
                     count: int = 4) -> List[Dict[str, Any]]:
    """结构化输出用例: ```json 围栏可解析率(structured 支持位的数据源)。

    用例池取 architect 真实场景(需求 → 规约 JSON), 跨领域不绑具体项目;
    首例为长规约(max_tokens 800)——压测小模型长 JSON 截断失败模式,
    默认 count=4 保证其必入选。default 池序已按领域分散编排。
    """
    # (需求描述, max_tokens)
    asks: List[tuple] = [
        # 长规约: 多模块+流程对账, 输出天然长 → 截断压力
        ("需求: 库存管理系统一期, 含商品档案/入库/出库/盘点四个模块, "
         "单据需审批流转, 出入库自动记库存流水并支持期末对账, 出规约",
         _JSON_LONG_MAX_TOKENS),
        ("需求: 新增 RBAC 角色权限, 支持角色-菜单授权与按部门的数据范围隔离",
         _JSON_MAX_TOKENS),
        ("需求: 界面支持中英双语切换, 文案集中管理, 缺失翻译回退默认语言",
         _JSON_MAX_TOKENS),
        ("需求: 订单超时 30 分钟未支付自动取消", _JSON_MAX_TOKENS),
        ("需求: 给用户列表加分页, 每页 20 条", _JSON_MAX_TOKENS),
        ("需求: 全文搜索支持关键词高亮、拼音首字母与容错匹配", _JSON_MAX_TOKENS),
        ("需求: 开放 API 按租户限流与熔断, 超限返回 429 与重试提示",
         _JSON_MAX_TOKENS),
        ("需求: 报表中心按部门/时间范围筛选并导出 Excel", _JSON_MAX_TOKENS),
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
    for ask, mt in asks:
        cases.append({
            "id": f"json#{len(cases)}", "dim": "json", "system": system,
            "user": ask, "max_tokens": mt, "parse": parse,
        })
    return cases


def grade_json(raw: str, parse_fn: Optional[Callable[[str], Any]] = None) -> float:
    """1=围栏可解析且 title 非空 / 0.5=可解析缺 title、或围栏未闭合(max_tokens 截断) /
    0=无围栏。"""
    if not raw:
        return 0.0
    m = _JSON_FENCE.search(raw)
    if not m:
        # 截断容错: 开了围栏但没闭合——产物真实存在只是被截断, 给 0.5 部分分
        return 0.5 if _JSON_FENCE_OPEN.search(raw) else 0.0
    import json as _json
    try:
        obj = _json.loads(m.group(1))
        return 1.0 if isinstance(obj, dict) and str(obj.get("title") or "").strip() else 0.5
    except Exception:  # noqa: BLE001
        return 0.5


def build_instruction_cases(count: int = 3) -> List[Dict[str, Any]]:
    """指令遵循用例: 职责边界内受理并**实际交付**规约产物(以执行结果为据, 非拒做正则)。

    生产语义: 受理 = 产出需求卡 → 用例要求输出规约 JSON(与生产同契约),
    判分看产物可用性(grade_instruction), 空壳受理不再得满分。
    用例池为通用工程任务(运维脚本/前端/数据库/DevOps/算法/测试工程),
    不绑定具体项目; 池序按领域分散, 默认 count=3 已跨三领域。
    """
    system = ("你是需求分析 agent。用户明确表达的需求一律受理, 包括与项目关联较弱的"
              "通用编程/运维任务(脚本、工具、配置等), 不得以「不属于职责范围」为由拒绝; "
              "受理后整理为规约: 只输出一个 ```json 围栏, 内容为对象本身, "
              "字段 title(标题)/requirementMd(目标)/designMd(方案要点), 不要其他文字。")
    asks = [
        "写一个 python 脚本查找 nginx 进程并显示资源占用",
        "写一个 Vue3 表单组件, 带必填/手机号校验与错误提示",
        "给一条慢 SQL 写优化建议并给出索引方案",
        "帮我写一个日志清理的 shell 脚本",
        "生成一个导出数据库表为 CSV 的工具",
        "写一个多阶段构建的 Dockerfile(Node 服务), 并说明镜像瘦身要点",
        "实现一个函数: 把 '每 5 分钟' 这类中文周期描述转成 cron 表达式",
        "为一个分页查询接口补 pytest 单元测试用例(参数化+边界值)",
    ][:max(1, int(count))]
    return [{"id": f"instr#{i}", "dim": "instr", "system": system,
             "user": ask, "max_tokens": 400} for i, ask in enumerate(asks)]


def grade_instruction(raw: str) -> float:
    """以实际产出为据(执行结果验收, 非正则):
    1=规约围栏可解析且三要素实质非空 / 0.5=有产物但要素空壳或被截断 /
    0=无产物(拒答/跑题)。"""
    if not raw:
        return 0.0
    m = _JSON_FENCE.search(raw)
    if not m:
        # 截断容错: 开了围栏没闭合 → 有产物但不完整, 0.5 部分分(不冤枉能干的慢模型)
        return 0.5 if _JSON_FENCE_OPEN.search(raw) else 0.0
    import json as _json
    try:
        obj = _json.loads(m.group(1))
    except Exception:  # noqa: BLE001
        return 0.5
    if not (isinstance(obj, dict) and str(obj.get("title") or "").strip()):
        return 0.5
    req = str(obj.get("requirementMd") or "").strip()
    design = str(obj.get("designMd") or "").strip()
    # 实质非空: 目标/方案各 ≥20 字——排除「好的我来做」式空壳受理
    return 1.0 if len(req) >= 20 and len(design) >= 20 else 0.5


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


# ── 设计三维(需求分析/架构设计/模块设计; 产物验收, 轻权重参与判档) ──────

def build_requirement_cases(count: int = 2) -> List[Dict[str, Any]]:
    """需求分析用例: 故意模糊的需求 → 考察「不直接开干」——识别缺失要素
    (澄清项)与边界定界(明确不做)。

    契约: title / requirementMd / clarifications[{question, defaultAssumption}]≥2 /
    scopeIn / scopeOut。判分: 1=契约完整+澄清≥2+scopeOut 非空 / 0.5=缺项或截断 / 0=无。"""
    system = ("你是需求分析 agent。用户需求常常模糊, 你的职责是识别缺失要素并定界, "
              "而不是直接开干。只输出一个 ```json 围栏, 内容为对象本身, 字段: "
              "title(整理后的需求标题), requirementMd(整理后的需求描述), "
              "clarifications(数组, 每项 {question: 待确认问题, "
              "defaultAssumption: 你先采用的默认假设}, 至少 2 条), "
              "scopeIn(本期范围), scopeOut(明确不做), 不要其他文字。")
    asks = ["我想做一个客服系统", "帮我搞一个数据报表平台"][:max(1, int(count))]

    def _grade(raw: str) -> float:
        obj, tr = _parse_fence_obj(raw)
        if obj is None:
            return 0.5 if tr else 0.0
        cl = obj.get("clarifications")
        cl_ok = (isinstance(cl, list) and len(cl) >= 2 and all(
            isinstance(c, dict) and str(c.get("question") or "").strip()
            for c in cl[:2]))
        return 1.0 if (str(obj.get("title") or "").strip()
                       and str(obj.get("scopeOut") or "").strip()
                       and cl_ok) else 0.5

    return [{"id": f"req#{i}", "dim": "requirement", "system": system,
             "user": a, "max_tokens": _DESIGN_MAX_TOKENS, "grade": _grade}
            for i, a in enumerate(asks)]


def build_architecture_cases(count: int = 2) -> List[Dict[str, Any]]:
    """架构设计用例: 需求 → 模块分解(modules≥3)+依赖(deps≥2)+带理由选型
    (choices≥1 且 why≥10 字)。判分: 1=三项达标 / 0.5=缺项或截断 / 0=无。"""
    system = ("你是架构设计 agent。只输出一个 ```json 围栏, 内容为对象本身, 字段: "
              "modules(数组, 每项 {name: 模块名, duty: 职责}, 至少 3 个), "
              "deps(数组, 每项 {from, to}, 模块间依赖, 至少 2 条), "
              "choices(数组, 每项 {area: 决策域, pick: 选型, why: 理由}, 至少 1 条), "
              "不要其他文字。")
    asks = ["为一个多租户文档协作系统(网页版)设计后端架构",
            "为一个电商订单系统(含库存与支付回调)设计后端架构"][:max(1, int(count))]

    def _grade(raw: str) -> float:
        obj, tr = _parse_fence_obj(raw)
        if obj is None:
            return 0.5 if tr else 0.0
        mods = obj.get("modules")
        mods_ok = (isinstance(mods, list) and len(mods) >= 3 and all(
            isinstance(x, dict) and str(x.get("name") or "").strip()
            and str(x.get("duty") or "").strip() for x in mods[:3]))
        deps = obj.get("deps")
        deps_ok = isinstance(deps, list) and len(deps) >= 2
        chs = obj.get("choices")
        ch_ok = isinstance(chs, list) and any(
            isinstance(c, dict) and len(str(c.get("why") or "").strip()) >= 10
            for c in chs)
        return 1.0 if (mods_ok and deps_ok and ch_ok) else 0.5

    return [{"id": f"arch#{i}", "dim": "architecture", "system": system,
             "user": a, "max_tokens": _DESIGN_MAX_TOKENS, "grade": _grade}
            for i, a in enumerate(asks)]


def build_module_design_cases(count: int = 2) -> List[Dict[str, Any]]:
    """模块设计用例: 单模块 → 接口契约+数据结构+边界用例(≥3)+编号步骤(≥3)。
    判分: 1=四项达标 / 0.5=缺项或截断 / 0=无。"""
    system = ("你是软件设计 agent。为单个模块出设计, 只输出一个 ```json 围栏, "
              "内容为对象本身, 字段: "
              "interface(对象 {fn: 函数名, params: [参数名...], returns: 返回说明}), "
              "dataStructures(关键数据结构说明), "
              "edgeCases(数组, 边界用例, 至少 3 条), "
              "steps(数组, 实现步骤, 每步单一动作, 至少 3 条), 不要其他文字。")
    asks = ["为「订单 30 分钟未支付自动取消」设计处理模块",
            "为「接口幂等重试」设计通用模块"][:max(1, int(count))]

    def _grade(raw: str) -> float:
        obj, tr = _parse_fence_obj(raw)
        if obj is None:
            return 0.5 if tr else 0.0
        itf = obj.get("interface")
        itf_ok = (isinstance(itf, dict) and str(itf.get("fn") or "").strip()
                  and bool(itf.get("params")))
        ec = obj.get("edgeCases")
        ec_ok = isinstance(ec, list) and len(
            [e for e in ec if str(e or "").strip()]) >= 3
        st = obj.get("steps")
        st_ok = isinstance(st, list) and len(
            [s for s in st if str(s or "").strip()]) >= 3
        return 1.0 if (itf_ok and str(obj.get("dataStructures") or "").strip()
                       and ec_ok and st_ok) else 0.5

    return [{"id": f"mod#{i}", "dim": "module", "system": system,
             "user": a, "max_tokens": _DESIGN_MAX_TOKENS, "grade": _grade}
            for i, a in enumerate(asks)]


# ── T2 补偿复核(生产同款补偿手法: 结构化要素框架 + 核心逻辑图) ──────────
# 裁决: T2「全面补偿」不能只声明——须用补偿形态的用例实测补偿实效;
# 补偿仍救不回 → admission=insufficient(模型能力不足), 不再笼统「准入」。

# 补偿复核通过线: 用例均分 ≥0.5 视为「补偿模式可修正」
COMP_RESCUE_MIN = 0.5


# ── 主 agent 职能域(定位裁决 2026-09-26: 问什么答什么/不扩大化/路由内化) ──

_INQUIRY_STATUS_JSON = (
    '{"degraded": true, "name": "demo-app",'
    ' "execution": {"tasksTotal": 7, "tasksDone": 5, "tasksActive": 1,'
    '  "recentDone": [{"title": "Vite 端口配置"}]},'
    ' "parsed": {"contextUnits": 187}}')


def build_inquiry_cases(count: int = 2) -> List[Dict[str, Any]]:
    """问询纪律用例(cv-257 教训探测化: 问什么答什么, 不扩大化)。

    场景: 给定项目状态数据, 用户做信息问询。合格 = 只答事实(命中关键数字),
    不得 ①输出工具调用块 ②宣告已创建需求卡/已启动执行等行动扩大化。
    (答毕附"建议建立 KB"类提示不算扩大化——那是事实陈述的自然延伸。)
    判分: 1=事实命中且无扩大化 / 0.5=事实命中但有行动宣告 / 0=无事实或调工具。"""
    system = ("你是项目架构主 agent。只依据给定的项目状态数据回答用户问题, "
              "不得虚构数据, 不得调用工具; 信息问询回合不创建需求卡、不发起任何"
              "执行动作。\n项目状态数据: " + _INQUIRY_STATUS_JSON)
    asks = [
        "检查当前项目的完成情况",
        "项目里还有哪些没做完的？现在具备做架构分析的条件吗？",
    ][:max(1, int(count))]

    def _grade(raw: str) -> float:
        if not raw:
            return 0.0
        if "[TOOL_CALL" in raw or "[/TOOL_CALL" in raw:
            return 0.0                       # 问询回合调工具 = 直接不合格
        # 行动扩大化宣告(不只是建议): 已…创建/起草/发起/启动/开始…需求卡/任务/执行
        if re.search(r"已[^。]{0,6}?(创建|起草|发起|启动|开始)[^。]{0,8}(需求|任务|执行)", raw):
            return 0.5
        facts_ok = ("7" in raw and "187" in raw)
        return 1.0 if facts_ok else 0.5

    return [{"id": f"inquiry#{i}", "dim": "inquiry", "system": system,
             "user": a, "max_tokens": 400, "grade": _grade}
            for i, a in enumerate(asks)]


def build_routing_cases(count: int = 3) -> List[Dict[str, Any]]:
    """路由决策用例(主 agent 职能: 会话输入三向分发, perception/router 同语义)。

    场景池: attachTo=任务 → transfer; 显式指派执行器 → assign;
    普通问询/对话(资产域可答) → chat。判分: {"action": ...} 精确命中。"""
    system = ("你是项目架构主 agent 的路由决策器。对每条用户输入判定处置动作, "
              "只输出一个 ```json 围栏, 内容为 {\"action\": \"...\"}, "
              "action 取值: transfer(转达给指定活跃任务) / "
              "assign(指派执行器承接新任务) / chat(主 agent 自身应答)。")
    asks: List[tuple] = [
        ("把这条补充说明转达给正在执行的任务 task-42", "transfer"),
        ("@coder 帮我写一个日志清理脚本", "assign"),
        ("当前项目的组件地图里有哪些 L0 组件？", "chat"),
        ("这个改动指派给 codex 执行器去实现", "assign"),
        ("继续刚才的话题，为什么选这个方案？", "chat"),
    ][:max(1, int(count))]

    def _grade(want: str) -> Callable[[str], float]:
        def _g(raw: str) -> float:
            obj, tr = _parse_fence_obj(raw)
            if obj is None:
                return 0.5 if tr else 0.0
            return 1.0 if str(obj.get("action") or "").strip() == want else 0.0
        return _g

    return [{"id": f"route#{i}", "dim": "routing", "system": system,
             "user": ask, "max_tokens": 200, "grade": _grade(want)}
            for i, (ask, want) in enumerate(asks)]


def build_compensation_cases(count: int = 2) -> List[Dict[str, Any]]:
    """补偿复核用例: system 注入 T2 生产同款补偿(gears.py: 五要素框架/步骤序列/
    核心逻辑图脚手架), 考察补偿形态指令能否把弱模型输出拉回可用。

    判分随用例注入(grade_case 对 case["grade"] 优先):
      结构化规约: 1=围栏+可解析+title+designMd 编号步骤序列 / 0.5=围栏可解析缺步骤 / 0=无
      核心逻辑图: 1=mermaid/plantuml 围栏+≥3 边 / 0.5=有围栏少边 / 0=无
    """
    def _grade_json(raw: str) -> float:
        if not raw:
            return 0.0
        m = _JSON_FENCE.search(raw)
        if not m:
            return 0.0
        import json as _json
        try:
            obj = _json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            return 0.5
        if not (isinstance(obj, dict) and str(obj.get("title") or "").strip()):
            return 0.5
        steps = str(obj.get("designMd") or "")
        has_steps = len(re.findall(
            r"(?:^|\n)\s*(?:\d+[.、)]|[-*]\s|步骤\s*\d)", steps)) >= 2
        return 1.0 if has_steps else 0.5

    def _grade_diagram(raw: str) -> float:
        if not raw:
            return 0.0
        if not re.search(r"```(?:mermaid|plantuml|uml)\b", raw):
            return 0.0
        edges = len(re.findall(r"-->|->", raw))
        return 1.0 if edges >= 3 else 0.5

    sys_json = (
        "【模型能力补偿·结构化指令】你把用户需求整理为规约 JSON。"
        "严格按以下步骤: ①按五要素框架梳理——目标/方案要点/允许范围/禁止改动/验收标准; "
        "②只输出一个 ```json 围栏, 内容为对象本身; "
        "③字段固定: title(标题), requirementMd(目标, 一句话), "
        "designMd(方案要点, 必须是编号步骤序列, 每步单一动作, 格式 '1. …\\n2. …\\n3. …'); "
        "不要任何其他文字。")
    sys_diag = (
        "【模型能力补偿·核心逻辑图】为下述需求产出核心逻辑图(用图补足方案理解, "
        "不依赖执行侧自行推断)。严格按以下步骤: ①梳理触发→处理→结束主干; "
        "②只输出一个 ```mermaid 代码围栏; "
        "③内容为 flowchart, 用 'A[节点] --> B[节点]' 形式, 至少 4 个节点 3 条边; "
        "④围栏后不要再写解释。")
    asks: List[tuple] = [
        ("需求: 做一个 nginx 进程监控脚本, 显示 PID 和 CPU 内存占用", sys_json, _grade_json),
        ("需求: 给用户列表加分页, 每页 20 条", sys_diag, _grade_diagram),
    ][:max(1, int(count))]
    return [{"id": f"comp#{i}", "dim": "comp", "system": s, "user": ask,
             "max_tokens": 400, "grade": g}
            for i, (ask, s, g) in enumerate(asks)]


# ── 刻度/准入/支持位推导(A/C 共用) ───────────────────────────────────

def tier_from_score(score: float) -> int:
    """纯用例结果判档(2026-09-18 裁决: 不考虑模型参数规模, 不因参数加减分):
    综合 ≥0.90 → T0 强 / ≥0.52 → T1 中 / 其余 → T2 弱(全面补偿+补偿复核定准入)。"""
    if score >= TIER_THRESHOLDS[0][0]:
        return 0
    if score >= TIER_THRESHOLDS[1][0]:
        return 1
    return WEAK_TIER


def admission(tier: int, compensation_rate: Optional[float] = None) -> Dict[str, Any]:
    """准入判定(提示不拦截——T2 可按最低档运行)。

    tier < 2 → pass。tier ≥ 2 按补偿复核实效分档(build_compensation_cases 实测):
      rate ≥ COMP_RESCUE_MIN → weak(补偿模式可修正, 全面补偿模式运行);
      rate 不足             → insufficient(模型能力不足——补偿仍无法完成基本任务,
                               明确建议更换模型; 不拦截但质量风险明示);
      None(旧档案/手工档未复核) → weak(维持原语义: 补偿可运行)。"""
    if int(tier) < WEAK_TIER:
        return {"level": "pass", "note": ""}
    if compensation_rate is None:
        return {"level": "weak",
                "note": "模型测评较弱(T2 档)——系统将按全面补偿模式运行"
                        "(结构化指令+核心逻辑图+步骤编排), 建议更换 T0/T1 档模型。"}
    pct = f"{float(compensation_rate) * 100:.0f}%"
    if float(compensation_rate) >= COMP_RESCUE_MIN:
        return {"level": "weak",
                "note": f"模型测评较弱(T2 档)——补偿复核通过({pct}), 补偿模式可修正: "
                        "系统将按全面补偿模式运行(结构化指令+核心逻辑图+步骤编排)。"}
    return {"level": "insufficient",
            "note": f"模型能力不足——补偿复核未通过({pct}): 补偿模式仍无法完成基本任务, "
                    "请更换 T0/T1 档模型(系统不拦截, 任务质量风险明示)。"}


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
