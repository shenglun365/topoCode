"""LLM 优化数据统一采集(llm_dataset)。

目标：为本地小模型微调与提示/工具优化持续沉淀「天然标注样本」——
  · llm_call       每次 LLM 调用(同步 llm.sync / 流式 llm.chat 起点)的模型/模式/时延/成败
  · tool_call      每次 architect 工具执行(原始 args + 结果摘要/错误)——审计超集
  · arg_coerce     中央类型收敛事件(修复1): 参数名 + 收敛前后类型摘要
  · arg_repair     聚焦修复外循环(修复5)样本对: {错误args, 错误, 修复后args, 成败}
                   —— 微调样本采集器，直接支撑本地小模型微调路线
  · fence_parse    proposal 围栏存在但 JSON 解析失败(提示模型输出格式回归)
  · guard_hit      守卫触发(编造/空承诺)上下文

存储：<data_dir>/architect/llm_dataset/events.jsonl 追加写，超 32MB 轮转(保留 3 份)。
原则：采集绝不影响业务——任何异常吞掉只打 debug 日志；单文件并发安全靠
进程内 threading.Lock(architect 服务单进程写方)。
"""
import json
import os
import threading
import time
from typing import Any, Dict

from fastapi import APIRouter

logger = __import__("logging").getLogger("topoone.llm_dataset")

router = APIRouter()

_MAX_BYTES = 32 * 1024 * 1024
_KEEP_ROTATED = 3
_TRUNC = 8000          # 单字段(JSON 串)截断
_LOCK = threading.Lock()


def _dir() -> str:
    from ...arch_routes import ctx
    return os.path.join(ctx.data_dir(), "architect", "llm_dataset")


def _path() -> str:
    return os.path.join(_dir(), "events.jsonl")


def _jstr(v: Any) -> str:
    """任意值 → 单行 JSON 串(截断)。"""
    try:
        s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        s = str(v)
    return s[:_TRUNC]


