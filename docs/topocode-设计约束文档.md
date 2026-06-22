# TopoCode 设计约束文档

> 版本: 1.0  
> 最后更新: 2026-06-22  
> 目的: 定义前后端架构的核心设计约束，确保所有功能拓展遵循一致的架构原则。

---

## 1. 整体架构

### 1.1 架构分层

```
Electron Main Process
  ├── preload.ts          ← contextBridge（唯一前后端通信通道）
  ├── zmq-router.ts       ← ZMQ DEALER/SUB 客户端
  ├── python-bridge.ts    ← Python 子进程管理
  └── window-manager.ts   ← 多窗口管理

Renderer Process (Vue 3)
  ├── pages/              ← 路由页面（5 个顶级路由）
  ├── components/         ← UI 组件（60+）
  ├── stores/             ← Pinia 状态管理（22 store）
  ├── services/ipc.ts     ← IPC 适配层（camelCase 转换）
  └── types/ipc.ts        ← IPC 接口类型定义

Python Backend (backend-core/)
  ├── zmq_server.py       ← ZMQ RPC 服务器 + 事件发布
  ├── core_service.py     ← 方法注册入口
  ├── sqlite_ctx.py       ← 多数据库管理 + 表定义
  ├── agent_workflow/     ← Agent 工作流引擎
  ├── context/            ← LLM 上下文装配系统
  ├── store/              ← 数据库 CRUD 封装
  ├── analyst_runner.py   ← 社区分析编排
  └── plugins/            ← 语言解析器、LLM 提供商等
```

### 1.2 通信模型

```
[Vue Component]
  → store.action()
    → services/ipc.ts (camelCase)
      → window.api.xxx.yyy()
        → [preload] ipcRenderer.invoke('ipc:call', {method, params})
          → [electron] zmqRouter.call(method, params)
            → DEALER socket → [Python] ZMQServer.methods[method](**params)
              → 返回结果 → DEALER socket ←
```

**约束：**
- 不允许从前端直接调用 Python 模块或访问文件系统
- 所有业务通信必须通过 IPC 信道（`ipc:call`）
- IPC 超时须在 zmq-router.ts 中按方法指定（默认 30s，长任务 600s）
- 事件推送通过 SUB socket（`zmq:event`），前端通过 `window.api.onZmqEvent` 订阅

---

## 2. 后端架构约束

### 2.1 ZMQ 方法注册

```
@server.register("module.method")
def my_method(param1=None, param2=None):
    # 参数同时支持 snake_case 和 camelCase
    ...
    return {"result": ...}
```

**约束：**
- 方法名使用 `module.method` 格式（点号分隔）
- 参数必须同时支持 `snake_case` 和 `camelCase`（`task_id` / `taskId`）
- 返回值必须是 JSON-serializable dict
- 同步方法直接返回；异步方法用 `asyncio.run_coroutine_threadsafe`
- 每个方法必须在 `rpc_ids.py` 中有唯一的 `API-XXX` 编号
- 新建方法不要复用已有 `API-XXX`，在 `rpc_ids.py` 末尾追加

### 2.2 数据库

**数据源划分：**
```
Main DB   (topoone.db)        ← 项目/任务/模型/配置等全局数据
Knowledge DB (knowledge.db)   ← 知识库文档
Session DB (sessions.db)      ← LLM 会话历史
Project DB (project.db)       ← 每个项目独立，存在 .topocode/data/ 下
```

**约束：**
- `TaskStore` 操作主库的 `analysis_tasks` 系列表
- `AnalysisStore` 操作项目库的 `graph_node` / `graph_edge` / `file_summaries` 等
- 项目库通过 `multi_db.get_project_db(project_id)` 获取（LRU 缓存，max=3）
- 写操作须立即 `commit()`，不允许延迟提交（Agent 流程可能随时被取消）
- 新建表在 `sqlite_ctx.py` 中同时定义：
  - `MAIN_DB_TABLES_SQL`（主库表）
  - `PROJECT_DB_TABLES_SQL`（项目库表）
  - `_migrate_main_tables()` 中的 ALTER TABLE（旧库迁移）
  - `_migrate_project_db()` 中的 ALTER TABLE（旧项目库迁移）

### 2.3 Agent 工作流

**路由注册**（`router.py`）：
```python
create_default_router().dispatch(action, task_id, context)
```

