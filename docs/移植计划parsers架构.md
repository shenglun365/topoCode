# 完整移植 parsers/ 架构计划

> 目标: 将 `transplant-parser-service/parsers/` 的完整实现移植到 `backend/parsers/`
> 数据存储: MongoDB → SQLite (已有 store 层)
> 任务调度: Celery → analyst_runner (已有)

---

## 一、架构映射

### 原始架构 (MongoDB)

```
parser.py (Celery task)
  ├─ AST 解析 → base_node (MongoDB)
extract_global_symbols.py
  ├─ 符号提取 → graph_node (MongoDB)
extract_call_graph.py
  ├─ 调用图 → graph_node (MongoDB)
extract_dependency_graph.py
  ├─ 依赖图 → graph_node (MongoDB)
```

### 目标架构 (SQLite)

```
analyst_runner._execute_task()
  ├─ Phase 1: parser.py → base_node (SQLite 项目库)
  ├─ Phase 2: extract_global_symbols.py → graph_node (SQLite 项目库)
  ├─ Phase 3: extract_call_graph.py → graph_node (SQLite 项目库)
  ├─ Phase 4: extract_dependency_graph.py → graph_node (SQLite 项目库)
  ├─ Phase 5: community_analysis.py → graph_doc (SQLite 项目库)
  └─ Phase 6: 汇总统计 → analysis_reports (SQLite 主库)
```

---

## 二、需要移植的文件

### 2.1 顶层模块 (6 个)

| 原始文件 | 目标路径 | 适配内容 |
|----------|---------|---------|
| `parsers/parser.py` | `backend/parsers/parser.py` | MongoDB → SQLite store |
| `parsers/extract_global_symbols.py` | `backend/parsers/extract_global_symbols.py` | MongoDB → SQLite store |
| `parsers/extract_call_graph.py` | `backend/parsers/extract_call_graph.py` | MongoDB → SQLite store |
| `parsers/extract_dependency_graph.py` | `backend/parsers/extract_dependency_graph.py` | MongoDB → SQLite store |
| `parsers/build_ctrl_graph.py` | ~~跳过~~ | 控制流图暂不需要 |
| `parsers/__init__.py` | `backend/parsers/__init__.py` | 导出新模块 |

### 2.2 语言配置层 (code_parser/, 15 个)

| 原始文件 | 目标路径 | 适配内容 |
|----------|---------|---------|
| `languages/code_parser/lang_base.py` | `backend/parsers/code_parser/lang_base.py` | 直接复制 |
| `languages/code_parser/lang_parser_conf.py` | `backend/parsers/code_parser/lang_parser_conf.py` | 已适配独立语言包 ✓ |
| `languages/code_parser/parser_factory.py` | `backend/parsers/code_parser/parser_factory.py` | 直接复制 |
| `languages/code_parser/registry.py` | `backend/parsers/code_parser/registry.py` | 直接复制 |
| `languages/code_parser/validator.py` | `backend/parsers/code_parser/validator.py` | 直接复制 |
| `languages/code_parser/lang_c.py` | `backend/parsers/code_parser/lang_c.py` | 直接复制 |
| `languages/code_parser/lang_cpp.py` | `backend/parsers/code_parser/lang_cpp.py` | 直接复制 |
| `languages/code_parser/lang_java.py` | `backend/parsers/code_parser/lang_java.py` | 直接复制 |
| `languages/code_parser/lang_python.py` | `backend/parsers/code_parser/lang_python.py` | 直接复制 |
| `languages/code_parser/lang_js.py` | `backend/parsers/code_parser/lang_js.py` | 直接复制 |
| `languages/code_parser/lang_ts.py` | `backend/parsers/code_parser/lang_ts.py` | 直接复制 |
| `languages/code_parser/lang_go.py` | `backend/parsers/code_parser/lang_go.py` | 直接复制 |
| `languages/code_parser/lang_rust.py` | ~~跳过~~ | Rust 暂不支持 |
| `languages/code_parser/lang_php.py` | ~~跳过~~ | PHP 暂不支持 |
| `languages/code_parser/lang_swift.py` | ~~跳过~~ | Swift 暂不支持 |
| `languages/code_parser/lang_csharp.py` | ~~跳过~~ | C# 暂不支持 |