def record(kind: str, **fields: Any) -> None:
    """追加一条事件。永不抛出。自动补 ts/会话/需求/项目/模型。"""
    try:
        from ...arch_routes import ctx
        rec: Dict[str, Any] = {"ts": int(time.time() * 1000), "kind": kind}
        try:
            rec["convId"] = ctx.get_conv() or ""
        except Exception:  # noqa: BLE001
            rec["convId"] = ""
        try:
            rec["reqId"] = ctx.get_req() or ""
        except Exception:  # noqa: BLE001
            rec["reqId"] = ""
        for k, v in fields.items():
            if v is None:
                continue
            if isinstance(v, (str, int, float, bool)):
                rec[k] = v
            else:
                rec[k] = _jstr(v)
        line = json.dumps(rec, ensure_ascii=False, default=str)
        with _LOCK:
            d = _dir()
            os.makedirs(d, exist_ok=True)
            p = _path()
            if os.path.exists(p) and os.path.getsize(p) > _MAX_BYTES:
                rotated = os.path.join(d, f"events-{int(time.time())}.jsonl")
                os.replace(p, rotated)
                olds = sorted(
                    (f for f in os.listdir(d)
                     if f.startswith("events-") and f.endswith(".jsonl")),
                    key=lambda f: os.path.getmtime(os.path.join(d, f)))
                for f in olds[:-_KEEP_ROTATED]:
                    try:
                        os.remove(os.path.join(d, f))
                    except OSError:
                        pass
            with open(p, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as e:  # noqa: BLE001 — 采集不碍业务
        logger.debug("[llm_dataset] record %s skipped: %s", kind, e)


# ── S2 消费口(采纳文档 2609): 吞错计数 + 失败聚合读口 ──────────────────

_SWALLOWS: Dict[str, int] = {}


def swallow(tag: str) -> None:
    """装配路径静默降级计数(turns/context + reflection 点名路径)。

    进程内计数, stats() 快照暴露; 不写盘。开关: agent.comp.overrides.
    swallow_counters(缺省启用)。永不抛出。
    """
    try:
        from ..compensation.overrides import override_enabled, read_overrides
        from ...arch_routes import store
        if not override_enabled(
                read_overrides(store.CollabConfigStore.get), "swallow_counters"):
            return
    except Exception:  # noqa: BLE001 — 开关判定失败按启用处理
        pass
    try:
        k = str(tag or "?")
        with _LOCK:
            _SWALLOWS[k] = _SWALLOWS.get(k, 0) + 1
    except Exception:  # noqa: BLE001
        pass


def _iter_events():
    """逐行产出已解析事件(坏行跳过); 无文件时不产出。"""
    p = _path()
    if not os.path.exists(p):
        return
    with open(p, "r", encoding="utf-8") as f:
        for ln in f:
            try:
                yield json.loads(ln)
            except Exception:  # noqa: BLE001
                continue


def _new_agg() -> Dict[str, Any]:
    return {"byKind": {}, "byTool": {}, "byModel": {},
            "repair": {"ok": 0, "fail": 0}}


def _agg_slot(agg: Dict[str, Any], r: Dict[str, Any]) -> None:
    """单事件并入聚合: 按 kind/tool/model 累计成败; 修复类另记修复率。"""
    k = str(r.get("kind") or "?")
    ok = bool(r.get("ok"))
    slot = agg["byKind"].setdefault(k, {"total": 0, "ok": 0, "fail": 0})
    slot["total"] += 1
    slot["ok" if ok else "fail"] += 1
    tool = str(r.get("tool") or "")
    if tool:
        ts = agg["byTool"].setdefault(tool, {"total": 0, "fail": 0})
        ts["total"] += 1
        if not ok:
            ts["fail"] += 1
    model = str(r.get("model") or "")
    if model:
        ms = agg["byModel"].setdefault(model, {"total": 0, "fail": 0})
        ms["total"] += 1
        if not ok:
            ms["fail"] += 1
    if k in ("arg_repair", "repair_loop"):
        agg["repair"]["ok" if ok else "fail"] += 1


def aggregate_failures(window_days: int = None) -> Dict[str, Any]:
    """失败聚合读口(治理/mining 只读消费; #3 tierSuggested 数据地基)。

    window_days: 只统计近 N 天(缺省全量)。永不抛出。"""
    out = _new_agg()
    out["windowDays"] = int(window_days or 0)
    try:
        cutoff = (int(time.time() * 1000) - int(window_days) * 86_400_000) \
            if window_days else 0
        for r in _iter_events():
            if cutoff and int(r.get("ts") or 0) < cutoff:
                continue
            _agg_slot(out, r)
        out["swallows"] = {"total": sum(_SWALLOWS.values()),
                           "byTag": dict(_SWALLOWS)}
    except Exception as e:  # noqa: BLE001
        logger.debug("[llm_dataset] aggregate failed: %s", e)
    return out


def stats() -> Dict[str, Any]:
    """采集健康度 + 失败聚合 + 吞错计数(单遍扫描; 管理页/CLI 观测口)。"""
    out: Dict[str, Any] = {"kinds": {}, "bytes": 0, "path": _path(),
                           "failures": _new_agg(),
                           "swallows": {"total": sum(_SWALLOWS.values()),
                                        "byTag": dict(_SWALLOWS)}}
    try:
        p = _path()
        if not os.path.exists(p):
            return out
        out["bytes"] = os.path.getsize(p)
        for r in _iter_events():
            k = r.get("kind", "?")
            slot = out["kinds"].setdefault(k, {"count": 0, "lastTs": 0})
            slot["count"] += 1
            slot["lastTs"] = max(slot["lastTs"], r.get("ts", 0))
            _agg_slot(out["failures"], r)
    except Exception as e:  # noqa: BLE001
        logger.debug("[llm_dataset] stats failed: %s", e)
    return out


@router.get("/llm-dataset/stats")
async def llm_dataset_stats():
    return stats()


@router.get("/llm-dataset/failures")
async def llm_dataset_failures(window_days: int = 0):
    """失败聚合读口(S2): 治理层/mining 消费(#3 数据地基), 管理面观测。"""
    return aggregate_failures(window_days or None)
