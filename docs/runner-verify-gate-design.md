# runner 程序化验收门禁设计（V1~V5 细化）

> 版本 v1.0 | 2026-09-11 | 状态：**设计定稿，待实现**（对应 roadmap P2-T5 修订）
> 背景：2026-09-11 执行模式评估结论——当前实施交付为**声明制**（`[[IMPLEMENT_DONE]]` 采信 agent 自述，runner 无任何程序化验证）；单测执行器（`test_runner.py`）与实施回路断线；回归/编译无保障；错误修复隐式依赖执行器内部循环。
> 关联文档：[product-iteration-roadmap-2026-09.md](product-iteration-roadmap-2026-09.md)（P2-T5）· [local-small-model-finetune.md](local-small-model-finetune.md) §2.3（反馈回路质量决定修复模型级别——本设计正是把反馈回路工程化）· [plan-B.md](archive/plan-B.md)（约束求解哲学，已归档）
> 实现载体：`packages/core/topoone/plugins/runner/implement.py`（ImplementJob 管线）+ `apps/architect/.../test_runner.py`（复用扩展）+ 会话/项目配置存储。**不依赖已退役的 SE 任务树状态机。**

---

## 1. 定位与设计原则

把实施作业的交付判定从「agent 声明」改为「runner 验证」：

```
现状:  agent 自述 DONE ──────────────────────▶ 终态（无验证）
目标:  agent 自述 DONE ─▶ runner 验证管线 ─▶ 验证矩阵 ─┬─ 全过 ──────▶ done
                                                      ├─ L1/L2 失败 ─▶ 修复回注轮（自动）
                                                      ├─ L3 失败 ────▶ 升级模型或上报
                                                      └─ 无法验证 ───▶ waiting_input + 确定性原因
```

四条设计原则：

1. **验证优先**：任何"完成"必须由退出码/结构化结果支撑，自述仅供摘要参考
2. **确定性反馈**：无法闭环 ≠ 静默通过。每个无法验证的环节必须产出 **原因码 + 人类可读文案 + 建议动作**（§8），杜绝"不知道为什么没验"
3. **零假设**：不假设项目语言/构建系统/测试框架，探测失败走分级降级（§3），而非报错或伪通过
4. **分层降级**：环境能力 A→D 四级，能力越低自动化越少、提示越显式，但**反馈永远确定**

---

## 2. 分层架构（五层）

| 层 | 职责 | 承载任务 |
|---|---|---|
| **L1 发现层** | 验收命令发现链：项目配置 > CI 文件 > 约定探测 > 语言默认（§4） | V1 |
| **L2 执行层** | worktree 内沙箱化执行、白名单、超时分级、输出截断（§6） | V1 |
| **L3 解析层** | 语言/框架适配器：原始输出 → 归一化结果（per-test 通过率/时长）（§5） | V2 |
| **L4 编排层** | 判定、修复回注、升级、重试上限（§9） | V4 |
| **L5 反馈层** | 闭环状态分类学、验证矩阵、DONE 诚实化、用户动作提示（§8） | V5 |
| 横切 | 回归基线（§7） | V3 |

验证管线时序（ImplementJob 内，回合结束触发）：

```
回合输出含 [[IMPLEMENT_DONE]]
  → V1 发现(L1): compile_cmd / test_cmd / baseline_cmd
  → V1 执行(L2): deps(可选) → build → test
  → V2 解析(L3): 适配器归一化
  → V3 基线对比: 新增失败 vs 存量失败
  → V4 编排(L4): 判定 → 修复回注 / 升级 / 终态
  → V5 反馈(L5): 验证矩阵落事件流 → 会话消息（含确定性文案）
```

---

## 3. 环境能力分级（A/B/C/D）

作业创建时探测一次，随首个事件上报；每级对应明确的自动化边界：

