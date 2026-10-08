"""资产地图 MCP 工具集 — architect 对外 MCP 服务的能力层（S4）。

设计：
- 纯函数 `run_tool(name, args) -> str(Markdown)`，stdio/HTTP 双传输共用；
- 输出 Markdown 文档（heading/表格/mermaid/文件锚点），供外部 AI coding agent
  在写码前理解架构资产（上下文预算友好：overview 给目录，按需下钻）；
- 数据源全部复用现有能力：KB 基线视图组件目录（build_component_catalog/
  build_architecture_model）、语义资产（SemanticAssetsStore）、编码规约（KB 文档）、
  命名规约/词汇表（NamingConventionStore/GlossaryStore）；
- 每次调用经 _record 落 arch_mcp_calls（外部调用页可见）。

工具：map.overview / map.component / map.assets / map.rules / map.graph
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

TOOLS = [
    {"name": "map.overview", "desc": "项目资产地图总览（组件目录/资产统计/覆盖率/基线视图），写码前先看",
     "args": {"project": "项目 id（多项目时必填，可先 project.list）"}},
    {"name": "map.component", "desc": "组件档案：文件清单/语义资产/依赖出入", "args": {"name": "组件名或 id", "project": "项目 id"}},
    {"name": "map.assets", "desc": "语义资产检索（kind/level/关键词）", "args": {"query": "关键词", "kind": "类别", "level": "粒度(business/implementation/logic)", "limit": "条数", "project": "项目 id"}},
    {"name": "map.rules", "desc": "规约全集：编码规约(自管)+词汇表+项目规则(.topo/rules)（编码必须遵守）", "args": {"project": "项目 id"}},
    {"name": "map.graph", "desc": "关系图（mermaid）：component=组件依赖图 / semantic=语义关系图", "args": {"kind": "component|semantic", "project": "项目 id"}},
    {"name": "ctx.search", "desc": "跨会话检索历史上下文（单元/消息/备案文档；讨论关联结论先查这里）", "args": {"query": "关键词", "type": "单元类型", "conversation": "限定会话 id", "limit": "条数", "project": "项目 id"}},
    {"name": "ctx.get", "desc": "会话上下文包：摘要+关键单元+备案文档", "args": {"conversation": "会话 id", "project": "项目 id"}},
    {"name": "ctx.summarize", "desc": "生成/刷新会话摘要（标题+结论/决策/待办）", "args": {"conversation": "会话 id"}},
]


def _record(tool: str, detail: str, status: str = "ok") -> None:
    try:
        from .. import store
        from ..common import _id, _ts
        store.CollabConfigStore  # 触发 store 就绪
        import sqlite3
        # 直接落 mcp_calls 表（复用 mcp_collab 语义）
        from ..ctx import get_db
        db = get_db()
        db.execute(
            "INSERT INTO arch_mcp_calls (id, tool, input, output, status, time) "
            "VALUES (?,?,?,?,?,?)",
            (_id("MCP"), tool, f'{{"source":"mcp-server","detail":"{detail[:200]}"}}',
             "", status, _ts()))
        db.commit()
    except Exception as e:  # noqa: BLE001
        logger.debug("[mcp-tools] 记录调用失败: %s", e)


def _resolve_project_entry(project: Optional[str] = None) -> Optional[dict]:
    """MCP 工具的项目解析：显式 id > 唯一项目 > None（带提示）。"""
    from .. import store
    rows = store.ProjectsStore.all()
    if project:
        for r in rows:
            if r.get("id") == project or r.get("name") == project:
                return r
        return None
    bound = [r for r in rows if r.get("rootPath")]
    return bound[0] if len(bound) == 1 else None


def _pid_of(proj: Optional[dict]) -> str:
    return (proj or {}).get("id") or ""


def _md_header(title: str, proj: Optional[dict]) -> str:
    name = (proj or {}).get("name") or "(未指定)"
    pid = (proj or {}).get("id") or "-"
    return f"# {title}\n\n> 项目: **{name}** (`{pid}`)\n"


def tool_overview(project: Optional[str] = None) -> str:
    from ..common import build_component_catalog
    proj = _resolve_project_entry(project)
    if not proj:
        rows = [f"- {r.get('id')} {r.get('name','')}" for r in ([])
                ] or []
        from .. import store
        allp = [f"- `{r.get('id')}` {r.get('name','')}" for r in store.ProjectsStore.list()]
        return ("# 资产地图\n\n无法唯一定位项目，请传 project 参数。可用项目：\n"
                + "\n".join(allp or ["- (无)"]))
    out = [_md_header("资产地图总览", proj)]
    try:
        catalog = build_component_catalog(proj.get("rootPath"), proj.get("id")) or {}
        comps = catalog.get("components") or []
        out.append(f"组件 **{len(comps)}** 个（KB 基线视图：{'生效' if not catalog.get('empty') else '未挂载-空'}）\n")
        out.append("| 组件 | 层级 | 文件数 | 依赖(出/入) |")
        out.append("|---|---|---|---|")
        for c in comps[:80]:
            deps_out = len((c.get("dependsOn") or c.get("dependencies") or []))
            deps_in = len((c.get("dependedBy") or []))
            out.append(f"| `{c.get('name')}` | {c.get('level','')} | {c.get('fileCount', len(c.get('files') or []))} | {deps_out}/{deps_in} |")
        if len(comps) > 80:
            out.append(f"| … 共 {len(comps)} 个（map.component 查看单个） | | | |")
    except Exception as e:  # noqa: BLE001
        out.append(f"组件目录不可用：{e}")
    # 语义资产统计
    try:
        from .. import store
        pid = _pid_of(proj)
        stats: dict[str, int] = {}
        for a in store.SemanticAssetsStore.all(pid, limit=5000) or []:
            stats[a.get("kind", "?")] = stats.get(a.get("kind", "?"), 0) + 1
        if stats:
            out.append("\n## 语义资产\n")
            out.append("| kind | 数量 |")
            out.append("|---|---|")
            for k, v in sorted(stats.items(), key=lambda x: -x[1]):
                out.append(f"| {k} | {v} |")
    except Exception:  # noqa: BLE001
        pass
    out.append("\n> 下钻：`map.component(name=...)` 组件档案 / `map.assets(query=...)` 资产检索 / `map.rules()` 规约")
    return "\n".join(out)


def tool_component(name: str, project: Optional[str] = None) -> str:
    from ..common import build_component_catalog
    proj = _resolve_project_entry(project)
    if not proj:
        return "# 组件档案\n\n无法唯一定位项目，请传 project 参数。"
    out = [_md_header(f"组件档案: {name}", proj)]
    try:
        catalog = build_component_catalog(proj.get("rootPath"), proj.get("id")) or {}
        all_comps = catalog.get("components") or []
        name_of = {c.get("id"): c.get("name") or c.get("id") for c in all_comps}
        nl = name.lower()
        comp = next((c for c in all_comps
                     if nl in (c.get("id") or "").lower()
                     or nl in (c.get("name") or "").lower()), None)
        if not comp:
            return out[0] + f"\n未找到组件 `{name}`（用 map.overview 查看目录）"
        out.append(f"- id: `{comp.get('id')}` | 层级 {comp.get('level','')} | 边类型 {comp.get('edgeType','')}")
        desc = comp.get("description") or comp.get("summary") or ""
        if desc:
            out.append(f"\n{desc}\n")
        files = comp.get("files") or []
        if files:
            out.append("## 文件\n")
            out.extend(f"- `{f}`" for f in files[:60])
        deps = comp.get("dependsOn") or comp.get("dependencies") or []
        if deps:
            out.append("\n## 依赖(出)\n")
            out.extend(f"- `{name_of.get(d, d)}`" for d in deps[:40])
        rdeps = comp.get("dependedBy") or []
        if rdeps:
            out.append("\n## 被依赖(入)\n")
            out.extend(f"- `{name_of.get(d, d)}`" for d in rdeps[:40])
        # 组件内语义资产
        try:
            from .. import store
            pid = _pid_of(proj)
            comp_assets = [a for a in store.SemanticAssetsStore.all(pid, limit=2000) or []
                           if any(nl in ((a.get("scope") or {}).get("key") or "").lower()
                                  or nl in (a.get("file") or "").lower()
                                  for _ in [0])]
            comp_assets = [a for a in store.SemanticAssetsStore.all(pid, limit=2000) or []
                           if (a.get("scope") or {}).get("type") == "component"
                           and nl in str((a.get("scope") or {}).get("key", "")).lower()]
            if comp_assets:
                out.append("\n## 语义资产\n")
                out.append("| kind | level | 名称 | 状态 |")
                out.append("|---|---|---|---|")
                for a in comp_assets[:60]:
                    out.append(f"| {a.get('kind')} | {a.get('level','')} | {a.get('name')} | {a.get('status','')} |")
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        out.append(f"模型不可用：{e}")
    return "\n".join(out)


def tool_assets(query: str = "", kind: str = "", level: str = "", limit: int = 30,
                project: Optional[str] = None) -> str:
    proj = _resolve_project_entry(project)
    if not proj:
        return "# 语义资产\n\n无法唯一定位项目，请传 project 参数。"
    from .. import store
    rows = store.SemanticAssetsStore.search(_pid_of(proj), text=query, kind=kind,
                                            level=level,
                                            limit=min(int(limit or 30), 200)) or []
    out = [_md_header("语义资产检索", proj),
           f"条件: query=`{query}` kind=`{kind}` level=`{level}` → {len(rows)} 条\n"]
    out.append("| kind | level | 名称 | 文件 | 状态 |")
    out.append("|---|---|---|---|---|")
    for a in rows:
        f = (a.get("scope") or {}).get("key") or a.get("file") or ""
        out.append(f"| {a.get('kind')} | {a.get('level','')} | {a.get('name')} | `{f}` | {a.get('status','')} |")
    return "\n".join(out)


def tool_rules(project: Optional[str] = None) -> str:
    proj = _resolve_project_entry(project)
    if not proj:
        return "# 规约\n\n无法唯一定位项目，请传 project 参数。"
    pid = _pid_of(proj)
    out = [_md_header("规约全集", proj), "编码前必读；冲突时以人工覆盖层 > 用户显式 > 派生约束。\n"]

    out.append("## 编码规约（自管，architect 独立维护）\n")
    try:
        from .. import store
        convs = store.NamingConventionStore.list(pid, status="active") or []
        if convs:
            for c in convs[:50]:
                out.append(f"- [{c.get('scenario','')}] {c.get('ruleText') or c.get('rule') or c.get('text') or ''}")
        else:
            out.append("(自管规约为空——可在规约工作台人工登记或由提取派生)")
        glos = store.GlossaryStore.list(pid) or []
        if glos:
            out.append("\n## 词汇表\n")
            out.append("| 术语 | 含义 |")
            out.append("|---|---|")
            for g in glos[:60]:
                out.append(f"| {g.get('term')} | {g.get('definition') or g.get('meaning') or ''} |")
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(out)


def tool_graph(kind: str = "component", project: Optional[str] = None) -> str:
    from ..common import build_architecture_model
    proj = _resolve_project_entry(project)
    if not proj:
        return "# 关系图\n\n无法唯一定位项目，请传 project 参数。"
    try:
        if kind == "semantic":
            from .. import store
            rows = store.SemanticAssetsStore.all(_pid_of(proj), limit=800) or []
            out = [_md_header("语义关系图", proj), "```mermaid\ngraph LR"]
            seen = set()
            for a in rows:
                aid = a.get("id") or a.get("name")
                if aid and aid not in seen:
                    seen.add(aid)
                    out.append(f"  {aid}[\"{a.get('name')}<br/>{a.get('kind','')}\"]")
                for rel in (a.get("relations") or [])[:6]:
                    tgt = rel.get("target") or rel.get("to")
                    if tgt:
                        out.append(f"  {aid} -->|{rel.get('kind','')}| {tgt}")
            out.append("```")
            return "\n".join(out)
        catalog = build_component_catalog(proj.get("rootPath"), proj.get("id")) or {}
        comps = catalog.get("components") or []
        name_of = {c.get("id"): c.get("name") or c.get("id") for c in comps}
        out = [_md_header("组件依赖图", proj), "```mermaid\ngraph LR"]
        def _nid(cid):
            import re as _re
            return "c" + _re.sub(r"\W", "_", str(cid))[-24:]
        for c in comps[:120]:
            out.append(f"  {_nid(c.get('id'))}[\"{c.get('name')}\"]")
        for c in comps[:120]:
            for d in (c.get("dependsOn") or c.get("dependencies") or [])[:20]:
                out.append(f"  {_nid(c.get('id'))} --> {_nid(d)}")
        out.append("```")
        return "\n".join(out)
    except Exception as e:  # noqa: BLE001
        return f"# 关系图\n\n生成失败: {e}"


def run_tool(name: str, args: dict) -> str:
    """MCP 工具统一入口（两种传输共用）；调用落 mcp_calls 日志。"""
    handlers = {
        "map.overview": lambda: tool_overview(args.get("project")),
        "map.component": lambda: tool_component(args.get("name") or "",
                                                args.get("project")),
        "map.assets": lambda: tool_assets(args.get("query") or "",
                                          args.get("kind") or "",
                                          args.get("level") or "",
                                          int(args.get("limit") or 30),
                                          args.get("project")),
        "map.rules": lambda: tool_rules(args.get("project")),
        "map.graph": lambda: tool_graph(args.get("kind") or "component",
                                        args.get("project")),
    }
    if name.startswith("ctx."):
        from ..agent.memory import units as context_registry
        _record(name, f"{name} {args}")
        return context_registry.run_tool(name, args)
    fn = handlers.get(name)
    if not fn:
        return f"未知工具: {name}（可用: {', '.join(h for h in handlers)}）"
    try:
        result = fn()
        _record(name, f"{name} {args}")
        return result
    except Exception as e:  # noqa: BLE001
        _record(name, f"error: {e}", status="blocked")
        return f"工具执行失败: {e}"
