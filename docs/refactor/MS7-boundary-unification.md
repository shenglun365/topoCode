# MS7 边界重塑与栈统一（B6）细化设计

> 状态：**待评审**（评审通过后按批执行，每批全绿合入）
> 核证日期：2026-09-25（工作区 clean，基线 dev-1 @ 07ba81c）
> 前置：已解除（DiagramViewer 方案A 定案）；MS6 已全部完结（d7ecfaf+046688b 质量修复）——**MS7 开工就绪**

## 1. 核证快照（实测）——两处重要修正

### 修正 A：workbench d3 图栈已是孤儿 ⚠️
`useD3Graph.ts(82) / render-manager.ts(337) / render-worker.ts(155) / render-worker-bundled.js(20,861) / workers/types.ts` 在 workbench src 内**零消费**（MS2 删消费组件时底层设施漏删）。`d3@7.9.0` 仍挂 package.json。
→ 裁决④"统一 cytoscape"的**迁移部分已无对象**：docs 已用 cytoscape（useGraphState.ts 参考实现），workbench 无图视图需求。剩余工作=纯删除。

### 修正 B：AIAssistantPanel 收敛已由 MS3 完成
architect 侧已删，仅 workbench 一套（1,436 行）。剩余工作=ChatSession 并入后的对接。

### 其余核证
| 项 | 实测 |
|---|---|
| ChatSession.vue | **1,585 行 / 77 函数**，apps/chat/src/pages/，import web-core diagramStateStore+DiagramViewer |
| topoone_app_chat | chat.py 1,815 + tagent_chat.py 285（tAgent 薄化开关）+ skills.py 226 + web_tools 子包 ✓ |
| 项目列表三处 | architect project-service.ts(110) / workbench HomePage(654 含列表) / docs ProjectList.vue(202) |
| portal 跳转 | src 内无硬编码 :3483（改址范围待 W0 核证 web-core portal 路由表） |
| kb_gateway | architect 单文件 161 行 + 测试 104 行 |
| chat 前端测试 | 无（M12 豁免备案）——上提前须补 |

## 2. 目标 / 非目标
- **目标**：chat 前端并入 workbench；chat 后端迁 workbench 域托管（:3483 独立进程保留）；d3 孤儿栈清零；项目列表三处数据层归一；kb_gateway 收口 MCP 通道；native 直读合法化入 CONV；CONV-00~04 全量更新收官
- **非目标**：不动 chat 后端行为（含 tagent 开关语义）；不合并进程模型；不做 UI 改版

## 3. 批次划分

| 批 | 内容 | 判据（全绿门禁） | 预估 |
|---|---|---|---|
| **W0 核证+安全网** | ① d3 孤儿复证（动态 import/字符串引用兜底 grep）② ChatSession 依赖盘点 ③ web-core portal 路由表核证 ④ ChatSession 迁移前 vitest 冒烟（chat 域建测试基建，M12 豁免收窄为"仅无测试页面"） | 盘点清单入档；chat 域 vitest run 绿 | 1d |
| **W1 d3 孤儿清零** | 删 useD3Graph/render-manager/render-worker+ bundled/types.ts + package.json d3 依赖 + lock 重算；**同变更核验** bundle-worker 不存在（实测未见） | workbench type-check+lint+test 绿；`grep -r d3 src/` 空；产物 -21K 行 | 0.5d |
| **W2 ChatSession 域内拆分** | 拆 useChatStream / useMessageActions / useChatCommands composables（仍在 apps/chat，行为零变） | chat 域 vitest（W0 建）绿；手测 SSE 流式对照清单 | 1.5d |
| **W3 chat 前端上提** | ChatSession+composables 迁 workbench/src/components/chat/；与 AIAssistantPanel 对接（复用 diagramStateStore 契约）；apps/chat/src 清理（DiagramViewer 留 web-core【MS6-W6 方案A 定案】，ChatSession 迁入 workbench 后改 @topo/web-core 引用不变） | workbench 全套件绿；两应用构建绿；chat 前端残余核空 | 1.5d |
| **W4 chat 后端域托管** | apps/chat/topoone_app_chat → apps/workbench/chat_service/（目录迁移+import 路径+pyproject+启动脚本+CI 路径）；**保留独立进程 :3483**；docs/portal 跳转改址（按 W0 路由表） | chat 32+docs 18 后端套件绿；进程启停冒烟；RPC 基线 diff 空 | 2d |
| **W5 项目列表三处归一** | 数据层归一（api/类型/分页契约对齐 workbench 主源），三处 UI 壳各自保留 | 三域测试绿；对照清单（字段/分页/排序）零漂移 | 1.5d |
| **W6 kb_gateway MCP + native 合法化** | kb_gateway 收口为 MCP 通道（architect 经 MCP 取 KB 基线组件语义）；native 直读 C2/C3 合法化条款入 CONV | kb_gateway 测试绿+MCP 冒烟；CONV 条文落笔 | 2d |
| **W7 收官** | CONV-00~04 全量更新（含裁决①~⑥最终态）；milestones 收口；全程序总结报告 | 五域全套件全绿；文档闭环 | 1.5d |