| 级别 | 判定条件 | 闭环策略 | 反馈形态 |
|---|---|---|---|
| **A 完整闭环** | 发现了测试命令 **且** 结果可结构化解析（§5 标 `structured`） | 编译+单测+回归全自动验收；失败自动修复回注 | 验证矩阵 + per-test 明细 |
| **B 半闭环** | 有测试/构建命令但仅退出码可判（无结构化输出） | pass/fail 级验收；失败回注附日志尾部（截断 800 字符×头尾） | 验证矩阵 + 日志摘要 |
| **C 待配置** | 探测不到构建或测试命令，但项目可执行 | **不猜命令**；`[[NEED_INPUT]]` 向用户索要验收命令或显式跳过 | 原因码 `NO_VERIFY_CONFIG` + 索要文案 |
| **D 仅审查** | 无工具链（语言运行时缺失）/ 纯文档/配置类变更（diff 仅含 md/txt/资源文件） | 跳过执行验收，强制人工 diff 审查（复用现有「查看差异」） | 原因码 + "本次交付仅可人工审查" |

> 级别是**每环节独立判定**的：同一作业可能 compile=A、unit=C（没找到测试）、regression=B。终态判定取最弱环节的用户选择（坚持验收 or 显式降级）。

---

## 4. 验收命令发现链（L1 层，V1）

按优先级取**第一个命中**，全过程记录"来源"字段（反馈文案要说明命令从哪来）：

| 优先级 | 来源 | 信号与提取规则 |
|---|---|---|
| **P0 项目显式配置** | `arch_projects.meta.verify`（或会话级 `verify` 配置、runner 环境变量覆盖）：`{build?, test?, baseline?, env?, timeoutMul?}` | 用户在设置/会话中声明；**最高权威**，命中即停 |
| **P1 CI 文件解析** | `.github/workflows/*.yml`（run 步骤中含 `test`/`build` 关键字的命令）、`gitlab-ci.yml`（test stage）、`Makefile`（`test:`/`check:` 目标） | 取 steps 中可静态提取的命令；CI 是项目作者声明的权威构建方式 |
| **P2 约定探测** | 清单文件 → 约定命令：`package.json` `scripts.test`/`scripts.build`；`pyproject.toml`（`[tool.pytest]` 存在→`pytest -q`）；`Cargo.toml`→`cargo test`；`go.mod`→`go test ./...`（复用 `analyst_runner.py:108` 的 go.mod 探测先例）；`pom.xml`→`mvn -q test`；`*.csproj`→`dotnet test` | 只认"清单声明了测试意图"的信号 |
| **P3 语言默认** | 按探测到的语言给保守默认（如 Python 有任意 .py 测试文件→`python -m pytest -q`，Go→`go build ./...`） | 标注 `source=heuristic`，反馈文案提示"自动推断，可在设置中固化" |
| **降级** | 全部未命中 → 级别 C（`NO_VERIFY_CONFIG`） | 索要文案附各语言示例命令 |

配套：P0 配置界面（architect 设置页"验收命令"卡，per-project 持久化）+ 会话内自然语言声明解析（"用 `pnpm test` 验收" → 写入会话配置）。

---

## 5. 语言 / 构建环境 / 测试框架适配矩阵（L3 层，V2）

适配器接口（统一归一化输出，`test_runner.py` 的 `lastResult` 形状扩展）：

```python
AdapterResult = {
  "verdict": "PASS|FAIL|UNVERIFIABLE",
  "stage": "build|test",
  "cmd": "...", "cmdSource": "config|ci|convention|heuristic",
  "exitCode": int, "durationMs": int,
  "perTest": [ {"name", "status", "durationMs", "message"} ],  # structured 档才有
  "summary": {"total", "passed", "failed", "skipped"},
  "logTail": str,          # 头尾各 800 字符
  "reason": str,           # UNVERIFIABLE 时必填（§8 原因码）
}
```

