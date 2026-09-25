"""architect 内核九层分层边界测试（B2/批次 2；纯 stdlib ast，零新依赖）。

规则（agent-structure-review 批次 B2）:
  R1 内核不反向依赖适配层——agent/** 不得 import arch_routes/*；
  R2 层序 perception < cognition/planning/memory/tools < execution < reflection，
     低层不得 import 高层；collab/governance 为横切白名单（任意层可引）；
  R3 agent 根（orchestrator.py/__init__.py）为顶层编排例外，可引各层。

棘轮纪律：下方 _R1_INVENTORY/_R2_INVENTORY 为 2026-09-17 存量违规冻结清单——
  冻结内不追究（逐步清退），冻结外新增一处即失败（输出违规文件与 import 链）。
  清退存量后应同步删除清单条目（清单只许缩短不许增长）。

Run: cd <repo> && python -m pytest apps/architect/tests/test_agent_layering.py -q
"""
import ast
import os

AGENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                         "topoone_app_architect", "agent")
ORDER = ["perception", "compensation", "cognition", "planning", "memory",
         "tools", "execution", "reflection", "requirements", "turns", "sessions"]
# sessions(2026-09-24 MS2 补刻度): 会话落库域此前仅引 app.arch_routes(shim),
# 对层序扫描不可见; shim 撤除后出现真实层依赖, 入刻度接受门禁。
RANK = {name: i for i, name in enumerate(ORDER)}
CROSSCUT = {"collab", "governance"}
# M1(2026-09-19): compensation=L1 补偿内核(设计 §3, 供各层引), turns=L2 回合引擎
# (设计 §4, 内核顶层执行半边)——均入层序刻度, 详见 docs/architect/agent-capability-design-2609.md。

