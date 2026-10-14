"""直通上下文组装(cv-266): 历史脉络注入 + architect MCP 默认接线。

从 proxy.py 拆出(file_size_gate §8.2 拆分纪律, 通道编排与上下文组装分离):
- _history_brief      本会话此前对话脉络(确定性拼接, 零 LLM)
- _merge_mcp_servers  ctx.* 检索面默认并入(用户自配优先, 形状按 caps 单源)
- _mcp_tools_brief    工具可用性告知(随 workspaceFiles 下发)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# 历史脉络默认注入缺省容量(字符; 执行器 config historyContextChars 覆盖, 0=关)
_HISTORY_CAP_DEFAULT = 3000


def _history_brief(conv_id: str, cap_chars: int,
                   exclude_msg_ids: set = frozenset()) -> str:
    """本会话此前对话脉络(确定性拼接, 零 LLM; cv-266 用户裁定: 默认注入)。

    新执行器会话不携带历史——注入最近轮次速览(user 原文/执行器产出首行,
    逐条截断), 深层历史由执行器经 MCP ctx.* 按需检索(见 _mcp_tools_brief)。
    """
    from ... import store as _st
    # messages()=ASC+LIMIT 取最早 N 条 → 大窗口取回后尾部切最近(速览语义)
    msgs = (_st.ConversationsStore.messages(conv_id, limit=400) or [])[-60:]
    lines: list = []
    for m in msgs:                                 # 时间正序
        if m.get("id") in exclude_msg_ids:
            continue
        role = "user" if (m.get("role") or "") == "user" else "executor"
        first = next((ln for ln in str(m.get("content") or "").splitlines()
                      if ln.strip()), "")
        if not first:
            continue
        lines.append(f"▸ [{role}] {first[:160]}")
    if not lines:
        return ""
    lines = lines[-40:]                            # 最近 40 条速览行
    body = "\n".join(lines)
    if len(body) > cap_chars:
        body = body[:cap_chars]
    return ("以下是本会话此前的对话记录（仅保留要点；完整历史可经 MCP 工具"
            f' ctx.get(conversation="{conv_id}") 按需检索）：\n{body}')


def _merge_mcp_servers(ecfg: dict, etype: str) -> Optional[Dict[str, Any]]:
    """architect MCP 默认接线(cv-266) + 用户自配合并(用户同名项优先)。

    能力对齐(caps 单源): cline=list(McpServerSpec) / opencode=dict /
    codex=None(adapter 不消费——不注入不告知, 不虚报能力)。"""
    from .exec_bridge import ARCH_BASE
    from .capabilities import caps
    shape = str(caps(etype).get("mcp_shape") or "")
    url = f"{ARCH_BASE}/mcp"
    user_cfg = (ecfg or {}).get("mcp_servers")
    if shape == "list":
        user_list = [e for e in user_cfg if isinstance(e, dict)] \
            if isinstance(user_cfg, list) else []
        if any(str(e.get("name") or "") == "topo-architect" for e in user_list):
            return user_list           # 用户自配优先, 不重复注入
        return [{"name": "topo-architect", "transport": "streamableHttp",
                 "url": url}, *user_list]
    if shape == "dict":
        user_dict = user_cfg if isinstance(user_cfg, dict) else {}
        return {"topo-architect": {"url": url, "timeout": 60000}, **user_dict}
    return None


def _mcp_tools_brief(conv_id: str, mcp, project_id: str = "") -> str:
    """工具可用性告知(执行器不知道工具存在就不会用)。无 MCP 面返回空。

    2610 cv-9/11/12/14 统筹升级: 资产地图段(map.*, 一律传 project)+命名
    形态说明+ctx.* 段; project_id 内联免摸索(多项目环境缺省无法唯一定位,
    执行器两轮实测踩坑)。直通(proxy)与任务链(dispatch)同源注入。"""
    wired = "topo-architect" in mcp if isinstance(mcp, dict) else any(
        str(e.get("name") or "") == "topo-architect"
        for e in (mcp or []) if isinstance(e, dict))
    if not wired:
        return ""
    proj_line = (f'\n- **一律传 `project="{project_id}"`**'
                 "（多项目环境缺省无法唯一定位）" if project_id else "")
    return (
        "\n## topo-architect MCP 已接线\n"
        "工具以服务名前缀注册，以你工具面实际注册名为准"
        "（cline 形如 `topo-architect__<tool>_<hash>`，"
        "opencode 形如 `topo-architect_<tool>`）。\n"
        "### 资产地图（写码/架构分析前先看）\n"
        "- `map.overview` — 组件目录/语义资产统计/KB 基线视图\n"
        "- `map.component(name)` / `map.assets(query, kind?, limit?)`"
        " — 组件档案 / 语义资产检索\n"
        "- `map.rules` / `map.graph(kind)` — 规约全集 / 依赖关系图(mermaid)"
        + proj_line + "\n"
        "### 历史上下文\n"
        f'- `ctx.get(conversation="{conv_id}")` — 本会话上下文包(摘要+关键单元)\n'
        "- `ctx.search(query, type?, limit?)` — 跨会话检索(消息/产物/决策/回执)\n"
        f'- `ctx.summarize(conversation="{conv_id}")` — 生成/刷新本会话摘要\n'
        "需要更早或完整的历史背景时按需调用, 不必依赖速览脉络。")

