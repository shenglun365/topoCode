# 开源参考项目清单（按 topocode 层分类）

> 状态：调研参考文档（开源项目分类清单）。
> 上下文：工作流矩阵 `topocode KB + topocode architect + Open Design + cline sdk / opencode / codex / ...` 的竞品调研衍生产出。
> 用途：标记「可演变为组件 / 仅学思想协议 / 禁止 fork」三类，为各层选型与集成提供依据。
> 注意：协议与活跃度以各仓库**当前标注**为准；标注 ⚠ 处凭知识库记忆，引入前必须复核。

---

## ① 规格驱动流水线（学 → architect 流程层）

| 项目 | 仓库 | 协议 | 可学 / 可演变点 |
|---|---|---|---|
| **github/spec-kit** ⭐ | github/spec-kit | MIT | 最佳教科书：constitution / specify / plan / tasks / implement 六命令工作流、需求模板（EARS 风格）、多 agent 引导脚本；可直接演变为 architect 的 spec 格式参照 |
| **Fission-AI/OpenSpec** | Fission-AI/OpenSpec | MIT | 轻量版 spec-driven（change-proposal 模式）；学「变更提案 vs 全量规格」的分工 |
| **MetaGPT** | geekan/MetaGPT | MIT | 角色 SOP 化（PM→架构师→工程师）提示词工程；学术严谨，借鉴其角色产出物模板 |
| **KiroCrew** ⚠ | kirodotdev/KiroCrew | 开源（Kiro 官方唯一开源件） | 学 AWS 版「持久工作区 + 跨会话状态」组织方式；Kiro 主体闭源，仅此件可参考 |
| **OpenHands**（前 OpenDevin） | All-Hands-AI/OpenHands | MIT | agent 事件流架构（Action/Observation 流水），与 architect turn 协议互参 |

## ② 代码库 KB / 上下文引擎（学 + 可部分演变 → topocode KB 层）

| 项目 | 仓库 | 协议 | 可学 / 可演变点 |
|---|---|---|---|
| **Aider repo map** ⭐ | Aider-AI/aider | Apache-2.0 | **最值得抄**：tree-sitter 符号抽取 + 图排序（PageRank）选关键上下文；可直接演变为本地图谱检索内核，替换朴素 LIKE 检索 |
| **continue** | continuedev/continue | Apache-2.0 | 代码库索引（LanceDB 嵌入）+ MCP client 全套实现；索引层可借鉴 |
| **pr-agent** | Codium-ai/pr-agent | Apache-2.0 | Qodo 开源侧：PR 分析的「结构化 Review 提议」范式，与 architect 验收卡同构 |
| Sourcegraph ⚠ | sourcegraph/sourcegraph | **Fair Source（已非纯开源）** | 代码图搜索 / 符号跳转思想参考；**不可直接 fork 商用** |

## ③ 代码理解知识产品（学产品化形态 → KB 的对外出口）

| 项目 | 仓库 | 协议 | 可学 / 可演变点 |
|---|---|---|---|
| **deepwiki-open** | AsyncFuncAI/deepwiki-open | Apache-2.0 | DeepWiki 的开源复刻：仓库→结构化 Wiki 生成管线；可演变为「资产→文档」导出器 |
| Aider repo map（同 ②） | Aider-AI/aider | Apache-2.0 | 轻量理解层的最小实现范本 |

## ④ 设计工作流（学 + 可 fork → OpenDesign 集成层）

| 项目 | 仓库 | 协议 | 可学 / 可演变点 |
|---|---|---|---|
| **OpenDesign** ⭐ | nexu-io/open-design | Apache-2.0 | 集成本体：SKILL.md 可组合协议、daemon headless 接入、DESIGN.md 设计系统沉淀、agent adapter 层（21 引擎）；按薄接口接，必要时 fork 定制 |
| **Penpot** | penpot/penpot | MPL-2.0 | 相邻参考：开源设计工具的 design tokens 处理；若未来要自建设计组件 |

## ⑤ 执行引擎 / 编排（学协议与沙箱 → runner 层）

| 项目 | 仓库 | 协议 | 可学 / 可演变点 |
|---|---|---|---|
| **Cline** | cline/cline | Apache-2.0 | 工具协议（browser / computer-use / 编辑器工具面）、human-in-the-loop 审批流；与 architect 验收门同题不同解 |
| **opencode** | sst/opencode | MIT | client / server 架构（TUI 与内核分离）、LSP 集成、provider 抽象——runner 接多引擎的最佳参照 |
| **codex** | openai/codex | Apache-2.0 | 沙箱执行模型（workspace-write / 审批策略）、Rust 内核 + 多前端 |

---

## 使用建议（演变 vs 仅参考）

- **可演变为组件**：spec-kit（规格模板）、Aider repo map（检索内核）、deepwiki-open（文档出口）、OpenDesign（设计阶段）
- **仅学思想 / 协议**：MetaGPT（角色模板）、KiroCrew（工作区组织）、Cline / codex / opencode（沙箱与审批）
- **禁止 fork**：Sourcegraph（Fair Source）

## 接入纪律（薄接缝原则）

1. 全部走 **MCP / ACP / AGENTS.md / SKILL.md** 已成事实标准，与 Kiro / OpenDesign 生态保持兼容；
2. architect 侧只依赖「CLI 调用 + 文件落盘」薄接口，不深入外部工具内部数据结构；
3. 事实源（资产 / 规格 / 设计 tokens）放 **KB**，不放外部工具——更换 / 拓展任何组件都是配置级变更。

## 待核实清单（引入前逐项确认）

- [ ] 各仓库 license 当前版本（尤其 ⚠ 项：KiroCrew、Sourcegraph）
- [ ] GitHub stars / 最近 commit / release 节奏（活跃度）
- [ ] spec-kit 需求模板格式与 architect spec 结构的映射可行性
- [ ] Aider repo map 算法对 Python/TS 之外的语种覆盖
- [ ] OpenDesign daemon CLI 的 headless 面貌（SKILL.md 协议细节，读其仓库 quickstart / roadmap）
