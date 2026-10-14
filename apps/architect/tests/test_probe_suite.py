"""探针套件纯函数层回归(probe_suite: A/C 两轴统一刻度/准入/structured 判据)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_probe_suite.py -q
"""
from topoone_app_architect.agent.cognition import probe_suite as ps  # noqa: E402


def _noop_parse(raw):
    return []


def test_tool_cases_use_real_tool_names():
    """工具协议用例接真实注册工具(name+参数形状由调用方注入)。"""
    tools = [{"name": "req.propose", "params_hint": '{"title", ...}'},
             {"name": "kb.asset.search", "params_hint": '{"text"}'}]
    cases = ps.build_tool_cases(tools, _noop_parse, count=3)
    assert len(cases) == 3
    assert all(c["dim"] == "tool" for c in cases)
    # 轮转覆盖全部真实工具
    wants = {c["want_tool"] for c in cases}
    assert wants == {"req.propose", "kb.asset.search"}
    # 系统段含真实参数形状与系统基本指令(工具调用协议)
    assert '{"title", ...}' in cases[0]["system"]
    assert "[TOOL_CALL]" in cases[0]["system"]
    assert ps.grade_case(cases[0], "plain text 无协议") == 0.0
    assert ps.grade_case(cases[0], "[TOOL_CALL]{bad json") == 0.5
    from topoone_app_architect.agent.tools.protocol import extract_tool_calls
    real = ps.build_tool_cases(tools, extract_tool_calls, count=1)
    assert ps.grade_case(
        real[0],
        '[TOOL_CALL]{"tool":"req.propose","arguments":{}}[/TOOL_CALL]') == 1.0


def test_json_and_instruction_grades():
    jc = ps.build_json_cases()
    assert ps.grade_case(jc[0], '```json\n{"title": "T"}\n```') == 1.0
    assert ps.grade_case(jc[0], "```json\n{bad}\n```") == 0.5
    assert ps.grade_case(jc[0], "没有围栏") == 0.0
    # 截断容错: 围栏开了没收口(max_tokens 截断) → 0.5 部分分, 不冤枉能干的慢模型
    assert ps.grade_case(jc[0], '```json\n{"title": "T", "requirementMd": "实时监控') == 0.5
    assert ps.grade_case(jc[0], "```json") == 0.0   # 只有围栏头无内容 = 无产物
    ic = ps.build_instruction_cases()
    # 指令判据 = 实际交付规约产物(非拒做正则): 空壳受理不再满分
    good = ('```json\n{"title": "nginx 监控", '
            '"requirementMd": "实时显示 nginx 进程 PID 与 CPU/内存占用", '
            '"designMd": "ps 采集进程数据, python 解析并格式化输出, 循环刷新"}\n```')
    assert ps.grade_case(ic[0], good) == 1.0
    assert ps.grade_case(
        ic[0], '```json\n{"title": "T", "requirementMd": "", "designMd": ""}\n```') == 0.5
    assert ps.grade_case(ic[0], "好的, 我来实现该脚本") == 0.0     # 无产物=未完成实际任务
    assert ps.grade_case(ic[0], "这超出我的能力范围, 建议您使用其他工具") == 0.0
    # 截断容错: 指令用例同规则
    assert ps.grade_case(ic[0], '```json\n{"title": "nginx 监控", "requirementMd": "实时显') == 0.5


def test_case_pool_diversity():
    """用例池覆盖面: 跨领域/不绑具体项目; 长规约截断压测必入选。"""
    jc = ps.build_json_cases()
    assert len(jc) == 4
    asks = {c["user"] for c in jc}
    assert len(asks) == 4                          # 无重复用例
    # 长规约(截断压力)为池首, 输出上限单独放大
    assert jc[0]["max_tokens"] == 1200
    assert all(c["max_tokens"] == 900 for c in jc[1:])
    # 完整池跨领域: 业务流程/权限/前端/检索/网关/数据(关键词抽样)
    full = ps.build_json_cases(count=8)
    joined = " ".join(c["user"] for c in full)
    for kw in ("RBAC", "双语", "超时", "分页", "搜索", "限流", "报表"):
        assert kw in joined, kw
    ic = ps.build_instruction_cases()
    assert len(ic) == 3
    ifull = ps.build_instruction_cases(count=8)
    itext = " ".join(c["user"] for c in ifull)
    for kw in ("python", "Vue3", "SQL", "shell", "CSV", "Dockerfile", "cron", "pytest"):
        assert kw in itext, kw                     # 运维/前端/数据库/DevOps/算法/测试
    # 工具问法三态轮转(直接点名/场景转述/带噪声)
    tools = [{"name": f"t{i}", "params_hint": "{}"} for i in range(3)]
    tc = ps.build_tool_cases(tools, _noop_parse, count=3)
    assert "背景噪声" in tc[2]["user"]
    assert "结合当前进展" in tc[1]["user"]


def test_tier_from_score_pure_result():
    """纯用例结果判档(2026-09-18 裁决: 参数规模不参与): 阈值单调映射 T0-T2。"""
    assert ps.tier_from_score(1.0) == 0
    assert ps.tier_from_score(0.90) == 0
    assert ps.tier_from_score(0.89) == 1
    assert ps.tier_from_score(0.60) == 1
    assert ps.tier_from_score(0.52) == 1
    assert ps.tier_from_score(0.51) == 2
    assert ps.tier_from_score(0.10) == 2


