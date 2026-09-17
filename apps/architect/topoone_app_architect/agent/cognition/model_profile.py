"""模型能力档案 (Model Capability Profile) — 分级适配架构的数据基座。

tier 分层(参数规模启发式为上限, 探测分数只降不升——小模型探测好也保留兜底):
  t0=27B+   t1=12-27B   t2=6-12B   t3=3-6B   t4=1-3B

档案来源优先级: 探测(probed) > 手工(manual) > 启发式(heuristic, 按名称猜参)。
存储: arch_collab_config 键 `llm.modelProfiles` (JSON: {modelId: profile})。

探测套件(~9 次小调用, max_tokens 250-400, 失败快速短路):
  P1 工具协议×3: [TOOL_CALL] 块产出率(协议遵循)
  P2 JSON 围栏×3: ```json 围栏可解析率(结构化输出)
  P3 指令边界×3: 职责边界内不拒做(指令遵循)
  P5 稳定性: 由 P1/P2 三次采样方差推导, 不单独调用
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
    from ...arch_routes import store
    return store


_PROFILES_KEY = "llm.modelProfiles"
_MANUAL_TAG = "manual"          # 手工设置 tier, 探测不覆盖
_PROBED_TAG = "probed"
_HEURISTIC_TAG = "heuristic"

# 已在本进程发起过懒探测的模型(防重复; 探测失败也会标记, 避免每轮重试)
_lazy_tried: set = set()
_lazy_lock = threading.Lock()

TIERS = {
    0: "T0 强(≥12B 全能力, 关闭多余兜底)",
    1: "T1 中(6-12B 标准兜底)",
    2: "T2 弱(<6B 全面补偿: 结构化指令+核心逻辑图+有界轮次)",
}


# ── 启发式分层(名称猜参) ───────────────────────────────────────────────

_B_PARAM_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*b(?![a-z0-9])", re.IGNORECASE)


def guess_params_b(model_name: str) -> Optional[float]:
    """模型名 → 参数规模(billion)。如 qwen3-8b→8.0, Qwen2.5-72B→72.0, 0.5b→0.5。"""
    for m in _B_PARAM_RE.finditer(model_name or ""):
        try:
            return float(m.group(1))
        except ValueError:  # pragma: no cover
            continue
    return None


def heuristic_tier(model_name: str) -> int:
    """名称启发式 tier(档案缺省/兜底路径)。无法判断 → 1(保守标准档)。

    刻度 2026-09-17 收敛 T0-T2: ≥12B 强(0) / 6-12B 中(1) / <6B 弱(2)。
    """
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
    """取档案(无则现场启发式, 不落库)。返回含 tier/caps/source/updatedAt。"""
    model_id = model_id or ""
    prof = _load_all().get(model_id)
    if isinstance(prof, dict) and isinstance(prof.get("tier"), int):
        return prof
    name = _model_name_of(model_id)
    return {"modelId": model_id, "modelName": name,
            "tier": heuristic_tier(name), "source": _HEURISTIC_TAG,
            "caps": {}, "probes": [], "updatedAt": 0}


def tier_of(model_id: str) -> int:
    try:
        return int(get_profile(model_id).get("tier") or 1)
    except Exception:  # noqa: BLE001
        return 1


def set_manual_tier(model_id: str, tier: int) -> Dict[str, Any]:
    """手工设置 tier(manual 优先级最高, 探测不覆盖)。"""
    tier = max(0, min(4, int(tier)))
    data = _load_all()
    prof = data.get(model_id) or {}
    prof.update({"modelId": model_id, "modelName": prof.get("modelName") or _model_name_of(model_id),
                 "tier": tier, "source": _MANUAL_TAG, "updatedAt": int(time.time() * 1000)})
    data[model_id] = prof
    _save_all(data)
    return prof


def all_profiles() -> Dict[str, Dict[str, Any]]:
    return _load_all()


# ── 探测套件 ──────────────────────────────────────────────────────────

def _probe_tools() -> List[Dict[str, str]]:
    """探针工具用例取真实注册工具(裁决: 测系统实际能力, 不用玩具用例)。

    从 B4 单源迁移表取 name+参数形状; 目录异常时退化为 req.propose 最小形状。
    """
    try:
        from ..cognition import prompt as _prompt
        docs = _prompt.TOOL_PARAM_DOCS
        names = [n for n in ("req.propose", "kb.asset.search", "map.overview")
                 if n in docs]
        return [{"name": n, "params_hint": docs[n]} for n in names]
    except Exception:  # noqa: BLE001
        return [{"name": "req.propose", "params_hint":
                 '{"title", "requirementMd", "designMd"}'}]


def _extract_calls(raw: str):
    from ...arch_routes import req_agent as _req_agent_mod
    return _req_agent_mod.extract_tool_calls(raw)


def _build_cases() -> Dict[str, List[Dict[str, Any]]]:
    """探测用例装配(判分函数注入——cognition 不引 tools 层)。"""
    from . import probe_suite as _ps
    return {
        "tool": _ps.build_tool_cases(_probe_tools(), _extract_calls),
        "json": _ps.build_json_cases(),
        "instr": _ps.build_instruction_cases(),
    }


def _probe_call(system: str, user: str, max_tokens: int, model_id: str) -> Optional[str]:
    from ...arch_routes import req_agent as _req_agent_mod
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
    tool_samples: List[str] = []
    tool_scores: List[float] = []
    for case in cases["tool"]:
        raw = _probe_call(case["system"], case["user"],
                          int(case.get("max_tokens") or 250), model_id)
        if raw is None:
            return {"modelId": model_id, "reachable": False,
                    "summary": "模型不可达(连通性失败), 未执行能力探测"}
        tool_samples.append(raw)
        tool_scores.append(_ps.grade_case(case, raw))
    json_scores: List[float] = []
    for case in cases["json"]:
        raw = _probe_call(case["system"], case["user"],
                          int(case.get("max_tokens") or 400), model_id)
        if raw is None:
            return {"modelId": model_id, "reachable": False,
                    "summary": "模型不可达(连通性失败), 未执行能力探测"}
        json_scores.append(_ps.grade_case(case, raw))
    instr_scores: List[float] = []
    for case in cases["instr"]:
        raw = _probe_call(case["system"], case["user"],
                          int(case.get("max_tokens") or 300), model_id)
        if raw is None:
            return {"modelId": model_id, "reachable": False,
                    "summary": "模型不可达(连通性失败), 未执行能力探测"}
        instr_scores.append(_ps.grade_case(case, raw))

    tool_rate = sum(tool_scores) / len(tool_scores)
    json_rate = sum(json_scores) / len(json_scores)
    instr_score = min(instr_scores)
    stability = min(_ps.stability(tool_samples), 0.2 + tool_rate)  # 方差受遵循率制约

    score = (_ps.WEIGHTS["tool"] * tool_rate + _ps.WEIGHTS["json"] * json_rate
             + _ps.WEIGHTS["instr"] * instr_score)
    base = heuristic_tier(_model_name_of(model_id))
    tier = _ps.tier_from_score(score, base)

    caps = {"toolCallRate": round(tool_rate, 2), "jsonRate": round(json_rate, 2),
            "instructionScore": round(instr_score, 2), "stability": round(stability, 2),
            "probeScore": round(score, 2)}
    prof = {"modelId": model_id, "modelName": _model_name_of(model_id),
            "tier": tier, "source": _PROBED_TAG, "caps": caps,
            "structured": _ps.structured_from(json_rate),
            "admission": _ps.admission(tier),
            "summary": (f"探测完成: 工具协议 {tool_rate:.0%} / JSON {json_rate:.0%} / "
                        f"指令 {instr_score:.0%} → tier {tier}({TIERS[tier]})"),
            "probes": [], "updatedAt": int(time.time() * 1000)}
    data = _load_all()
    old = data.get(model_id) or {}
    if old.get("source") == _MANUAL_TAG:
        prof["tier"] = int(old.get("tier") or tier)   # 手工 tier 不被探测覆盖
        prof["source"] = _MANUAL_TAG
        prof["summary"] += "(tier 为手工设定, 探测分数仅供参考)"
    history = (old.get("probes") if isinstance(old.get("probes"), list) else [])[-2:]
    history.append({"ts": prof["updatedAt"], "caps": caps, "tier": prof["tier"]})
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
