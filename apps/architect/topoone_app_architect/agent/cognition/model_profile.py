"""模型能力档案 (Model Capability Profile) — 分级适配架构的数据基座。

tier 判档纯用例结果(2026-09-18 裁决, 参数规模彻底退出):
  综合 ≥0.90 → T0 强 / ≥0.52 → T1 中 / 其余 → T2 弱(全面补偿+补偿复核定准入)。
  存量旧刻度(T0-T4)读路径归一 T0-T2; 未探测缺省中性 T1。

档案来源优先级: 探测(probed) > 手工(manual) > 缺省 T1(heuristic 标记=未探测)。
存储: arch_collab_config 键 `llm.modelProfiles` (JSON: {modelId: profile})。

探测套件(~16 次小调用, T2 追加补偿复核×2, 失败快速短路):
  输出预算按胜任容量分层(2026-09-18): 1~5B→4K / 6~15B→8K / 15B+→16K / 未知→8K
  ——思考型模型 reasoning 占输出容量, 预算给足防「无法输出」误判;
  仅影响测试预算, 不影响评分与判档(判档纯用例结果)。
  P1 工具协议×3: [TOOL_CALL] 块产出率(协议遵循; 问法三态轮转)
  P2 JSON 围栏×4: ```json 围栏可解析率(结构化输出; 跨领域池+长规约截断压测;
     围栏未闭合=max_tokens 截断 → 0.5 部分分, 不冤枉能干的慢模型)
  P3 指令边界×3: 受理并实际交付规约产物(以执行结果为据, 空壳受理 0.5 分)
  P4 设计三维各×2: 需求分析(模糊澄清+定界)/架构设计(分解+依赖+选型)/
     模块设计(契约+边界+步骤)——产物验收, 轻权重参与判档(2026-09-18)
  P5 稳定性: 由 P1 三次采样方差推导, 不单独调用
逐用例原始输出留痕: probes[].samples(各 160 字) + 服务端 INFO 日志,
档案可回溯「为什么 0 分」(nex-n2.5-mini 截断误判的生产回归教训)。
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional


logger = logging.getLogger("arch.model_profile")

def _store():
    from ... import store
    return store


_PROFILES_KEY = "llm.modelProfiles"
_MANUAL_TAG = "manual"          # 手工设置 tier, 探测不覆盖
_PROBED_TAG = "probed"
_HEURISTIC_TAG = "heuristic"

# 已在本进程发起过懒探测的模型(防重复; 探测失败也会标记, 避免每轮重试)
_lazy_tried: set = set()
_lazy_lock = threading.Lock()


# ── 探测并发治理: 互斥(全局串行) + FIFO 排队 + 同模型滤重 ──────────────
# 套件 ~10 次小调用、耗时数十秒: 并发探测会争抢模型服务吞吐且档案互踩,
# 故全局同一时刻仅一个套件在跑; 其余模型 FIFO 排队等待轮转;
# 已在跑/已在队的模型再次请求 → 立即回执 dedup(不重复入队)。

class _ProbeGate:
    def __init__(self) -> None:
        from collections import deque
        self._cond = threading.Condition()
        self._queue: deque = deque()   # FIFO 等待序
        self._in: set = set()          # 在跑 ∪ 在队(滤重依据)
        self._running = ""

    def enter(self, model_id: str) -> str:
        """登记: 阻塞至轮到执行返回 'run'; 同模型已在跑/在队 → 立即返回 'dup'。"""
        with self._cond:
            if model_id in self._in:
                return "dup"
            self._queue.append(model_id)
            self._in.add(model_id)
            # 互斥条件: 无在跑(runner 出队后仍持运行位) 且 轮到本模型队头
            while self._running or self._queue[0] != model_id:
                self._cond.wait()
            self._queue.popleft()
            self._running = model_id
            return "run"

    def leave(self, model_id: str) -> None:
        with self._cond:
            if self._running == model_id:
                self._running = ""
            self._in.discard(model_id)
            self._cond.notify_all()

    def status(self) -> Dict[str, Any]:
        """闸门自省(自省接口/前端状态条): 谁在跑、FIFO 队列还有谁。"""
        with self._cond:
            return {"running": self._running, "queue": list(self._queue)}


_probe_gate = _ProbeGate()


def probe_model_gated(model_id: str) -> Dict[str, Any]:
    """探测统一入口(互斥+排队+滤重)。返回 {status: run|dup, profile}。

    dup: 同模型重复点击 → 不重复探测, 立即回执当前档案 + dedup 标记。
    异模型: FIFO 排队, 前一探测完成后串行执行(HTTP 请求在 to_thread 内等待)。
    """
    st = _probe_gate.enter(model_id)
    if st == "dup":
        prof = dict(get_profile(model_id))
        prof["dedup"] = True
        prof["summary"] = ("该模型探测已在进行中(执行/排队), 本次请求已滤重"
                           "——请等待完成后刷新查看档案")
        return {"status": "dup", "profile": prof}
    try:
        return {"status": "run", "profile": probe_model(model_id)}
    finally:
        _probe_gate.leave(model_id)

TIERS = {
    0: "T0 强(≥12B: 胜任主 agent 全职能——问询纪律/规约/路由/编排)",
    1: "T1 中(6-12B: 规约与路由可胜任, 边缘职能走补偿)",
    2: "T2 弱(<6B: 严格受控问询+全面补偿, 编码类任务必须外派执行器)",
}


# ── 启发式分层(已退役, 兼容保留; 参数解析现仅用于胜任容量分层) ─────────


def guess_params_b(model_name: str) -> Optional[float]:
    """[委托 probe_suite] 模型名 → 参数规模(兼容导出; 现仅用于胜任容量分层)。"""
    from .probe_suite import guess_params_b as _g
    return _g(model_name)


def heuristic_tier(model_name: str) -> int:
    """[已退役] 名称启发式 tier——2026-09-18 裁决: 判档纯用例结果, 参数规模
    不参与任何档位判断。函数仅为兼容保留(测试/外部引用), 探测与缺省路径
    均不再调用。"""
    b = guess_params_b(model_name)
    if b is None:
        return 1
    if b >= 12:
        return 0
    if b >= 6:
        return 1
    return 2


# ── 档案存取 ──────────────────────────────────────────────────────────

def _load_all() -> Dict[str, Dict[str, Any]]:
    try:
        raw = _store().CollabConfigStore.get(_PROFILES_KEY, "")
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_all(data: Dict[str, Dict[str, Any]]) -> None:
    _store().CollabConfigStore.set(_PROFILES_KEY, json.dumps(data, ensure_ascii=False))


def _model_name_of(model_id: str) -> str:
    """档案缺省时从模型目录取名称(启发式输入); 取不到用 id 本身。"""
    try:
        raw = _store().CollabConfigStore.get("llm.models", "")
        rows = json.loads(raw) if raw else []
        for r in rows or []:
            if isinstance(r, dict) and r.get("id") == model_id:
                return str(r.get("model") or r.get("name") or model_id)
    except Exception:  # noqa: BLE001
        pass
    return model_id


def get_profile(model_id: str) -> Dict[str, Any]:
    """取档案(无则未探测缺省, 不落库)。返回含 tier/caps/source/updatedAt。

    判档纯用例结果(2026-09-18 裁决): 探测档只由综合分决定; 未探测模型
    缺省中性 T1(不按名称猜参——参数规模不参与任何档位判断),
    source=_HEURISTIC_TAG 仅作「未探测」标记(供懒探测触发)。"""
    model_id = model_id or ""
    prof = _load_all().get(model_id)
    # 有效档案 = 含 tier(综合档) 或 asset(资产解析独立档, 2026-10-03 共表独立字段)
    if isinstance(prof, dict) and (isinstance(prof.get("tier"), int) or prof.get("asset")):
        prof = dict(prof)
        if isinstance(prof.get("tier"), int):
            # 存量归一: 旧 T0-T4 五档刻度的 3/4 → 2(现行刻度 T0-T2)
            prof["tier"] = max(0, min(2, int(prof["tier"])))
        return prof
    return {"modelId": model_id, "modelName": _model_name_of(model_id),
            "tier": 1, "source": _HEURISTIC_TAG,
            "caps": {}, "probes": [], "updatedAt": 0}


def tier_of(model_id: str) -> int:
    try:
        raw = get_profile(model_id).get("tier")
        # 注意 falsy-zero: T0=0 不能走 `or 1`(会把 T0 吞成 T1)
        return int(raw) if isinstance(raw, (int, float)) else 1
    except Exception:  # noqa: BLE001
        return 1


def set_manual_tier(model_id: str, tier: int) -> Dict[str, Any]:
    """手工设置 tier(manual 优先级最高, 探测不覆盖)。现行刻度 T0-T2。"""
    tier = max(0, min(2, int(tier)))
    data = _load_all()
    prof = data.get(model_id) or {}
    prof.update({"modelId": model_id, "modelName": prof.get("modelName") or _model_name_of(model_id),
                 "tier": tier, "source": _MANUAL_TAG, "updatedAt": int(time.time() * 1000)})
    data[model_id] = prof
    _save_all(data)
    return prof


def all_profiles() -> Dict[str, Dict[str, Any]]:
    return _load_all()


def clear_profiles() -> int:
    """清空全部探测档案(旧套件/旧刻度残留清理——避免与新探测结果互相干扰)。

    返回清除的模型数; 清空后各模型回到未探测缺省(中性 T1), 重探即生成新档案。"""
    data = _load_all()
    if not data:
        return 0
    _save_all({})
    return len(data)


def clear_profile(model_id: str) -> bool:
    """清空单个模型档案(重探前复位)。返回是否确有档案被清。"""
    data = _load_all()
    if model_id in data:
        del data[model_id]
        _save_all(data)
        return True
    return False


# ── 探测套件 ──────────────────────────────────────────────────────────

def _probe_tools() -> List[Dict[str, str]]:
    """探针工具用例取真实注册工具(裁决: 测系统实际能力, 不用玩具用例)。

    MS-B3: 迁移表退役后直读注册表条目(params_doc 注册点声明 → 签名生成兜底);
    目录异常时退化为 req.propose 最小形状。
    """
    try:
        from ..tools.registry import _ARCH_TOOLS, derive_params_doc
        names = [n for n in ("req.propose", "kb.asset.search", "map.overview")
                 if n in _ARCH_TOOLS]
        out = []
        for n in names:
            entry = _ARCH_TOOLS[n]
            hint = (entry.get("params_doc") or "").strip() \
                or derive_params_doc(entry["handler"])
            out.append({"name": n, "params_hint": hint})
        return out
    except Exception:  # noqa: BLE001
        return [{"name": "req.propose", "params_hint":
                 '{"title", "requirementMd", "designMd"}'}]


def _extract_calls(raw: str):
    from ...agent.tools import req_agent as _req_agent_mod
    return _req_agent_mod.extract_tool_calls(raw)


def _build_cases() -> Dict[str, List[Dict[str, Any]]]:
    """探测用例装配(判分函数注入——cognition 不引 tools 层)。"""
    from . import probe_suite as _ps
    return {
        "tool": _ps.build_tool_cases(_probe_tools(), _extract_calls),
        "json": _ps.build_json_cases(),
        "instr": _ps.build_instruction_cases(),
        "requirement": _ps.build_requirement_cases(),
        "architecture": _ps.build_architecture_cases(),
        "module": _ps.build_module_design_cases(),
        # 主 agent 职能域(定位裁决 2026-09-26): 问询纪律 + 路由决策
        "inquiry": _ps.build_inquiry_cases(),
        "routing": _ps.build_routing_cases(),
    }


def _probe_call(system: str, user: str, max_tokens: int, model_id: str) -> Optional[str]:
    from ...agent.tools import req_agent as _req_agent_mod
    try:
        res = _req_agent_mod.llm_sync([{"role": "system", "content": system},
                                       {"role": "user", "content": user}],
                                      mode="chat", model_id=model_id or None, max_tokens=max_tokens)
        return (res or {}).get("content") or ""
    except Exception as e:  # noqa: BLE001
        logger.warning("[model-probe] 调用失败 model=%s: %s", model_id, e)
        return None


def _stability(samples: List[str]) -> float:
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


def probe_model(model_id: str) -> Dict[str, Any]:
    """同步执行探测套件并落档。模型不可达 → reachable=False(不写 tier, 保留原档案)。

    返回完整档案(调用方直接展示/使用)。
    """
    model_id = model_id or ""
    from . import probe_suite as _ps
    cases = _build_cases()
    # 胜任容量分层(2026-09-18): 输出预算按参数规模 4K/8K/16K——思考型模型
    # reasoning 占输出容量, 预算给足防「无法输出」误判; 仅影响预算不影响评分
    budget = _ps.output_budget(_model_name_of(model_id))
    # 逐用例原始输出留痕(截断 160 字)——档案 probes 历史可回溯「为什么 0 分」
    samples: Dict[str, List[str]] = {}

    def _run(dim: str, case: Dict[str, Any]) -> Optional[str]:
        raw = _probe_call(case["system"], case["user"], budget, model_id)
        sample = (raw or "")[:160]
        samples.setdefault(dim, []).append(sample)
        if raw is not None:
            logger.info("[model-probe] %s case=%s budget=%d raw=%.140s",
                        model_id, case.get("id"), budget, raw)
        return raw

    tool_samples: List[str] = []
    tool_scores: List[float] = []
    for case in cases["tool"]:
        raw = _run("tool", case)
        if raw is None:
            return {"modelId": model_id, "reachable": False,
                    "summary": "模型不可达(连通性失败), 未执行能力探测"}
        tool_samples.append(raw)
        tool_scores.append(_ps.grade_case(case, raw))
    json_scores: List[float] = []
    for case in cases["json"]:
        raw = _run("json", case)
        if raw is None:
            return {"modelId": model_id, "reachable": False,
                    "summary": "模型不可达(连通性失败), 未执行能力探测"}
        json_scores.append(_ps.grade_case(case, raw))
    instr_scores: List[float] = []
    for case in cases["instr"]:
        raw = _run("instr", case)
        if raw is None:
            return {"modelId": model_id, "reachable": False,
                    "summary": "模型不可达(连通性失败), 未执行能力探测"}
        instr_scores.append(_ps.grade_case(case, raw))
    req_scores: List[float] = []
    for case in cases["requirement"]:
        raw = _run("requirement", case)
        if raw is None:
            return {"modelId": model_id, "reachable": False,
                    "summary": "模型不可达(连通性失败), 未执行能力探测"}
        req_scores.append(_ps.grade_case(case, raw))
    arch_scores: List[float] = []
    for case in cases["architecture"]:
        raw = _run("architecture", case)
        if raw is None:
            return {"modelId": model_id, "reachable": False,
                    "summary": "模型不可达(连通性失败), 未执行能力探测"}
        arch_scores.append(_ps.grade_case(case, raw))
    mod_scores: List[float] = []
    for case in cases["module"]:
        raw = _run("module", case)
        if raw is None:
            return {"modelId": model_id, "reachable": False,
                    "summary": "模型不可达(连通性失败), 未执行能力探测"}
        mod_scores.append(_ps.grade_case(case, raw))
    inquiry_scores: List[float] = []
    for case in cases["inquiry"]:
        raw = _run("inquiry", case)
        if raw is None:
            return {"modelId": model_id, "reachable": False,
                    "summary": "模型不可达(连通性失败), 未执行能力探测"}
        inquiry_scores.append(_ps.grade_case(case, raw))
    routing_scores: List[float] = []
    for case in cases["routing"]:
        raw = _run("routing", case)
        if raw is None:
            return {"modelId": model_id, "reachable": False,
                    "summary": "模型不可达(连通性失败), 未执行能力探测"}
        routing_scores.append(_ps.grade_case(case, raw))

    tool_rate = sum(tool_scores) / len(tool_scores)
    json_rate = sum(json_scores) / len(json_scores)
    instr_score = min(instr_scores)
    req_rate = sum(req_scores) / len(req_scores)
    arch_rate = sum(arch_scores) / len(arch_scores)
    mod_rate = sum(mod_scores) / len(mod_scores)
    inquiry_rate = sum(inquiry_scores) / len(inquiry_scores)
    routing_rate = sum(routing_scores) / len(routing_scores)
    stability = min(_ps.stability(tool_samples), 0.2 + tool_rate)  # 方差受遵循率制约

    score = (_ps.WEIGHTS["tool"] * tool_rate + _ps.WEIGHTS["json"] * json_rate
             + _ps.WEIGHTS["instr"] * instr_score
             + _ps.WEIGHTS["requirement"] * req_rate
             + _ps.WEIGHTS["architecture"] * arch_rate
             + _ps.WEIGHTS["module"] * mod_rate
             + _ps.WEIGHTS["inquiry"] * inquiry_rate
             + _ps.WEIGHTS["routing"] * routing_rate)
    tier = _ps.tier_from_score(score)

    # T2 补偿复核: 用生产同款补偿形态用例实测「补偿能否修正」(裁决: 不只声明)
    compensation_rate: Optional[float] = None
    if tier >= 2:
        comp_scores: List[float] = []
        for case in _ps.build_compensation_cases():
            raw = _probe_call(case["system"], case["user"], budget, model_id)
            if raw is None:          # 复核中不可达 → 视为未通过
                comp_scores = []
                break
            comp_scores.append(_ps.grade_case(case, raw))
        if comp_scores:
            compensation_rate = sum(comp_scores) / len(comp_scores)
    adm = _ps.admission(tier, compensation_rate)

    caps = {"toolCallRate": round(tool_rate, 2), "jsonRate": round(json_rate, 2),
            "instructionScore": round(instr_score, 2), "stability": round(stability, 2),
            "probeScore": round(score, 2),
            "requirementScore": round(req_rate, 2),
            "archScore": round(arch_rate, 2),
            "moduleScore": round(mod_rate, 2),
            "inquiryScore": round(inquiry_rate, 2),
            "routingScore": round(routing_rate, 2)}
    if compensation_rate is not None:
        caps["compensationRate"] = round(compensation_rate, 2)
    summary = (f"探测完成: 工具 {tool_rate:.0%} / JSON {json_rate:.0%} / "
               f"指令 {instr_score:.0%} / 需求 {req_rate:.0%} / "
               f"架构 {arch_rate:.0%} / 模块 {mod_rate:.0%} / "
               f"问询 {inquiry_rate:.0%} / 路由 {routing_rate:.0%}"
               f" → tier {tier}({TIERS[tier]})")
    if compensation_rate is not None:
        summary += (f" → 补偿复核 {'通过' if compensation_rate >= 0.5 else '未通过'}"
                    f"({compensation_rate:.0%})")
    prof = {"modelId": model_id, "modelName": _model_name_of(model_id),
            "tier": tier, "source": _PROBED_TAG, "caps": caps,
            "structured": _ps.structured_from(json_rate),
            "admission": adm,
            "summary": summary,
            "probes": [], "updatedAt": int(time.time() * 1000)}
    data = _load_all()
    old = data.get(model_id) or {}
    if old.get("source") == _MANUAL_TAG:
        prof["tier"] = int(old.get("tier") or tier)   # 手工 tier 不被探测覆盖
        prof["source"] = _MANUAL_TAG
        prof["summary"] += "(tier 为手工设定, 探测分数仅供参考)"
    history = (old.get("probes") if isinstance(old.get("probes"), list) else [])[-2:]
    history.append({"ts": prof["updatedAt"], "caps": caps, "tier": prof["tier"],
                    "samples": samples})
    prof["probes"] = history
    data[model_id] = prof
    _save_all(data)
    try:
        from ..reflection import dataset as llm_dataset
        llm_dataset.record("model_probe", model=model_id, ok=True,
                           **{f"cap_{k}": v for k, v in caps.items()}, tier=prof["tier"])
    except Exception:  # noqa: BLE001
        pass
    return prof


def get_profile_or_lazy(model_id: str) -> Dict[str, Any]:
    """WS 首轮用: 有档案直接返回; 无档案 → 返回启发式并后台探测一次(不阻塞)。

    测试环境(PYTEST_CURRENT_TEST)不起后台线程——探测线程会并发消耗
    测试 monkeypatch 的 llm_sync, 造成跨测试干扰。
    """
    prof = get_profile(model_id)
    if prof.get("source") != _HEURISTIC_TAG:
        return prof
    import os as _os
    if _os.environ.get("PYTEST_CURRENT_TEST"):
        return prof
    mid = model_id or ""
    with _lazy_lock:
        if mid in _lazy_tried:
            return prof
        _lazy_tried.add(mid)

    def _bg():
        try:
            probe_model(mid)
        except Exception as e:  # noqa: BLE001
            logger.warning("[model-probe] 懒探测失败 %s: %s", mid, e)

    threading.Thread(target=_bg, daemon=True, name=f"probe-{mid}").start()
    return prof
