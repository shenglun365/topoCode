"""修复任务注册表(反射层) — 补偿组件的隔离修复循环集合(可扩展)。

架构(2026-09-17 裁决): 修复需求以「任务种类」注册——每种错误一个 builder,
产出 RepairTask 交 run_repair_loop 隔离执行(**不污染主上下文**); 失败如实
回落调用方既有路径, 绝不静默。新增修复需求 = 注册新 kind, 不改循环引擎。

kind 注册表:
- tool_call: 工具名/参数错误修复(M4 补偿组件; 工具调用协议层, 每调用限 1 次)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from .repair import RepairTask, run_repair_loop

logger = logging.getLogger("arch.reflection.repair_tasks")

# kind → builder(**kwargs) -> RepairTask
_REPAIR_BUILDERS: Dict[str, Callable[..., RepairTask]] = {}


def register_repair(kind: str) -> Callable:
    """修复任务种类注册装饰器(扩展点: 新增修复需求注册新 kind)。"""
    def deco(fn: Callable[..., RepairTask]) -> Callable[..., RepairTask]:
        _REPAIR_BUILDERS[kind] = fn
        return fn
    return deco


def repair_kinds() -> List[str]:
    return sorted(_REPAIR_BUILDERS)


_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)


def _parse_tool_call_json(raw: str) -> Optional[Dict[str, Any]]:
    """修复器产物解析: 单个 {"tool", "arguments"} JSON(围栏容忍)。"""
    if not raw:
        return None
    m = _JSON_OBJ.search(raw)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(obj, dict) or not str(obj.get("tool") or "").strip():
        return None
    args = obj.get("arguments")
    return {"tool": str(obj["tool"]).strip(),
            "arguments": args if isinstance(args, dict) else {}}


@register_repair("tool_call")
def _build_tool_call_repair(*, name: str, arguments: Dict[str, Any],
                            error: str, valid_tools: List[str],
                            model_id: str = "") -> RepairTask:
    """工具调用修复: 原调用 + 错误 + 合法工具清单 → 修正后的单个调用 JSON。"""
    valid = "\n".join(f"- {t}" for t in (valid_tools or [])[:40]) or "- (无)"
    return RepairTask(
        task_id=f"repair_tool_call[{name}]",
        system=(
            "你是工具调用修复器。一次工具调用存在机械性错误(工具名拼写/参数形状)。"
            "依据错误信息与合法工具清单, 只输出修正后的【单个】调用, 格式为 JSON 对象:\n"
            '{"tool": "<合法工具名>", "arguments": {…}}\n'
            "不要输出其它文字; 若原调用语义上无法映射到任何合法工具, 输出 {}。"),
        user=(f"原调用: {json.dumps({'tool': name, 'arguments': arguments}, ensure_ascii=False)}\n"
              f"错误: {error}\n合法工具清单:\n{valid}"),
        parse=_parse_tool_call_json,
        max_tokens=500,
        model_id=model_id or "",
        dataset_kind="tool_call_repair",
        meta={"original": {"tool": name, "arguments": arguments},
              "error": error[:200]},
    )


def run_tool_call_repair(name: str, arguments: Dict[str, Any], error: str,
                         valid_tools: List[str],
                         model_id: str = "") -> Optional[Dict[str, Any]]:
    """工具调用隔离修复(每调用限 1 次, 预算由调用方控制)。

    返回 {"tool", "arguments"}(已校验在合法清单)或 None(修复失败/无法映射)。
    语义: 机械性错误纠正; 失败绝不静默——调用方回落原错误如实上抛。
    """
    valid = {t for t in (valid_tools or []) if t}
    task = _build_tool_call_repair(name=name, arguments=arguments, error=error,
                                   valid_tools=sorted(valid),
                                   model_id=model_id)
    out = run_repair_loop(task)
    parsed = out.get("parsed") if isinstance(out, dict) else None
    if not isinstance(parsed, dict):
        return None
    tool = parsed.get("tool") or ""
    if tool not in valid:
        # 修复器无法映射(空对象/仍非法) → 如实失败
        return None
    return {"tool": tool, "arguments": parsed.get("arguments") or {}}
