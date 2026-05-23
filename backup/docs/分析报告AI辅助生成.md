# 分析报告 AI 辅助生成（修订方案）

## 整体流程

```
[用户点击"生成报告"]
    │
    ├── 0. LLM API 校验 ── 无配置 → 提示用户配置模型
    │
    ├── 1. 预处理阶段
    │   ├── 扫描依赖文件（按语言生态 — package.json / Cargo.toml / pom.xml 等）
    │   └── 提取 README.md
    │   （源码文件摘要 不由 LLM 自动生成 → 需用户手动触发）
    │
    ├── 2. 逐层社区分析（从最细粒度开始，用户按需触发）
    │   ├── 展示所有社区为可勾选的任务列表（按 L2/L1/L0 分组）
    │   ├── 用户选择要分析的社区（可多选 → 批量提交）
    │   ├── L2 社区分析 → 提取名称(≤20字) + 功能摘要
    │   ├── L1 社区分析 → 聚合其子 L2 摘要
    │   └── L0 社区分析 → 聚合其子 L1 摘要 + 架构图
    │
    ├── 步骤1: 项目概要      ── 模板: report_project_summary
    ├── 步骤2: 架构分解      ── 模板: report_arch_decomposition
    ├── 步骤3: 核心模块说明  ── 模板: report_core_modules
    ├── 步骤4: 依赖与调用分析 ── 模板: report_dependency_analysis
    └── 步骤5: 最终整合      ── 模板: report_final_assembly
         │
         ▼
    [生成完整 MD → 打开 report-md Tab → ReportMDViewer 渲染]
```

---

## 补充需求逐项方案

### 需求A: LLM API 校验

**现状**: `ReportGenerationPipeline.vue:154-159` 已有简单校验（检查 `modelId`）。

**改进**:

| 层级 | 校验点 | 行为 |
|------|--------|------|
| ReportHome (入口) | 点击"生成报告"前检查 | 无模型 → 弹出配置引导 Dialog, 链接到设置页 |
| 流水线每步执行前 | `runStep()` 开头 | 无模型 → 跳过该步, 标记 error, 提示"请先配置模型" |
| 文件摘要前置任务 | 每个文件摘要调用前 | 同上 |

### 需求B: 上下文限制

**方案**: 在每个 LLM 请求前执行 token 预估 + 超限降级。

```python
# 后端工具函数: estimate_token_count(messages) -> int
# 启发式: 中文 ~1.5 chars/token, 英文 ~4 chars/token
# 混合: chars / 2.5 (保守估计)

# 降级策略按步骤:
SUMMARY_LIMIT = 0.6  # 每个摘要 ≤ 60% 上下文
COMMUNITY_LIMIT = 0.5  # 社区分析 ≤ 50% 上下文
```

**各步骤降级策略**:

| 步骤 | 降级策略 |
|------|---------|
| 文件摘要预处理 | 按文件优先级（核心 > 工具 > 测试）排队, 每次摘要仅包含单个文件 |
| L2 社区摘要 | 每个社区独立请求, 数据仅包含该社区的节点和边 |
| L1/L0 聚合 | 输入只有子社区的摘要文本（已压缩的） |
| 步骤1 项目概要 | 限制文件摘要数量, 按重要性排序取 top N |
| 步骤5 最终整合 | 不传完整前四步输出, 仅传各步的核心结论摘要 |

**模型配置扩展**: `model_configs` 表增加 `context_window` 字段（默认 8192 token）。

### 需求C: 任务树 UI

**现状**: 流水线只显示 5 个高层步骤，不显示子任务。

**改进**: 将任务树从固定 5 步改为动态树结构。

