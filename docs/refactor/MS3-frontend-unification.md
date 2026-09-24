# MS3 细化设计：前端职能归一（architect 独立 + KB 系基建归一）

> 状态：**已评审通过并实施完成**（2026-09-24，U0~U8 全部落地，无挂账项） | 日期：2026-09-24
> 裁决：U6=案 A（settings 六件随迁 workbench，portal 收缩 #/settings）；U2 前置=本期合入（在途工作 e06d1bd 先行落地，碰撞面解除，判据 1 全口径达成） | 上游：[milestones.md](milestones.md) §2-MS3 · [0924 重构方案](../architecture-refactor-plan-20260924.md) B2 · 裁决①
> 事实基线：2026-09-24 三路核证（architect 依赖面 / KB 归一面 / sidecar 与图域），全部带 文件:行号。
> 方向：architect 对 web-core **零依赖**（深路径与包声明全摘）；KB 系收敛到单一 web-core；web-core 只留多 app 真共享物。

## 1. 目标

1. architect 前端彻底独立（裁决①）：7 文件 9 处 `@topo/web-core` import 全部自持替换，依赖声明摘除，独立构建
2. KB 系基建归一：token key 单一 `topocode:token`（含迁移）、对话框系统合一（useDialog 扩展 choices 吸收 useConfirm）
3. web-core 瘦身：越位物下沉 workbench（安全三件先行；ipc 双件作为评审裁决点）
4. 图域归口：`diagram-normalize` 移入 graph-kernel；sidecar 更名 `@topo/cline-sidecar`
5. 顺带清偿 MS2 漏网：两个孤儿可视化组件（~930 行，删除前零引用复验）

## 2. 范围

**纳入**：U0 图域归口+孤儿删除 ‖ U1 architect 独立化（干净面 3 文件） ‖ U2 architect 独立化收尾（碰撞面 4 文件，**前置条件见 F1**） ‖ U3 token 统一 ‖ U4 对话框合一 ‖ U5 web-core 下沉安全三件 ‖ U6 ipc 双件下沉（评审裁决点） ‖ U7 sidecar 更名 ‖ U8 收口。

**排除/降级**（核证后裁决）：
- **auth-service 合一 → 降级为文档化分歧**：workbench 版（270 行，含 USE_MOCK 分支）是 web-core portal 版（120 行纯 request）的超集；消费者互不交叉（workbench↔portal）。合并需处置 dev-mock 行为，收益低风险中——保持两份，注释互指
- **Markdown 三实例合一 → 不成立，保持分工**：web-core render（mermaid/plantuml 直通+community 链接改写，chat/docs 共享）、workbench AIAssistantPanel（cmd 可点击指令码）、architect MarkdownView（极简转义）——三者 highlight/后处理本质不同，非重复而是分表面配置
- **StarLogoMark 不动**：architect 副本已带 i18n 化差异（独立化方向正确）；web-core 副本服务 KB 三 app+portal
- ipc/types/ipc 的**最终归宿**取决于 U6 裁决，本设计给两案

## 3. 现状事实基线