| 语言 | 构建信号→命令 | 测试信号→命令 | 结果结构化 | 默认级别 |
|---|---|---|---|---|
| **Python** | `pyproject.toml`/`setup.py`/`requirements.txt` → `pip install -e .`（或 `uv sync`/`poetry install`，按锁文件探测）；`python -m compileall`（快速语法档） | `pytest -q --junitxml=…`；`python -m unittest discover` | ✅ junit XML 解析 | A |
| **Node/TS** | `package.json` lockfile 探测包管理器（`package-lock`/`pnpm-lock`/`yarn.lock`）→ install；`tsc --noEmit`（有 tsconfig 时） | `npm test`（jest `--json --outputFile` / vitest `--reporter=json` / mocha spec→exit code） | ✅ jest/vitest JSON | A |
| **Go** | `go.mod` → `go build ./...` | `go test ./... -json` | ✅ 原生 JSON 流 | A |
| **Rust** | `Cargo.toml` → `cargo check` | `cargo test`（exit code + 输出解析；`--format json` 为 nightly，标 B） | ⚠️ 文本解析 | B |
| **Java** | `pom.xml`→`mvn -q -DskipTests compile`；`build.gradle`→`gradle build -x test` | `mvn test` / `gradle test` → surefire/junit XML | ✅ XML 解析 | A |
| **C#/.NET** | `*.csproj`/`*.sln` → `dotnet build` | `dotnet test --logger trx` | ✅ trx 解析 | A |
| **C/C++** | `CMakeLists.txt`→`cmake -B build && cmake --build`；`Makefile`→`make` | `ctest --output-junit`（有 CMake 项目时）；否则 exit code | ⚠️ 视项目 | B/C |
| **Shell/脚本** | `bash -n`（语法档） | 常无框架 | ❌ | D→B |
| **纯文档/配置** | —（diff 仅 md/txt/yaml/资源） | — | — | **D 仅审查** |

实现纪律：**每个适配器独立模块 + fixture 项目单测**（§10 V2）；结果解析失败不判 PASS（降 B 档按退出码）；未知语言不硬造命令（降 C 档）。

---

## 6. 执行层约束（L2 层，V1）

- **隔离**：一律在作业 worktree 内执行（cwd=wt）；禁止引用 wt 外路径（复用 `test_runner.py` 的路径穿越防护）
- **白名单**：只允许 runner 代执行「构建/测试/依赖安装」类命令（发现链产出 + 用户显式配置）；任何 `rm`/`curl | sh` 等出现在配置中 → 拒绝并提示
- **顺序与超时**（默认值，可经 `timeoutMul` 缩放）：

| 阶段 | 默认超时 | 失败处理 |
|---|---|---|
| deps install | 120s（首次可放宽 600s） | FAIL `DEP_INSTALL_FAILED` |
| build/compile | 300s | FAIL `BUILD_FAILED`（附首个 error 行定位） |
| test | 600s | 已完成用例照常解析 + `TIMEOUT` 标注 |

- **资源**：单作业内串行；输出单命令截断 20k 字符（头 2k + 尾 18k）；失败 bundle 只带头尾 800×2（§9）
- **环境**：继承 runner 进程 env + 项目配置 `env` 覆盖；`CI=1` 注入（部分框架输出更稳定）

---

## 7. 回归基线（V3）

1. **基线运行**：作业创建时（worktree 就绪后、首轮实施前）在 base commit 的临时 worktree 异步跑一次 `baseline_cmd`（默认=test_cmd），结果缓存（key: `root+baseCommit+cmd` 内容哈希）；基线未完成不阻塞实施，仅延后验收对比
2. **对比判定**：验收时 per-test 对照——
   - 新增失败（基线过、现在挂）→ `FAIL`
   - 仅存量失败（基线就挂）→ `PASS_WITH_KNOWN`（矩阵标注"存量 N 项，与本作业无关"，附清单）
   - flaky 判定：单测重跑一次，两轮结果不一致 → 标 `flaky`，不计入新增失败但列提示
3. **测试选择优化**（可选加速，非正确性依赖）：diff 变更文件 → 适配器映射受影响测试（jest `--findRelatedTests`、go test 无则全量）；映射失败一律全量兜底
4. **无基线**（首次分析/基线超时/纯新增项目）→ regression 环节 `UNVERIFIABLE NO_BASELINE`，不阻塞 unit 判定

---

## 8. 闭环状态分类学与确定性反馈（L5 层，V5）★核心

### 8.1 验证矩阵（每作业必产，落事件流 + 会话消息）