```
📋 报告生成: 项目名
├── 📄 文件摘要 (3/12)
│   ├── ✅ src/main.ts               ← 每个文件摘要是一个子任务
│   ├── ✅ src/App.vue
│   ├── 🔄 src/store/index.ts           ← 正在执行
│   └── ⏳ ... (9 个待处理)
├── 📖 依赖文件提取 (2/2)
│   ├── ✅ package.json
│   └── ✅ Cargo.toml
├── 📊 社区逐层分析
│   ├── 🔄 L2 (2/8)
│   │   ├── ✅ comm_l2_001 "表单处理"
│   │   ├── 🔄 comm_l2_002 "API 路由"
│   │   └── ⏳ ...
│   ├── ⏳ L1 (0/3)
│   └── ⏳ L0 (0/1)
├── 📝 步骤1: 项目概要
├── 🏗  步骤2: 架构分解
├── 🔧 步骤3: 核心模块说明
├── 🔗 步骤4: 依赖与调用分析
└── 📚 步骤5: 最终整合
```

**实现**:

- `PipelineTaskNode` 接口:
  ```typescript
  interface PipelineTaskNode {
    id: string
    label: string
    type: 'group' | 'step' | 'subtask'
    status: 'pending' | 'running' | 'completed' | 'error'
    progress?: number      // 0-100, group 类型时聚合子节点
    children?: PipelineTaskNode[]
    stepId?: string        // 关联的步骤 ID（非 leaf 节点可选）
    error?: string
  }
  ```

- 组件: `PipelineTaskTree.vue` — 递归渲染树形结构, 每个节点显示图标 + 名称 + 状态 + 进度条
- 进度计算: 叶子节点加权平均 → 父节点汇总

### 需求D: 步骤1 细化 — 文件摘要 + README + 依赖文件

#### D1: 文件摘要（用户按需触发，非自动）

**设计决策**: 不对每个源码文件自动生成 LLM 摘要（代价过大）。仅在用户明确需要时（如右侧 AI 面板的"生成文件摘要"按钮），对选中的单个文件提交 LLM 分析。预处理阶段自动提取的仅限于 README.md 和依赖管理文件（package.json 等）。

**新增表**: `file_summaries`（项目库级别）

```sql
CREATE TABLE IF NOT EXISTS file_summaries (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    task_id TEXT,               -- 可选, 关联到生成时的任务
    file_path TEXT NOT NULL,
    summary TEXT NOT NULL,      -- ≤100 字
    summary_len INTEGER DEFAULT 0,
    source TEXT DEFAULT 'llm',  -- 'llm' | 'readme' | 'dep_file' | 'manual'
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_file_summaries_project ON file_summaries(project_id);
CREATE INDEX IF NOT EXISTS idx_file_summaries_file ON file_summaries(project_id, file_path);
```

**新建模板**: `file_summarize`

```
ID:       file_summarize
Mode:     structured (JSON 输出)
Category: report_pipeline
```

System Prompt:
```
你是一个代码摘要专家。为提供的源码文件生成不超过 100 字的功能摘要。
返回 JSON 格式，包含: summary, keywords (最多 5 个标签)
用中文回答。
```

User Prompt:
```
## 文件: {filePath}
## 语言: {language}

```{language}
{codeContent}
```

请生成功能摘要（不超过 100 字）。
```

Output Schema:
```json
{
  "type": "object",
  "properties": {
    "summary": {"type": "string", "maxLength": 100},
    "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 5}
  },
  "required": ["summary"]
}
```

**执行策略**: 不全部摘要 — 仅对以下文件生成:
1. `reportTypes` 对应的分析类型覆盖的核心文件（从社区节点推断）
2. 用户显式勾选的文件（扩展需求）
3. 限制单次最多 50 个文件（按优先级排序：核心模块 > 工具类 > 配置文件 > 测试文件）

#### D2: README 提取

直接读取 `README.md` 文件内容, 存入 `file_summaries`（source='readme', summary=前 500 字符）, 传入步骤1 的变量。

**IPC**: 无需新增 — 通过已有 `project.getFileTree` 找到 README.md, 再用 `fs.readFile` 读取。

#### D3: 依赖文件提取

**检测逻辑**: 按语言生态扫描项目根目录