# 存量违规冻结（2026-09-17 快照）——内核反向依赖适配层(arch_routes)。
# 多为 store/req_agent 历史接缝; 清退时删除条目, 禁止新增。
_R1_INVENTORY = {
    "cognition/llm.py", "cognition/model_profile.py", "cognition/prompt.py",
    "cognition/roles.py", "reflection/dataset.py", "reflection/evaluator.py",
    "reflection/mining.py", "reflection/repair.py", "reflection/tier_suggest.py",
    "planning/req_spec.py",
    "planning/scope_probe.py", "planning/task_plan.py", "perception/commands.py",
    "collab/cards.py", "memory/dossier.py",
    # memory/store.py 已退役(2026-09-21, 零调用方清退——清单只许缩短的合法剪条)
    # requirements/clarify.py(2026-09-22 立条): 策略库配置化(D5 偿还)后经
    # load_strategies 读 CollabConfigStore(惰性导入)——随 dataset 先例,
    # 清退随策略配置基座上提。
    "memory/units.py", "memory/working.py", "governance/boundary.py",
    # memory/distill.py(2026-09-17 P1 立条): 错误提炼编排层, 与 memory/units.py
    # 同款依赖(store/adaptation/agent_roles 惰性导入)——读错误材料 + 轻任务
    # 提炼 + 落 error_pattern 单元; 依赖注入拆解与 units 清退同批处置。
    "memory/distill.py",
    # turns/{chat,context}.py(2026-09-19 M1 立条): 自 orchestrator(R3 例外层)
    # 机械搬迁的阶段函数, arch_routes 惰性导入随行; ChatTurn 接缝重构时清退。
    "turns/chat.py", "turns/context.py",
    # turns/intent_llm.py(2026-09-22 立条): 受限 LLM 意图兜底+误路由遥测(#5)——
    # overrides/policy 读取的 arch_routes 惰性导入随 context.py 同款先例。
    # turns/goal.py(2026-09-22 立条): GU 目标理解(GoalProfile 产出+决策表解析)——
    # apply_goal_directive 内 policy 读取的 arch_routes 惰性导入同款先例。
    "turns/intent_llm.py", "turns/goal.py",
    # execution/{merge,recover}.py(2026-09-19 M2 立条): 自 exec_bridge 机械
    # 迁出的合并域/恢复对账域(store/execution/runner 接缝随行); DispatchTurn
    # 接缝重构时随 runner_client 单源化(G7)清退。
    "execution/merge.py", "execution/recover.py",
    # sessions/coding.py(2026-09-19 M2 立条): 自 arch_routes/sessions.py 迁出的
    # coding 子会话编排(adaptation 摘要中继随行)。
    # (D12 门禁)——链 3 全量收编后本条即门禁正源, 不清退。
    # (agent_roles 适配层 cfg 加载随行; 配置域 REST 不变)。
    "turns/catalog.py",
    # tools/impl/*(2026-09-19 M3 立条): 自 req_agent 按域迁出的工具实现
    # (common/project/semantic_assets/store 惰性导入随行); DispatchTurn 接缝
    # 重构时随 runner_client 单源化清退。
    "tools/impl/kb.py", "tools/impl/map.py", "tools/impl/semantic.py",
    "tools/impl/asset.py", "tools/impl/diagram.py",
    # requirements/harness.py(2026-09-19 M3 立条): clarify/collect LLM 编排
    # (run_tools_loop/semantic_assets/design 随行); M4 迁 CallTurn 后清退。
    "requirements/harness.py",
    # execution/dispatch.py(2026-09-19 M4 立条): 自 exec_bridge 迁出的下发域
    # (store/execution/req_agent 接缝随行, _eb() 调用期绑定); DispatchTurn
    # 接缝重构时随 runner_client 单源化(G7)清退。
    "execution/dispatch.py",
    # governance/flow.py(2026-09-21 立条): 会话流程相位机(states 词表 + IO 收口
    # governance/focus.py(2026-09-22 批戊立条): 焦点栈派生单源(工作记忆显式化)——
    # 与相位机同源同族(states 词表引用随 flow.py 同款先例); flow 降级为
    # 纯配置消费者后, 判别派生单源收敛于此。
    # recompute/recover)——states 单源与 store 访问为相位机本职(recover.py 同款
    # 调用期解析先例); 策略/任务/自愈三方消费的公共事实轴, 清退随 states 上提。
    # (agent.flow.policy 缺省单源+读取)——states 词表引用随 flow.py 同款先例;
    # 行为面数据驱动为本职, 清退随 states 上提。
    "execution/exec_bridge.py",  # MS4-W2(2026-09-24) 适配层本体移入 agent/execution——通道保留至 W3 抽取清退
    "tools/req_agent.py",        # MS4-W2(2026-09-24) 同上, agent/tools/req_agent——W3 清退,
}

# 存量违规冻结——低层引高层。
# cognition→reflection: llm/model_profile 引 reflection 评测产物;
# perception→planning: commands 引任务计划。清退时删除条目。
# →turns(2026-09-19 M3 立条): R3.1 链3收编——入口/计划/探针调用点经 CallTurn
# 统一入口(设计 §4 目标形态: 入口层路由进内核 L2), 属目标架构而非债务。
_R2_INVENTORY = {
    # ── MS4-W2(2026-09-24) 权威重算: req_agent 移入 tools 后按门禁逻辑全量扫描,
    # 12 条为当前真实上行集(合并历史立条); W3 抽取/回调注入后逐条清退(只许缩短) ──
    "requirements/harness.py": {"turns"},  # M4 立条: clarify/collect 经 CallTurn(链3②)
    "cognition/llm.py": {"reflection"},  # 引 reflection 评测产物
    "cognition/model_profile.py": {"reflection", "tools"},
    "cognition/prompt.py": {"tools"},
    "memory/distill.py": {"reflection"},  # 蒸馏经 repair 摘要
    "memory/units.py": {"reflection", "tools"},  # 摘要回路 + W2 tools 就地
    "memory/working.py": {"tools"},
    "perception/commands.py": {"planning", "turns", "compensation", "execution"},
    "planning/req_spec.py": {"reflection", "tools"},  # MS2 显形 + W2 就地
    "planning/scope_probe.py": {"turns", "tools"},  # W2 就地
    "planning/task_plan.py": {"turns", "execution"},
    "tools/req_agent.py": {"requirements", "turns", "reflection"},  # W2 移入本体
}



