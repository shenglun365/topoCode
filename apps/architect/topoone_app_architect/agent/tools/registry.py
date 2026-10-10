"""architect 工具注册表(工具层) — skills/tools 元数据注册。

P1 自 req_agent.py 迁入(注册表数据结构 + 装饰器 + 策略常量)。
工具 handler 本体仍注册于此表(经 req_agent 兼容层装饰器)；
执行环(run_arch_tool/参数收敛/修复)P2 随编排器迁入执行面。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

# ── Skills 注册表(architect 专属) ──────────────────────────────────────

_ARCH_SKILLS: List[Dict[str, Any]] = []


def register_architect_skill(name: str, description: str = "",
                             steps: int = 1, category: str = "requirement-analysis") -> Callable:
    """类/函数装饰器：注册 architect 专属技能元数据(与主后端 skill_registry 同形)。"""
    def decorator(fn):
        _ARCH_SKILLS.append({
            "name": name, "description": description, "steps": steps, "category": category,
        })
        return fn
    return decorator


def architect_skills() -> List[Dict[str, Any]]:
    seen: set = set()
    out = []
    for s in _ARCH_SKILLS:
        if s["name"] not in seen:
            seen.add(s["name"])
            out.append(s)
    return out


# ── Tools 注册表(architect 专属: 知识库检索 / 项目上下文) ──────────────

_ARCH_TOOLS: Dict[str, Dict[str, Any]] = {}


def derive_params_doc(fn: Callable) -> str:
    """从 handler 签名自动生成 params_doc 兜底(MS-B1: 签名是唯一真相源)。

    无默认值位置参数标 (必填); root/project(系统自动注入)与 *args/**kwargs
    不入文档; Optional[X] 剥壳取 X。产物只有形状无语义——语义说明仍应手写
    在注册点 params_doc, 本函数仅消灭「零参数教育」的生存空间(cv-3 类事故)。
    """
    import inspect
    import typing as _t
    try:
        sig = inspect.signature(fn)
        hints = _t.get_type_hints(fn)
    except Exception:  # noqa: BLE001
        return ""
    parts = []
    for pname, p in sig.parameters.items():
        if pname in ("root", "project") \
                or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        hint = hints.get(pname)
        tn = ""
        if hint is not None:
            if _t.get_origin(hint) is _t.Union:
                inner = [a for a in _t.get_args(hint) if a is not type(None)]
                if len(inner) == 1:
                    hint = inner[0]
            origin = _t.get_origin(hint)
            if origin is None:
                tn = getattr(hint, "__name__", str(hint))
            elif origin in (list, dict):
                tn = "list" if origin is list else "dict"
            else:
                tn = str(hint).replace("typing.", "")
        has_default = p.default is not inspect.Parameter.empty
        parts.append(f'"{pname}": {tn or "值"}{"" if has_default else "(必填)"}')
    return "{" + ", ".join(parts) + "}"


def register_architect_tool(name: str, description: str = "",
                            params_doc: str = "", brief: str = "",
                            arg_aliases: Optional[Dict[str, str]] = None,
                            arg_alias_sections: Optional[Dict[str, str]] = None,
                            flags: Optional[Dict[str, bool]] = None,
                            requires: tuple = (),
                            doc_after: str = "",
                            ) -> Callable:
    """注册工具。B4 单源: brief(能力清单一行简介)/params_doc(参数形状)为
    能力文档渲染元数据, 注册点直接传参(优先于 prompt.py 迁移表)。
    arg_aliases: 参数别名声明(机制与契约分离——执行环统一折叠, 工具自声明
    兼容面)。{别名参数: 目标参数}: 模型误传别名时确定性改名续执行, 与
    _coerce_args 类型收敛同族, 是 cv-188 报错兜底的前置防线。注册时
    fail-fast: 目标参数必须存在于 handler 签名(防契约漂移)。
    arg_alias_sections: {别名参数: 节标题}——多别名汇同一目标时按声明序以
    '## {节标题}' 分节拼接; 单别名直填不带节。
    flags: 行为标志位(MS-D1, 收编散落同族工具名集合)——已定义位:
      landing_card(落卡工具: 空收尾=卡片即产物, cv-196/203)
      deny_archive(归档会话禁写, PR1)  artifact(自动沉淀知识单元)
      hidden(能力文档隐藏: 不入工具清单仍可调用)
    requires: 前置条件声明(词汇单源)——已定义: "boundReq"(会话已绑定需求,
    GU 限面剔除未满足条件的工具, MS-D2)。
    doc_after: 能力文档锚定 id(清单行后附加说明文档, 如层级约定)。
    注: 存量迁移表(TOOL_BRIEFS/TOOL_PARAM_DOCS)在 cognition/prompt.py——
    它们是提示词内容而非执行元数据, 放 cognition 层避免反向依赖本模块。"""
    def decorator(fn):
        aliases = dict(arg_aliases or {})
        if aliases:
            import inspect as _inspect
            sig_params = set(_inspect.signature(fn).parameters)
            bad = {a: t for a, t in aliases.items() if t not in sig_params}
            if bad:
                raise ValueError(
                    f"工具 {name} 的 arg_aliases 目标参数不存在于签名: {bad}"
                    f"(签名参数: {sorted(sig_params)})")
        _ARCH_TOOLS[name] = {"name": name, "description": description,
                             "handler": fn,
                             "params_doc": params_doc, "brief": brief,
                             "arg_aliases": aliases,
                             "arg_alias_sections": dict(arg_alias_sections or {}),
                             "flags": dict(flags or {}),
                             "requires": tuple(requires),
                             "doc_after": str(doc_after or "")}
        return fn
    return decorator


def tools_with_flag(flag: str) -> frozenset:
    """按标志位取工具集(MS-D1: 同族概念单源——散落各模块的工具名集合收编)。"""
    return frozenset(n for n, e in _ARCH_TOOLS.items()
                     if e.get("flags", {}).get(flag))


def tool_requires_met(name: str, facts: Dict[str, bool]) -> bool:
    """前置条件判定(MS-D2): 注册声明的 requires 全部满足。"""
    entry = _ARCH_TOOLS.get(name) or {}
    for req in entry.get("requires") or ():
        if not facts.get(req, False):
            return False
    return True


def resolve_arg_aliases(entry: Dict[str, Any],
                        kwargs: Dict[str, Any]) -> tuple:
    """通用别名归一(纯函数, 零工具名/参数名字面量): 按注册声明折叠别名参数。

    语义(与 _coerce_args 同层的确定性兜底, 非语义修复):
    - 别名键始终弹出(否则 fn(**kwargs) 必 TypeError);
    - 显式参数优先: 目标已给出且非空 → 别名丢弃;
    - 目标缺省 → 别名填充: 单别名原值直填(类型交 _coerce_args 收敛);
      多别名汇同一目标按声明序以 arg_alias_sections 分节拼接(缺省裸值
      空行拼接)。
    返回 (新 kwargs, [(别名, 目标), ...] 命中清单)——调用方记遥测。
    """
    aliases: Dict[str, str] = entry.get("arg_aliases") or {}
    if not aliases or not kwargs:
        return kwargs, []
    hit = [a for a in aliases if a in kwargs]
    if not hit:
        return kwargs, []
    sections: Dict[str, str] = entry.get("arg_alias_sections") or {}
    order = {a: i for i, a in enumerate(aliases)}
    out = dict(kwargs)
    mapped: List[tuple] = []
    by_target: Dict[str, List[str]] = {}
    for a in hit:
        by_target.setdefault(aliases[a], []).append(a)
    for target, alias_list in by_target.items():
        alias_list.sort(key=lambda a: order[a])
        explicit = out.get(target)
        if isinstance(explicit, str):
            explicit = explicit.strip()
        vals: List[tuple] = []
        for a in alias_list:
            v = out.pop(a)
            if explicit:
                continue            # 显式参数优先, 别名丢弃
            if isinstance(v, str):
                v = v.strip()
            if v in (None, "", [], {}):
                continue
            vals.append((a, v))
            mapped.append((a, target))
        if vals and not explicit:
            if len(vals) == 1:
                out[target] = vals[0][1]
            else:
                parts = []
                for a, v in vals:
                    title = sections.get(a)
                    parts.append(f"## {title}\n{v}" if title else str(v))
                out[target] = "\n\n".join(parts)
    return out, mapped


def architect_tools() -> List[Dict[str, str]]:
    return [{"name": t["name"], "description": t["description"]} for t in _ARCH_TOOLS.values()]


def architect_tools_full() -> List[Dict[str, str]]:
    """全量元数据(含 brief/params_doc)——能力展示面(工具管理页)单源。

    MS-B1: params_doc 空时以签名自动生成兜底(形状级), 管理页不再出现
    「无文档」条目; 手写语义文档仍在注册点。
    """
    out = []
    for t in _ARCH_TOOLS.values():
        pd = (t.get("params_doc") or "").strip() \
            or derive_params_doc(t["handler"])
        out.append({"name": t["name"], "description": t.get("description") or "",
                    "brief": t.get("brief") or "", "params_doc": pd})
    return out




# 归档会话上禁止的动作类工具(生成/落库/指派); 检索与读取类不在此列
# MS-D1: 由注册 flags(deny_archive) 派生——须在工具注册完成后(惰性)调用,
# 模块级快照会捕到空集(注册晚于 registry import)。

# v2 统一会话: 规约状态机工具在快捷挡退役(严格挡恢复可用, run_arch_tool 按挡放行)
# ——快捷挡模型误调时给出引导而非静默失败(P2 物理删除注册)。
# 文案必须是快捷挡语义(此映射只在 quick 挡触达模型; strict 挡放行不会看到)。
_RETIRED_TOOLS = {
    "req.finalize": "req.finalize 已退役——需求卡创建即 ready, 无需确认步骤。",
}
