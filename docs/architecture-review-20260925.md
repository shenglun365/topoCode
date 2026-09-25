# 架构评审归档 — 2026-09-25（MS7 收官）

> MS7 边界重塑与栈统一收口评审。判据对照（MS7-boundary-unification.md §3）：

## 判据逐项

1. **chat 并入** ✅ — docs 两处跳转核证零硬编码（W0）；`:3483` 服务域托管于
   `apps/workbench/chat_service/`（manifest 留 apps/chat/ 供 gateway 发现），
   import 级冒烟 OK；完整 uvicorn 启停留用户环境验证（命令已备）。
2. **图栈** ✅（核证修正后）— workbench d3 栈系零消费孤儿，纯删除 -21,552 行；
   docs cytoscape 不动；性能 gate 随消费场景消亡留档结案（无对象可测）。
3. **边界** ✅ — architect 网络面=KB RPC/MCP+只读 HTTP（kb_gateway 双通道，
   MCP 出向首个消费路由 /kb/semantics/* 已落地+3 冒烟）；grep @topo/web-core
   architect=0（MS3 达成，MS7 复验未回归）。
4. **CONV** ✅ — CONV-00/01/04 chat 行更新（域托管后拓扑）；CONV-03 §3.1 C2
   薄层档准入（≤20 方法/无独立 DB/无长任务+触发线）；CONV-04 §5.1 C3 只读
   WAL 共享档（ro/同机/manifest 声明三约束 + open_project_ro() 工厂）。

## 遗留与移交

- **V3-StepB**（chat.py 1,815 单文件保留）已结项（W8 先例）。
- **W5 列表归一核证修正**：三处本就同源主库，唯一漂移（docs 缺排序）已修；
  architect arch_projects 独立域经对照清单 golden 确认合法（裁决①）。
- **跨套件同名 test 模块合并跑冲突**（MS5 卫生债再触发）：test:py 已改分域
  顺序执行口径；conftest 归属单一化留后续卫生批次。
- **chat FE 手测清单**：ChatSession 冒烟为挂载级；SSE 流式/会话切换建议
  人工手测一轮（迁移后 UI 行为等价性最终确认）。

## 门禁终态（分域口径）

core 296 · chat_service 32 · docs 18 · architect 1101 · workbench FE 21 +
typecheck 0 + build 13.2s · parity 5 · RPC 基线 diff 0 · file_size_gate 基线
重建（knowledge.py 350，W6 合法新增）。
