# MS6 前端巨型组件拆分（B5）细化设计

> 状态：**待评审**（评审通过后按批执行，每批全绿合入）
> 核证日期：2026-09-25（工作区 clean，基线 dev-1 @ 07ba81c）

## 1. 核证快照（实测）

### architect（vitest 基建 ✓）
| 组件 | 行数 | 路径 | 备注 |
|---|---|---|---|
| AssetManagementWorkspace | **3,296** | src/pages/ | 最大巨石 |
| SemanticGraphView | **2,649** | src/components/assets/ | 手绘 SVG（无图库依赖，zoom-pan/viewBox 自实现） |
| AnalysisChat | **2,383** | src/components/requirements/ | |
| ConversationDock | 951 | src/components/chat/ | 用户在途件已合入（e06d1bd），**软上限内不入本批** |

### workbench（vitest 基建 ✓）
| 目标 | 行数 | 路径 |
|---|---|---|
| ReportHome | **1,443** | src/components/report/ |
| ProjectCard | **1,441** | src/components/project/ |
| community-store | **1,252** | src/stores/ → 抽 useComponentAnalysis（现不存在） |

### 移交项
- **DiagramRebuildDialog + DiagramViewer 共改裁决**（MS2 移交）：web-core 现存 446+ 行 DiagramViewer，消费方 5 处（architect FlowDiagram / chat ChatSession+ChatMessage / docs DocViewer / workbench AIAssistantPanel+ChatView）
- **architect types/index.ts 死类型清理**：Blueprint/KbQuery* 等（MS2 在途保护 deferred）

## 2. 目标 / 非目标
- **目标**：六目标件降至 <800 行/件；每件拆出"子组件 + composables + 类型"三层；行为零变（纯结构重构）
- **非目标**：不改 UI/交互/API 契约；不动 ConversationDock（951 行软上限内）；不做性能优化（除顺带）

## 3. 批次划分（安全网先行，同 MS1 模式）

| 批 | 内容 | 判据（全绿门禁） | 预估 |
|---|---|---|---|
| **W0 安全网** ✅ | 六目标件 vitest 挂载冒烟+交互守卫（Vue 原生 createApp 挂载，零新依赖；两域 vitest 补 vue 插件口径已统一） | architect 64/64 + workbench 19/19 + 双域 typecheck 干净 | 1.5d |
| **W1 AssetManagementWorkspace** ✅ | 逻辑层八域 composable（asset-workspace/：core 四元组整块+diff/chat/framework/unowned/sync/purgeBatch/graphTabs）+ 模板三面板（provide/inject 每挂载一套状态，行为语义保持） | 64/64+typecheck 0 错；SFC 3,296→615 行 | 1.5d |
| **W2 SemanticGraphView** ✅ | S1 逻辑层四域 + S2 模板两面板（GraphToolbarPanel 326 / GraphMainPanel 703，SGV_WS_KEY 注入；样式分发：icon-pulse→工具栏，anchor-flash/td-node/card-*→主区） | 64/64+typecheck 0 错；**SFC 2,649→282 行**（<800 达成） | 1.5d |
| **W3 AnalysisChat** ✅ | S1 逻辑八域(chat-view/) + S2 模板两面板(ChatFeedPanel 1055/ChatBottomPanel 356, WS_KEY 注入+props 整体 v-bind 透传) | 64/64+typecheck 0 错；**SFC 2,383→421 行** | 1d |
| **W4 ReportHome + ProjectCard** ✅ | ReportHome: load/presum/ui 三域+MainPanel(样式随迁); ProjectCard: state/menu/edit/actions 四域+MainPanel(模板+scoped 样式下沉, **全局 .context-menu 样式留 SFC**) | workbench 19/19+typecheck 0 错；**1,443→157 / 1,441→167** | 1.5d |
| **W5 community-store 抽 useComponentAnalysis** ✅ | 组件分析簇(useComponentAnalysis 174: analyzeSelected/runTask/stop/retry) + agent 任务簇(useAgentTasks 364: 触发/轮询/历史/取消)外移；store 792 行仍为唯一 API 面(return 展开) | workbench 19/19+typecheck 0 错；**1,252→792(-37%)** | 1d |
| **W6 收尾** | types 死类型清理 + **DiagramViewer 裁决已定案（2026-09-25 方案A：留 web-core；RebuildDialog=私有子件标注已落）**+ 文档回写 | 全套件+milestones 更新 | 1d |

**合计 ~9 人日**（与原估算一致）。tag 计划：开工前 `git tag pre-MS6`。

## 4. 风险与缓解
| 风险 | 缓解 |
|---|---|
| 大组件隐式依赖（provide/inject、事件总线、store 直引） | W0 先做依赖盘点（grep inject/emit/$bus）入档再动刀 |
| 拆出后 props 钻透过深 | 允许 composables 内直引 store（项目既有模式），不强推纯 props |
| 用户在途工作冲突 | 每批开工前核 git status；涉 chat/ 目录先协调 |
| vitest 对大组件挂载超时 | shallowMount+关键子组件 stub |

