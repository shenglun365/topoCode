# B1-W4 实施文档：AGENTS.md 规则链闭环 + K2 回执测试段

> 组：W4(2d) · 依赖：无硬依赖（可与 W2 并行）· 决策依据：**D-2 方案 A 已裁决**（生成基线段+项目规则追加+手改问询）
> 定位：契约文件从"生成"到"分层加载合并"闭环（Roo 优先级洋葱模式的 architect 化）；执行回执补测试主张字段

---

## 1. 模块操作总表

| 模块 | 操作 | 摘要 |
|---|---|---|
| `arch_routes/agents_md.py` | **变更** | `build_project_agents_md` 合并 `.topo/rules/`；定界符包裹生成段；`sync_agents_md` 手改检测→问询卡 |
| `agent/execution/exec_bridge.py` | **变更** | execution_report schema 加 `tests` 段（K2 扩展）；落库点写入 |
| `src/services/contract-service.ts` | **变更** | 类型同步（AGENTS.md 构建结果 + 回执类型） |
| `.topo/rules/` 目录约定 | **新增（用户侧约定）** | 项目规则文件目录（非代码；文档化） |
| 问询卡（choices 通道） | **复用 + 变更** | 新增一种稳定 key（基线段手改处置） |
| 移除 | 无 | 旧纯生成模式保留为退化路径（无 `.topo/rules/` 时行为不变） |

## 2. 逐模块明细

### 2.1 `arch_routes/agents_md.py`（规则链，D-2 方案 A）

**改动**：
1. **定界符**：生成段用注释定界包裹（如 `<!-- topo:generated-begin -->…<!-- topo:generated-end -->`，markdown 注释不影响执行器解析）
2. **合并**：`build_project_agents_md` 产出 = 生成基线段 + `.topo/rules/` 目录内容追加（分文件、按文件名排序；文件不区分大小写；过滤 `.log/.tmp` 等缓存后缀——学 Roo 规则目录纪律）；项目规则在后 = 更近用户
3. **手改保护**：`sync_agents_md` 时检测定界段**内部**与上次生成物的差异——有差异即判定手改，**不静默覆盖**：发问询卡（复用 cv-282 choices 模式，稳定 key `agents_md_manual_edit`；选项：保留手改并停止该文件自动同步 / 覆盖为生成版 / 取消）
4. 无 `.topo/rules/` 且无手改时：行为与现状完全一致（退化路径）

**上游**：`.topo/rules/*.md`（用户/项目侧）；既有生成数据源（契约条目/规约）。
**下游**：外部 agent（Cursor/Cline 等直读 AGENTS.md 的消费者）；执行器（载荷经 context_pack 引用 AGENTS.md，既有行为）；W5 事实层（不直接依赖，但规约文件影响生成内容）。

### 2.2 `agent/execution/exec_bridge.py`（K2 回执测试段）

**改动**：execution_report 单元（`type: execution_report`，exec_bridge.py:500 一带）schema 增加可选 `tests` 段：
```json
"tests": {
  "files": [{"path": "...", "target_symbols": ["..."]}],
  "run_result": "pass|fail|not_run|partial",
  "uncovered_reason": "..."   // 可选；coverage 字段不采（D-8 暂缓）
}
```
done/failed 回执落库时从执行器过程流提取（执行器自述为线索；test_runner 实际执行结果为事实，提取优先取事实）。**测试清单不新造文件**——清单即 `tests.files` 字段。

**上游**：执行器结题事件（cline/opencode/codex 过程流）；`arch_routes/test_runner.py` 执行结果。
**下游**：W5 事实层对账（`tests.files` ∩ 扫描集）；（远期）CI/CD 整合时回执字段升级。

### 2.3 `src/services/contract-service.ts`

**改动**：回执类型定义加 `tests` 可选段；AGENTS.md 构建结果类型不变（内容级变化）。i18n 如问询卡文案需新增 key。

## 3. 数据与契约变更

| 面 | 变更 | 兼容性 |
|---|---|---|
| AGENTS.md 文件形态 | 定界符 + 规则追加段 | 纯增量；执行器对注释与追加内容按普通 markdown 消费 |
| execution_report schema | 新增可选 `tests` 段 | 老回执无此段不炸；契约变更走 CONV-04（G4 门禁） |
| 问询卡稳定 key | 新增 `agents_md_manual_edit` | 复用 choices 通道，fingerprint 单源 |

**无表结构变更**。

## 4. 测试计划

- `tests/test_agents_md_rules.py`：① 无 rules 目录=现状（退化）② rules 多文件按序追加 ③ 定界段手改触发问询不覆盖 ④ 问询选"覆盖"后正确重建
- `tests/test_execution_report_tests.py`：tests 段写入/缺省缺失/老回执兼容
- 手测：`.topo/rules/` 项目规则出现在生成 AGENTS.md 尾部（DoD 4）

## 5. 回退

| 片 | 回退 |
|---|---|
| 规则链 | 删 `.topo/rules/` 即回纯生成；合并逻辑对空目录无行为 |
| tests 段 | 可选字段，消费方判空即可 |
| 问询卡 | 回退为"覆盖+备份旧文件到 .topo/backup/"（次选方案） |

## 6. 组内验收清单

- [ ] `.topo/rules/` 规则出现在生成 AGENTS.md 尾部（定界正确）
- [ ] 基线段手改触发问询卡，不静默覆盖（cv-282 同款体验）
- [ ] execution_report 含 tests 段（委派任务实测）；老回执兼容
- [ ] CONV-04 契约变更登记完成