### 2.3 调用图提取层 (call_parser/, 7 个)

| 原始文件 | 目标路径 | 适配内容 |
|----------|---------|---------|
| `languages/call_parser/extractor_factory.py` | `backend/parsers/call_parser/extractor_factory.py` | 直接复制 |
| `languages/call_parser/c_parser.py` | `backend/parsers/call_parser/c_parser.py` | MongoDB → SQLite |
| `languages/call_parser/python_call_parser.py` | `backend/parsers/call_parser/python_call_parser.py` | MongoDB → SQLite |
| `languages/call_parser/java_call_parser.py` | `backend/parsers/call_parser/java_call_parser.py` | MongoDB → SQLite |
| `languages/call_parser/javascript_call_parser.py` | `backend/parsers/call_parser/javascript_call_parser.py` | MongoDB → SQLite |
| `languages/call_parser/go_call_parser.py` | `backend/parsers/call_parser/go_call_parser.py` | MongoDB → SQLite |
| `languages/call_parser/rust_call_parser.py` | ~~跳过~~ | Rust 暂不支持 |
| `languages/call_parser/java_oop_resolver.py` | `backend/parsers/call_parser/java_oop_resolver.py` | MongoDB → SQLite |

### 2.4 依赖图提取层 (dependence_parser/, 7 个)

| 原始文件 | 目标路径 | 适配内容 |
|----------|---------|---------|
| `languages/dependence_parser/extractor_factory.py` | `backend/parsers/dependence_parser/extractor_factory.py` | 直接复制 |
| `languages/dependence_parser/c_dependence_parser.py` | `backend/parsers/dependence_parser/c_dependence_parser.py` | 直接复制 |
| `languages/dependence_parser/python_dependence_parser.py` | `backend/parsers/dependence_parser/python_dependence_parser.py` | 直接复制 |
| `languages/dependence_parser/java_dependence_parser.py` | `backend/parsers/dependence_parser/java_dependence_parser.py` | 直接复制 |
| `languages/dependence_parser/javascript_dependence_parser.py` | `backend/parsers/dependence_parser/javascript_dependence_parser.py` | 直接复制 |
| `languages/dependence_parser/go_dependence_parser.py` | `backend/parsers/dependence_parser/go_dependence_parser.py` | 直接复制 |
| `languages/dependence_parser/rust_dependence_parser.py` | ~~跳过~~ | Rust 暂不支持 |

### 2.5 符号提取层 (symbol_parser/, 2 个)

| 原始文件 | 目标路径 | 适配内容 |
|----------|---------|---------|
| `languages/symbol_parser/base_handler.py` | `backend/parsers/symbol_parser/base_handler.py` | 直接复制 |
| `languages/symbol_parser/c_family_handler.py` | `backend/parsers/symbol_parser/c_family_handler.py` | 直接复制 |
| `languages/symbol_parser/extractor_factory.py` | `backend/parsers/symbol_parser/extractor_factory.py` | 直接复制 |

### 2.6 语言处理器 (8 个)

| 原始文件 | 目标路径 | 适配内容 |
|----------|---------|---------|
| `languages/c/processor.py` | `backend/parsers/languages/c/processor.py` | 替换 imports |
| `languages/cpp/processor.py` | `backend/parsers/languages/cpp/processor.py` | 替换 imports |
| `languages/java/processor.py` | `backend/parsers/languages/java/processor.py` | 替换 imports |
| `languages/python/processor.py` | `backend/parsers/languages/python/processor.py` | 替换 imports |
| `languages/go/processor.py` | `backend/parsers/languages/go/processor.py` | 替换 imports |
| `languages/javascript/processor.py` | `backend/parsers/languages/javascript/processor.py` | 替换 imports |
| `languages/typescript/processor.py` | `backend/parsers/languages/typescript/processor.py` | 替换 imports |
| `languages/base.py` | `backend/parsers/languages/base.py` | 替换 imports |
| `languages/language_registry.py` | `backend/parsers/languages/language_registry.py` | 替换 imports |