| 文件 | 语言/生态 | 处理方式 |
|------|----------|---------|
| `pom.xml` | Java (Maven) | 解析 `<dependencies>` 提取 groupId:artifactId:version |
| `build.gradle` / `build.gradle.kts` | Java (Gradle) | 正则提取 implementation/testImplementation 依赖 |
| `settings.gradle` / `settings.gradle.kts` | Gradle 多模块 | 提取 include 的子模块 |
| `package.json` | Node.js | JSON 解析 dependencies + devDependencies |
| `package-lock.json` / `yarn.lock` / `pnpm-lock.yaml` | Node.js | 提取锁定版本信息 |
| `requirements.txt` | Python | 逐行解析包名+版本 |
| `pyproject.toml` | Python (PEP 621) | TOML 解析 dependencies |
| `Pipfile` / `Pipfile.lock` | Python (Pipenv) | 解析 |
| `poetry.lock` | Python (Poetry) | 解析 |
| `CMakeLists.txt` | C/C++ (CMake) | 正则提取 find_package / target_link_libraries |
| `conanfile.txt` / `conanfile.py` | C/C++ (Conan) | 解析 |
| `vcpkg.json` | C/C++ (vcpkg) | JSON 解析 |
| `Cargo.toml` | Rust | TOML 解析 dependencies |
| `Cargo.lock` | Rust | 解析锁定版本 |
| `go.mod` | Go | 解析 require |
| `go.sum` | Go | 解析哈希校验 |
| `composer.json` | PHP | JSON 解析 |
| `Gemfile` | Ruby | 解析 |
| `*.csproj` | C# | 解析 `<PackageReference>` |
| `packages.config` | C# (旧) | 解析 |
| `pubspec.yaml` | Dart/Flutter | YAML 解析 dependencies |

**实现**:

- 后端新函数: `_extract_dependency_info(root_path: str) -> Dict[str, Any]`
- 遍历已知文件名模式, 按对应格式解析
- 结果结构:
  ```json
  {
    "projectName": "...",
    "dependencyFiles": [
      {"file": "package.json", "type": "node", "dependencies": {"express": "^4.18.0", ...}},
      ...
    ]
  }
  ```
- 结果存入 `file_summaries`（source='dep_file'）, 传入步骤1 变量

### 需求E: 步骤2+3 社区分析细化 — 逐层 + 文件名/边 + Tools Calling

#### E1: 逐层生成（从最细到最粗，用户按需触发）

**设计决策**: 社区分析以可勾选的任务列表呈现，而非自动全部执行。用户可以：

- 选择部分社区（多选 → 一次提交多个，批量处理）
- 配置并发批大小（1/2/3/5/10）
- 单独暂停/继续/重试某个社区
- 一键重试所有出错社区

```
社区层级分析（并行任务列表）
│
├── 展示所有社区（按 L2/L1/L0 分组）
│   ├── 每个社区显示: 复选框, ID, 节点数, 状态(pending/running/completed/error)
│   ├── 全选/反选按层级
│   └── 底部: 批大小选择器 + "分析选中(N)"按钮
│
├── 用户勾选 → 点击"分析选中" → 批量执行
│   ├── 按批大小并发（如一次 3 个）
│   ├── 每个社区使用 community_analyze 模板 (structured 模式)
│   │     ├── 输出: name (≤20字) + summary (Markdown)
│   │     └── 前端解析结构化 JSON → 展示名称+摘要
│   └── 支持中途暂停/继续
│
├── L2 → L1 → L0 聚合
│   ├── L1/L0 的 parentSummaries 变量 = 子社区的名称+摘要
│   └── L0 输出还可包含 Mermaid 架构图
│
└── 结果存储: file_summaries (source='community_l2'/'community_l1'/'community_l0')
```

#### E2: Prompt 包含源码路径和边 + 输出社区名称(≤20字)

**新建模板**: `community_analyze`（替换原 `community_summarize`）

```
ID:       community_analyze
Mode:     structured (JSON 输出 — name ≤20字 + summary)
Category: report_pipeline
```

System Prompt:
```
你是一个代码社区分析专家。请根据以下社区结构信息,生成该社区的功能和架构说明。
社区包含多个源码文件（节点）及其调用/依赖关系（边）。
你可以使用提供的工具获取文件的完整内容或符号的详细信息。
输出 Markdown 格式，包含:
1. 社区名称（根据功能命名）
2. 核心功能说明
3. 涉及的文件列表（按重要性排序）
4. 内部调用关系概述
用中文回答。
```

