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


def stats() -> Dict[str, Any]:
    """按 kind 统计条数/字节/末次时间(供管理页/CLI 观测采集健康度)。"""
    out: Dict[str, Any] = {"kinds": {}, "bytes": 0, "path": _path()}
    try:
        p = _path()
        if not os.path.exists(p):
            return out
        out["bytes"] = os.path.getsize(p)
        with open(p, "r", encoding="utf-8") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except Exception:  # noqa: BLE001
                    continue
                k = r.get("kind", "?")
                slot = out["kinds"].setdefault(k, {"count": 0, "lastTs": 0})
                slot["count"] += 1
                slot["lastTs"] = max(slot["lastTs"], r.get("ts", 0))
    except Exception as e:  # noqa: BLE001
        logger.debug("[llm_dataset] stats failed: %s", e)
    return out


@router.get("/llm-dataset/stats")
async def llm_dataset_stats():
    return stats()