| # | 事实 | 依据 |
|---|---|---|
| F1 **碰撞面** | architect 的 9 处 web-core import 分布在 7 文件，其中 **4 文件恰为用户未提交在途改动**（ConversationDock.vue:23 / conversation-store.ts:18 / i18n/en-US.ts:1 / i18n/zh-CN.ts:1）——先动必混入；干净面仅 3 文件（AppTopbar.vue:6-7 / settings-store.ts:4-10 / useDiagramRenderer.ts:9-10） | git status + grep 核证 |
| F2 | 4 个被引模块（shell / i18n/common / useTopoRender / diagram-normalize）**全部被 KB 系消费**——无「仅 architect 用」可搬走项，全部走「architect 拷贝副本 + SYNC-WITH 锚点」 | 三 app import 面核证 |
| F3 | 拷贝连带体积：shell 闭包 ≈ shell 10 文件 668 行 + i18n/setup 50 + ThemeToggle/useTheme ~90 + 2 svg（AppToolbar 固定拉全家居；architect 仅用 9/28 导出符号）；i18n/common 488 行纯常量（239 键×2）；useTopoRender 186 行（architect 仅用 `renderDiagram`，可裁剪并改接自家 api-client 鉴权）；diagram-normalize 29 行零依赖 | 逐文件核证 |
| F4 | 测试 mock 面：`tests/conversation-live-buffer.test.ts:47` `vi.mock('@topo/web-core/shell')`——随碰撞文件迁移同步改（该 mock 正是为碰撞面文件服务） | 核证 |
| F5 **token 双轨** | workbench 唯一双轨 app：登录态走 `topocode_token`（auth-store.ts:40/63/81 + web-core utils/http.ts:12/31/39/49 + portal use-auth.ts:38/61/79，伴生 `topocode_user`），IPC 走 `topocode:token`（token.ts/browser-api）；chat/docs/architect/graph-kernel 全部已是 `topocode:token`。**迁移风险**：直接换 key 会把已登录用户判未登录；X-Refresh-Token 续期只刷旧 key | 全量 grep |
| F6 **对话框三套** | workbench useConfirm（44 行，有 choices/variant，无 prompt/alert，渲染内联在 AppShell.vue:222-255）/ web-core useDialog（37 行，有 prompt/alert/title，无 choices）/ architect useAppDialog（58 行，队列+全能力，architect 自留——独立化方向不并入）。useDialog **不是** useConfirm 超集，合一需扩展 | 核证 |
| F7 **web-core 越位物** | 五件消费者全部仅 workbench ✓，但**下沉连带**：ipc.ts(714)+types/ipc.ts(1127) 被 web-core portal/settings 三面板（General/Agents/ModelsPanel）import，而 SettingsPage 被 workbench 路由（router/index.ts:22,28）**与** portal 独立构建（vite.config.portal.ts→portal/main.ts）**双消费**——0905 评估未发现此耦合；useComponentId 连带 ConfirmDialog（仅 workbench 消费）；browser-api 连带 services/token.ts（留 web-core，chat/docs 共用） | 消费者矩阵核证 |
| F8 | 孤儿组件：workbench `D3ForceGraph.vue`（478 行，无 src 引用）与 `MermaidViewer.vue`（454 行，无 src 引用，仅 CONV-02 文字提及）——MS2 漏网（当时未被列入 0905 死码清单） | 引用核证 |
| F9 | graph-kernel（3,629 行/36 文件）健康：exports 通配、无构建步、architect 5 处 + web-core 3 处消费；`diagram-normalize` 是纯图域逻辑，现居 web-core（render.ts:15 再导出） | 核证 |
| F10 **sidecar 现名** | `@topocode/cline-sidecar`（非 @topo 前缀）；目录 `packages/agent-sidecar`；无任何包声明依赖它；Python 侧 4 个路径收口函数 + 8 处 build 命令字符串 + 3 处测试路径按**目录名**引用 | 全量 grep |

## 4. 分步设计（文件级，九批独立 commit）

### U0 图域归口 + 孤儿清偿（先行，零风险）

1. `git mv packages/web-core/src/services/diagram-normalize.ts packages/graph-kernel/src/core/diagram-normalize.ts`；web-core 留 3 行 re-export 兼容层（`services/diagram-normalize.ts` → `export * from '@topo/graph-kernel/core/diagram-normalize'`，render.ts 不动）；消费者（workbench useDiagramRenderer:12）可后批迁graph-kernel 直引或暂走兼容层
2. 删除孤儿（**执行前复验零引用**）：`apps/workbench/src/components/visualization/{D3ForceGraph,MermaidViewer}.vue`（−932 行）
3. 验证：workbench vitest + type-check；`grep -rn "D3ForceGraph\|MermaidViewer" apps packages` 零命中（CONV-02 文字随 U8 修）

### U1 architect 独立化·干净面（5/9 import 清除）

**新建自持模块**（全部带 `SYNC-WITH: packages/web-core/src/...` 锚点头注，纪律=改一方须 diff 另一方）：
- `apps/architect/src/shell/`（拷贝裁剪）：`prefs.ts`（readModelPref/readLocale/writeLocale/readFontSize/writeFontSize/setFontSize + 常量，~70 行）、`AppToolbar.vue`+`ModelSettingsDropdown.vue`+连带小件（FontSizeSelect/LocaleToggle/HelpButton/ThemeToggle/toolbar.css/useTheme/2 svg，~800 行）——**不拷** useAppPrefs 全量与 PanelToggleButton/StarLogoMark（architect 已有自家 logo）
- `apps/architect/src/i18n/common.ts`：commonZh/commonEn 全量拷贝（488 行，SYNC-WITH）
- `apps/architect/src/services/topo-render.ts`：renderDiagram 裁剪版（~120 行），鉴权从 web-core api.authHeaders 改接 architect 自家 `api-client.ts`（SYNC-WITH 注明差异点=鉴权源）
- diagram-normalize：**不拷**——U0 后直接 `@topo/graph-kernel/core/diagram-normalize`

