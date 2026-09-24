"""cv-187: 未关联 KB 项目自动关闭 kb.* 工具(提示面 + 执行面同口径)。

判定单源: project.kb_degraded(无项目或无 baselineId 基线, 全插件共用口径)。
- 提示面: turns/context._chat_context → kb_enabled=False → 能力文档裁 kb.*;
- 执行面: run_arch_tool 对 kb.* 拦截并给本地替代指引(internal 系统路径放行)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_kb_autoclose.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect import store

_KB_ARGS = [("kb.asset.search", {"text": "支付"}),
            ("kb.code_mappings", {"asset_ids": ["a1"]}),
            ("kb.baseline", {}),
            ("kb.graph", {"comp_ids": ["c1"]})]


def test_kb_degraded_criterion(arch_env):
    """判定口径: 无 baselineId(未关联/未建基线)或未登记项目 → 降级。"""
    from topoone_app_architect.arch_routes.project import kb_degraded
    store.ProjectsStore.create({"id": "proj-kbL", "name": "有基线",
                                "rootPath": "/tmp/kbL", "baselineId": "BL-1"})
    store.ProjectsStore.create({"id": "proj-kbN", "name": "无基线",
                                "rootPath": "/tmp/kbN"})
    assert kb_degraded(project_id="proj-kbL") is False
    assert kb_degraded(project_id="proj-kbN") is True
    assert kb_degraded(root="/tmp/未登记路径") is True


def test_run_arch_tool_blocks_kb_when_degraded(arch_env):
    """执行面: 降级项目上 kb.* 四件全部拦截, 错误带本地替代指引。"""
    from topoone_app_architect.arch_routes import req_agent
    for name, args in _KB_ARGS:
        r = req_agent.run_arch_tool(name, args, root=None, project=None)
        assert "未关联知识库" in str(r.get("error")), (name, r)
        assert "asset.semantic.search" in str(r.get("error"))


def test_run_arch_tool_kb_passes_when_linked(arch_env, monkeypatch):
    """已关联(有基线)项目: 拦截放行, 工具真实执行。"""
    import topoone_app_architect.arch_routes.project as proj_mod
    import topoone_app_architect.agent.tools.impl.kb as kb_impl
    from topoone_app_architect.arch_routes import req_agent
    monkeypatch.setattr(proj_mod, "kb_degraded",
                        lambda root=None, project_id=None: False)
    monkeypatch.setattr(kb_impl, "_model_assets",
                        lambda root, project: [{"id": "a1", "name": "订单中心"}])
    r = req_agent.run_arch_tool("kb.asset.search", {"text": "订单"},
                                root=None, project="proj-x")
    assert r.get("result") and r["result"][0]["id"] == "a1", r


def test_run_arch_tool_kb_internal_bypass(arch_env):
    """internal=True(系统确定性路径)不拦——回退工具原降级语义。"""
    from topoone_app_architect.arch_routes import req_agent
    r = req_agent.run_arch_tool("kb.asset.search", {"text": "x"},
                                root=None, project=None, internal=True)
    assert "error" not in r and r.get("result") == []


def test_chat_context_cuts_kb_tools_when_unlinked(arch_env):
    """提示面: 未关联 → 能力文档无 kb.* 且路由文案去 KB 话术; 关联 → 保留。"""
    from topoone_app_architect.agent.turns import context as ctx_mod
    store.ProjectsStore.create({"id": "proj-kbL", "name": "有基线",
                                "rootPath": "/tmp/kbL", "baselineId": "BL-1"})
    store.ProjectsStore.create({"id": "proj-kbN", "name": "无基线",
                                "rootPath": "/tmp/kbN"})

    def _sys_text(root, project):
        _, msgs, _ = ctx_mod._chat_context(
            {"root": root, "project": project},
            {"conv": {"analysisMode": "strict"}}, [], [], "", None)
        return "\n".join(m["content"] for m in msgs if m["role"] == "system")

    linked = _sys_text("/tmp/kbL", "proj-kbL")
    assert "kb.asset.search" in linked and "kb.graph" in linked
    assert "对话路线(判据)" in linked                   # GU-3 静态人格块恒置
    unlinked = _sys_text("/tmp/kbL", "proj-kbN")     # 项目存在但无基线
    assert "kb.asset.search" not in unlinked and "kb.code_mappings" not in unlinked
    assert "KB 已绑定" not in unlinked                # cv-189: KB 叙述整句不注入
    assert "task.propose" in unlinked                # 双出口教学在判据/工具文档层


def test_degraded_prompt_free_of_kb_narrative(arch_env):
    """cv-189 注入层硬控制验收(模型 API 日志口径):
    未关联 KB → 系统提示词零 KB 叙述; 已关联 → KB 能力叙述照常。"""
    from topoone_app_architect.arch_routes import req_agent
    store.ProjectsStore.create({"id": "proj-kbN", "name": "无基线",
                                "rootPath": "/tmp/kbN"})
    store.ProjectsStore.create({"id": "proj-kbL", "name": "有基线",
                                "rootPath": "/tmp/kbL", "baselineId": "BL-1"})
    prompt = req_agent.chat_system_prompt("/tmp/kbN", "proj-kbN",
                                          skill_scenarios=["extract"])
    for bad in ("知识库", "kb.", "KB"):
        assert bad not in prompt, f"降级提示词仍含 {bad!r}"
    # 提取 skill 注入但 kb 定位指引已换本地
    assert "asset.semantic.extract" in prompt and "map.assets" in prompt
    linked = req_agent.chat_system_prompt("/tmp/kbL", "proj-kbL",
                                          skill_scenarios=["extract"])
    assert "KB 已绑定" in linked and "kb.asset.search" in linked


def test_run_arch_tool_blocks_mcp_call_when_degraded(arch_env):
    """执行面: mcp.call(KB MCP 出向代理)在降级项目上硬拦。"""
    from topoone_app_architect.arch_routes import req_agent
    r = req_agent.run_arch_tool("mcp.call", {"tool": "x", "params": {}},
                                root=None, project=None)
    assert "未关联知识库" in str(r.get("error")), r


def test_placeholder_only_turn_not_landed_as_noise():
    """cv-189: 弱模型把占位符当正文输出——折叠正则命中各类占位变体;
    常规正文不受影响。"""
    from topoone_app_architect.agent.turns.chat import _PLACEHOLDER_ONLY_RE as R
    for s in ("(已调用工具)", "（已调用工具）。", "(调用知识库检索)",
              "(已调用工具)!", " (已调用工具) "):
        assert R.match(s.strip()), s
    for ok in ("(已调用工具) 结果如下", "确认执行", "🔧 已调用工具: project.ctx", ""):
        assert not (ok.strip() and R.match(ok.strip())), ok