User Prompt:
```
## 社区信息
- 社区ID: {communityId}
- 层级: {level} (L0/L1/L2)
- 节点数: {nodeCount}
- 边数: {edgeCount}

## 节点列表（源码文件/符号）
{nodeListWithPaths}

## 边关系（调用/依赖）
{edgeListWithDetails}

{parentSummaries}  ← L2→L1→L0 聚合时传入子社区摘要

请分析这个社区的功能和架构含义。如果需要查看某个文件的详细内容或某个符号的详情，请使用提供的工具。
```

**nodeListWithPaths 格式**（对比旧版的关键改进）:
```yaml
- node: UserService.createUser
  file: src/service/UserService.java
  type: method
- node: UserRepository
  file: src/repository/UserRepository.java
  type: class
```

**edgeListWithDetails 格式**:
```yaml
- source: UserService.createUser (src/service/UserService.java:45)
  target: UserRepository.save (src/repository/UserRepository.java:102)
  type: CALL
  direction: caller→callee
```

**父社区摘要聚合**: L1 和 L0 时, 传入 `parentSummaries`:
```
## 子社区摘要
### 子社区: 用户管理 (comm_l2_001)
用户管理社区包含 3 个文件: UserService.java, UserController.java, UserRepository.java。
核心功能: 用户的增删改查操作。
内部调用: UserController → UserService → UserRepository
```

#### E3: Tools Calling 支持（保留但不用于社区分析）

**设计决策**: 社区分析使用 `structured` 模式（JSON Schema 校验输出），无需工具调用。Tools Calling 保留用于 `arch_analysis`（架构深度解析）模板，用户可在右侧 AI 面板手动触发。

**现有工具已完善**:

| 工具 | 状态 | 用途 |
|------|------|------|
| `get_file_content` | ✅ 从磁盘读取真实文件内容 | AI 面板按需查看源码 |
| `get_symbol_detail` | ✅ 查询 base_node | 架构分析 |
| `get_community_subgraph` | ✅ 真实查询 graph_doc | 社区探索 |
| `get_edge_detail` | ✅ 调用者/被调用者详情 | 依赖分析 |
| `search_symbols` | ✅ 模糊搜索 | 符号查找 |
| `get_call_chain` | ✅ BFS 查询 graph_node | 调用链路分析 |
| `get_ast_node` | ✅ 新增 — 按 node_id 查 AST | 架构分析 |

---

## 新增/修改的文件清单

### 后端

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/prompt_manager.py` | 新增 2 模板 | `file_summarize` (structured), `community_summarize` (tools) |
| `backend/prompt_manager.py` | 修改 5 模板 | 更新变量和 prompt 内容以支持新数据源 |
| `backend/sqlite_ctx.py` | 新增表 | `file_summaries` 表 |
| `backend/tools_executor.py` | 完善 3 工具 | `get_file_content`(读取真实文件), `get_community_subgraph`(真实查询), `get_call_chain`(BFS) |
| `backend/core_service.py` | 新增 IPC | `report.prepareFileSummaries`, `report.extractDependencyFiles`, `report.getReadmeContent` |
| `backend/core_service.py` | 新增 IPC | `report.getLevelCommunityDetail` — 获取指定层级的社区完整信息（含节点路径和边详情） |

### 前端

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/components/report/ReportGenerationPipeline.vue` | 重构 | 改为动态树结构, 支持子任务树, 预处理阶段 |
| `src/components/report/PipelineTaskTree.vue` | 新建 | 递归渲染任务树的组件 |
| `src/components/report/FileSummaryPreprocessor.vue` | 新建 | 文件摘要预处理流程 UI |
| `src/components/report/CommunityAnalysisPipeline.vue` | 新建 | 逐层社区分析流程 UI |
| `src/components/report/ReportHome.vue` | 修改 | 入口增加 LLM API 校验, 展开预处理流程 |
| `src/types/ipc.ts` | 新增类型 | 新增 IPC 方法类型定义 |
| `src/stores/analysis.ts` | 修改 | 增加 `fileSummaries` 状态, `loadFileSummaries` action |

