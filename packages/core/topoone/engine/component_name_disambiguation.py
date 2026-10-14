"""
component_name_disambiguation — 组件命名消歧（独立流程，可按需反复运行）。

背景：UNIFIED 合并后 LLM 逐组件独立命名（互相不可见），易产生重复/相似名称
（如 L0 与 L1 同时出现 "nginx-core-modules"、多个 NginxCoreModules 变体）。

本模块提供三类能力，独立于标准分析流水线（不接入 analyzeComponents/pipeline 完成链）：
- strip_doc_header: 剥离语义文档 MD 中渲染期合成的元数据头部
  （社区/ID/父组件/结构分析块），供编辑保存兜底与存量清理；
- scan_name_conflicts: 全任务组件名冲突排查（归一化精确重复 + 相似度分组），零 LLM；
- resolve_group / clean_community_summaries: LLM 消歧与存量 summary 清理。

不变式：
- name_manual 非空（人工命名）的行只作为 LOCKED 占用名参与冲突判定，绝不被改名；
- 渲染期合成的 MD 头部永不落库（saveCommunityResult 写入前兜底剥离）。
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# 相似判定阈值：归一化串编辑相似度 / token Jaccard
SIMILAR_RATIO = 0.85
TOKEN_JACCARD = 0.8
# 与现有分析口径一致（component_analyst / agentic prompt 的 ≤20 chars）
NAME_MAX_LEN = 20

# ── 渲染期合成的元数据模式（SubDocViewer.loadDoc / docs /api/community-doc）──
RE_HEADING = re.compile(r"^\s*#\s*(?:社区|Community)\s*[:：].*$")
RE_ID_LINE = re.compile(r"^\s*\*\*ID\*\*\s*[:：].*$")
RE_PARENT_HEADING = re.compile(r"^\s*##\s*(?:父组件|Parent Component)\s*$")
RE_STRUCT_HEADING = re.compile(r"^\s*##\s*(?:结构分析|Structural Analysis).*$")
RE_STRUCT_GROUP = re.compile(r"^\s*###\s*(?:依赖关系|调用关系|Dependency|Call Relationship).*$")
RE_COMM_LINK = re.compile(r"^\s*-\s*\[[^\]]*\]\(##community:[^)]*\)\s*$")
RE_HR = re.compile(r"^\s*-{3,}\s*$")

_SYNTH_RE = (RE_HEADING, RE_ID_LINE, RE_PARENT_HEADING, RE_STRUCT_HEADING,
             RE_STRUCT_GROUP, RE_COMM_LINK)


def _is_synthesized(line: str) -> bool:
    return any(rx.match(line) for rx in _SYNTH_RE) or bool(RE_HR.match(line))


def _consume_blank_hr(lines: list, i: int) -> int:
    """跳过连续的空行/分隔线，返回停下的下标。"""
    n = len(lines)
    while i < n:
        s = lines[i].strip()
        if not s or RE_HR.match(lines[i]):
            i += 1
        else:
            break
    return i


def strip_doc_header(text: str) -> str:
    """剥离语义文档 MD 中渲染期合成的元数据块（兼容存量多层污染）。

    识别并删除：
    - `# 社区: x` / `# Community: x` 标题行（任意位置、任意层）
    - `**ID**: ...`（含 docs 端 `**ID**: x  **类型**: y` 同行形式）
    - `## 父组件` / `## Parent Component` 块（标题 + 紧随的一行内容）
    - `## 结构分析` / `## Structural Analysis` 块（标题 + ### 分组 + ##community: 链接行）
    - 上述块相邻的空行/分隔线；收尾压缩 3+ 连续空行并去首尾空白。
    用户正文不受影响（仅精确匹配合成模式）。
    """
    if not text:
        return text or ""
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if RE_HEADING.match(line) or RE_ID_LINE.match(line):
            i += 1
            continue
        if RE_PARENT_HEADING.match(line):
            i += 1
            # 父组件块：标题后紧跟一行内容（name — summary 片段）
            while i < n and not lines[i].strip():
                i += 1
            if i < n and lines[i].strip() and not _is_synthesized(lines[i]):
                i += 1
            i = _consume_blank_hr(lines, i)
            continue
        if RE_STRUCT_HEADING.match(line):
            i += 1
            while i < n:
                s = lines[i].strip()
                if not s or RE_HR.match(lines[i]) or _is_synthesized(lines[i]):
                    i += 1
                else:
                    break
            i = _consume_blank_hr(lines, i)
            continue
        if RE_HR.match(line):
            # 分隔线仅在其后紧跟合成块时丢弃（属于合成块的组成分隔线）
            j = _consume_blank_hr(lines, i + 1)
            if j < n and _is_synthesized(lines[j]) and not RE_HR.match(lines[j]):
                i = j
                continue
            out.append(line)
            i += 1
            continue
        out.append(line)
        i += 1
    cleaned = "\n".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    # 去除收尾后仍残留的首部空行/分隔线
    while True:
        stripped = cleaned.lstrip()
        if stripped.startswith("---"):
            stripped = stripped[3:].lstrip("\n").lstrip()
        else:
            break
        cleaned = stripped
    return cleaned.strip()


def normalize_name(name: str) -> str:
    """名称归一化：NFKC 全半角 + casefold + 去分隔符（空格/_/-/等）。"""
    if not name:
        return ""
    text = unicodedata.normalize("NFKC", str(name)).casefold()
    return re.sub(r"[\s_\-/\\·・]+", "", text)


def _tokens(name: str) -> set:
    text = unicodedata.normalize("NFKC", str(name)).casefold()
    return {t for t in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text) if t}


def _pair_similar(na: str, nb: str, ta: set, tb: set) -> bool:
    if not na or not nb:
        return False
    if na == nb:
        return True
    if SequenceMatcher(None, na, nb).ratio() >= SIMILAR_RATIO:
        return True
    union = ta | tb
    if union and len(ta & tb) / len(union) >= TOKEN_JACCARD:
        return True
    return False


def _load_rows(project_db, task_id: str) -> list:
    try:
        return project_db.fetchall(
            "SELECT comm_id, comm_lv, edge_type, name, name_manual, summary, status "
            "FROM community_llm_results WHERE task_id=?",
            (task_id,)) or []
    except Exception as e:
        logger.warning("[NameDisambiguation] load rows failed: %s", e)
        return []


def _load_parent_map(project_db, task_id: str) -> dict:
    try:
        rows = project_db.fetchall(
            "SELECT comm_id, parent_comm_id FROM graph_doc "
            "WHERE task_id=? AND parent_comm_id IS NOT NULL AND parent_comm_id != ''",
            (task_id,)) or []
        return {r["comm_id"]: r["parent_comm_id"] for r in rows}
    except Exception:
        return {}


def scan_name_conflicts(project_db, task_id: str, comm_ids: Optional[list] = None) -> dict:
    """全任务组件名冲突排查（零 LLM）。

    返回 {scanned, groups: [{kind, members, locked}], dirtySummaryCommIds}。
    member: {commId, commLv, edgeType, name, manual, status, summaryClean, parentName}
    - name_manual 非空的行照常参与分组（占用名），但标记 manual=True（resolver 不改名）；
    - status='failed' 或 name 为空的行跳过（未成功分析）。
    """
    rows = _load_rows(project_db, task_id)
    parent_map = _load_parent_map(project_db, task_id)

    items = []
    dirty_ids = []
    for r in rows:
        cid = r["comm_id"] or ""
        if comm_ids and cid not in set(comm_ids):
            continue
        name = (r["name_manual"] or r["name"] or "").strip()
        manual = bool((r["name_manual"] or "").strip())
        if not name or (r["status"] == "failed"):
            continue
        summary = r["summary"] or ""
        summary_clean = strip_doc_header(summary)
        if summary_clean != summary:
            dirty_ids.append(cid)
        parent_id = parent_map.get(cid, "")
        items.append({
            "commId": cid,
            "commLv": r["comm_lv"] or "L0",
            "edgeType": r["edge_type"] or "UNIFIED",
            "name": name,
            "manual": manual,
            "status": r["status"] or "",
            "summaryClean": summary_clean,
            "parentId": parent_id,
            "_norm": normalize_name(name),
            "_tok": _tokens(name),
        })

    name_of = {it["commId"]: it["name"] for it in items}
    for it in items:
        pid = it.pop("parentId", "")
        it["parentName"] = name_of.get(pid, pid or "")

    # 并查集成组
    n = len(items)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if items[i]["_norm"] and items[i]["_norm"] == items[j]["_norm"]:
                union(i, j)
            elif _pair_similar(items[i]["_norm"], items[j]["_norm"],
                               items[i]["_tok"], items[j]["_tok"]):
                union(i, j)

    clusters: dict = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    groups = []
    for idxs in clusters.values():
        if len(idxs) < 2:
            continue
        members = [{k: v for k, v in items[i].items() if not k.startswith("_")}
                   for i in idxs]
        locked = all(m["manual"] for m in members)
        norms = [items[i]["_norm"] for i in idxs]
        kind = ("exact" if any(
            norms[a] and norms[a] == norms[b]
            for a in range(len(idxs)) for b in range(a + 1, len(idxs))
        ) else "similar")
        groups.append({"kind": kind, "members": members, "locked": locked})

    groups.sort(key=lambda g: (-len(g["members"]), g["members"][0]["name"]))
    for it in items:
        it.pop("_norm", None)
        it.pop("_tok", None)
    return {
        "scanned": n,
        "groups": groups,
        "dirtySummaryCommIds": dirty_ids,
    }


def _parse_name_map(text: str) -> dict:
    if not text:
        return {}
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        t = "\n".join(lines[1:])
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
        t = t.strip()
    try:
        obj = json.loads(t)
        if isinstance(obj, dict):
            return {str(k): str(v).strip() for k, v in obj.items()
                    if isinstance(v, str)}
    except Exception:
        pass
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return {str(k): str(v).strip() for k, v in obj.items()
                        if isinstance(v, str)}
        except Exception:
            pass
    return {}


def _build_resolve_prompt(group_members: list, taken_names: list,
                          language: str) -> list:
    lines = [
        "You are a component naming arbitrator for a code architecture KB.",
        "The components below got conflicting / too-similar names because each was",
        "analyzed independently. Propose ONE new name for each component listed",
        "under RENAME so that all names become mutually distinguishable.",
        "",
        "Rules:",
        "- New names must be mutually distinct AND distinct from every name in TAKEN.",
        "- Reflect each component's specific domain (protocol / subsystem / key files);",
        "  do NOT reuse the bare project or framework name as the whole name.",
        "- Keep each component's original language"
        + (f"; output names in {'Chinese' if language == 'zh' else 'English'}."
           if language in ("zh", "en") else ".") ,
        f"- At most {NAME_MAX_LEN} characters, no leading/trailing whitespace.",
        "- Members marked [LOCKED] keep their name — treat it as occupied.",
        "- Output ONLY a JSON object mapping comm_id to new name for RENAME members.",
        "",
        f"TAKEN: {json.dumps(taken_names, ensure_ascii=False)}",
        "",
        "CONFLICT GROUP:",
    ]
    for m in group_members:
        flag = " [LOCKED]" if m["manual"] else ""
        lines.append(
            f"- {m['commId']} | name: {m['name']}{flag} | level: {m['commLv']}"
            + (f" | parent: {m['parentName']}" if m.get("parentName") else "")
            + f" | summary: {(m.get('summaryClean') or '')[:200]}"
        )
    lines.append("")
    lines.append("RENAME: all members without [LOCKED].")
    return [{"role": "system", "content": lines[0]},
            {"role": "user", "content": "\n".join(lines[1:])}]


def _valid_new_name(name: str, old_norm: str, taken_norm: set) -> bool:
    name = (name or "").strip()
    if not name or len(name) > NAME_MAX_LEN:
        return False
    if name.lower().startswith("comm-") or re.match(r"^L\d+-\d+$", name):
        return False
    norm = normalize_name(name)
    if not norm or norm == old_norm or norm in taken_norm:
        return False
    return True


async def resolve_group(multi_db, project_db, task_id: str, comm_keys: list,
                        language: str = "", llm_fn: Optional[Callable] = None) -> dict:
    """对一组冲突组件做 LLM 消歧并写回。

    comm_keys: [{commId, commLv, edgeType?}]（来自 scan 的某个 group.members）
    - 服务端按 key 重读行，重建成员与占用名（不信任客户端携带的名称/标记）；
    - name_manual 非空的成员保持 LOCKED，其余成员改名；
    - 单名无效仅该成员回退原值，不影响其他成员。
    返回 {changes: [{commId, oldName, newName}], failed: [{commId, reason}]}。
    """
    rows = _load_rows(project_db, task_id)
    by_key = {(r["comm_id"], r["comm_lv"] or "L0", r["edge_type"] or "UNIFIED"): r
              for r in rows}
    parent_map = _load_parent_map(project_db, task_id)

    members = []
    for k in (comm_keys or []):
        cid = (k.get("commId") or k.get("comm_id") or "").strip()
        lv = (k.get("commLv") or k.get("comm_lv") or "L0").strip()
        et = (k.get("edgeType") or k.get("edge_type") or "UNIFIED").strip()
        r = by_key.get((cid, lv, et))
        if not r:
            continue
        manual = bool((r["name_manual"] or "").strip())
        name = (r["name_manual"] or r["name"] or "").strip()
        if not name or r["status"] == "failed":
            continue
        members.append({
            "commId": cid, "commLv": lv, "edgeType": et,
            "name": name, "manual": manual,
            "summaryClean": strip_doc_header(r["summary"] or ""),
            "parentName": "",
        })
    if len(members) < 2:
        return {"changes": [], "failed": [], "skipped": "need >= 2 members"}
    if all(m["manual"] for m in members):
        return {"changes": [], "failed": [], "skipped": "all members locked (name_manual)"}

    name_of = {r["comm_id"]: (r["name_manual"] or r["name"] or "").strip()
               for r in rows}
    for m in members:
        pid = parent_map.get(m["commId"], "")
        m["parentName"] = name_of.get(pid, pid or "")

    # 占用名 = 全任务所有 name/name_manual，排除本组待改名成员自身
    rename_ids = {m["commId"] for m in members if not m["manual"]}
    taken = set()
    for r in rows:
        for v in (r["name_manual"], r["name"]):
            v = (v or "").strip()
            if v and r["comm_id"] not in rename_ids:
                taken.add(v)
    taken_norm = {normalize_name(v) for v in taken if normalize_name(v)}
    for m in members:
        if m["manual"]:
            taken_norm.add(normalize_name(m["name"]))

    if llm_fn is None:
        from topoone.agent.agent_workflow.llm_adapter import create_llm_chat_fn
        llm_fn = create_llm_chat_fn(multi_db)

    messages = _build_resolve_prompt(members, sorted(taken), language)
    try:
        resp = await llm_fn(messages=messages, temperature=0.2, max_tokens=800)
    except Exception as e:
        logger.warning("[NameDisambiguation] LLM call failed: %s", e)
        return {"changes": [], "failed": [{"commId": "*", "reason": str(e)}]}

    proposed = _parse_name_map(resp if isinstance(resp, str) else str(resp))
    changes, failed = [], []
    assigned_norm = set()
    for m in members:
        if m["manual"]:
            continue
        old = m["name"]
        new = (proposed.get(m["commId"]) or "").strip()
        if not new or normalize_name(new) == normalize_name(old):
            failed.append({"commId": m["commId"], "reason": "no valid proposal"})
            # 改名失败 → 原名继续占用，后续成员须避开
            taken_norm.add(normalize_name(old))
            continue
        if not _valid_new_name(new, normalize_name(old),
                               taken_norm | assigned_norm):
            failed.append({"commId": m["commId"], "reason": f"invalid/duplicate: {new}"})
            taken_norm.add(normalize_name(old))
            continue
        assigned_norm.add(normalize_name(new))
        changes.append({"commId": m["commId"], "commLv": m["commLv"],
                        "edgeType": m["edgeType"], "oldName": old, "newName": new})

    for c in changes:
        try:
            project_db.execute(
                "UPDATE community_llm_results SET name=?, updated_at=datetime('now') "
                "WHERE task_id=? AND edge_type=? AND comm_lv=? AND comm_id=?",
                (c["newName"], task_id, c["edgeType"], c["commLv"], c["commId"]))
        except Exception as e:
            logger.warning("[NameDisambiguation] update failed for %s: %s",
                           c["commId"], e)
            c["newName"] = c["oldName"]
            failed.append({"commId": c["commId"], "reason": str(e)})
    if changes:
        try:
            project_db.commit()
        except Exception as e:
            logger.warning("[NameDisambiguation] commit failed: %s", e)
    logger.info("[NameDisambiguation] resolve_group: %d renamed, %d failed",
                len(changes), len(failed))
    return {"changes": changes, "failed": failed}


def clean_community_summaries(project_db, task_id: str) -> dict:
    """存量清理：剥离 community_llm_results.summary 内嵌的合成头部并写回。"""
    rows = _load_rows(project_db, task_id)
    cleaned = 0
    for r in rows:
        summary = r["summary"] or ""
        if not summary.strip():
            continue
        stripped = strip_doc_header(summary)
        if stripped != summary:
            try:
                project_db.execute(
                    "UPDATE community_llm_results SET summary=?, updated_at=datetime('now') "
                    "WHERE task_id=? AND edge_type=? AND comm_lv=? AND comm_id=?",
                    (stripped, task_id, r["edge_type"] or "UNIFIED",
                     r["comm_lv"] or "L0", r["comm_id"]))
                cleaned += 1
            except Exception as e:
                logger.warning("[NameDisambiguation] clean summary failed for %s: %s",
                               r["comm_id"], e)
    if cleaned:
        try:
            project_db.commit()
        except Exception as e:
            logger.warning("[NameDisambiguation] clean commit failed: %s", e)
    logger.info("[NameDisambiguation] clean_community_summaries: %d cleaned", cleaned)
    return {"cleaned": cleaned, "scanned": len(rows)}
