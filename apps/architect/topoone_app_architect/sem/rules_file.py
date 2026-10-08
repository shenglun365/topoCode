"""AGENTS.md 规约文件面(纯文件模式, 2610 定型修订)——真相源与缓存同步。

对齐业界标准(Codex/Claude Code/opencode 三家共同模式):
- repo 根 AGENTS.md = 100% 人治 markdown(git 版本化), 无生成段/指纹定界;
- architect 只做两件事: 初稿生成(init, 已有文件给建议不盲改) 与
  挖掘采纳 append(人审后落文件);
- 引擎消费(convention_check/提取注入/词汇映射)走 NamingConvention/Glossary
  store 缓存: 文件章节解析回填, 坏行跳过容错(glossary_map 同款先例)。

章节约定(解析契约; 其余章节自由格式不参与解析):
  ## 命名规约   每行一条: - [场景] 规则文本 (场景可省略)
  ## 术语表     | 术语 | 别名 | 含义 | 表格(别名列可空)

同步语义(文件为真相, 仅当文件存在时生效):
- 文件存在 → active 集合全量重建(文件有→建, 文件无→删; pending 提案不动);
- 文件不存在 → 不动 store(遗留数据照旧, init 合并迁移后才进入文件态)。
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Dict, List, Optional

logger = logging.getLogger("sem.rules_file")

FILE_NAME = "AGENTS.md"
SEC_CONVENTIONS = "命名规约"
SEC_GLOSSARY = "术语表"

_RULE_LINE = re.compile(r"^\s*-\s*(?:\[([^\]]*)\]\s*)?(.+?)\s*$")

# 惰性同步指纹: root → (mtime_ns, size); 变化才解析重建
_sync_seen: Dict[str, tuple] = {}


def agents_md_path(root: str) -> str:
    return os.path.join(root or "", FILE_NAME)


def read_agents_md(root: str) -> Dict[str, object]:
    """读文件 → {exists, content, hash, mtime}。"""
    path = agents_md_path(root)
    if not os.path.isfile(path):
        return {"exists": False, "content": "", "hash": ""}
    content = open(path, encoding="utf-8").read()
    st = os.stat(path)
    return {"exists": True, "content": content,
            "hash": _sha(content), "mtime": st.st_mtime_ns}


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def write_agents_md(root: str, content: str, base_hash: str = "") -> Dict[str, object]:
    """写文件(乐观锁: base_hash=sha1 前 16 位; 空串=文件应不存在)。

    冲突返回 {conflict: True, current_hash}(外部已改, 调用方重读合并)。
    """
    path = agents_md_path(root)
    cur = read_agents_md(root)
    cur_hash = str(cur.get("hash") or "")
    if cur_hash != (base_hash or ""):
        return {"ok": False, "conflict": True, "current_hash": cur_hash}
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content.rstrip() + "\n")
    _sync_seen.pop(root, None)
    return {"ok": True, "conflict": False, "hash": _sha(content)}


def _iter_section_lines(content: str, title: str) -> List[str]:
    """提取 `## <title>` 章节正文行(到下一同级/更高级标题止)。"""
    lines: List[str] = []
    inside = False
    for ln in (content or "").splitlines():
        if ln.startswith("#"):
            inside = ln.rstrip() == f"## {title}"
            continue
        if inside:
            lines.append(ln)
    return lines


def parse_agents_md(content: str) -> Dict[str, list]:
    """章节 → 结构化数据(坏行跳过, 计入 skipped)。"""
    skipped = 0
    conventions: List[Dict[str, object]] = []
    for ln in _iter_section_lines(content, SEC_CONVENTIONS):
        m = _RULE_LINE.match(ln)
        if not m:
            if ln.strip():
                skipped += 1
            continue
        rule = m.group(2).strip()
        if rule:
            sc = (m.group(1) or "").strip()
            conventions.append({"ruleText": rule,
                                "scenarios": [sc] if sc else ["general"]})

    glossary: List[Dict[str, object]] = []
    for ln in _iter_section_lines(content, SEC_GLOSSARY):
        s = ln.strip()
        if not s.startswith("|") or set(s) <= {"|", "-", " ", ":"}:
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in ("术语", "Term"):
            continue
        term = cells[0]
        alias = [a.strip() for a in re.split("[，,]", cells[1]) if a.strip()] \
            if len(cells) >= 3 and cells[1] and cells[1] != "—" else []
        definition = cells[-1] if len(cells) >= 2 else ""
        if len(cells) == 2:                       # | 术语 | 含义 | 两列形态
            alias, definition = [], cells[1]
        if term:
            glossary.append({"term": term, "alias": alias, "definition": definition})
    return {"conventions": conventions, "glossary": glossary, "skipped": skipped}


def ensure_rules_synced(root: str, project_id: str,
                        force: bool = False) -> Dict[str, object]:
    """惰性同步(mtime+size 变化才解析重建)。文件不存在=no-op。

    返回 {synced, conventions, glossary}(计数; synced=False=未变化/无文件)。
    """
    if not root or not project_id:
        return {"synced": False, "conventions": 0, "glossary": 0}
    path = agents_md_path(root)
    if not os.path.isfile(path):
        return {"synced": False, "conventions": 0, "glossary": 0}
    st = os.stat(path)
    sig = (st.st_mtime_ns, st.st_size)
    if not force and _sync_seen.get(root) == sig:
        return {"synced": False, "conventions": 0, "glossary": 0}
    _sync_seen[root] = sig
    parsed = parse_agents_md(open(path, encoding="utf-8").read())
    _rebuild_cache(project_id, parsed)
    return {"synced": True, "conventions": len(parsed["conventions"]),
            "glossary": len(parsed["glossary"]), "skipped": parsed["skipped"]}


def _rebuild_cache(project_id: str, parsed: Dict[str, list]) -> None:
    """文件为真相: active 全量重建(pending 提案不动); 坏行跳过留痕。"""
    from .. import store
    file_rules = {str(c["ruleText"]) for c in parsed["conventions"]}
    active = store.NamingConventionStore.list(project_id, limit=1000)
    for row in active:
        if row.get("ruleText") not in file_rules:
            store.NamingConventionStore.delete(row["id"])
    have = {row.get("ruleText") for row in active}
    for c in parsed["conventions"]:
        if c["ruleText"] not in have:
            store.NamingConventionStore.create(
                project_id, str(c["ruleText"]),
                scenarios=list(c["scenarios"] or []), source="file")

    file_terms = {str(g["term"]) for g in parsed["glossary"]}
    for row in store.GlossaryStore.list(project_id, limit=1000):
        if row.get("term") not in file_terms:
            store.GlossaryStore.delete(row["id"])
    have_t = {r.get("term") for r in store.GlossaryStore.list(project_id, limit=1000)}
    for g in parsed["glossary"]:
        if g["term"] not in have_t:
            store.GlossaryStore.create(
                project_id, str(g["term"]), alias=list(g["alias"] or []),
                definition=str(g["definition"] or ""), source="file")
    if parsed.get("skipped"):
        logger.info("[rules-file] 跳过不可解析行 %s 条(文件容错, 不阻塞)",
                    parsed["skipped"])


def append_convention(root: str, project_id: str, rule_text: str,
                      scenarios: Optional[list] = None) -> Dict[str, object]:
    """采纳落文件: `## 命名规约` 章节追加一行(章节缺失则建); 随即重建缓存。

    文件不存在 → {written: False, hint} 只入 store(提案确认照旧), 提示先 init。
    """
    rule_text = (rule_text or "").strip()
    if not rule_text:
        return {"written": False, "error": "规则文本为空"}
    path = agents_md_path(root)
    if not os.path.isfile(path):
        return {"written": False,
                "hint": "AGENTS.md 不存在——规约已暂存缓存, 可运行 agents.md.init 并入初稿"}
    content = open(path, encoding="utf-8").read()
    sc = (scenarios or ["general"])[0] if scenarios else ""
    line = f"- [{sc}] {rule_text}" if sc else f"- {rule_text}"
    if f"## {SEC_CONVENTIONS}" in content:
        # 追加到章节最后一行之后
        out, inside, last_rule_idx = [], False, -1
        for ln in content.splitlines():
            if ln.startswith("#"):
                inside = ln.rstrip() == f"## {SEC_CONVENTIONS}"
            elif inside and _RULE_LINE.match(ln):
                last_rule_idx = len(out)
            out.append(ln)
        out.insert(last_rule_idx + 1, line)
        new = "\n".join(out) + "\n"
    else:
        new = content.rstrip() + f"\n\n## {SEC_CONVENTIONS}\n\n{line}\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new)
    ensure_rules_synced(root, project_id, force=True)
    return {"written": True, "hash": _sha(new)}