### 数据库迁移

```sql
-- 1. 新建 file_summaries 表
CREATE TABLE IF NOT EXISTS file_summaries (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    task_id TEXT,
    file_path TEXT NOT NULL,
    summary TEXT NOT NULL,
    summary_len INTEGER DEFAULT 0,
    source TEXT DEFAULT 'llm',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- 2. model_configs 增加 context_window 字段
ALTER TABLE model_configs ADD COLUMN context_window INTEGER DEFAULT 8192;
```

---

## 任务树数据结构

```typescript
// src/types/pipeline.ts (新建)
interface PipelineTaskNode {
  id: string
  label: string
  type: 'group' | 'step' | 'subtask'
  status: 'pending' | 'running' | 'completed' | 'error' | 'skipped'
  progress: number           // 0-100
  children?: PipelineTaskNode[]
  error?: string
  templateId?: string        // 关联的模板 ID
  dependsOn?: string[]       // 前置任务 ID 列表
}

// 流水线状态
interface PipelineState {
  rootTask: PipelineTaskNode
  currentPhase: 'validating' | 'preprocessing' | 'community_analysis' | 'step1' | 'step2' | 'step3' | 'step4' | 'step5' | 'done' | 'error'
  overallProgress: number    // 0-100
  startedAt: string
  completedAt?: string
}
```

---

## 各步骤变量更新

### 步骤1: 项目概要 (report_project_summary)

新增变量:

| 变量 | 新数据来源 | 说明 |
|------|-----------|------|
| `readmeContent` | `report.getReadmeContent()` | README.md 前 500 字 |
| `dependencySummary` | `report.extractDependencyFiles()` | 各语言依赖的格式化摘要 |
| `fileSummaries` | `file_summaries` 表, source='llm' | 前 20 个核心文件的 ≤100 字摘要 |

Update User Prompt 增加:
```
## README 摘要
{readmeContent}

## 依赖信息
{dependencySummary}

## 核心文件摘要
{fileSummaries}
```

### 步骤2: 架构分解 (report_arch_decomposition)

不再使用 `getCascadeLevels` 原始 JSON，改为使用社区层级分析结果：

| 变量 | 新数据来源 |
|------|-----------|
| `communitySummary` | `file_summaries` where source='community_l0' |

### 步骤3: 核心模块说明 (report_core_modules)

| 变量 | 新数据来源 |
|------|-----------|
| `topCommunities` | `file_summaries` where source='community_l1' + L2 |
| `count` | 社区数量 |

### 步骤4: 依赖与调用分析 (report_dependency_analysis)

| 变量 | 新数据来源 |
|------|-----------|
| `crossCommunityEdges` | `analysis.getCommunityGraph(taskId, 'CALL', 'L0', [], depth=2)` — 真实跨社区边 |

---

## 实现进度

