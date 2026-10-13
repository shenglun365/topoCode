"""核心资产守护评估引擎(2610 P1)——architect 视角, 评估性非阻断。

裁决(2026-10-12): 三层标记(asset|component|file) / 先确定性量化 /
任务链自动+直通轻量自动(配置可关, collab override "core_guard_injection") /
规约=skill 式自由文本(rules_md)。

pre-flight(执行前): 改动面(边界文件/允许范围) ∩ 标记集 → 触碰清单+规约
  → 注入 context_pack(任务链)与直通指令尾部(轻量)。
post-flight(执行后): changed_files → 命中标记 + 确定性程度量化(文件/资产
  stale 迁移数预留) → task.receipt 扩展输出。

分层合规: 本模块仅依赖 store/sem 同层与 common, 不引 arch_routes。
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger("arch.sem.core_guard")

# 配置开关键(collab overrides; 缺省开启, 显式 false 关闭——与会话 UI 开关同源)
CONFIG_KEY = "core_guard_injection"

_PATH_RE = re.compile(r"[\w./-]+\.\w{1,8}")


def guard_enabled(getter) -> bool:
    """读取配置(缺省开)。getter=CollabConfigStore.get 同型。"""
    try:
        from ..agent.compensation.overrides import (
            override_enabled, read_overrides)
        return override_enabled(read_overrides(getter), CONFIG_KEY)
    except Exception:  # noqa: BLE001 — 配置面失败按缺省开
        return True


def _norm(p: str) -> str:
    return (p or "").strip().replace("\\", "/").lstrip("./")


def load_marks(project_id: str) -> List[dict]:
    # 守护消费单口(2610 重构): 挂载关联聚合展开(挂载即核心, 无分级)。
    if not project_id:
        return []
    try:
        from .. import store
        return store.TargetRuleStore.list_effective(project_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("[core-guard] 标记读取失败 pid=%s: %s", project_id, e)
        return []


def _file_index(project_id: str) -> Dict[str, List[dict]]:
    """文件路径 → 命中标记(file 层精确/后缀匹配 + component 层 owns + asset 层锚点)。"""
    marks = load_marks(project_id)
    if not marks:
        return {}
    # component 层: 组件 → owns 文件清单(catalog 单源)
    comp_owns: Dict[str, List[str]] = {}
    for m in marks:
        if m.get("targetType") != "component":
            continue
        try:
            from ..common import build_component_catalog
            root = _root_of(project_id)
            cat = build_component_catalog(root, project_id) or {}
            for c in (cat.get("components") or []):
                if str(c.get("id") or "") == str(m.get("targetId") or "") \
                        or str(c.get("name") or "") == str(m.get("targetId") or ""):
                    comp_owns[_norm(str(m.get("targetId") or ""))] = \
                        [_norm(f) for f in (c.get("owns") or [])]
                    break
        except Exception as e:  # noqa: BLE001
            logger.debug("[core-guard] 组件归属读取失败: %s", e)
    # asset 层: 语义资产 → 锚点文件(与 acceptance._assets_for_files 同口径)
    asset_files: Dict[str, List[str]] = {}
    for m in marks:
        if m.get("targetType") != "asset":
            continue
        try:
            from .. import store
            for a in (store.SemanticAssetsStore.all_status(project_id, limit=20000) or []):
                if str(a.get("id") or "") == str(m.get("targetId") or ""):
                    refs = a.get("astRefs") or []
                    asset_files[_norm(str(m.get("targetId") or ""))] = \
                        [_norm((r or {}).get("file") or "") for r in refs if (r or {}).get("file")]
                    break
        except Exception as e:  # noqa: BLE001
            logger.debug("[core-guard] 资产锚点读取失败: %s", e)

    idx: Dict[str, List[dict]] = {}
    for m in marks:
        tt = str(m.get("targetType") or "")
        tid = _norm(str(m.get("targetId") or ""))
        if tt == "file":
            idx.setdefault(tid, []).append(m)
        elif tt == "component":
            for f in comp_owns.get(tid, []):
                idx.setdefault(f, []).append(m)
        elif tt == "asset":
            for f in asset_files.get(tid, []):
                idx.setdefault(f, []).append(m)
    return idx


def _root_of(project_id: str) -> str:
    try:
        from .. import store
        return str((store.ProjectsStore.get(project_id) or {}).get("rootPath") or "")
    except Exception:  # noqa: BLE001
        return ""


def match_files(project_id: str, files: List[str]) -> List[dict]:
    """改动文件清单 → 命中标记(去重保序)。"""
    idx = _file_index(project_id)
    if not idx or not files:
        return []
    hits: List[dict] = []
    seen = set()
    for f in files:
        nf = _norm(str(f or ""))
        if not nf:
            continue
        for m in idx.get(nf, []) + _suffix_hits(idx, nf):
            key = str(m.get("id") or "")
            if key not in seen:
                seen.add(key)
                hits.append(m)
    return hits


def _suffix_hits(idx: Dict[str, List[dict]], f: str) -> List[dict]:
    out = []
    for key, marks in idx.items():
        if key and (f.endswith("/" + key) or key.endswith("/" + f)) and key != f:
            out.extend(marks)
    return out


def match_text(project_id: str, text: str) -> List[dict]:
    """轻量文本匹配(直通回合): 消息中出现的文件路径/标记 id/标题词命中。"""
    marks = load_marks(project_id)
    if not marks or not text:
        return []
    paths = {p for p in _PATH_RE.findall(text or "") if "/" in p or "." in p}
    hits = []
    for m in marks:
        tid = str(m.get("targetId") or "")
        title = str(m.get("title") or "")
        if ((tid and (tid in text or _norm(tid) in paths))
                or (title and title[:20] and title[:20] in text)):
            hits.append(m)
    return hits


def preflight_md(project_id: str, files: List[str],
                 scope_hints: Optional[List[str]] = None) -> str:
    """执行前评估段(markdown; 无命中返回空——零噪音)。"""
    files = [str(f) for f in (files or []) if f]
    hints = [str(h) for h in (scope_hints or []) if h]
    marks = match_files(project_id, files)
    if not marks and hints:
        # 允许范围(语义别名)命中标题/ id → 一并提示
        text = " ".join(hints)
        marks = match_text(project_id, text)
    if not marks:
        return ""
    lines = ["### 核心资产守护（评估性提示——不阻断, 规约以代码事实为准）"]
    for m in marks[:10]:
        lvl = "★"
        rules = str(m.get("rulesMd") or "").strip()
        lines.append(
            f"- {lvl} [{m.get('targetType')}] **{m.get('title') or m.get('targetId')}**"
            + (f"：{rules}" if rules else "（未附规约文本）"))
    lines.append("以上为用户标记的核心资产；如本次改动触及, 请对照规约自检并在回执中说明。")
    return "\n".join(lines)


def preflight_light_md(project_id: str, message: str) -> str:
    """直通回合轻量评估段(消息文本匹配; 无命中且有标记时给一行自查指针)。"""
    marks = match_text(project_id, message or "")
    if marks:
        lines = ["### 核心资产守护（评估性提示——不阻断）"]
        for m in marks[:6]:
            rules = str(m.get("rulesMd") or "").strip()
            lines.append(f"- ★ [{m.get('targetType')}] **{m.get('title') or m.get('targetId')}**"
                         + (f"：{rules}" if rules else ""))
        return "\n".join(lines)
    total = len(load_marks(project_id))
    if total:
        return (f"### 核心资产守护（评估性）\n"
                f"本项目有 {total} 项核心资产标记；如本次诉求涉及其文件/组件, "
                "改前自查 `map.core`（核心清单+绑定规约）。")
    return ""


def postflight_report(project_id: str, changed_files: List[str]) -> Optional[dict]:
    """执行后确定性评估: 命中标记 + 修改程度量化(评估性, 不改任务状态)。"""
    files = [str(f) for f in (changed_files or []) if f]
    marks = match_files(project_id, files)
    if not marks:
        return None
    hit_files = set()
    idx = _file_index(project_id)
    for f in files:
        nf = _norm(f)
        if nf in idx or _suffix_hits(idx, nf):
            hit_files.add(f)
    hit_list = sorted(hit_files)
    return {
        "marks": [{"type": m.get("targetType"),
                   "title": m.get("title") or m.get("targetId"),
                   "rules": str(m.get("rulesMd") or "")[:400]} for m in marks],
        "hitFiles": hit_list[:40],
        "totalChanged": len(files),
        "hitChanged": len(hit_files),
        # 修改程度(确定性): 纯命中数驱动(2610 重构: critical 分级退役)
        "extent": {
            "hitRatio": round(len(hit_files) / len(files), 2) if files else 0.0,
            "verdict": "heavy" if len(hit_files) > 5
                       else ("medium" if hit_files else "light"),
        },
        "assetImpact": _assets_on_files(project_id, hit_list),
        "componentRadius": _component_radius(project_id, hit_list),
    }


def _assets_on_files(project_id: str, files: List[str]) -> List[dict]:
    """触及文件上的语义资产(名称/类型/stale 态)——代码锚点联动数据源。

    R1 合规: 不引 arch_routes.acceptance——此处与 acceptance._assets_for_files
    同口径直读 store(首锚点文件 ∈ 范围的 active/stale 资产)。"""
    try:
        from .. import store
        want = {f for f in files if f}
        out = []
        for a in (store.SemanticAssetsStore.all_status(project_id, limit=20000) or []):
            if len(out) >= 20:
                break
            if (a.get("status") or "active") not in ("active", "stale"):
                continue
            refs = a.get("astRefs") or []
            f0 = _norm((refs[0] or {}).get("file") or "") if refs else ""
            if f0 and any(f0 == w or f0.endswith("/" + w) or w.endswith("/" + f0)
                          for w in want):
                out.append({"id": str(a.get("id") or ""),
                            "name": str(a.get("name") or "")[:60],
                            "kind": str(a.get("kind") or ""),
                            "status": str(a.get("status") or "active")})
        return out
    except Exception as e:  # noqa: BLE001 — 资产面失败降级空(不阻塞评估)
        logger.debug("[core-guard] 资产影响读取失败: %s", e)
        return []


def _component_radius(project_id: str, files: List[str]) -> List[dict]:
    """触及文件 → 归属组件及其依赖出/入度(结构影响半径; catalog 单源)。"""
    try:
        from ..common import build_component_catalog
        root = _root_of(project_id)
        comps = (build_component_catalog(root, project_id) or {}).get("components") or []
        nf = {_norm(f) for f in files}
        out = []
        for c in comps:
            owns = {_norm(f) for f in (c.get("owns") or [])}
            if not (owns & nf):
                continue
            out.append({"id": str(c.get("id") or ""), "name": str(c.get("name") or "")[:40],
                        "depsOut": len(c.get("dependsOn") or c.get("dependencies") or []),
                        "depsIn": len(c.get("dependedBy") or [])})
            if len(out) >= 8:
                break
        return out
    except Exception as e:  # noqa: BLE001 — 组件面失败降级空
        logger.debug("[core-guard] 组件影响半径读取失败: %s", e)
        return []


def postflight_md(project_id: str, changed_files: List[str]) -> str:
    """执行后评估段(markdown; 无命中返回空)。"""
    r = postflight_report(project_id, changed_files)
    if not r:
        return ""
    verdict_label = {"light": "轻", "medium": "中", "heavy": "重"}[r["extent"]["verdict"]]
    lines = [f"### 核心资产变更评估（确定性 · 程度: {verdict_label}）",
             f"- 改动 {r['totalChanged']} 文件, 其中触及核心标记 {r['hitChanged']} 个"]
    for m in r["marks"][:10]:
        lines.append(f"- ★ [{m['type']}] **{m['title']}**"
                     + (f"：{m['rules'][:160]}" if m["rules"] else ""))
    if r["hitFiles"]:
        lines.append("- 触及文件: " + ", ".join(f"`{f}`" for f in r["hitFiles"][:8])
                     + ("…" if len(r["hitFiles"]) > 8 else ""))
    lines.append("（评估性提示: 请对照绑定规约复核; 与规约冲突时在回执/说明中给出理由）")
    return "\n".join(lines)
