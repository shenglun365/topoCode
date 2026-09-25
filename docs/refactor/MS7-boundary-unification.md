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
| **W1 d3 孤儿清零** ✅ | 删 5 文件(-21,552 行含 bundled)+d3/@types/d3 依赖移除+孤儿 i18n 键清理；lock 剩余 d3=mermaid/cytoscape 生态传递引用(非本仓声明) | typecheck 0+19/19；package.json/root grep 零命中 ✓ | 0.5d |
| **W2 ChatSession 域内拆分** ✅ | **chat 前端 vitest 基建建成(零新依赖, M12 豁免收窄为 2 例挂载冒烟)** + useChatStream(165)/useChatMsgactions(161) 外移(ctx 式 D 注入) | chat vitest 2/2；SFC 1,585→1,445 | 1.5d |
| **W3 chat 前端上提** ✅ | git mv 纯迁移(98-100% 相似度)：ChatSession+chat-view+5 组件→workbench(components/chat/+pages/)；i18n 深合并(base 优先/chat 补缺, common 冲突安全)；/chat 路由+导航标题；**chat FE src 核空+deps 清零+FE 配置移除**；AIAssistantPanel 对接=共享 diagramStateStore 契约(已成立, 零改动)；strict:true 适配(reasoning 安全访问) | workbench 21/21+typecheck 0+**构建 13.2s 绿**；chat 后端 32 绿 | 1.5d |
| **W4 chat 后端域托管** ✅ | git mv 包体+tests+pyproject → apps/workbench/chat_service/（99-100% 纯移）；**manifest 原地瘦身**（gateway 发现=apps/*/manifest.toml 硬约定，不可随迁；static_dir/mount 随 FE 并入退役）；conftest sys.path 引导免 pip 重装；setup.sh/CI/README/test:py 路径全改；**独立进程 :3483 保留**(python_entry 不变) | 后端 32+docs 18+architect 1098+parity 5 全绿；import 冒烟 OK；RPC 基线 diff=0 | 2d |
| **W5 项目列表三处归一** ✅ | 核证修正：三处**同源主库**（docs /api/projects 即主库 4 字段；architect arch_projects=裁决① 独立域合法）。唯一漂移=docs **缺主源排序**→ 已对齐（pinned DESC, sort_order ASC, updated_at DESC）；diagram-editor 跨服务 import 路径修复（conftest 引导） | docs 18 绿（含 diagram-editor 修复）；对照清单 golden 入档 | 1.5d |
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


---

## 7. W2 执行记录（2026-09-25）

- **chat vitest 基建**：零新依赖（vitest/jsdom 经 workspace 提升；plugin-vue 走根 node_modules）；`test` script 从 echo 占位改为 `vitest run`——**M12 豁免正式收窄**
- **冒烟 2 例**：全服务面 Proxy 桩 + BroadcastChannel/matchMedia/ResizeObserver jsdom 补桩下挂载/重复挂载
- **抽取**：useChatStream(send/SSE/abort/图表开关) + useChatMsgActions(选择/删除/复制/引用/续写/存笔记)，SFC 1,585→1,445
- **重大发现**：ChatSession.vue 头部 **@ts-nocheck**（M12 迁移豁免）——chat FE 的 typecheck 门对本文件恒 vacuous，**真实门禁 = vitest 冒烟**；W3 上提时维持此口径
- 剩余大块（notes/archives/annotations/tabs 状态机 ~700 行）随 W3 上提原样随迁，不再预拆（收益不足）


---

## 8. W3 执行记录（2026-09-25）

- **迁移形态**：git mv 纯移动（rename 检测 98-100%）；`@topo/web-core` 引用全部不变（workbench 本依赖 web-core）；`@/components/*` → `@/components/chat/*` 重写 5 处
- **i18n 合并**：chat 树（common/session/msg/note/... 8 命名空间）与 workbench 树 `common` 冲突——深合并 `mergeChatApp<T>(base, extra): T`（**泛型保型**避免 vue-i18n schema 推断爆炸/TS2589；已有键 base 优先，chat 补缺）
- **strict:true 适配**：ChatMessage reasoning 可选链（chat 原 tsconfig 宽松）
- **残余核空**：apps/chat 仅存 backend(topoone_app_chat)+tests(py)+manifest/pyproject；FE deps 清零、FE 配置(vite/vitest/tsconfig/index.html/dist)全删
- chat 后端 32 例回归 ✓（未触及）


---

## 9. W4 执行记录（2026-09-25）

- **决定性约束**：`discover_apps` = `apps/*/manifest.toml` 硬扫描 → manifest 不可随包迁移；包体迁至 chat_service/ 后 `python_entry = "topoone_app_chat:main"` 模块路径不变（import 由 editable/conftest 解析），gateway/uvicorn **零改动**
- **conftest sys.path 引导**：tests 目录插入包父路径——免 pip 重装即可跑（CI editable 路径同步更新后双保险）
- **残余清单**：apps/chat/ 仅存 manifest.toml（发现约定必需）；workspaces/lock/setup.sh/CI/README/chat.py 注释全部改净（grep 零命中）
- **裁决② 达成度 100%**：前端(W3) + 后端(W4) 均入 workbench 域托管，:3483 独立进程保留


---

## 10. W5 执行记录（2026-09-25）

### 对照清单 golden（三处契约，核证后定稿）

| 维度 | workbench（主源基准） | docs | architect |
|---|---|---|---|
| 端点 | RPC `project.list`（engine/service/project.py:105） | REST `/api/projects`（docs web_root.py） | REST `/project/list`（arch_routes/project.py:261） |
| 数据源 | 主库 projects 表 | **同主库**（multi_db.main_db） | arch_projects（architect 自持，裁决① 独立域） |
| 字段 | 全字段+groups+存储统计（snake→camel 经 ipc.adaptProject） | id/name/rootPath/isResource（4 字段） | ProjectInfo（architect 域类型） |
| 排序 | pinned DESC → sort_order ASC → updated_at DESC | **W5 已对齐同序**（原无排序=漂移点） | pinned → favorite → updatedAt（architect 域语义） |
| 分页 | 无（全量） | 无（全量，量级小） | 无（全量） |

### 修复项
1. docs `/api/projects` 加主源同款 ORDER BY（排序零漂移）
2. docs diagram-editor 跨服务 import `topoone_app_chat`——W4 迁移后路径断裂 → docs/tests/conftest.py sys.path 引导（`parents[2]/workbench/chat_service`；生产由 setup.sh editable 覆盖）
3. Web-Root 页面（/projects 门户壳）为 docs 独立入口，UI 壳保留 ✓
