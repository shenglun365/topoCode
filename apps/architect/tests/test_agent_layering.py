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
ORDER = ["perception", "cognition", "planning", "memory", "tools",
         "execution", "reflection"]
RANK = {name: i for i, name in enumerate(ORDER)}
CROSSCUT = {"collab", "governance"}

# 存量违规冻结（2026-09-17 快照）——内核反向依赖适配层(arch_routes)。
# 多为 store/req_agent 历史接缝; 清退时删除条目, 禁止新增。
_R1_INVENTORY = {
    "cognition/llm.py", "cognition/model_profile.py", "cognition/prompt.py",
    "cognition/roles.py", "reflection/dataset.py", "reflection/evaluator.py",
    "reflection/mining.py", "reflection/repair.py", "planning/req_spec.py",
    "planning/scope_probe.py", "planning/task_plan.py", "perception/commands.py",
    "collab/cards.py", "memory/dossier.py", "memory/store.py",
    "memory/units.py", "memory/working.py", "governance/boundary.py",
    # memory/distill.py(2026-09-17 P1 立条): 错误提炼编排层, 与 memory/units.py
    # 同款依赖(store/adaptation/agent_roles 惰性导入)——读错误材料 + 轻任务
    # 提炼 + 落 error_pattern 单元; 依赖注入拆解与 units 清退同批处置。
    "memory/distill.py",
}

# 存量违规冻结——低层引高层。
# cognition→reflection: llm/model_profile 引 reflection 评测产物;
# perception→planning: commands 引任务计划。清退时删除条目。
_R2_INVENTORY = {
    "cognition/llm.py": {"reflection"},
    "cognition/model_profile.py": {"reflection"},
    "perception/commands.py": {"planning"},
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