```
| 环节        | 判定              | 命令(来源)              | 明细                |
| 编译        | ✅ PASS           | go build ./... (ci)     | 12.3s               |
| 单元测试    | ❌ FAIL (2/47)    | go test ./... (ci)      | TestXxx / TestYyy   |
| 回归对比    | ⚠️ UNVERIFIABLE   | —                       | NO_BASELINE         |
```

判定枚举（环节级）：`PASS` / `FAIL` / `PASS_WITH_KNOWN`（仅存量失败）/ `UNVERIFIABLE`（想验验不了）/ `SKIPPED`（用户显式跳过）。**作业终态 = 三环节矩阵的用户可见裁决**，禁止只报笼统"成功"。

### 8.2 原因码表（UNVERIFIABLE 必带其一，附确定性文案与建议动作）

| 原因码 | 触发 | 反馈文案（模板） | 建议动作 |
|---|---|---|---|
| `NO_VERIFY_CONFIG` | 发现链 P0~P3 全未命中 | "未发现可用的构建/测试命令，无法自动验收。请告知验收命令（如 `pnpm test`），或发送「跳过验收」转人工审查。" | 提供命令 / 显式跳过 |
| `NO_TOOLCHAIN` | 语言运行时缺失（如无 go/node） | "检测到 Go 项目但运行环境无 go 工具链，无法执行编译验收。" | 安装工具链或在设置中指定 runner 环境 |
| `NO_TEST_TARGET` | 可构建但无任何测试 | "项目可编译但未发现测试目标；已通过编译验证，单测环节跳过。" | 补充测试（可触发单测草稿生成 tagent_utgen） |
| `DEP_INSTALL_FAILED` | 依赖安装失败 | "依赖安装失败：{首个 error 行}。常见原因：私有源未配置/网络受限。" | 配置源或 env |
| `BUILD_FAILED` | 编译失败 | "编译失败：{file:line 首错}。已附错误上下文交执行工程师修复。" | 自动修复轮（L1） |
| `TEST_FAILED` | 测试失败 | "N 项测试失败（新增 M/存量 K）：{失败清单}。" | L1/L2 自动修复轮 |
| `TIMEOUT` | 超时 | "{阶段}超时（>{n}s）。可在验收配置中调大 timeoutMul 后重试。" | 调参重跑 / 排查挂死 |
| `NO_BASELINE` | 无基线可比 | "无基线测试记录，回归对比不可用（不影响单测判定）。" | 等待基线运行 / 忽略 |
| `PARSE_FAILED` | 结果无法解析 | "测试已执行但输出无法解析（退出码 {n}），按通过/失败二值判定，无明细。" | 接受 B 档 / 提交适配器问题 |
| `RUNNER_ENV_BROKEN` | worktree/git 异常 | "验收环境异常：{e}。分支与工作区已保留。" | 重开作业 |

### 8.3 DONE 诚实化（防幻觉汇报）

- agent 输出 `[[IMPLEMENT_DONE]]` 时，runner **忽略其自述矩阵**，以实测矩阵覆写后落消息：真实矩阵 + agent 摘要（标注"自述"）并排展示
- **自述与实测不符**（自述全过但实测 FAIL / 自述跑过测试但无测试事件）→ 该回合按 `waiting_input` 处理，附提示："DONE 声明与验证结果不符，已退回。" 并计入诚实率度量（§9.3）——**连续 2 次不守约自动升级提示模型能力不足**

---

## 9. 错误分类与修复编排（L4 层，V4）

### 9.1 失败包（failure bundle）

```json
{ "stage": "test", "reason": "TEST_FAILED",
  "newFailures": [{"name":"TestX","message":"…","file":"a.go:42"}],
  "knownFailures": ["TestOld"], "logHead": "…800", "logTail": "…800",
  "attempt": 2, "maxAttempts": 3 }
```

### 9.2 修复回注策略

