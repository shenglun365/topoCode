# Web AI 对话 — 消息引用格式、Tools 与 Skills

## 1. 消息引用格式

每条消息的 `metadata.refs` 承载该消息关联的上下文引用。

### 1.1 引用类型定义

```typescript
type RefType =
  | 'project'         // 项目
  | 'task'            // 分析任务
  | 'community_doc'   // 社区分析文档 (LLM 结果)
  | 'community_graph' // 社区图结构
  | 'source_file'     // 源码文件
  | 'symbol'          // 符号 (函数/类/方法)
  | 'ast_node'        // AST 语法节点
  | 'subgraph'        // 自定义子图 (多个节点+边)
  | 'archive'         // 归档知识条目
```

### 1.2 引用结构

```json
{
  "refs": [
    {
      "type": "project",
      "id": "proj_abc123",
      "label": "MyApp"
    },
    {
      "type": "task",
      "id": "task_def456",
      "projectId": "proj_abc123",
      "label": "Analysis v2"
    },
    {
      "type": "community_doc",
      "taskId": "task_def456",
      "commId": "comm_xyz",
      "edgeType": "CALL",
      "label": "AuthModule (L0/CALL)"
    },
    {
      "type": "community_graph",
      "taskId": "task_def456",
      "commId": "comm_xyz",
      "edgeType": "CALL",
      "level": "L0",
      "depth": 2,
      "label": "AuthModule Graph"
    },
    {
      "type": "source_file",
      "projectId": "proj_abc123",
      "path": "src/auth/login.ts",
      "label": "src/auth/login.ts"
    },
    {
      "type": "symbol",
      "projectId": "proj_abc123",
      "name": "authenticateUser",
      "file": "src/auth/service.ts",
      "label": "authenticateUser"
    },
    {
      "type": "ast_node",
      "projectId": "proj_abc123",
      "file": "src/auth/service.ts",
      "nodeId": "base_node_uuid",
      "label": "FunctionDeclaration: authenticateUser"
    },
    {
      "type": "subgraph",
      "taskId": "task_def456",
      "nodes": ["node_1", "node_2"],
      "edges": ["edge_1"],
      "label": "Selected Scope"
    },
    {
      "type": "archive",
      "id": "arch_789",
      "label": "Previous: Auth Performance"
    }
  ]
}
```

### 1.3 存储位置

`llm_messages.metadata` JSON 字段，与现有 `token_count`, `model_id` 等并列。

```json
{
  "model_id": "deepseek-v4-flash",
  "token_count": 1234,
  "latency_ms": 5678,
  "refs": [ ... ]
}
```

### 1.4 自动注入逻辑

创建 session 或发送消息时，服务端根据 refs 自动执行 `_resolve_refs_to_context()`：

```
对于每个 ref:
  type=community_doc → 查 community_llm_results 表 → 注入文档摘要
  type=community_graph → 查 graph_doc → 注入社区节点/边概要
  type=source_file → 读文件头2000字符 → 注入内容片段
  type=symbol → 查 graph_node/base_node → 注入符号信息
  type=archive → 查 chat_archives → 注入归档内容
  type=subgraph → 解析 nodes/edges → 注入结构概要
  type=project → 注入项目基本信息
  type=task → 注入任务状态+社区数

结果组装为 system message 注入消息列表开头:
{
  role: "system",
  content: "用户引用了一个社区分析结果「AuthModule（L0/CALL）」：
           该社区包含 12 个文件，功能摘要：用户认证模块...
           用户引用了一个源码文件「src/auth/login.ts」：
           [文件内容摘要...]"
}
```

---

## 2. Tools（可被 LLM function calling 调用的工具）

### 2.1 Web 层工具清单