**迁移 3 个干净文件**：AppTopbar.vue（import 改 `@/shell/...`）、settings-store.ts（改 `@/shell/prefs`）、useDiagramRenderer.ts（改 `@/services/topo-render` + graph-kernel 直引）。
**验证**：`grep @topo/web-core apps/architect/src` 仅余碰撞面 4 文件命中；vue-tsc + vitest 54 全绿。

### U2 architect 独立化·碰撞面收尾（4/9）——前置条件已裁决本期合入（在途工作先行单独 commit 落地）

- 前置条件声明：ConversationDock.vue / conversation-store.ts / i18n/en-US.ts / i18n/zh-CN.ts 均有未提交在途改动（F1）。**等待合入后执行**；若 MS3 收口时仍未合入，U2 顺延挂账至 MS6 前置，MS3 以「5/9 清除 + 自持模块就位」验收
- 动作：4 文件 import 改自持路径；`tests/conversation-live-buffer.test.ts:47` mock 路径同步；摘除 `apps/architect/package.json:23` 临时依赖；`grep -rn "@topo/web-core" apps/architect` 全仓零命中；`npm run build -w @topo/app-architect` 独立构建成功

### U3 token 统一（`topocode:token` 单轨 + 一次性迁移）

改 10 处字面量：web-core utils/http.ts ×4、portal/user/use-auth.ts ×3、workbench auth-store.ts ×3（伴生 `topocode_user` 同步改 `topocode:user`）。
**迁移垫片**（防登出事故）：auth-store.loadSession（:39-52）与 portal use-auth 首读处加一次性兼容——新 key 无值而旧 key 有值 → 写新 key、删旧 key；http.ts X-Refresh-Token 续期写回新 key。
**单源化**：三处文件改 import `TOKEN_KEY` from web-core/services/token.ts（消除字面量）。
验证：`grep -rn "topocode_token" packages apps --include=*.ts --include=*.vue` 零命中；workbench 登录/续期/登出手动清单。

### U4 对话框合一（useDialog 扩展吸收 useConfirm）

1. web-core useDialog 增 `confirmChoice(message, choices, opts?) → Promise<string>`（ChoiceOption 带 variant：primary/danger/warning/ghost，对齐 useConfirm.ts:26 语义）；AppDialog.vue 增 choices 渲染分支（样式沿用 workbench AppShell.vue:222-255 的 overlay+choices 结构）
2. workbench 迁移：AppShell.vue 内联模板段（:222-255）替换为 `<AppDialog>`；stores/project.ts:116-117/371-372 动态 import 改 useDialog.confirmChoice/confirm
3. 删除 `apps/workbench/src/composables/useConfirm.ts`
4. 验证：web-core vitest（AppDialog 新增用例：choices 渲染/promise 解析/默认取消）；workbench vitest；chat 回归（useDialog 现有消费不受扰——新增 API 零侵入）

### U5 web-core 下沉·安全三件（无 portal 纠缠）

| 下沉物 | 去向 | 连带 |
|---|---|---|
| utils/statusBadge.ts(86) + tests/statusBadge.test.ts | apps/workbench/src/utils/ | 无（web-core 内零消费者） |
| composables/useComponentId.ts(17) + components/ConfirmDialog.vue(219) | apps/workbench/src/{composables,components}/ | ConfirmDialog 仅 workbench 消费（GroupManager:15/ProjectCard:26 同步改 `@/`）；web-core index.ts:43 re-export 摘除 |
| services/browser-api.ts(533) | apps/workbench/src/services/ | token.ts 留 web-core（chat/docs 经 api.ts 共用），browser-api 改 `import ... from '@topo/web-core/services/token'`；workbench main.ts:11 改 `@/services/browser-api`；index.ts:22 re-export 摘除 |

