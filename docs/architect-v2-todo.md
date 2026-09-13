# topoOne Architect v2 重构待办

> 更新: 2026-09-13(P0 落地 + cv-147~150 实证补丁后)

## 决策基线

单流+过滤器 / 混合触发 / 轻门禁(任务卡一次确认) / 破坏式重构 /
引擎顺序 **cline → opencode → codex**(opencode serve 已先行打通, cline 适配器保持
TurnAdapter 协议解耦) / 意图识别按**通用 agent 模式**(不局限 KB/architect 能力,
合理路由到 coding subagent)。

## P0 遗留(近期)

| # | 事项 | 说明 | 量级 |
|--|--|--|--|
| 1 | 真机端到端验证 | 对话→任务卡→确认→opencode 执行→⏸提问→回复→✅完成 全链未真机走通; cv-147~150 复测 | 验证 |
| 2 | cline sidecar 真机联调 | node/依赖/sidecar script 环境从未真机跑过; 任务卡已可切换 cline 引擎 | P0 内 |
| 3 | task_done 验收入口 | 完成消息无「验收/查看差异」按钮(worktree diff 入口未接) | 小 |
| 4 | guide 端点旧文案 | `/sessions/{id}/guide` 后端建议仍是旧命令风格, 未适配 v2 | 小 |
| 5 | t4 软提示不重判 | 模型切换后 profiles 缓存不刷新(新会话才重查) | 极小 |

## P1: harness skills + 资产表

- `arch_assets` 表: requirement(需求表格)/todo(待办)/plan(执行快照)/data_asset/analysis
- asset 工具面: `asset.upsert/list/delete`(LLM 可读写)
- 可执行 skills(从 `_ARCH_SKILLS` 纯元数据升级): extract.requirement /
  extract.plan / extract.todo / extract.data_asset / analyze.suggest
- 轮次编排: 资产面板摘要注入 + 轮后提取钩子(资产 draft 入库)
- AssetsPanel.vue(侧栏需求表格/待办)
- 提取用会话模型 + 4B+ 软提示(已实现提示面)

## P2: 旧机制清退

- exec_bridge 旧路径: start_implement/_pump/_handle_pump_event/jobs 账本(约 600 行)
- websocket: _maybe_draft_card/specDraft/guard_autoland 规约域、_guard_autoland
- sessions: coding-sessions/sub-seen REST(存量只读)、_executor_hint 残留引用
- 前端: bind-coding 死接线、子会话池面板(存量查看)、job_done 卡兼容渲染、
  i18n 旧键(session.target.*/session.subs.*)
- req_agent: req.propose/finalize/amend 注册物理删除(现 internal 旁路)
- 旧测试与 fixture 清理

## P3: 引擎打磨

- cline sidecar 真机打磨(嵌入式: node 版本/依赖包/多轮会话复活)
- opencode serve 回归(多项目并发/session 复活)
- codex app-server 接入实测

## 已知小问题(随手修)

- SSE progress 事件里 `msgCount` 统计含 reasoning 消息(粒度粗, 无碍)
- `_task_instruction` 的 prior_brief 参数未接线(重试前情简报, P1 资产化时做)
- runner `[[NEED_INPUT]]` 回合标记契约仍在(v2 语义降级为状态提示, P3 评审)

## 实证档案

- cv-147: 9b 模型输出图 IR 裸 JSON(未开绘图增强) → extract_task_fence 已防误判
- cv-148/149: 通用任务(检测编译环境/统计文件数)被 KB 检索话术推诿 → 通用路由守卫已修
- cv-150: 任务载荷以 ```json 围栏输出未执行工具 → 任务围栏代落已修;
  编造「任务已创建/执行进度」→ 守卫任务域规则 + repair_task 修复动作已修;
  执行器无处设定 → 任务卡执行器 chips(pending_confirm 可换)已修