| Tool | 底层调用 | 用途 | 参数 |
|---|---|---|---|
| `web_list_projects` | main_db 直查 | 列出所有项目 | `{}` |
| `web_get_project` | main_db 直查 | 获取单个项目详情 | `{projectId}` |
| `web_get_task_list` | main_db 直查 | 列出项目下任务 | `{projectId}` |
| `web_get_architecture_overview` | project_db 查 report_subdocs | 获取架构概览文档 | `{taskId}` |
| `web_get_community_tree` | community_data.get_cascade_levels | 浏览社区层级树 | `{taskId, edgeType}` |
| `web_get_community_detail` | project_db 查 community_llm_results | 获取社区分析详情 | `{taskId, commId, edgeType}` |
| `web_get_community_graph` | community_data.get_community_graph | 获取社区子图 (节点+边) | `{taskId, commId, edgeType, depth, gran}` |
| `web_get_community_files` | project_db 查 graph_doc node_list | 获取社区包含的文件 | `{taskId, commId, edgeType}` |
| `web_read_file` | 磁盘读取 | 读取源码文件 | `{projectId, path}` |
| `web_get_file_summary` | project_db 查 file_summaries | 获取文件预摘要 | `{taskId, path}` |
| `web_search_symbols` | community_data / graph_node 搜索 | 搜索符号 | `{projectId, query, limit}` |
| `web_get_symbol_detail` | project_db 查 graph_node/base_node | 符号详情 | `{projectId, symbolId}` |
| `web_get_call_chain` | project_db 查 graph_edge | 调用链 | `{projectId, symbol, depth}` |
| `web_search_archives` | main_db 查 chat_archives | 搜索知识归档 | `{query, projectId?, category?}` |
| `web_save_archive` | main_db INSERT chat_archives | 保存知识归档 | `{sessionId, title, content, category?, tags?}` |

### 2.2 现有复用策略

所有 Web 工具复用现有的数据查询代码，不重复实现：
- `multi_db.main_db` / `multi_db.get_project_db(pid)` / `multi_db.sessions_db` 直接查
- `community_data` 模块的 `get_cascade_levels`, `get_community_graph` 等已有函数
- 文件读取复用 `web_server.py` 已有的 `_find_file_alternatives`、权限校验
- 归档操作复用 chat_archives 表

---

## 3. Skills（可组合能力单元）

### 3.1 Skill 定义

```python
@dataclass
class Skill:
    name: str                            # 唯一标识
    title: str                           # 显示标题
    description: str                     # 描述（前端展示）
    icon: str                            # 前端图标
    tools: list[str]                     # 包含的工具名列表
    context_prompt: str                  # 激活时的 system prompt 片段
    default: bool = False                # 是否默认启用
```

### 3.2 预置 Skills

```python
SKILLS = {
    "project_browser": Skill(
        name="project_browser",
        title="项目浏览",
        description="浏览已分析的项目和任务",
        icon="📁",
        tools=["web_list_projects", "web_get_project", "web_get_task_list"],
        context_prompt="用户可以浏览已分析的项目和任务。",
        default=True,
    ),
    "architecture_explorer": Skill(
        name="architecture_explorer",
        title="架构探索",
        description="浏览社区层级、查看社区分析详情和结构图",
        icon="🏗",
        tools=[
            "web_get_architecture_overview",
            "web_get_community_tree",
            "web_get_community_detail",
            "web_get_community_graph",
        ],
        context_prompt=(
            "项目架构按社区层级组织（L0-L5），"
            "用户可以查询各层级的社区详情、子图结构和组件关系。"
        ),
        default=True,
    ),
    "source_reader": Skill(
        name="source_reader",
        title="源码阅读",
        description="读取源码文件和文件摘要",
        icon="📄",
        tools=["web_read_file", "web_get_file_summary", "web_get_community_files"],
        context_prompt="用户可以读取项目源码文件和文件摘要。",
        default=False,
    ),
    "symbol_analyzer": Skill(
        name="symbol_analyzer",
        title="符号分析",
        description="搜索符号、查看定义和调用关系",
        icon="🔍",
        tools=["web_search_symbols", "web_get_symbol_detail", "web_get_call_chain"],
        context_prompt=(
            "用户可以搜索项目中的符号（函数/类/方法），"
            "查看符号的详细定义和调用链。"
        ),
        default=False,
    ),
    "knowledge_keeper": Skill(
        name="knowledge_keeper",
        title="知识归档",
        description="保存和检索对话中产生的分析结论",
        icon="💾",
        tools=["web_search_archives", "web_save_archive"],
        context_prompt="用户可以检索历史对话的归档知识，也可以将当前结论存入归档。",
        default=False,
    ),
}
```

### 3.3 Skills 注册与组合