验证：chat/docs/architect 三 app import 面零变化（本就不消费）；workbench type-check+vitest；`grep useComponentId packages/web-core/src` 仅历史注释。

### U6 ipc 双件下沉 —— **评审裁决点**（二选一）

事实（F7）：ipc.ts+types/ipc.ts（1,841 行）被 portal/settings 三面板双消费。
- **案 A（建议）：settings 三面板随迁 workbench**——它们本就是工作台域页面（经 workbench router 渲染）；portal 独立构建剔除 settings 路由（portal=登录/门户面，设置属工作台）。动：三面板+SettingsPage 迁 `apps/workbench/src/components/settings/`，ipc/types/ipc 迁 workbench，portal 路由表与 AppPortal 相应收缩，web-core index.ts:21 re-export 摘除
- **案 B：ipc 双件留 web-core**，接受「web-core 含 workbench 单消费者大件」现状，挂账 MS6 重评 web-core/portal 边界
**评审裁决：案 A（2026-09-24 确认）。**

### U7 sidecar 更名 `@topo/cline-sidecar`

- `packages/agent-sidecar/` → `packages/cline-sidecar/`（git mv）；package.json:2 name 改 `@topo/cline-sidecar`；根 package.json:9 workspaces 同步；`npm install` 再生 lockfile
- Python 4 路径收口函数：turn_adapter.py:291、agent_executors.py:864、cline_engines.py:64（+exec_bridge 间接无需动）；build 命令字符串 8 处（cline_engines.py:193/196、agent_executors.py:455/660/684/685、AgentExecutorsCard.vue:65）；测试 3 处（test_turn_adapter.py:929、test_cline_engines.py:64/111）
- 验证：`grep -rn "agent-sidecar" --include='*.py' --include='*.json' --include='*.vue' packages apps` 零命中（文档提及随 U8 修）；architect pytest（cline 相关）+ sidecar vitest 全绿

### U8 收口

全量门禁（type-check/lint 不增/test:py/test:fe）+ 各验证 grep 组 + `git diff pre-MS3..HEAD --shortstat` 统计 + CONV-02（MermaidViewer 文字、web-core 职责清单更新）+ milestones/设计文档回写。

## 5. 测试计划

- U1/U2：architect vue-tsc + vitest（54 例）+ 独立 build；U2 后新增「依赖零声明」断言（临时脚本 grep package.json）
- U3：web-core+workbench vitest；新增 token 迁移垫片单测（旧 key→新 key 写读删）
- U4：web-core AppDialog choices 用例新增；chat useDialog 回归
- U5/U6：workbench 全量 vitest + type-check；chat/docs 零变化验证（diff import 面）
- U7：sidecar vitest（505 行 host 测试）+ architect cline 相关 pytest
- 手动清单（一次过）：workbench 登录/续期/登出、AI 助手确认框、chat 发消息含图、docs 查看器、architect 顶栏（主题/字号/语言/模型下拉）

## 6. 验收门禁（对 milestones §2-MS3 判据的执行口径）

| # | 命令 | 预期 |
|---|---|---|
| 1a | `grep -rn "@topo/web-core" apps/architect/src` | U1 后仅余碰撞面 4 文件；U2 后**零命中** + package.json 零声明 + 独立 build 成功（若 U2 挂账则如实标注） |
| 2 | `grep -rn "topocode_token" packages apps --include=*.ts --include=*.vue` | 零命中 |
| 3 | 全量 vitest + pytest + 手动清单 | 全绿（lint 存量豁免同 MS1/2） |
| 4 | `grep -rn "services/ipc\|types/ipc\|browser-api\|useComponentId\|statusBadge" packages/web-core/src/index.ts`；消费者 grep | 下沉件仅存于 workbench（U6 按裁决结果口径） |
| 5 | `grep -rn "agent-sidecar" packages apps --include='*.py' --include='*.json' --include='*.vue'` | 零命中 |
| 6 | `grep -rn "D3ForceGraph\|MermaidViewer" apps packages` | 零命中 |

## 7. 风险与回退