## 5. 与其他里程碑的接口
- W6 DiagramViewer 裁决**已定案（方案A 留 web-core）**——MS7-W3 无迁移联动；重评触发条件（第 3 消费应用/需求分叉）已写入组件头注
- 不依赖 MS5-V3B / MS7，可**立即开工**


---

## 6. W0 执行记录（2026-09-25）

### 6.1 依赖盘点（动刀前入档）
| 目标 | props/emits | 外部依赖面 | inject/provide |
|---|---|---|---|
| AssetManagementWorkspace | 无 props / 无 emits | api-client + semantic-asset/git/kb-assets/requirement 四服务；useRouter（import 了但**未实际使用**——W1 顺带清除） | 无 |
| SemanticGraphView | tab/diffFiles/compareData/fileIndex... / emit close | settings-store + semantic-asset-service；自含 GraphTabDef/GraphFileEntry 导出 | 无 |
| AnalysisChat | turns/busy/busyLabel... / emit send、set-analysis-mode... | api-client；contract/naming/kb-analysis 均 type-only | 无 |
| ReportHome | taskId/tabId / emit open-md、open-presummary | project/analysis/report/community 四 store + ipc + display-dispatcher | 无 |
| ProjectCard | project / emit select | project store + ipc | 无 |
| community-store | ——（store） | ipc/llmClient/control-dispatcher/sound + analysis/project store；模块级 ref：pipelineSummary/agentCompletedSignal | 无 |

**盘点结论**：六件均无 inject/provide 纠缠，拆分只需处理 props/emits/store 三类边界——比预估干净。

