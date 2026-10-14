# architect 全能力 → MCP → 执行器打通方案（2610 暂存）

> 状态：方案已裁决，待实施。Phase 0 起步。
> 原则：**agent 能力保持**（主 agent 48 工具 + [TOOL_CALL] 协议体系不动）；**非 agent 能力打通**（经 MCP 暴露给执行器）。
> 用户裁决四条：① 写类白名单开放；② 全量注册 + 意图按需注入（非全量注入）；③ codex 不纳入（走 AGENTS.md 替代）；④ 新工具同源注册主 agent 内部注册表。

## 一、能力盘点结论

### agent 能力（保持）
主 agent 五段管线（orchestrator.handle_chat）+ `_ARCH_TOOLS` 注册表 48 工具 + 6 技能（agent/skills.py）+ 补偿 providers + governance/gears + 执行泵。经裁决（mcp-spec-finalization-2610 M-1）不走 MCP。

### 非 agent 能力（打通对象）
确定性服务：语义资产引擎（检索/影响面/trace/符号卡/图谱）、结构化提取、逻辑视图、命名校验、契约查询、验收比对、unit-advice、KB 映射、docs/git。
当前 MCP 仅暴露 11 工具（map.*×6 + task.mandate/receipt + ctx.*×3）。

### 管道现状（已通，缺的只是工具面）
- architect `/mcp`（3470，FastMCP 双传输，stdio+streamable HTTP），单口 `sem/map_tools.run_tool`，落 `arch_mcp_calls` 台账
- 执行器 MCP client 已通：cline（sidecar InMemoryMcpManager）/opencode（内联 config dict）；`proxy_ctx._merge_mcp_servers` 默认自动接线 + `_mcp_tools_brief` 告知
- 3460 是遗留假 MCP 门面（仅日志转发）
- sidecar `skills?: string[]` 预留未接线

## 二、现状核查（2610-10-14）

### 意图选择器：原语具备，语义缺口
- ✅ `turns/intent_llm.classify_intent(question, context)` — 受限 LLM 分类（catalog_call light:intent 通道 + schema 约束 + 指纹缓存 + fail-soft），纯函数可独立调用
- ✅ `perception/intent.py` 确定性正则（GENERIC_EXEC_RE/BUILD_MARK_RE/DEFLECT_RE）可作 fallback 样板
- ❌ 现有分类输出是 kind（需求/操作/咨询）与三分类（是否通用执行），**无「任务→工具组」域标签**；`_INTENTS` 词表冻结（D10）
- ⚠️ `build_goal_profile` 依赖 conv/focus，仅主 agent 轮次内可用，不可直接复用

### 按需注入：不具备
- ❌ `build_mcp()` 单实例全量 11 工具，无 tools/list 过滤
- ❌ `_merge_mcp_servers` URL 硬编码 `{ARCH_BASE}/mcp` 全量注入；`_mcp_tools_brief` 静态全量文案
- 注入点仅 2 处：proxy_ctx（直通链）+ dispatch.py:644（任务链）

## 三、实施计划

### Phase 0 — Spike
per-group 多 FastMCP 实例多路径挂载验证（`/mcp` 全量 + `/mcp/<group>` 子集；复用 server.py「mount 剥前缀→路由提升」模式）；cline 实连确认 tools/list 子集与工具名前缀行为（cline 形如 `topo-architect__<tool>_<hash>`，多实例需 per-group 服务名防冲突）。
协议级改写 tools/list 响应的方案已否决（脆弱）。

### Phase 1 — 工具层
新建 `sem/expert_tools.py`（run_tool 单口同模式，Markdown 输出，落台账）→ `build_mcp(groups=...)` 全量注册 → 同源注册 `_ARCH_TOOLS`（agent/tools/impl/ 转调）。

工具组与清单（新增 17 个）：

| 组 | 工具 | 来源单口 |
|---|---|---|
| asset | kb.impact / kb.trace / kb.symbol / kb.baseline-diff / kb.unowned / kb.mappings / kb.logic-view / kb.asset-compare | sem/engine.py、trace.py、compare.py |
| extract（写·白名单） | kb.extract-sync / kb.reconcile / kb.graph-collect | sync_extract.py、job_runner |
| verify | convention.check / kb.contract / acceptance.run / unit.advice | convention_check、contracts、acceptance、unit_advice |
| env | kb.docs / kb.git-status | docs.py、git_probe |

不暴露（agent 编排专属）：coding.feed/sessions、任务卡/req.*、会话管理、资产语义编辑（save/merge/split）。

### Phase 2 — 意图选择器 + 按需注入
- 域分类器：复用 catalog_call 轻任务通道全套纪律（缓存/fail-soft/遥测），schema 换组枚举（如 asset_maintenance|verify|docs_env|mixed），确定性 fallback 关键词正则
- `TOOLS` 表加 `group` 字段 → `_merge_mcp_servers(ecfg, etype, task_text)` 接分类器生成 per-group URL → `_mcp_tools_brief(groups)` 按组渲染 → dispatch.py:644 同口径
- fallback：分类失败=默认组（asset+env）+ brief 告知全量端点 `{arch}/mcp` 可接入

### Phase 3 — 执行器矩阵
cline（streamableHttp）+ opencode（dict 形状）注入验证；codex 明确排除。

### Phase 4 — skills 文档层
AGENTS.md/`.cline/rules` 增「工具使用指引」段（map.core 自查先例扩写）；sidecar skills 预留口接线挂账后续。

### Phase 5 — 测试与台账
expert_tools 分发/组过滤/注入链（proxy+dispatch 双链）测试 + sidecar 集成冒烟。

## 四、风险与对策
- 意图误判致工具缺失 → fallback 宽组 + 全量端点告知
- 写类误用 → extract-sync/reconcile 返回作业预览+dry-run 语义；task.receipt 越界检测兜底
- 多实例工具名冲突 → per-group 服务名（topo-architect-asset 等）
