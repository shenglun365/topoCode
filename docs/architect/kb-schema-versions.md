# KB Schema Versions — 知识资产格式版本登记（K1）

> 唯一运行时权威：`arch_routes/store/migrations.py` 的 `SCHEMA_VERSIONS` +
> `_MIGRATIONS`（只追加）。本档为**发布记录**（dsh 双权威模式：常量手写权威 +
> 文档登记发布），逐条记录版本语义与迁移证据。

## 纪律（变更三件套）

对四张持久表的**结构变更**（含 meta/refs 等自由 JSON 的键结构）：

1. `store/migrations.py::SCHEMA_VERSIONS` bump `N → N+1`；
2. `register_migration(table, N, *fns)` 注册迁移（只追加；重复/缺口 = RuntimeError）；
3. 快照测试（`test_kb_schema_versions.py` 增例）+ 本档追加一行发布记录。

迁移为**读时惰性**（旧行读时内存补齐，不批量刷库，下次写时落新版本）；
迁移函数操作 **API 形状行**（camelCase、JSON 已解码）。未登记表恒等。

## 覆盖表（持久知识域，2026-09-17 K1 立项）

| 表 | 当前版本 | 域 |
|---|---|---|
| `arch_semantic_assets` | 1 | L1 语义资产（代码锚点） |
| `arch_glossary` | 1 | L2 词典约束 |
| `arch_context_units` | 1 | L3 会话派生单元（含 error/execution_report/error_pattern） |
| `arch_docs` | 1 | L3 备案文档 |

**不在登记范围**（登记即承诺迁移纪律，收缩为负面空间）：
- 运行时/审计表（conversations/messages/tasks/tool_audit/mcp_calls/interactions 等）——会话流水，非知识资产；
- `arch_requirements`/验收/契约表——主业务链，格式变更走既有 `spec_versions`/`_add_cols` 先例，未来是否纳入另议；
- 模型侧档案/数据集——已搁置（2026-09-17 裁决）。

## 发布记录

| 日期 | 表 | 版本 | 变更 | 证据 |
|---|---|---|---|---|
| 2026-09-17 | 四表 | 1 | **立项基线**：加 `schema_version INTEGER DEFAULT 1` 列 + 迁移链机制（`store/migrations.py`）。同批：`arch_assets` 表退役（L4 降级裁决——回执/里程碑并入 `arch_context_units`，五类资产词汇废止；REST `/assets` → `/units`） | `test_kb_schema_versions.py`（7 例） |