| 模块 | 文件 | 状态 |
|------|------|------|
| Schema | `sqlite_ctx.py` — `file_summaries` 表 + `model_configs.context_window` | ✅ 已实现 |
| 模板 | `prompt_manager.py` — `file_summarize` (structured, 用户按需触发) | ✅ 已实现 |
| 模板 | `prompt_manager.py` — `community_analyze` (structured, name≤20字+summary) | ✅ 已实现 |
| 模板 | `prompt_manager.py` — 5 个报告流水线模板新增变量 (readmeContent/dependencySummary) | ✅ 已实现 |
| 模板 | `prompt_manager.py` — `community_summarize` (tools) 替换为 `community_analyze` (structured) | ✅ 已替换 |
| 工具 | `tools_executor.py` — 全部 7 个工具完善 | ✅ 已实现 |
| IPC | `core_service.py` — `report.*` 方法 | ✅ 已实现 |
| IPC | `main.py` — 注册 report 方法 | ✅ 已实现 |
| 类型 | `src/types/ipc.ts` — 新增 report.* IPC + PipelineTaskNode + PipelineState | ✅ 已实现 |
| 组件 | `PipelineTaskTree.vue` — 递归渲染动态任务树 | ✅ 已实现 |
| 组件 | `FileSummaryPreprocessor.vue` — 仅 README + 依赖文件提取（无 LLM 源码摘要） | ✅ 已重写 |
| 组件 | `CommunityAnalysisPipeline.vue` — 任务列表（勾选/暂停/继续/重试/批量） | ✅ 已重写 |
| 组件 | `ReportGenerationPipeline.vue` — 动态树 + 嵌入预处理和社区分析组件 | ✅ 已更新 |
| 组件 | `ReportHome.vue` — LLM API 校验 + 模型提示 | ✅ 已实现 |
| 日志 | `llm_service.py` — `_save_stream_messages` 完整填充16列 (messages_json/response_content/tool_calls/tokens/latency/error) | ✅ 已实现 |
| 日志 | `llm_service.py` — `_execute_streaming` 跟踪 latency + token (Ollama eval_count/OpenAI usage) | ✅ 已实现 |
| 日志 | `llm_service.py` — 新增 `_save_interaction_log` 写入 `report_interaction_log` 表 | ✅ 已实现 |
| 日志 | `llm_service.py` — error/abort 状态写入 call_logs | ✅ 已实现 |
| 日志 | `backend/core_service.py` — 新增 `report.getCallLogs` / `report.getInteractionLogs` IPC | ✅ 已实现 |
| 日志 | `backend/sqlite_ctx.py` — 新增 `report_interaction_log` 表 DDL | ✅ 已实现 |
| 日志 | `electron/preload.ts` — 注册 getCallLogs / getInteractionLogs 桥接 | ✅ 已实现 |
| 日志 | `src/types/ipc.ts` — 新增 getCallLogs / getInteractionLogs 类型 | ✅ 已实现 |
| 日志 | `ReportGenerationPipeline.vue` — 传入 `pipeline_step` 到 extra_meta | ✅ 已实现 |
| 日志 | `CommunityAnalysisPipeline.vue` — 传入 `community_id/community_level/batch_id` 到 extra_meta | ✅ 已实现 |

## 已知问题

1. 社区分析以任务列表呈现，L2+L1+L0 的社区总数可能达数百/上千个。用户通过勾选+批量提交控制执行范围，批大小可配置（1-10）
2. 源码文件摘要不由 LLM 自动生成（代价过大）— 仅在用户主动需要时（右侧 AI 面板）对单个文件触发
3. 依赖文件解析器已覆盖 package.json / Cargo.toml / go.mod / pom.xml / requirements.txt / pyproject.toml / build.gradle 等主流格式，但部分格式需要第三方库（如 tomllib/tomli for TOML）
4. 上下文限制的 token 预估是启发式的，不同模型的 tokenizer 不同（cl100k / o200k / llama 等），后续可接入 `tiktoken` 精确计数
5. Steps 2-4 仍然使用 `getCascadeLevels` 的元数据而非 `graph_doc` 的真实边数据传递给 LLM — 需要后续对接 `analysis.getCommunityGraph` 改善 prompt 质量

---

## 附录: LLM 交互日志体系

### 设计目标

完整记录系统和 LLM 之间的每一次交互，支持：
- **审计**：追踪每次 LLM 调用使用的模板、prompt、耗时、token 用量
- **调试**：当生成结果异常时，可直接从 DB 查看完整的 request/response 内容
- **成本追踪**：按模板/步骤/社区统计 token 消耗
- **重放**：根据 `messages_json` 能重现同样的 LLM 请求

### 数据流

