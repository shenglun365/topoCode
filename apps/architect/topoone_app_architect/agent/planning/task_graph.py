"""taskPlan 依赖图(A2 最小 DAG, 纯函数层)。

采借 dsh task-graph 机制(数据结构与校验), 自主权不采——出入口仍是 architect
+ 用户确认。节点 = taskPlan 项 {seq, title, instruction, taskId, status,
depends: [seq]}; CAS/多 agent 认领不做(单编排者+人在环, 无并发冲突面)。

语义:
- depends 值为 1 基 seq; 缺省 [] = 无前置(与旧顺序计划兼容)。
- 就绪 = status==pending 且依赖全 done(failed/waiting_input 均不解锁后继——
  fail-fast: 失败步骤阻塞后继等人工, 不自动跳过)。
- 校验(建图/改图确定性执行, 不信任任何模型产出): 自依赖/悬空引用/重复边/
  环; 校验失败 → 调用方降级线性链并明示。
"""
from __future__ import annotations

from typing import Any, Dict, List


def normalize_plan(plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """补齐 depends 字段(缺省 []; 非法值清洗为合法 seq 列表)。"""
    seqs = {s.get("seq") for s in plan or []}
    out = []
    for s in plan or []:
        deps = s.get("depends")
        clean: List[int] = []
        if isinstance(deps, list):
            for d in deps:
                try:
                    di = int(d)
                except (TypeError, ValueError):
                    continue
                if di in seqs:
                    clean.append(di)
        s = dict(s)
        s["depends"] = sorted(set(clean))
        out.append(s)
    return out


def linear_depends(plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """线性链: seq>1 → depends=[前一 seq](弱挡/校验降级的兜底形态)。"""
    out = normalize_plan(plan)
    prev = None
    for s in out:
        s["depends"] = [] if prev is None else [prev]
        prev = s.get("seq")
    return out


def validate_graph(plan: List[Dict[str, Any]]) -> Dict[str, Any]:
    """确定性校验(不信任模型产出): 自依赖/悬空/重复/环。验原始图(悬空边不被清洗)。"""
    errors: List[str] = []
    raw = plan or []
    seen: set = set()
    seqs = {s.get("seq") for s in raw}
    by_seq: Dict[int, Dict[str, Any]] = {}
    for s in raw:
        seq = s.get("seq")
        if seq in seen:
            errors.append(f"重复 seq: {seq}")
        seen.add(seq)
        by_seq[seq] = s
        deps = s.get("depends") or []
        if seq in deps:
            errors.append(f"自依赖: 步骤 {seq}")
        if len(deps) != len(set(deps)):
            errors.append(f"重复依赖边: 步骤 {seq}")
        for d in deps:
            if d not in seqs:
                errors.append(f"悬空依赖: 步骤 {seq} → {d}")
    # 环检测(DFS, 仅在 seq 无重复时可靠)
    if not any(e.startswith("重复 seq") for e in errors):
        state: Dict[int, int] = {}

        def dfs(seq: int, stack: List[int]) -> None:
            if state.get(seq) == 1:
                errors.append(f"依赖环: {'→'.join(map(str, stack + [seq]))}")
                return
            if state.get(seq) == 2:
                return
            state[seq] = 1
            for d in (by_seq.get(seq, {}).get("depends") or []):
                if d in by_seq:
                    dfs(d, stack + [seq])
            state[seq] = 2

        for s in raw:
            if s.get("seq") not in state:
                dfs(s.get("seq"), [])
    return {"ok": not errors, "errors": errors}


def _deps_satisfied(s: Dict[str, Any], by_seq: Dict[int, Dict[str, Any]]) -> bool:
    for d in s.get("depends") or []:
        row = by_seq.get(d)
        if not row or row.get("status") != "done":
            return False
    return True


def ready_indices(plan: List[Dict[str, Any]]) -> List[int]:
    """就绪步骤下标(0 基): pending 且依赖全 done。"""
    norm = normalize_plan(plan)
    by_seq = {s.get("seq"): s for s in norm}
    return [i for i, s in enumerate(norm)
            if s.get("status") == "pending" and _deps_satisfied(s, by_seq)]


def blocked_summary(plan: List[Dict[str, Any]]) -> str:
    """阻塞概览(计划卡/回执文案): pending 但依赖未满足的步骤。"""
    norm = normalize_plan(plan)
    by_seq = {s.get("seq"): s for s in norm}
    blocked = [s.get("seq") for i, s in enumerate(norm)
               if s.get("status") == "pending" and not _deps_satisfied(s, by_seq)]
    failed = [s.get("seq") for s in norm if s.get("status") == "failed"]
    parts = []
    if failed:
        parts.append(f"失败步骤: {', '.join('#' + str(x) for x in failed)}")
    if blocked:
        parts.append(f"阻塞步骤: {', '.join('#' + str(x) for x in blocked)}")
    return "；".join(parts)