| 风险 | 缓解 | 回退 |
|---|---|---|
| R1 碰撞面强依赖用户在途进度 | U1/U2 分裂设计；U2 挂账机制（MS6 前置） | — |
| R2 shell 拷贝后双源漂移 | SYNC-WITH 锚点纪律；U8 收口跑一次双源 diff 归档 | 还原 import（单 commit revert） |
| R3 token 迁移致登出 | 一次性垫片 + 单测覆盖旧→新路径 | revert U3 |
| R4 useDialog 扩展扰动 chat | 新增 API 零侵入设计 + chat 回归清单 | revert U4 |
| R5 U6 案 A 动 portal 构建 | 评审裁决点前置；portal 路由收缩单独 commit | 改判案 B（保留现状） |
| R7 sidecar 更名漏改路径 | 路径已收口 4 函数；全量 grep 验证组 5 | revert U7 |

## 8. commit 序列（预估 ~7 人日）

| 序 | 内容 | 预估 |
|---|---|---|
| U0 | diagram-normalize 归口 + 孤儿×2 删除 | 0.5d |
| U1 | architect 自持模块 4 件 + 干净面 3 文件迁移 | 2d |
| U2 | 碰撞面 4 文件 + mock + 依赖摘除（**gated**） | 0.5d |
| U3 | token 统一 + 迁移垫片 + 单测 | 0.5d |
| U4 | useDialog 扩展 + useConfirm 退役 | 1d |
| U5 | 下沉安全三件 + ConfirmDialog | 0.5d |
| U6 | ipc 双件（按裁决案 A/B） | 1~2d |
| U7 | sidecar 更名 | 0.5d |
| U8 | 收口验收回写 | 0.5d |

开工前 `git tag pre-MS3`；U2 若挂账，MS3 验收按 1a 双口径如实记录。


---

## 9. 实施记录（2026-09-24，全部落地）

| 批 | commit | 内容 |
|---|---|---|
| 前置 | e06d1bd | 在途工作合入（chevron 单源/ctx chip/问询卡收口，19 文件，vitest 54+pytest 38 全绿）+ R1 为 ctx_usage 立条 |
| 前置 | 3c0415b | 补录前序设计文档 2 件 |
| U0 | d3fdf88 + 2d74809 | diagram-normalize 归口 graph-kernel（barrel 出口；web-core 留 barrel 兼容层——深路径 export * 在 app 侧 tsconfig 解析失败，实施期改走根 barrel）+ 孤儿组件删除 −968 行 |
| U1+U2 | 7518adb | 自持 shell 13 件 + i18n/common 488 行 + topo-render 裁剪版；7 文件 9 import 迁移 + mock 同步 + 依赖摘除；独立 build ✓ |
| U3 | 00f59e0 | token 10 字面量归一 + migrateLegacyAuthKeys 垫片（token.ts 单源，两 loadSession 首行调用）+ 单测 3 例 |
| U4 | 78c86f3 | useDialog 扩展 choices/confirmChoice/ok·cancelLabel；AppDialog choices 渲染；useConfirm 退役 |
| U5+U6 | 7a737c3 + f533d87 | 五件下沉（37+18+14+2 消费面改本地）+ settings 六件随迁 + AppPortal 收缩；git add -A 误回扫孤儿已纠正 |
| U7 | 00d8498 | sidecar 更名（目录+包名+4 路径函数+8 命令串+3 测试；lockfile 再生） |
| U8 | 75bad87 + 本提交 | CONV-02 对齐 + window.api 本地断言（全局 declare 随 ipc 下沉）+ 验收回写 |

### 实施期修正记录
1. **graph-kernel 深路径解析**：`export * from '@topo/graph-kernel/core/...'` 在 workbench/architect tsconfig（moduleResolution: bundler）下 TS2307——改走根 barrel 出口（architect 裸引先例路径），绕开子路径解析差异
2. **git add -A 陷阱复发**：U0 mv-away 后又 mv-back 的孤儿组件被 U5/U6 的 `git add -A` 重新扫入——f533d87 纠正；教训与 MS1-D1 同源，pathspec 提交纪律必须贯彻
3. **window.api 全局声明**：declare global 随 ipc.ts 居 workbench——web-core 三处使用点改 `(window as any)` 本地断言（portal 独立构建下 api 本就可能不存在，类型上如实化）
4. **验收证据**：判据 1 全口径（src/tests/package.json 零命中，仅 shell/index.ts:1 独立化说明注释提及）；判据 2 = 0；判据 3 = 349 py + FE vitest 54/9/9/12 + architect 1101（R1 存量豁免）；判据 4/5/6 = 0 命中