def test_admission_weak_not_blocking():
    """准入: T2 → weak 提示(不拦截); T0/T1 → pass。"""
    weak = ps.admission(2)
    assert weak["level"] == "weak" and "建议更换" in weak["note"]
    assert ps.admission(1)["level"] == "pass"
    assert ps.admission(0)["level"] == "pass"


def test_compensation_cases_and_admission():
    """T2 补偿复核: 生产同款补偿形态用例判分 + admission 三档实效分档。"""
    cases = ps.build_compensation_cases()
    assert len(cases) == 2
    # 结构化规约补偿: 围栏+可解析+title+编号步骤序列 → 1.0; 缺步骤 → 0.5; 无围栏 → 0
    rescued = '```json\n{"title": "T", "designMd": "1. a\\n2. b\\n3. c"}\n```'
    assert ps.grade_case(cases[0], rescued) == 1.0
    assert ps.grade_case(cases[0], '```json\n{"title": "T", "designMd": "随便写"}\n```') == 0.5
    assert ps.grade_case(cases[0], "没有围栏") == 0.0
    # 核心逻辑图补偿: mermaid 围栏+≥3 边 → 1.0; 有围栏少边 → 0.5; 无围栏 → 0
    diag = "```mermaid\nflowchart TD\nA[x] --> B[y]\nB --> C[z]\nC --> D[w]\n```"
    assert ps.grade_case(cases[1], diag) == 1.0
    assert ps.grade_case(cases[1], "```mermaid\nflowchart TD\nA --> B\n```") == 0.5
    assert ps.grade_case(cases[1], "纯文字回答") == 0.0
    # admission 三档: pass / weak(未复核=legacy 与 补偿可修正) / insufficient(补偿救不回)
    assert ps.admission(1)["level"] == "pass"
    assert ps.admission(2)["level"] == "weak"
    ok = ps.admission(2, 0.75)
    assert ok["level"] == "weak" and "补偿复核通过" in ok["note"]
    bad = ps.admission(2, 0.25)
    assert bad["level"] == "insufficient" and "模型能力不足" in bad["note"]


def test_structured_bit_threshold():
    assert ps.structured_from(0.7) is True
    assert ps.structured_from(1.0) is True
    assert ps.structured_from(0.69) is False


def test_output_budget_by_size():
    """胜任容量分层(2026-09-18): 1~5B→4K / 6~15B→8K / 15B+→16K / 未知→8K。
    仅影响测试预算, 与评分/判档无关。"""
    assert ps.output_budget("qwen3.5-2b-mtp") == 4096       # 2B
    assert ps.output_budget("qwen3.5-4b-mtp") == 4096       # 4B
    assert ps.output_budget("llama-3.2-3b") == 4096
    assert ps.output_budget("qwen3.5-9b-mtp") == 8192       # 9B
    assert ps.output_budget("gemma-4-12b-it") == 8192       # 12B
    assert ps.output_budget("m-15b") == 8192                # 15B 含在 6~15B
    assert ps.output_budget("qwen3.6-35b-a3b-mtp") == 16384 # 35B
    assert ps.output_budget("nex-n2.5-mini") == 8192        # 规模未知 → 中档默认


def test_design_dims_cases_and_weights():
    """设计三维(需求/架构/模块): 用例构造 + 产物验收判分 + 权重和=1。"""
    assert abs(sum(ps.WEIGHTS.values()) - 1.0) < 1e-9
    rc = ps.build_requirement_cases()
    assert len(rc) == 2
    good_req = ('```json\n{"title": "客服系统", "requirementMd": "在线客服与工单", '
                '"clarifications": [{"question": "是否接入外部 IM?", "defaultAssumption": "一期不接"}, '
                '{"question": "并发规模?", "defaultAssumption": "100 并发"}], '
                '"scopeIn": "网页端会话与工单", "scopeOut": "不做语音"}\n```')
    assert ps.grade_case(rc[0], good_req) == 1.0          # 澄清≥2+定界=需求分析力
    assert ps.grade_case(
        rc[0], '```json\n{"title": "t", "clarifications": [], "scopeOut": ""}\n```') == 0.5
    assert ps.grade_case(rc[0], '```json\n{"title": "客服"') == 0.5   # 截断容错
    assert ps.grade_case(rc[0], "直接开干写代码") == 0.0              # 模糊需求直接开干=0
    ac = ps.build_architecture_cases()
    assert len(ac) == 2
    good_arch = ('```json\n{"modules": [{"name": "a", "duty": "x"}, '
                 '{"name": "b", "duty": "y"}, {"name": "c", "duty": "z"}], '
                 '"deps": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}], '
                 '"choices": [{"area": "存储", "pick": "postgres", '
                 '"why": "多租户行级隔离成熟且团队熟悉"}]}\n```')
    assert ps.grade_case(ac[0], good_arch) == 1.0
    assert ps.grade_case(ac[0], '```json\n{"modules": [{"name": "a", "duty": "x"}]') == 0.5
    mc = ps.build_module_design_cases()
    assert len(mc) == 2
    good_mod = ('```json\n{"interface": {"fn": "cancel_order", '
                '"params": ["order_id"], "returns": "bool"}, '
                '"dataStructures": "orders 表 status/expire_at", '
                '"edgeCases": ["已支付", "重复取消", "订单不存在"], '
                '"steps": ["扫描过期", "置状态", "发通知"]}\n```')
    assert ps.grade_case(mc[0], good_mod) == 1.0
    assert ps.grade_case(mc[0], "没有围栏") == 0.0