```
会话创建时:
  POST /api/chat/sessions body.skills = ["project_browser", "architecture_explorer"]

服务端:
  1. 收集 active_skills 的 tools → 注册到 function calling 列表
  2. 收集 active_skills 的 context_prompt → 拼接为 system message
  3. 存入 session.metadata.active_skills

前端展示:
  [📁 项目浏览] [🏗 架构探索] [📄 源码阅读] [🔍 符号分析] [💾 知识归档]
     ● 已启用         ● 已启用       ○ 已禁用       ○ 已禁用       ○ 已禁用

用户可随时切换:
  PUT /api/chat/sessions/{id}
  body: { "skills": ["project_browser", "source_reader"] }
  → 重新注册 tool 列表（下一条消息生效）
```

### 3.4 Skills 与引用的协同

```
引用注入 = 静态上下文（用户带来的外部信息）
Skills    = 动态能力（LLM 可以主动查询的工具）

例如:
  用户从 viewer 引用了一个社区文档 → refs 注入 system message
  用户启用了 architecture_explorer skill → LLM 可主动查子社区、子图

两者互不冲突，引用提供初始上下文，Skills 提供探索能力。
```

---

## 4. 集成到 web_server.py

### 4.1 新增路由

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/skills` | 返回预置 Skills 列表（前端展示/选择用） |
| `POST` | `/api/chat/sessions` | 同上，加 `skills` 和 `refs` 字段 |
| `PUT` | `/api/chat/sessions/{id}` | 同上，加 `skills` 更新 |
| `POST` | `/api/chat/sessions/{id}/messages` | 同上，消息中可带 `refs` |

### 4.2 SSE 流式中 tool calling 增强

在 SSE 端点中，注册 active_skills 对应的 tool 到 model 的 function calling：

```
POST /api/chat/sessions/{id}/messages
  1. 读取 session.metadata.active_skills
  2. 查 SkillRegistry 获取 tools
  3. 调用 LLM 时传入 tools 列表
  4. SSE 输出: chunk / tool_call / tool_result / done / error
```

### 4.3 Ref 解析函数

```python
def _resolve_refs_to_context(refs: list[dict], multi_db) -> str:
    """将 refs 列表解析为注入用的 system message 内容"""
    parts = []
    for ref in refs:
        t = ref.get("type")
        if t == "community_doc":
            text = _resolve_community_doc(ref, multi_db)
        elif t == "source_file":
            text = _resolve_source_file(ref, multi_db)
        elif t == "symbol":
            text = _resolve_symbol(ref, multi_db)
        # ... 其他类型
        if text:
            parts.append(text)
    return "\n\n".join(parts) if parts else ""
```

---

## 5. 数据流总图

```
viewer.html
[引用到AI] 按钮
  │  POST /api/chat/sessions {refs, skills, projectId}
  ▼
web_server.py
  ├─ 创建 session (llm_sessions)
  ├─ _resolve_refs_to_context(refs) → system message
  ├─ SkillRegistry.collect_context(active_skills) → system message
  ├─ 存 skills/refs 到 metadata
  └─ 返回 sessionId
      │
      ▼ 浏览器打开 /chat?sessionId=xxx
      │
chat.html 用户提问
  │  POST /api/chat/sessions/{id}/messages
  ▼
web_server.py SSE 端点
  ├─ 查 session → active_skills → tool_definitions
  ├─ 查 messages → 历史
  ├─ 调 LLM (带 tools)
  ├─ tool_call → ToolExecutor.execute → tool_result
  ├─ SSE chunk 流式推送
  └─ 流结束 → 保存 assistant message
```

## 6. 实施步骤

| 步骤 | 内容 | 工时 |
|---|---|---|
| 1 | `web_tools.py` — 15 个工具定义 + 执行器 | 1d |
| 2 | `skills.py` — Skill 数据类 + SkillRegistry + 预置 5 个 Skills | 0.3d |
| 3 | `web_server.py` — `_resolve_refs_to_context()` + 引用注入 | 0.5d |
| 4 | `web_server.py` — SSE 端点集成 Skill+tools | 0.5d |
| 5 | `web_server.py` — GET /api/skills + session 增改 skills/refs | 0.3d |
| **合计** | | **~2.6d** |