**工作流类型：**
| 类型 | 基类 | 执行模式 | 适用场景 |
|------|------|----------|----------|
| 顺序工作流 | `AgentWorkflow` | `plan()` → 预定义步骤 → `finalize()` | 预摘要、架构分析 |
| 智能工作流 | `AgenticWorkflow` | ReAct 循环：LLM→工具→观察→LLM... | 组件分析 |

**约束：**
- 每个 `AgenticWorkflow` 须实现 `get_system_prompt()` 方法
- 工具类继承 `AgentTool`，实现 `execute(**kwargs) → ToolResult`
- Tool 注册通过 `ToolRegistry.register()`，由 `tool_factory.py` 统一管理
- 顺序工作流的步骤通过 `AgentTool.execute(**step.args)` 执行
- `AgenticWorkflow` 每组件每轮超时由 `max_turn_timeout` 控制（默认 900s）
- 取消通过 `runtime.cancel()`（设置 `self._cancelled`），在 turn/component 边界检查
- **不通过 `SubAgent._task_cancelled` 传播取消**（`-j` 并发时多个 Agent 共享 task_id）

**取消检查点：**
```
组件循环开始:  if self._cancelled: break
Turn 循环开始: if self._cancelled: break
LLM 调用中:    每 2s 轮询一次 self._cancelled（_run_agentic_chat）
```

**保存时机：**
- `_save_component_result()` 在 turn 循环退出后、组件 for 循环内执行
- **取消时已完成的分析结果仍然落库**

### 2.4 Context Assembly 系统

**核心类：**
```
ContextIngredient      ← 单一数据源：collect() + format()
CollectContext         ← 数据收集上下文（dataclass）
ContextAssembler       ← 按 recipe 组装：assemble(recipe, ctx) → str
```

**约束：**
- 每个 ingredient 只能负责**一种**数据源
- `collect()` 只做数据查询，`format()` 只做文本格式化，两者分离
- `collect()` 接收 `CollectContext`，不能访问全局状态
- ingredient 之间不允许互相调用
- 新增数据源只需新建 `ContextIngredient` 子类 + `registry.py` 中 `register()`
- Recipe 在 `recipes/__init__.py` 中声明（ingredient name 数组）
- `CollectContext._comm_meta` 由调用方传入，供 `CommunityInfoIngredient` 等使用

**当前 Recipe 定义：**
| Recipe | Ingredients | 用途 |
|--------|-------------|------|
| `RECIPE_COMPONENT_ANALYSIS` | community_info, file_list, directory_tree, exported_symbols, file_centrality, edge_relations, parent_chain, import_external | 非 Agentic 组件分析 |
| `RECIPE_COMPONENT_ANALYSIS_AGENTIC` | community_info, directory_tree, exported_symbols, edge_relations | Agentic 组件精简上下文 |
| `RECIPE_ARCH_COMMUNITY` | community_info, file_list, directory_tree, exported_symbols, file_centrality, edge_relations | 架构分析每社区 |
| `RECIPE_ARCH_OVERVIEW` | tech_stack, test_coverage, entry_points | 架构总览 |
| `RECIPE_FILE_SUMMARY` | file_metadata | 文件预摘要 |

**扩展路径：**
```python
class NewSourceIngredient(ContextIngredient):
    name = "new_source"

    def collect(self, ctx: CollectContext):
        return ctx.db.execute(...).fetchall()

    def format(self, data) -> str:
        return f"数据: {', '.join(...)}"

# registry.py 中:
a.register(NewSourceIngredient())

# 或加到已有 recipe:
RECIPE_COMPONENT_ANALYSIS = [..., "new_source"]
```

### 2.5 文件预摘要

**约束：**
- 所有文件统一走 AST 结构提取（`_should_use_structure` 不再检查文件大小）
- 只有 AST 数据缺失时才回退全文读取
- 每个文件摘要前注入元上下文（导出/导入/引用方/类型）
- 输出格式为结构化文本：
  ```
  [类型] module/utility/config/entry/test/api
  [用途] 一句话（30 字内）
  [导出] 关键函数/类名
  [依赖] 外部包或文件依赖
  [说明] 详细说明（100 字以内）
  ```
- 摘要缓存通过 `file_summaries` 表（project_id + file_path 唯一）
- 缓存写入是同步 `commit()`，取消不影响已完成的写入

---

