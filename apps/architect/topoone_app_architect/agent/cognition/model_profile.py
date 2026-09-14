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
    0: "27B+ (全能力, 关闭多余兜底)",
    1: "12-27B (标准适配)",
    2: "6-12B (标准兜底: 草稿卡收敛/意图追问/高宽容解析)",
    3: "3-6B (加强兜底: 输出后处理)",
    4: "1-3B (极简提示/单轮单任务聚焦/max 宽容解析)",
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
    """名称启发式 tier(档案缺省/兜底路径)。无法判断 → 1(保守标准档)。"""
    b = guess_params_b(model_name)
    if b is None:
        return 1
    if b >= 27:
        return 0
    if b >= 12:
        return 1
    if b >= 6:
        return 2
    if b >= 3:
        return 3
    return 4


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

_TOOL_SYSTEM = (
    "你是工具调用代理。可用工具: req.propose(参数: title, requirementMd, designMd), "
    "kb.asset.search(参数: text)。\n"
    "需要执行动作时, 只输出一个工具调用块, 格式:\n"
    '[TOOL_CALL]{"tool":"<工具名>","arguments":{参数}}[/TOOL_CALL]\n'
    "输出工具调用块后不要再写其它内容。"
)

_TOOL_CASES = [
    ("req.propose", "请创建需求提案: 标题=用户登录, 目标=实现手机号验证码登录, 方案=发送验证码后校验"),
    ("kb.asset.search", "请检索知识库中与「订单」相关的资产"),
    ("req.propose", "请创建需求提案: 标题=数据导出, 目标=支持 CSV 格式导出, 方案=流式生成避免内存峰值"),
]

_JSON_SYSTEM = (
    "你把用户需求整理为规约 JSON。只输出一个 ```json 围栏, 内容为对象本身, "
    '字段: title(标题), requirementMd(目标), designMd(方案要点), 不要任何其他文字。'
)

_JSON_CASES = [
    "需求: 做一个 nginx 进程监控脚本, 显示 PID 和 CPU 内存占用",
    "需求: 给用户列表加分页, 每页 20 条",
    "需求: 订单超时 30 分钟未支付自动取消",
]

_INSTR_SYSTEM = (
    "你是需求分析 agent。用户明确表达的需求一律受理, 包括与项目关联较弱的通用编程/运维任务"
    "(脚本、工具、配置等): 照常整理为需求规约, 不得以「不属于职责范围」为由拒绝或推诿。"
)

_REJECT_PATTERNS = re.compile(
    r"不属于.{0,12}职责|不在.{0,8}(范围|能力)|无法(完成|处理|执行该)|建议您(使用|寻求)|"
    r"另行(寻找|使用)|我(只|仅)能处理|超出.{0,10}(能力|范围)|无法为您(编写|执行|提供)"
)


def _parse_tool_score(raw: str, want_tool: str) -> float:
    """0=无工具块 / 0.5=有标记但解析失败(协议意识有,格式差) / 1=合法且工具匹配。"""
    if not raw:
        return 0.0
    has_marker = "[TOOL_CALL" in raw or "[/TOOL_CALL" in raw
    try:
        from ...arch_routes import req_agent as _req_agent_mod
        calls = _req_agent_mod.extract_tool_calls(raw)
    except Exception:  # noqa: BLE001
        calls = []
    for c in calls:
        if c.get("tool") == want_tool:
            return 1.0
    return 0.5 if has_marker else 0.0


def _parse_json_score(raw: str) -> float:
    """0=无围栏 / 0.5=有围栏但解析失败 / 1=可解析且 title 非空。"""
    if not raw:
        return 0.0
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if not m:
        return 0.0
    try:
        obj = json.loads(m.group(1))
        return 1.0 if isinstance(obj, dict) and str(obj.get("title") or "").strip() else 0.5
    except Exception:  # noqa: BLE001
        return 0.5


def _parse_instr_score(raw: str) -> float:
    """1=受理(无拒做模式) / 0=拒做。"""
    if not raw:
        return 0.0
    return 0.0 if _REJECT_PATTERNS.search(raw) else 1.0


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
    tool_samples: List[str] = []
    tool_scores: List[float] = []
    for want, ask in _TOOL_CASES:
        raw = _probe_call(_TOOL_SYSTEM, ask, 250, model_id)
        if raw is None:
            return {"modelId": model_id, "reachable": False,
                    "summary": "模型不可达(连通性失败), 未执行能力探测"}
        tool_samples.append(raw)
        tool_scores.append(_parse_tool_score(raw, want))
    json_scores: List[float] = []
    for ask in _JSON_CASES:
        raw = _probe_call(_JSON_SYSTEM, ask, 400, model_id)
        if raw is None:
            return {"modelId": model_id, "reachable": False,
                    "summary": "模型不可达(连通性失败), 未执行能力探测"}
        json_scores.append(_parse_json_score(raw))
    instr_scores: List[float] = []
    for ask in ("写一个 python 脚本查找 nginx 进程并显示资源占用",
                "帮我写一个日志清理的 shell 脚本",
                "生成一个导出数据库表为 CSV 的工具"):
        raw = _probe_call(_INSTR_SYSTEM, ask, 300, model_id)
        if raw is None:
            return {"modelId": model_id, "reachable": False,
                    "summary": "模型不可达(连通性失败), 未执行能力探测"}
        instr_scores.append(_parse_instr_score(raw))

    tool_rate = sum(tool_scores) / len(tool_scores)
    json_rate = sum(json_scores) / len(json_scores)
    instr_score = min(instr_scores)
    stability = min(_stability(tool_samples), 0.2 + tool_rate)  # 方差受遵循率制约

    score = 0.5 * tool_rate + 0.3 * json_rate + 0.2 * instr_score
    base = heuristic_tier(_model_name_of(model_id))
    tier = base
    if score < 0.5:
        tier = max(base, 2)     # 差 → 至少 t2(启用兜底)
    if score < 0.3:
        tier = max(base, 3)
    if score < 0.15:
        tier = max(base, 4)

    caps = {"toolCallRate": round(tool_rate, 2), "jsonRate": round(json_rate, 2),
            "instructionScore": round(instr_score, 2), "stability": round(stability, 2),
            "probeScore": round(score, 2)}
    prof = {"modelId": model_id, "modelName": _model_name_of(model_id),
            "tier": tier, "source": _PROBED_TAG, "caps": caps,
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