```
[前端 Pipeline/社区分析组件]
  │ 调用 llm.chat({ templateId, variables, pipeline_step, community_id })
  ▼
[chat IPC 处理器]
  │ 提取 extra_meta = { template_id, pipeline_step, community_id, ... }
  ▼
[streaming_chat] → 记录 _start_time
  ▼
[_execute_streaming]
  │ 调用 _sync_stream_ollama / _sync_stream_openai
  │ 捕获 token 使用量 (eval_count / usage)
  │ 收集 tool_calls
  │ 计算 latency_ms
  ▼
[_save_stream_messages]
  │ 写入 llm_call_logs (完整 16 列)
  │   ├── messages_json      ← 完整消息历史
  │   ├── response_content   ← LLM 返回内容（截断 100K）
  │   ├── tool_calls_json    ← 工具调用记录
  │   ├── token_*/latency_ms ← 性能数据
  │   ├── template_id        ← 关联模板
  │   └── error_message      ← 错误详情
  ▼
[_save_interaction_log]
  │ 写入 report_interaction_log (含 meta_json)
  │   ├── session_id / request_id
  │   ├── mode / status / latency_ms
  │   └── meta_json → { template_id, pipeline_step, community_id, ... }
  ▼
[查询 IPC: report.getCallLogs / report.getInteractionLogs]
  │ filter: sessionId, requestId, templateId, status
  ▼
[日志查看]
```

### 数据库表

#### llm_call_logs（已存在，完善填充）

| 列名 | 类型 | 以前 | 现在 |
|------|------|------|------|
| `template_id` | TEXT | ❌ 始终 NULL | ✅ 由 chat IPC 传入 |
| `messages_json` | TEXT | ❌ 始终 NULL | ✅ 序列化完整消息 |
| `response_content` | TEXT | ❌ 始终 NULL | ✅ LLM 返回（截断） |
| `tool_calls_json` | TEXT | ❌ 始终 NULL | ✅ 工具调用详细 |
| `token_prompt` | INT | ❌ 始终 NULL | ✅ Ollama: prompt_eval_count / OpenAI: usage.prompt_tokens |
| `token_completion` | INT | ❌ 始终 NULL | ✅ Ollama: eval_count / OpenAI: usage.completion_tokens |
| `token_total` | INT | ❌ 始终 NULL | ✅ 前两者之和 |
| `latency_ms` | INT | ❌ 始终 NULL | ✅ time.monotonic() 差值 |
| `error_message` | TEXT | ❌ 始终 NULL | ✅ 异常时记录 |
| `status` | TEXT | ✅ 'success' 硬编码 | ✅ 支持 'success'/'error'/'aborted' |

#### report_interaction_log（新增）

| 列 | 类型 | 说明 |
|----|------|------|
| `id` | TEXT PK | |
| `session_id` | TEXT | |
| `request_id` | TEXT | |
| `provider` | TEXT | ollama / openai |
| `model_name` | TEXT | |
| `mode` | TEXT | chat / tools / structured |
| `status` | TEXT | success / error / aborted |
| `latency_ms` | INTEGER | |
| `meta_json` | TEXT | JSON 对象: `{"template_id": "...", "pipeline_step": "step1", "community_id": "..."}` |
| `created_at` | TEXT | |

### 前端传入的日志字段

各组件在调用 `llm.chat` 时通过 `variables` 传入以下字段（后端自动提取到 extra_meta）：

| 组件 | 字段 | 值示例 | 说明 |
|------|------|--------|------|
| ReportGenerationPipeline | `pipeline_step` | `step1`, `step2`, ... | 流水线步骤标识 |
| CommunityAnalysisPipeline | `source` | `community_analysis` | 固定标记 |
| CommunityAnalysisPipeline | `community_id` | `comm_l2_001` | 当前分析的社区 |
| CommunityAnalysisPipeline | `community_level` | `L2` | 社区层级 |
| CommunityAnalysisPipeline | `batch_id` | `batch-1715000000` | 批次标识 |

### 查询 IPC

```typescript
// 查询 LLM 调用日志
const result = await window.api.report.getCallLogs({
  sessionId: 'pipeline-xxx-step1-...',
  templateId: 'report_project_summary',
  limit: 50,
  offset: 0,
})
// result.logs = [{ id, request_id, template_id, messages_json, response_content,
//                  token_prompt, token_completion, token_total, latency_ms, status, error_message, ... }]

// 查询报告交互日志（含 meta_json 上下文）
const result = await window.api.report.getInteractionLogs({
  templateId: 'community_analyze',
  limit: 100,
})
// result.logs = [{ id, request_id, provider, model_name, mode, status, latency_ms, meta_json, ... }]
// meta_json 可通过 JSON.parse 展开: { template_id, pipeline_step, community_id, ... }
```