**合计 ~11.5 人日**（原估 12d 持平，修正 A 省出的量转入 W0 加固）。
tag 计划：`git tag pre-MS7`；W4 前追加 `pre-MS7-W4`（目录迁移回退锚点）。

## 4. 风险与缓解
| 风险 | 缓解 |
|---|---|
| ChatSession 上提后 SSE 跨域鉴权/代理路径变化 | W3 先在 workbench 加代理或复用同一 origin 策略，手测清单把关 |
| 后端目录迁移触发 MS4-W1 同款 multi-name from-import 事故 | 全量 import 复扫脚本（W1 已有）随迁必跑 |
| ChatSession 与 V3-StepB 挂起专项的耦合 | W2 拆分仅动前端，不涉 chat.py；专项结论不影响本批 |
| 项目列表归一改字段引发下游断言 | 对照清单 golden 化（三域快照）先行 |
| MCP 通道为新增面，无既有测试范式 | W6 先写契约测试（请求/响应 schema）再实现 |

## 5. 依赖与顺序
- **依赖 MS6-W6**（DiagramViewer 裁决）→ 建议 MS6 先行
- **不依赖 MS5-V3B**（chat.py 挂起专项与前端拆分/迁移正交）
- V3-StepB 若仍挂账，W4 迁移时**原样搬迁不拆分**（W8 先例：不为迁移而拆）


---

## 6. W0 核证批执行记录（2026-09-25，开工准备）

- **tag**：`pre-MS7` 已打（裁决⑥ 兜底纪律）
- **① d3 孤儿复证 ✅**：全 src 唯一 d3 引用在 render-worker.ts 自身内部（动态 import），外部消费面为零——W1 纯删安全成立
- **② ChatSession 依赖盘点 ✅**：web-core 依赖 9 处（api/render/diagramStateStore/parseContent/chat-stream/shell/toast/dialog/AppDialog/DiagramViewer/domain types——workbench 本就依赖 web-core，上提零新增）+ 本地组件 5 个随迁（ChatInput/ChatSidebar/ChatMessage/RenameDialog/SaveAsDocDialog）；chat 前端全量 2,550 行 / 7 vue
- **③ 3483 引用面 ✅**：前端**零硬编码**；引用全部在 chat 域自身（manifest.toml 声明式端口 + main.py 默认值）——W4 迁移只动 manifest/pyproject/CI 路径
- **④ 重大发现：代理链** —— chat 前端 vite proxy `/api → 3456 主服务`（**非直连 3483**！），与 workbench 现有 proxy 完全一致 → **W3 上提后零代理改动**（原设计的"跨域鉴权风险"不成立，同源同代理语义）
- **⑤ chat 前端测试基建**：无 vitest（M12 echo）——W2 前需建最小冒烟（vitest.config + ChatSession 挂载 2 例）
