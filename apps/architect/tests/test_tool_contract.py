"""工具契约硬门禁(MS-B2)——签名是唯一真相源, 漂移即红。

四条断言(逐注册工具):
 ① params_doc 深度1参数名 ⊆ handler 签名 ∪ arg_aliases 键 ∪ 豁免清单
 ② 无默认值必填参数(root/project 系统注入除外)必须出现在 params_doc
 ③ arg_aliases 目标参数 ∈ handler 签名(注册期 fail-fast 的双保险)
 ④ description 非空(能力清单渲染的最低契约)

豁免清单逐项附理由; 豁免项消失时必须从清单移除(防豁免腐化)。
"""
from __future__ import annotations

import inspect
import re

import pytest

from topoone_app_architect.agent.tools.registry import (
    _ARCH_TOOLS, derive_params_doc)


@pytest.fixture(autouse=True)
def _prod_tool_registry():
    """对齐生产注册态(golden 同款): ctx.*/probe/评估/提炼经 orchestrator
    幂等注册——空注册表下的门禁是空转绿灯, 必须在生产形态断言。"""
    from topoone_app_architect.agent.orchestrator import register_session_tools
    register_session_tools()

# 参数名豁免: {工具: {参数名: 理由}}——豁免的存在性也会被断言(见下)
PARAM_EXEMPT = {
    "req.amend": {
        "title": "cv-188 **extra 折叠通道吸收(非签名参数); MS-D 收编 arg_aliases 后移除",
    },
}

_SYS_INJECTED = {"root", "project"}   # run_arch_tool 按签名自动注入


def _depth1_param_names(pd: str) -> set:
    """params_doc(JSON-ish 放宽格式)深度1参数名提取。

    键形态: "name" 后随可选 ? 与 ':'; 嵌套对象/数组内的引号词(如
    asset.semantic.save 的 {"name","kind"} 示例)不入参。跨多个顶层
    JSON 块(如 req.amend 尾注的第二示例)均收集——都是模型可见的
    「教出来的参数名」。
    """
    keys = set()
    depth = 0
    i, n = 0, len(pd)
    while i < n:
        c = pd[i]
        if c == '"':
            if depth == 1:
                m = re.match(r'"(\w+)"\s*\??\s*:', pd[i:])
                if m:
                    keys.add(m.group(1))
                    i += m.end()
                    continue
            i += 1
            while i < n and pd[i] != '"':
                i += 1
            i += 1
            continue
        if c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
        i += 1
    return keys


def _sig_params(fn) -> tuple:
    """(全部参数名, 必填参数名)——root/project 与 *args/**kwargs 除外。"""
    all_p, req_p = set(), set()
    for pname, p in inspect.signature(fn).parameters.items():
        if pname in _SYS_INJECTED or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        all_p.add(pname)
        if p.default is inspect.Parameter.empty:
            req_p.add(pname)
    return all_p, req_p


def test_every_tool_params_doc_subset_of_signature():
    """①文档教的参数名必须存在于签名(或声明的别名面)。"""
    bad = []
    for name, entry in sorted(_ARCH_TOOLS.items()):
        pd = (entry.get("params_doc") or "").strip() \
            or derive_params_doc(entry["handler"])
        if not pd:
            continue
        sig_p, _ = _sig_params(entry["handler"])
        doc_p = _depth1_param_names(pd)
        allowed = sig_p | set(entry.get("arg_aliases") or {}) \
            | set(PARAM_EXEMPT.get(name, {}))
        extra = doc_p - allowed
        if extra:
            bad.append(f"{name}: 文档参数 {sorted(extra)} 不在签名/别名/豁免内")
    assert not bad, "params 漂移(教了不存在的参数):\n" + "\n".join(bad)


def test_every_tool_required_params_documented():
    """②必填参数必须在 params_doc 出现(漏教=模型漏传 TypeError)。"""
    bad = []
    for name, entry in sorted(_ARCH_TOOLS.items()):
        pd = (entry.get("params_doc") or "").strip() \
            or derive_params_doc(entry["handler"])
        if not pd:
            bad.append(f"{name}: 零参数文档")
            continue
        _, req_p = _sig_params(entry["handler"])
        doc_p = _depth1_param_names(pd)
        missing = req_p - doc_p
        if missing:
            bad.append(f"{name}: 必填参数 {sorted(missing)} 未入文档")
    assert not bad, "必填参数缺文档:\n" + "\n".join(bad)


def test_every_tool_alias_targets_in_signature():
    """③别名目标 ∈ 签名(注册期 fail-fast 的运行时双保险)。"""
    bad = []
    for name, entry in sorted(_ARCH_TOOLS.items()):
        sig_p, _ = _sig_params(entry["handler"])
        for alias, target in (entry.get("arg_aliases") or {}).items():
            if target not in sig_p:
                bad.append(f"{name}: 别名 {alias}→{target} 目标不在签名")
    assert not bad, "\n".join(bad)


def test_every_tool_has_description():
    """④能力清单最低契约: description 非空(brief 兜底渲染依赖它)。"""
    bad = [name for name, entry in sorted(_ARCH_TOOLS.items())
           if not (entry.get("description") or "").strip()]
    assert not bad, f"description 为空的工具: {bad}"


def test_param_exemptions_still_valid():
    """豁免清单防腐化: 豁免参数仍需真实出现在对应文档中(已收敛则必须移除)。"""
    stale = []
    for tool, params in PARAM_EXEMPT.items():
        entry = _ARCH_TOOLS.get(tool)
        if entry is None:
            stale.append(f"{tool}: 工具不存在(豁免悬空)")
            continue
        pd = (entry.get("params_doc") or "").strip() \
            or derive_params_doc(entry["handler"])
        doc_p = _depth1_param_names(pd)
        for p in params:
            if p not in doc_p:
                stale.append(f"{tool}.{p}: 文档已不含该参数——豁免应移除")
    assert not stale, "\n".join(stale)


def test_derive_params_doc_marks_required():
    """B1 兜底生成器: 必填标注 + root/project 剔除(机制自身契约)。"""

    def _demo(a: str, b: int = 1, root=None, project=None):
        return a

    pd = derive_params_doc(_demo)
    keys = _depth1_param_names(pd)
    assert keys == {"a", "b"}
    assert "(必填)" in pd and "root" not in pd and "project" not in pd
