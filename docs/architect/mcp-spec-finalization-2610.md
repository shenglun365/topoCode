# 规约 & MCP 完整功能定型（2610）

> 2026-10-08 · 性质：**设计定案（已实施 P1~P5）**
> 背景：对标 Roo/Roomote 后的方向收敛（见 [benchmark-adoption-assessment-2610.md](benchmark-adoption-assessment-2610.md)），
> 用户裁决：执行器编码期**完全自主**（当前 coding agent 能力已强），architect 主 agent 只在
> **两端**提供认知辅助——任务描述生成时（帮开发者准确描述干什么/关键点怎么干）与任务完成时
> （干得怎么样/都干了什么/是否符合要求或可接受）。

## 一、规约两层职责（定型）

```
项目级（人治 · AGENTS.md 单文件 · 约束性信息only）   任务级（architect 组装 · 动态）
────────────────────────────────────────────     ──────────────────────────────
AGENTS.md = 唯一对外规约产物                       spec snapshot → context_pack:
 ├ 生成段(机器投影, 只读): 自管命名规约+词汇表       allowedScope/forbiddenScope/
 │   (NamingConvention/GlossaryStore 单源,          acceptance/图邻域(W2)
 │    引擎消费面零改动)                             —— 细节规约全部在任务级,
 └ 人工段(.topo/rules/*.md): 架构约束/              derived 组件约束彻底删除
    编码规约/需求对齐, 人写(REST 路径钳制)
UI: 单页统一编辑器(预览+编辑+sync+命名治理折叠)
```

**裁决记录**：

| # | 裁决 | 理由 |
|---|---|---|
| S-1 | 命名规约/词汇表真相源=store，AGENTS.md 生成段为投影 | 反思挖掘/convention_check/语义提取注入/记忆映射四类引擎深消费，纯文件真相源改造面大收益小 |
| S-2 | 三层架构规约面（override/explicit/derived+confirm+changelog）整体退役 | 消费者仅自身 UI；derived 组件约束属动态派生，固化项目版本本就别扭——**完全删除**（不降级任务级） |
| S-3 | AGENTS.md 只含约束性信息，资产概览统计表裁掉 | 概览性质对编码零约束力，且资产数变化触发 sync 噪音 |
| S-4 | 需求级 spec 不进 AGENTS.md | repo 长期文件 vs per-req 短期边界，两层分离 |
| S-5 | 统一编辑器=单页（预览只读+rules 文件编辑+一键 sync+命名治理折叠） | 纯 AGENTS.md 模式精神：一个文件一个界面，UI 简化统一管理 |

## 二、MCP 能力定型（两端交互 + 按需资源）

**定位**：serve 模式执行器 / 外部 TUI/WebUI 与 architect 的开发工作交互面。
不重复执行器自身能力（文件/git/测试/自有插件/三方 MCP）——只供 architect 独有数据面。

| 环节 | 交互 | 工具 | 数据源 |
|---|---|---|---|
| **开工前** | 取执行契约 | `task.mandate`(task_id/req_id) | context_pack 同源 + tool_rules |
| 写码前 | 规约全集 | `map.rules` | 自管编码规约+词汇表+.topo/rules |
| 写码中(自主取用) | 组件/资产/图 | `map.component/assets/graph/overview` | 组件目录+SemanticAssets |
| 找历史决策 | 跨会话检索 | `ctx.search/get/summarize` | 会话单元 |
| **完工后** | 提交回执请求验收 | `task.receipt`(changed_files,summary) | _acceptance_brief 同源（L-1① 自纠正回执+验收对照+改动分布） |

**裁决记录**：

| # | 裁决 | 理由 |
|---|---|---|
| M-1 | 主 agent = **非 MCP 消费者**（原生注册表），出向 mcp.call(KB :3460) 退役 | dormant 遗留与定位冲突；MCP 是对外暴露面不是对内工具面 |
| M-2 | `map.neighborhood` 不做（砍） | 执行器自主有代码理解力；architect 侧邻域需求已由 W2 注入 context_pack 覆盖 |
| M-3 | task.receipt 评估性返回，不改任务状态机 | D-4 延伸：状态机是 architect 内域，外部只读评估 |
| M-4 | ctx.* 三件保留 | 历史上下文=开发中必要交互（找之前决策） |

## 三、实施清单（已完成）

| # | 提交 | 内容 |
|---|---|---|
| P1 | `0394db99` | /arch/spec+/spec/confirm+/kb/coding-rules 退役；AGENTS.md 裁资产概览；map_tools desc 修正；schema deprecated 注释 |
| P2 | `fa87ed6c` | rules-files REST(list/get/write/delete, 路径钳制)+preview；SpecWorkspace 单页统一编辑器重写；FE 残留清理(spec-store/codingRules/chips) |
| P3+P4 | `14968051` | sem/task_tools.py 两端工具+注册；mcp.call 全链退役(prompt/req_agent/测试/golden)；McpPage 5→10 |
| P5 | 本文 | 定型文档 |

门禁终态：pytest **1405** / vitest **89** / tsc 0 / vite build ✓ / 棘轮绿（schema.py 基线补登记 1134——65ab304a 迁移兜底欠账）。

## 四、遗留与关联

- **模型路由提醒**：全局默认(llm.modelId) < 角色注册表(agent_roles)——语义管线
  (extract/verify/induce/pseudo/evaluate/mine)按角色路由，改默认模型需同步角色或清空跟随
- L-1② 符号勾稽仍随 P2-T4（见 [b1/deferred-2610.md](b1/deferred-2610.md)）
- arch_specs 表留存仅迁移兼容，无消费者，可在后续大版本清理