def _resolve_module(node, pkg: str):
    """ImportFrom → 绝对模块名（解析相对导入 level）。非本项目导入返回 None。"""
    if isinstance(node, ast.ImportFrom) and node.level:
        base = pkg.split(".")
        if node.level >= 2:
            base = base[:-(node.level - 1)]
        return ".".join(base + ([node.module] if node.module else []))
    if isinstance(node, ast.ImportFrom) and node.module \
            and node.module.startswith("topoone_app_architect"):
        return node.module
    return None


def _scan():
    """扫描 agent/** 全部文件 → {relpath: (layer, {dep_layer|'app.<x>'})}。"""
    out = {}
    for root, dirs, files in os.walk(AGENT_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        rel = os.path.relpath(root, AGENT_DIR)
        layer = "." if rel == "." else rel.split(os.sep)[0]
        if layer == ".":
            continue                                   # R3: 根层例外
        pkg = ("topoone_app_architect.agent"
               + ("" if layer == "." else "." + rel.replace(os.sep, ".")))
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            fp = os.path.join(root, f)
            relp = os.path.relpath(fp, AGENT_DIR).replace(os.sep, "/")
            deps = set()
            tree = ast.parse(open(fp, encoding="utf-8").read())
            for node in ast.walk(tree):
                mod = _resolve_module(node, pkg)
                if not mod:
                    continue
                parts = mod.split(".")
                if len(parts) < 2 or parts[0] != "topoone_app_architect":
                    continue
                if parts[1] != "agent":
                    deps.add("app." + parts[1])
                elif len(parts) > 2 and parts[2] in set(ORDER) | CROSSCUT:
                    deps.add(parts[2])
            out[relp] = (layer, deps)
    return out


def test_r1_no_new_kernel_to_routes_deps():
    """R1: agent/** → arch_routes 仅允许冻结清单内文件；新增即失败。"""
    graph = _scan()
    violations = sorted(relp for relp, (_, deps) in graph.items()
                        if "app.arch_routes" in deps and relp not in _R1_INVENTORY)
    assert not violations, (
        "内核反向依赖适配层(arch_routes)——冻结清单外新增:\n  "
        + "\n  ".join(violations)
        + "\n处置: 依赖上提/回调注入拆除; 确属必要须先在 _R1_INVENTORY 立条并注明理由")


def test_r2_no_new_upward_deps():
    """R2: 低层不得引高层（collab/governance 横切豁免）；冻结外新增即失败。"""
    graph = _scan()
    violations = []
    for relp, (layer, deps) in sorted(graph.items()):
        if layer in CROSSCUT:
            continue    # 横切层(governance/collab)可引任意内核层(文档语义)
        upward = {d for d in deps
                  if d in ORDER and RANK[d] > RANK[layer]}
        extra = upward - _R2_INVENTORY.get(relp, set())
        if extra:
            violations.append(f"{relp} ({layer}) -> {sorted(extra)}")
    assert not violations, (
        "层序违规——低层引高层(冻结清单外新增):\n  " + "\n  ".join(violations)
        + "\n处置: 下沉依赖或回调注入; 确属必要须先在 _R2_INVENTORY 立条并注明理由")


def test_inventory_files_still_exist():
    """冻结清单自洽：清单内文件不得消失/更名（清退时同步删条目，防僵尸清单）。"""
    graph = _scan()
    gone_r1 = sorted(_R1_INVENTORY - set(graph))
    gone_r2 = sorted(set(_R2_INVENTORY) - set(graph))
    assert not gone_r1 and not gone_r2, (
        f"冻结清单含已不存在的文件——请同步删除条目: {sorted(set(gone_r1) | set(gone_r2))}")