### 2.7 C 族共享工具

| 原始文件 | 目标路径 | 适配内容 |
|----------|---------|---------|
| `languages/c_family/ast_parser.py` | `backend/parsers/c_family/ast_parser.py` | 替换 imports |
| `languages/c_family/utils.py` | `backend/parsers/c_family/utils.py` | 直接复制 |

---

## 三、MongoDB → SQLite 适配

### 3.1 数据访问层

原始代码使用 `from databases.db_pools import get_mongo_client`，需要改为使用已有的 SQLite store 层：

```python
# 原始 (MongoDB)
mongo_client = get_mongo_client()
db = mongo_client.topocode
base_node_coll = db.base_node
graph_node_coll = db.graph_node
proj_info_coll = db.proj_info

# 目标 (SQLite)
from store.task_store import TaskStore
from store.analysis_store import AnalysisStore

store = AnalysisStore(project_db)  # 项目库
store.bulk_insert_nodes(nodes)     # → base_node
store.insert_graph_node(record)    # → graph_node
```

### 3.2 字段映射

| MongoDB 字段 | SQLite 字段 | 说明 |
|-------------|-------------|------|
| `proj_id` | (项目库隐式) | SQLite 按项目分库，不需要 proj_id |
| `file_id` (INT) | `file_id` (TEXT) | 类型不同，需转换 |
| `file_path` | `file_path` | 一致 |
| `file_name` | `file_name` | 一致 |
| `file_lang` | `language` | 字段名不同 |
| `hashcode` | `hashcode` | 一致 |
| `parse_status` | (无) | 暂不需要 |

---

## 四、执行步骤

### Phase 0: 清理现有 parsers_new 代码

1. 删除 `backend/parsers/` 下 parsers_new 模式的文件：
   - `ast_parser.py`, `base.py`, `symbol_extractor.py`, `call_graph_extractor.py`, `dependency_extractor.py`
2. 删除 `backend/parsers/languages/*/parser.py` (parsers_new 版本)
3. 保留 `language_loader.py` (独立语言包加载器，已适配)

### Phase 1: 移植语言配置层

1. 复制 `code_parser/` 全部文件 (12 个)
2. 验证 tree-sitter 语言包加载

### Phase 2: 移植顶层 AST 解析器

1. 移植 `parser.py` (MongoDB → SQLite)
2. 移植 `extract_global_symbols.py` (MongoDB → SQLite)
3. 端到端测试: 解析 Python 文件 → base_node 写入

### Phase 3: 移植调用图/依赖图提取器

1. 移植 `call_parser/` (6 个语言提取器)
2. 移植 `dependence_parser/` (5 个语言提取器)
3. 移植 `extract_call_graph.py` (MongoDB → SQLite)
4. 移植 `extract_dependency_graph.py` (MongoDB → SQLite)

### Phase 4: 移植语言处理器

1. 移植 7 种语言的 `processor.py`
2. 移植 `language_registry.py`
3. 移植 `symbol_parser/`

### Phase 5: 集成到 analyst_runner

1. 修改 `analyst_runner.py` 调用新模块
2. 修改 `task_manager.py` 适配新接口
3. 端到端测试: 完整分析流程

### Phase 6: 清理验证

1. 删除 parsers_new 残留
2. 更新文档
3. 全量测试

---

## 五、预估工作量

| Phase | 文件数 | 适配复杂度 | 说明 |
|-------|--------|-----------|------|
| Phase 0 | 删除 10+ | 低 | 清理旧代码 |
| Phase 1 | 12 | 低 | 直接复制 |
| Phase 2 | 2 | 中 | MongoDB → SQLite |
| Phase 3 | 16 | 中 | MongoDB → SQLite |
| Phase 4 | 10 | 中 | 替换 imports |
| Phase 5 | 2 | 高 | 集成测试 |
| Phase 6 | - | 低 | 清理验证 |
| **总计** | **~42** | | |