| 失败类别（对应 finetune 文档 §2.3） | 判据 | 动作 |
|---|---|---|
| **L1** 编译/静态 | `BUILD_FAILED`/lint 类 | 回注修复回合（bundle + "仅修复，不改测试"），上限 3 轮 |
| **L2** 定位明确的测试失败 | `TEST_FAILED` 且失败项 ≤ 5 且错误栈完整 | 同上回注；第 2 轮起 bundle 只含未过项（去噪） |
| **L3** 症状≠根因/跨文件 | 同一失败 3 轮未修复，或失败项 > 5，或修复引发新失败 | 升级：① 角色绑定允许时切换更强模型重开回合 ② 否则 `[[NEED_INPUT]]` 上报人工（附完整 bundle） |
| flaky 疑似 | 重跑结果翻转 | 不回注，标记待人工确认 |

### 9.3 度量（并入 roadmap P2-T2 埋点）

一次通过率（首轮验证 PASS 占比）/ 平均修复轮次 / DONE 诚实率（自述=实测比例）/ 升级率（L3 占比）/ 各环节 UNVERIFIABLE 占比（环境短板地图——指导哪些项目该补验收配置）。

---

## 10. 任务分解与排期

| 编号 | 任务 | 内容 | 依赖 | 估时 |
|---|---|---|---|---|
| V1 | 门禁核心（L1+L2） | 发现链 P0~P3、配置存储（arch_projects.meta.verify + 会话声明解析）、白名单沙箱执行、超时分级、级别判定（A/B/C/D） | 无 | 5d |
| V2 | 适配器层（L3） | 统一归一化接口 + 适配器：pytest/junit、jest/vitest JSON、go test -json、cargo、maven/gradle、dotnet trx、ctest；每适配器 fixture 项目单测 | V1 | 5~6d |
| V3 | 回归基线 | base 基线异步运行与缓存、新增/存量区分、flaky 标记、（可选）diff 测试选择 | V1+V2 | 3~4d |
| V4 | 编排（L4） | 失败包、修复回注轮（上限/去噪）、L3 升级（换模型或 NEED_INPUT）、exec_bridge 事件扩展 | V1+V2 | 4~5d |
| V5 | 反馈（L5） | 验证矩阵落事件流/会话消息、原因码文案表、DONE 诚实化、度量埋点 | V1~V4 | 3~4d |
| — | E2E 验证 | 每语言 1 个最小 fixture 项目（py/ts/go 必做，其余适配器就绪一个验一个）走完 矩阵→修复→终态 全链 | V5 | 3d |

**合计 23~26 人日**。验证门禁：runner 侧改动过 G3（`packages/core/tests`）+ G6（进程拓扑不变）；architect 侧过 G3+G4+G5+G7；不新增进程、不动端口。

---

## 11. 风险与对策

| 风险 | 对策 |
|---|---|
| 验收命令被注入破坏性指令 | 白名单 + worktree 隔离 + 配置来源审计（P0 配置才算用户意图） |
| 依赖安装拖慢验收（node_modules 等） | deps 阶段结果缓存（lockfile 哈希 key）；基线 worktree 复用缓存 |
| flaky 测试污染新增失败判定 | 重跑一次翻转即标 flaky，不阻塞终态，列提示 |
| agent 为骗过门禁改测试（删断言） | diff 审查面提示"测试文件变更"标记；度量盯测试净删除量；后续可加"测试改动需人工确认"开关 |
| 跨平台差异（Windows/mac） | 首版仅承诺 Linux（与现有部署口径一致）；命令模板留平台字段 |
| 小语言/怪项目探测失败率高 | C/D 档确定性反馈兜底（宁可不验，不可假验）；UNVERIFIABLE 占比度量暴露短板 |

---

## 12. 与路线图的关系

- roadmap **P2-T5 修订**：由"单测结果回写任务树状态（3d）"改为"程序化验收门禁 V1~V5（23~26d），实现载体为 runner implement 管线（旧 SE 任务树已退役）"
- 排期归属：V1/V2 在 Phase 2 内随 P2-T3 断点修复轮并行推进（修复轮正需要门禁提供真实失败信号）；V3~V5 紧随其后
- 与微调专项（L 组）的衔接：本设计交付的失败包/修复轮数据即是 L7（L2 修复微调）的训练语料来源
