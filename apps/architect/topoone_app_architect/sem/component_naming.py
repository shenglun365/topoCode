"""组件快速命名作业（数据主权批C）。

定位：为自管社区组件（arch_components）生成中文名+一句话职责——「快速理解、
对齐需求语义」通道（用户裁决：轻量，不做 KB 式全面解读/agentic 循环）。

链路：组件 owns 文件清单 + 每文件代表符号（最大行数区间， GraphStore）→
编号清单 prompt（N. 路径 [符号, …]）→ llm_sync structured 批量输出
[{n, name, summary}]（编号引用——induce num 形态经验：可靠性碾压名称回抄）
→ upsert_naming 落 arch_component_naming + 回写 arch_components.name。

缓存指纹：rev + sorted(owns)（owns 变化即 stale，重命名只补缺失/过期组件）。
模型：llm_sync 惯例（显式 > architect 偏好 llm.modelId，ModelNotConfigured
明确报错不静默）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from ..store.graph import ComponentStore, GraphStore
from . import job_runner
from .job_runner import JobCtx

logger = logging.getLogger(__name__)

_BATCH = 8          # 单次 LLM 调用命名的组件数上限(上下文防爆)
_SYMBOLS_PER_FILE = 2

_SYSTEM = "你是软件架构组件命名专家。根据组件包含的文件与代表符号，给出简短中文名与一句话职责。只输出 JSON。"

_USER_TMPL = """为以下 {n} 个代码组件命名。

组件清单（n 为编号，回填到输出）：
{items}

要求：
- name: 2-6 个字的中文组件名，概括该组文件的共同职责；
- summary: 不超过 40 字的一句话职责说明；
- 严格按 JSON 输出：{{"items": [{{"n": 编号, "name": "...", "summary": "..."}}]}}，n 必须与清单编号一致。"""

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "name": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["n", "name"],
            },
        }
    },
    "required": ["items"],
}


def owns_fingerprint(owns: List[str]) -> str:
    return hashlib.sha1(
        json.dumps(sorted(owns or []), ensure_ascii=False).encode()
    ).hexdigest()[:16]


def _represent_symbols(nodes_by_file: Dict[str, List[dict]], owns: List[str]) -> str:
    """owns 文件 → 代表符号摘要（每文件取行区间最大的前 N 个：名+签名截断）。"""
    parts: List[str] = []
    for f in owns or []:
        syms = nodes_by_file.get(f) or []
        top = sorted((s for s in syms if s.get("kind") not in ("file",)),
                     key=lambda s: int(s.get("end_line") or 0) - int(s.get("start_line") or 0),
                     reverse=True)[:_SYMBOLS_PER_FILE]
        sigs = "、".join(
            f"{s.get('name')}({(s.get('signature') or s.get('kind') or '')[:40]})"
            for s in top)
        parts.append(f"  - {f}" + (f"  [{sigs}]" if sigs else ""))
    return "\n".join(parts)


def _parse_items(res: Optional[dict], n: int) -> List[dict]:
    """LLM 返回 → items（编号越界/重名忽略；坏输出返回空）。

    llm_sync(mode=structured) 返回信封 {content, output:{items}}——
    items 取 output 信封；content 文本兜底 JSON 提取。"""
    if not isinstance(res, dict):
        return []
    payload = res.get("output") if isinstance(res.get("output"), dict) else res
    raw = payload.get("items")
    if raw is None and isinstance(res.get("content"), str):
        try:
            m = re.search(r"\{[\s\S]*\}", res["content"])
            raw = (json.loads(m.group(0)) or {}).get("items") if m else []
        except Exception:  # noqa: BLE001
            raw = []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:  # noqa: BLE001
            raw = []
    out: List[dict] = []
    seen: set = set()
    for it in raw or []:
        if not isinstance(it, dict):
            continue
        try:
            idx = int(it.get("n"))
        except (TypeError, ValueError):
            continue
        name = (it.get("name") or "").strip()
        if idx < 0 or idx >= n or not name or idx in seen:
            continue
        seen.add(idx)
        out.append({"n": idx, "name": name,
                    "summary": (it.get("summary") or "").strip()})
    return out


def _job_component_name(ctx: JobCtx) -> dict:
    from ..agent.cognition.llm import ModelNotConfigured, llm_sync

    pid = ctx.pid
    scope = ctx.scope or {}
    rev = ComponentStore.latest_rev(pid)
    if not rev:
        return {"error": "无自管组件(先运行 community-group 分组)"}
    comps = ComponentStore.list_rev(pid, rev)
    if not comps:
        return {"error": "自管组件目录为空(先运行 community-group 分组)"}
    want = set(scope.get("componentIds") or [])
    force = bool(scope.get("force"))
    namings = ComponentStore.namings(pid, rev)
    targets = [c for c in comps
               if (not want or c["id"] in want)
               and (force
                    or c["id"] not in namings
                    or namings[c["id"]].get("status") != "active"
                    or namings[c["id"]].get("fingerprint") != owns_fingerprint(c.get("owns") or []))]
    if not targets:
        return {"named": 0, "total": len(comps), "cached": True,
                "rev": rev, "note": "全部组件命名有效(缓存命中)"}

    # 代表符号：快照内按 file 聚合一次
    nodes_by_file: Dict[str, List[dict]] = {}
    for n in GraphStore.nodes(pid, rev, limit=100000):
        nodes_by_file.setdefault(n.get("file_path") or "", []).append(n)

    named, failed, errors = 0, 0, []
    model_id = scope.get("modelId") or ""
    for i in range(0, len(targets), _BATCH):
        if ctx.cancelled():
            return {"named": named, "failed": failed, "cancelled": True, "rev": rev}
        batch = targets[i:i + _BATCH]
        items_txt = "\n".join(
            f"{j}. {c['id']}（{len(c.get('owns') or [])} 文件）\n"
            f"{_represent_symbols(nodes_by_file, c.get('owns') or [])}"
            for j, c in enumerate(batch))
        prompt = _USER_TMPL.format(n=len(batch), items=items_txt)
        res: Optional[dict] = None
        for attempt in (0, 1):  # 坏采样重试 1 次
            try:
                res = llm_sync(
                    [{"role": "system", "content": _SYSTEM},
                     {"role": "user", "content": prompt}],
                    mode="structured", output_schema=_OUTPUT_SCHEMA,
                    model_id=model_id or None,
                    on_error=errors.append if attempt == 0 else None)
            except ModelNotConfigured as e:
                return {"error": f"模型未配置: {e}", "named": named, "rev": rev}
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))
                res = None
            items = _parse_items(res, len(batch))
            if items:
                fps = {c["id"]: owns_fingerprint(c.get("owns") or [])
                       for c in batch}
                written = ComponentStore.upsert_naming(
                    pid, rev,
                    [{"componentId": batch[it["n"]]["id"], "name": it["name"],
                      "summary": it["summary"]} for it in items],
                    model_id=model_id, fingerprints=fps)
                named += written
                failed += len(batch) - written
                break
        else:
            failed += len(batch)
        ctx.progress(total=len(targets), done=min(i + _BATCH, len(targets)),
                     current=f"已命名 {named}/{len(targets)}")
    return {"named": named, "failed": failed, "total": len(targets),
            "rev": rev, "errors": errors[:5]}


job_runner.register("component_name", _job_component_name)  # noqa: E305