## 3. 前端架构约束

### 3.1 Store 模式

所有 Store 使用 Pinia composition API：

```typescript
export const useXxxStore = defineStore('xxx', () => {
  // State（ref）
  const items = ref<Item[]>([])

  // Getters（computed）
  const selectedItem = computed(() => items.value.find(i => i.id === selectedId.value))

  // Actions（async function）
  async function loadItems(projectId: string) {
    items.value = await ipc.xxx.listItems(projectId)
  }

  return { items, selectedItem, loadItems }
})
```

**约束：**
- 禁止在组件中直接调用 `window.api`，必须通过 `services/ipc.ts` 适配层
- IPC 调用参数使用 camelCase（`taskId` 而非 `task_id`），适配层自动转换
- API 返回字段在前端也使用 camelCase（由 `services/ipc.ts` 中 `camelizeKeys` 转换）
- 存储社区数据的唯一来源是 `community-store.ts` 中的 `tasks[taskId].communities`
- 每个 task 运行时数据通过 `ensureTask(taskId)` 懒初始化

### 3.2 架构图渲染

**组件层级：**
```
CommunityGraphView.vue
  └── GraphCanvas.vue
       └── CytoscapeGraph.vue    ← 核心渲染器
```

**约束：**
- 使用 Cytoscape.js 作为力导向图引擎
- 边数据在传入 `CytoscapeGraph.vue` 前已完成双向边合并（`_bidirectional` 标记）
- 节点半径通过 `getNodeRadius()` 计算（公式：`Math.sqrt(nodeCount) * 3 + 8`）
- 节点颜色通过 `nodeColor()` 根据 `qualityScore` 映射色阶
- 节点默认 `text-wrap: 'wrap'` + `text-max-width` 实现自动换行
- 标签长度 >24 字符时截断加 `…`
- 社区标签优先级：`LLM name > 算法分配 ID（L1-0000）`
- drill-down 通过 `drillPath` 数组维护，双击节点推送新层级

### 3.3 子文档预览

`SubDocViewer.vue` 渲染 LLM 分析结果：
- 标题显示 `result.name`
- 内容渲染 Markdown（通过 `<SubDocContent>` 组件）
- 底部自动追加子组件列表（从 `communities` 过滤 `parentId`）
- 无结果时显示引导提示："请先通过 AI 助手运行组件分析"

---

## 4. 数据流约束

### 4.1 LLM 分析结果流向

```
LLM 输出 JSON
  → parse_structured_response() / json.loads()
    → 插入 component_analysis 表（task_id, component_id, analyzed_name, functional_summary, status）
      → 同步写入 community_llm_results 表（name, summary）
        → 前端 loadCommunities() 合并到 CommunityItem.name
          → communityLabel() 展示
```

**约束：**
- `component_analysis` 是主存储，`community_llm_results` 是为标签视图同步的副本
- 两表通过 `_save_fn` 中的同步逻辑保持一致
- 解析失败（`_parse_error=true`）时 status 标记为 `failed`
- `communityLabel()` 显示优先级：`saved.name > communityIdLabel(item.communityId)`

### 4.2 外部依赖/调用数据流向

```
graph_node (kind='import') + graph_edge (kind='imports')
  → getExternalStats() Python 差集过滤
    → { externalDeps, externalCalls }
      → community-store.ts t.externalStats
        → CommunityGraphView 外部标签页
```

**约束：**
- `target_id = ''` 的 CALL 边视为未解析的外部调用
- 外部依赖通过"import 节点"减去"已解析 imports 边"的差集计算
- `loadExternalStats()` 在切换外部标签时强制加载（`force=true`）
- 空结果不缓存（`externalStats = null`），允许后续重试

### 4.3 预摘要数据流向

```
startPreSummary()
  → PreSummaryWorkflow.plan() → 按 batch 分批
    → SummarizeFileTool.execute() → SubAgent.summarize_files()
      → _read_or_cache() per file
        → _summarize() + file_cache.put()
          → file_summaries 表 commit
```

**约束：**
- 取消检查在 batch 边界，当前 batch 全部完成后才响应取消
- 每个文件三阶段：检查缓存 → LLM 摘要 → 写入缓存（同步 commit）
- LLM 摘要与写入之间没有取消检查点

---

## 5. 功能拓展流程

### 5.1 新增后端 API

