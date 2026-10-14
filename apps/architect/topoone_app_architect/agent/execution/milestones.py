"""关键节点回执(milestones 检查点, 遗留#2; 展示型起步, 裁决 2026-10-10)。

契约约束「做什么」、路径开放「怎么做」的检查点机制——不是步骤脚本:
- 任务行 milestones = [{id, title, doneWhen}] JSON(REST 可设, saved 态);
  规约快照同名字段经 context_pack 装配随行(用户/LLM 可在规约中声明)。
- 存在节点时指令附「节点回执约定」: 执行器到达节点输出 [[MILESTONE:id 标题]]
  标记行后继续执行——零 runner 协议改动, 复用既有事件通道。
- architect 侧在完整文本(input_required/done)解析标记 → progress.milestones
  命中态(节点卡/任务卡可视) + 消息流节点回执卡(kind=task_milestone)。
  展示型: 不阻断执行器自主推进; 用户可借节点中途 steer 纠偏。
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

_TAG_RE = re.compile(r"\[\[MILESTONE:([A-Za-z0-9_\-]+)[^\]]*\]\]")


def normalize_milestones(raw) -> List[Dict[str, str]]:
    """归一: 字符串(JSON)/列表 → [{id, title, doneWhen}](去空/去重/截限前 12)。"""
    items = []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except Exception:  # noqa: BLE001 — 损坏按空处理
            raw = []
    if not isinstance(raw, list):
        return []
    seen = set()
    for it in raw[:12]:
        if not isinstance(it, dict):
            continue
        mid = str(it.get("id") or "").strip()[:40]
        title = str(it.get("title") or "").strip()[:80]
        if not mid or not title or mid in seen:
            continue
        seen.add(mid)
        items.append({"id": mid, "title": title,
                      "doneWhen": str(it.get("doneWhen") or "").strip()[:200]})
    return items


def milestones_instruction(ms: List[Dict[str, str]]) -> str:
    """节点回执约定指令段(任务存在节点时注入)。"""
    if not ms:
        return ""
    lines = ["", "## 关键节点回执", "本任务有以下关键节点——到达节点时**先输出一行标记**再继续执行："]
    for m in ms:
        lines.append(f"- `[[MILESTONE:{m['id']} {m['title']}]]`"
                     + (f"（达成判据: {m['doneWhen']}）" if m.get("doneWhen") else ""))
    lines.append("标记行独占一行、原样输出（不要改写格式）；节点间路径与做法由你自主决定。")
    return "\n".join(lines)


def parse_milestone_tags(text: str) -> List[str]:
    """完整文本解析 [[MILESTONE:id ...]] → 命中 id 列表(保序去重)。"""
    out, seen = [], set()
    for mid in _TAG_RE.findall(text or ""):
        if mid not in seen:
            seen.add(mid)
            out.append(mid)
    return out


def merge_progress_milestones(ms: List[Dict[str, str]], progress: dict,
                              hit_ids: List[str], ts: int) -> dict:
    """命中合并: progress.milestones = {id: {title, doneWhen, done, doneAt}}。"""
    cur = dict(progress.get("milestones") or {})
    for m in ms:
        cur.setdefault(m["id"], {**m, "done": False, "doneAt": 0})
    for mid in hit_ids:
        row = cur.get(mid)
        if row is not None and not row.get("done"):
            cur[mid] = {**row, "done": True, "doneAt": ts}
    return cur
