"""行数门禁(整体设计 §7-4 / §8.1) — 大文件**软约束**棘轮: 防失控增长, 不强制即时拆分。

基线: goldens/line_baseline.json(2026-09-19, agent/ + arch_routes/ 全部 .py)。
- 存量文件: 允许小幅漂移(容差 +5%, 最低 10 行); 超容差增长提示"宜拆分"并红灯——
  拆分节奏由各阶段(§8.2)把握, 门禁只防失控回弹;
- 新增文件: ≤ 400 行软上限(超限须登记 NEW_FILE_WHITELIST 并附理由)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_file_size_gate.py -q
"""
import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                    "apps/architect/topoone_app_architect")
BASELINE_PATH = os.path.join(os.path.dirname(__file__), "goldens",
                             "line_baseline.json")
SOFT_CAP = 400
REBOUND_RATIO = 1.05     # 存量容差: +5%
REBOUND_MIN_LINES = 10   # 小文件最低容差行数

# 新文件软上限豁免(登记须附理由; 优先拆分而不是登记):
NEW_FILE_WHITELIST: dict = {
    # M1 自 orchestrator 机械搬迁的 chat 执行半边(工具循环/降级/围栏代落);
    # M3 ChatTurn 接缝重构时按 structured 轮/降级通道/落库再拆。
# cv-196: 收尾短路(落卡轮跳过叙述轮)+占位折叠+澄清注入随行
    "agent/turns/chat.py": 620,
    # M4 自 exec_bridge 机械搬迁的下发域(propose/confirm/task_input/停止/恢复
    # 衔接; 接缝 _eb() 调用期绑定占据行数); 2026-09-20 默认保存裁决 +saved/ignored
    # 生命周期与 ignore/改写通道随行; DispatchTurn 接缝重构时再拆。
    # 2026-09-21 流程相位机接线(+safetyClass 三值轴消费/ dismiss 消化出口/
    # 收口点 recompute)——G2 补偿矩阵与安全等级为本域职责, 拆分随 DispatchTurn。
    "agent/execution/dispatch.py": 780,
}

with open(BASELINE_PATH, encoding="utf-8") as f:
    BASELINE: dict = json.load(f)


def _py_lines():
    out = {}
    for sub in ("agent", "arch_routes"):
        root = os.path.join(ROOT, sub)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
                with open(full, encoding="utf-8") as f:
                    out[rel] = sum(1 for _ in f)
    return out


def test_existing_files_no_runaway_growth():
    """存量软棘轮: 小幅漂移放行(+5%/≥10 行), 失控增长提示拆分。"""
    current = _py_lines()
    rebound = {}
    for rel in BASELINE:
        if rel not in current:
            continue
        base, cur = BASELINE[rel], current[rel]
        allowance = max(REBOUND_MIN_LINES, int(base * (REBOUND_RATIO - 1)))
        if cur > base + allowance:
            rebound[rel] = (base, cur, f"+{cur - base}(容差 +{allowance})")
    assert not rebound, f"文件行数失控增长(宜按 §8.2 拆分, 勿继续增长): {rebound}"


def test_removed_files_prune_baseline():
    """文件删除(如溶解的兼容门面)后须同步收缩基线。"""
    current = _py_lines()
    stale = [rel for rel in BASELINE if rel not in current]
    assert not stale, f"基线含已删除文件(请更新 goldens/line_baseline.json): {stale}"


def test_new_files_within_soft_cap():
    """新增文件 ≤400 行软上限(拆分产物按单一职责切分)。"""
    current = _py_lines()
    oversized = {}
    for rel, n in current.items():
        if rel in BASELINE:
            continue
        cap = NEW_FILE_WHITELIST.get(rel, SOFT_CAP)
        if n > cap:
            oversized[rel] = (n, cap)
    assert not oversized, f"新文件超行数上限(拆分或登记豁免): {oversized}"