```python
# 1. rpc_ids.py 追加
"analysis.myNewFeature": "API-089",

# 2. task_manager.py / core_service.py 注册
@server.register("analysis.myNewFeature")
def my_new_feature(task_id=None, taskId=None, ...):
    tid = task_id or taskId
    ...

# 3. src/types/ipc.ts 追加接口类型
myNewFeature: (params: { taskId: string; ... }) => Promise<{ ... }>

# 4. src/services/ipc.ts 追加适配
myNewFeature: (params) => ipcCall('analysis.myNewFeature', params),

# 5. store / component 调用
const result = await ipc.analysis.myNewFeature({ taskId })
```

### 5.2 新增 LLM 分析场景

```python
# 1. context/ingredients/ 新建数据源
class MySourceIngredient(ContextIngredient):
    name = "my_source"
    ...

# 2. context/registry.py 注册
a.register(MySourceIngredient())

# 3. context/recipes/__init__.py 定义 recipe
RECIPE_MY_ANALYSIS = ["community_info", "my_source", ...]

# 4. 新建 workflow
class MyAnalysisWorkflow(AgentWorkflow):
    ...

# 5. agent_workflow/router.py 注册路由
router.register("my_analysis", MyAnalysisWorkflow, tool_builder=...)

# 6. 前端调用
ipc.analysis.startMyAnalysis({ taskId, ... })
```

### 5.3 新增前端视图

```typescript
// 1. 定义接口类型 src/types/ipc.ts

// 2. store 中定义状态和 action
// 3. 组件引用 store，通过 ipc 调用后端
// 4. 遵守组件层级：页面 → 容器组件 → 纯展示组件
// 5. 力导向图集成：通过 GraphCanvas.vue 包装 CytoscapeGraph.vue
```

---

## 6. 性能约束

| 场景 | 约束 |
|------|------|
| IPC 默认超时 | 30s |
| 项目导入超时 | 300s |
| 分析任务超时 | 600s |
| Agent 每轮超时 | 900s |
| 项目库 LRU 缓存 | max=3 |
| LLM 上下文截断 | `functional_summary` 2000 字 |
| 文件预摘要输入 | ≤10000 字符 |
| 文件预摘要输出 | ≤2000 字符 |
| 社区标签显示长度 | ≤14 字符（`communityLabel`） |
| 并行 Agent 数 (`-j`) | 1-10 |
| `getCommunityResult` 摘要截断 | 300 字符 |
| 架构总览社区结果截断 | 10000 字符 |

---

## 7. 命名约定

| 领域 | 后端 | 前端 IPC | 前端 Store/组件 |
|------|------|----------|----------------|
| 参数风格 | `snake_case` | `camelCase` | `camelCase` |
| API 方法 | `module.method` | `ipc.module.method` | `store.action()` |
| 数据库字段 | `snake_case` | 通过 services/ipc.ts 自动转换 | `camelCase` |
| 文件名 | `snake_case.py` | — | `PascalCase.vue` / `kebab-case.ts` |
| 类名 | `PascalCase` | — | `PascalCase` |
| 社区 ID | `comm-{hash}-{edge}-{level}-{index}` | 同左 | `communityId` |

---

## 8. 已移除的废弃模式

以下模式已从代码库中移除，新代码**不得**再使用：

| 废弃模式 | 替代方案 | 移除原因 |
|----------|----------|----------|
| `_FILE_SIZE_THRESHOLD` 大小阈值决定 AST/全文 | 统一走 AST（`_should_use_structure` 检查 AST 是否存在） | 小文件用 AST 结构信息更充分 |
| inline `ctx_parts.append()` 构建 LLM 上下文 | `ContextAssembler.assemble(recipe, ctx)` | 可组合性、可测试性差 |
| `SubAgent._task_cancelled` 传播取消 | `AgentRuntime._cancelled` 实例级标志 | `-j` 并发时误取消其他 Agent |
| `defaultName` 从文件路径推断社区名 | 仅使用 LLM name 或 `communityIdLabel` 算法 ID | 目录名如 "util" 无意义 |
| `frontend loadExternalStats` 永久缓存空结果 | 空结果设 `null` + 切换标签时 `force=true` | 分析完成后无法刷新 |
| 全局 `getExternalStats` `except Exception: dep_rows = []` | `logger.error(..., exc_info=True)` 打印异常 | 静默吞错误导致排查困难 |