### 6.2 安全网落地
- 新增 6 文件 / 20 例：architect 3 文件 10 例（AMW 挂载+页头+重复挂载；SGV 空索引+**FILE_BUDGET 规模闸门守卫**+命名空间渲染；AC 空挂载+busyLabel 覆盖/**默认回落**（真实 i18n key `requirement.chat.thinking`）+turns 渲染）
- workbench 3 文件 10 例（RH 挂载+重复挂载+空态；PC 名称渲染+**点击 emit select**（h() + onSelect 捕获）+pinned 样式位；CS **15 键运行时形状守卫**+模块信号量+动作面>10+getSelections 默认值）
- 挂载方式：Vue 原生 `createApp`（@vue/test-utils 因 registry 无授权不可装——零新依赖方案）；emit 捕获用 `h()` 透传 `onXxx`
- 桩策略：服务面 Proxy 全桩 + RICH 默认形状（items/total/counts/status...）；jsdom 缺 API 补桩（ResizeObserver/scrollTo）
- 门禁：architect **64/64**、workbench **19/19**、双域 `vue-tsc --noEmit` 干净


---

## 7. W1 执行记录（2026-09-25，两段提交）

### W1-S1 逻辑层（c4e4ffe）
- `pages/asset-workspace/`：`useAssetCore.ts`(四元组整块 671 行——data+compTree+scopeFilter+semanticTreeRows 内部纠缠不切, 零接缝风险) + 七特征域(diff 251/chat 153/framework 132/unowned 211/sync 131/purgeBatch 136/graphTabs 100) + `index.ts` 总装(73)
- 跨域互引经 D 注入袋惰性解析(computed 天然惰性)；scope/q/哨兵三个 watch 在总装层接线
- **生命周期留宿主**：窗口事件/会话钩子注册/轮询接管/初始加载在 SFC onMounted——composable 保持无副作用可测
- SFC 3,296→1,758；typecheck 0 错 + 64/64

### W1-S2 模板面板化
- 三面板(panels/)：OverviewPanel 386 + SemanticTreePanel 648 + WorkspaceModals 251——模板块**逐行迁出**，状态经 `ASSET_WS_KEY` provide/inject 注入(每挂载一套状态, 语义与原页一致)
- `kindIcon/copyAsset` 随树面板需求移入 core；根级 FileSourceCard 因**多根模板**留宿主(根关闭符在其前)
- SFC 最终 **615 行**（目标 <800 达成）；typecheck 0 错 + 64/64

### 陷阱记录
1. 多根模板陷阱：根级 FileSourceCard 在根 `</div>` 之后——首刀误吞根关闭符致面板 30/31 失衡，vitest SFC 解析器报"missing end tag"而 vue-tsc(strict:false) 放行——**SFC 解析器比 vue-tsc 更严，两者都要过**
2. 手术必须自底向上+硬断言边界；一次误差累积后从 git 恢复重做优于补丁式修复


---

## 8. W2 执行记录（2026-09-25，S1 逻辑层落地）

### 方法论升级：机械抽取管线
W1 手工转写 → W2 升级为**机械抽取脚本**（核心资产，后续组件复用）：
- 域内代码**逐行原文**；跨域标识符自动 `D.<域>.` 前缀重写（排除集：后随 `:` / `?` / `"` —— 类型成员/对象键/可选属性/字符串键不重写）
- **TS AST 语句对齐不可靠**（getStart 跳注释+行号偏移）；最终用**声明标记分段法**（顶层 `const/let/function/interface/type/watch` 行为分割点，范围=相邻标记之间——天然语句完整）
- 类型声明自动提升到模块级 + export；SFC 头部 import 按 body 引用自动随迁（聚合按源、默认导入保原样）
- 陷阱入档：① 返回块正则贪心吞关键字（解构名单须来自 defs 精确集合）② `level?:` 可选属性被重写 ③ SFC 多根模板（W1 已见）④ SFC 解析器比 vue-tsc 严

### W2-S1 结果
- `graph-view/`：useGraphData 333 / useGraphDetail 327 / useGraphCode 629 / useGraphRender 756 / graphTypes 5
- SFC 2,649→1,117（脚本 ~275 接线 + 模板 730 + 样式 113）；typecheck 0 错 + 64/64（FILE_BUDGET 冒烟守卫过）
- **W2-S2 已完成**：模板两面板 + key.ts(SGV_WS_KEY/provideSgvWs/useSgvWs)；SFC 最终 **282 行**
- W2 陷阱补充：⑤ 面板相对路径错位（panels/ 下的 `./X.vue` → `../../X.vue`——vite 报错清晰但 vue-tsc 不查）⑥ scoped 样式不穿透子组件——按消费方分发到面板自己的 style 块 ⑦ 注入键/面板组件的 import 插入用「条件包含性检查」会漏（早前部分插入残留+条件失配 → 重复声明/缺失并发）——**每轮手术前 grep 实况，不用记忆推断**


---

## 9. W3 执行记录（2026-09-25，S1 逻辑层落地）

### 管线固化
- 抽取管线固化为可复用工具 `/tmp/opencode/extract-vue.py`（配置驱动：domains 行段表 + anchor 锚点串）——W4/W5 直接复用
- SFC 2,383→1,613；八域 chat-view/：cards 223 / input 214 / route 166 / digest 143 / send 121 / actions 161 / proposal 89 / contract 130 + key.ts + chatTypes
- typecheck 0 错 + 64/64

### 管线陷阱新增（均已修入工具）
1. **锚点坐标漂移**（最重）：keep_tail_from 是切割后坐标——wiring 被插进模板中部。改为**唯一字符串锚**（`anchor: "onUnmounted(() => {"`）
2. `has_word(body,"t(")` 的 `\b` 尾巴在 `(` 后永不匹配 → use_i18n 永远 False——改直接正则
3. 守卫测试随架构更新：choices-card/spec-view 的源码断言改为扫描 SFC+chat-view/*.ts 组件族聚合源
4. **严禁对已抽取文件重跑抽取器**（行段坐标失效 → 组合件垃圾）——重跑前必须 git restore
5. W3-S2 陷阱：面板切割范围吞 SFC 根关闭/`</template>`（BottomPanel 尾部三连）——**面板化切割终点=内容块末行，绝不写到根关闭**；emits 清单须 `grep "emit('"` 全量收集
6. props 透传用 `v-bind="props"` 整体绑定（面板声明子集），避免逐 props 打地鼠
7. 源码守卫测试升级：聚合源 = SFC + 域目录 *.ts + panels/*.vue（递归）


---

## 10. W4 执行记录（2026-09-25）

### 结果
- **ReportHome 1,443→157**：report-view/（useReportLoad 192+ / useReportPresum 137+ / **useReportUi** 派生域）+ ReportMainPanel（模板+scoped 样式 642 行随迁）
- **ProjectCard 1,441→167**：project-view/（useCardState/Menu/Edit/Actions）+ ProjectMainPanel（模板+scoped 样式；**全局 .context-menu 样式留 SFC**——teleport 菜单需要全局作用域）
- 门禁：workbench 19/19 + typecheck 0 错

### 陷阱新增
1. **嵌套 `</template>` 截断**：面板取模板必须用 `rindex("</template>")`（v-if 内嵌 template 标签会让 index 命中中段）——W2-S2 同病复发于 W4
2. emits/props 清单以 `grep` 全量收集为准；SFC 转发 `@xxx="(p) => emit('xxx', p)"`
3. store 别名注入进 composable 函数体（pinia 单例等价原语义）；**注入的 import 必须放模块级**
4. v-bind="props" 整体透传 + 面板声明子集 = 零逐 props 打地鼠


---

## 11. W5 执行记录（2026-09-25）

- **模式**：store 逻辑簇外移为 ctx 注入式 composable（`useX(ctx)` 解构后裸名访问，正文零改写）；store setup 内接线并 `return { ...analysisApi, ...agentApi, ...原有面 }` —— API 面逐名保全（W0 形状守卫直接验证）
- 交织区教训：triggerOverview/triggerComponentAnalysis(742-820) 与 agent 轮询机制深度交织——首次切割留中段导致保留区引用移出名（use-before-declaration）；**二次切割按语义簇合并交织区**
- 保留区引用移出名的：wiring 后局部解构绑定（compile-driven 全量收集）
- 门禁：workbench 19/19 + typecheck 0 错
