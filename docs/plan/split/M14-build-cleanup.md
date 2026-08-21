# M14 统一构建与清理（P4）

> 阶段：P4（收尾） | 预估：1–2 d | 前置：M01–M13 全部完成 | 后续：无（P5 拆仓库为预留）
> 状态：⬜ 未开始

## 1. 改造目标

统一根级构建/开发/测试脚本到新的 Monorepo 结构，删除全部过渡物（legacy 目录/静态回退/双份配置/垃圾文件），更新文档，跑通**最终全量验收（8 项门禁）**。完成后仓库即目标结构，无过渡代码。

## 2. 功能边界

**包含（In）**
- 根 `package.json` scripts 重构 + workspaces 终态
- `scripts/` 终态（serve.sh manifest 驱动确认 + setup.sh 一键安装）
- 过渡代码删除：gateway static legacy 回退、根旧 vite/vitest/tailwind/postcss 配置（若以转发形式残留）、`plugins/reports/static`、各 `sys.path` 引导残留
- 垃圾文件/目录清理（§3 清单）
- `.gitignore` 更新
- README.md / README.en.md 更新（目录结构/安装/运行/开发/子项目说明）
- 最终验收：remove-electron 文档 §4 的 8 项验收门

**不包含（Out）**
- P5 拆独立 git 仓库（预留能力，不执行）
- 新功能开发

## 3. 清理清单

| 项 | 处置 | 前置确认 |
|---|---|---|
| `backend-core/`（整目录） | **删除** | M02–M08 后仅剩 `Bn`、`main.db`、`requirements*.txt`、`__pycache__`；requirements 已并入 `packages/core/pyproject.toml`（M08 任务 8.3 已验证） |
| `plugins/`（整目录） | **删除** | M06 删 reports 插件件、M08 迁 mcp/runner、M13 迁 architect 后，仅剩 `chat_service/`、`arch_kernel/`（只有 `__pycache__` 残留）与空目录 |
| `src/`（整目录） | **删除** | M10 迁移后 |
| `web/`（整目录） | **删除** | M09（共享件）+ M11/M12/M13（各域）迁移后；`main.ts.bak`、`star-logo-mark*.svg` 未引用者确认删除 |
| `index.html`、`vite.config.ts`（根）、`vite.web.config.ts`、`vite.architect.config.ts`、`vitest.config.ts`、`tailwind.config.js`、`postcss.config.js`（根） | **删除** | 已迁入 `apps/workbench` 与 web-core（M09/M10）；若 M10 前以转发形式保留，本步删除转发 |
| `tests/`（根） | **删除** | M09（web-core 4 测试）+ M10（剩余）迁移后 |
| `plugins/reports/static/` | **删除** | M06 legacy 回退代码删除 + 各 app dist 构建产物就绪（`/`、`/app`、`/viewer`、`/projects`、`/chat`、`/architect` 全 200 验证后） |
| `dist/`（根构建产物） | **删除** + gitignore 已有 | workbench 产物改在 `apps/workbench/dist` |
| `B[模块2]n`（根，0 字节） | **删除** | 无引用 |
| `backend-core/Bn`、`backend-core/main.db` | **删除** | 随 backend-core 目录 |
| `dump.rdb`（redis 残留） | **删除** | 项目不用 redis |
| `tmp-module-build/`、`dist-modules/`、`dist-plugins/`（若本地存在） | **删除**（gitignore 已覆盖） | 构建产物 |
| `.pytest_cache/` | **删除**（gitignore 追加） | |
| `release/`（Electron 时代构建产物：AppImage/deb/rpm/exe） | **删除本地产物**；gitignore 已有 `release/` | 若需保留历史产物，归档至仓库外 |
| 根 `package.json` 失效脚本 `next:setup:pip` / `next:backend:test` / `next:backend:shell`（指向已删除的 `next/backend`） | **删除** | grep 确认无引用 |
| 根 `package.json` dependencies 中与 app 重复项 | **删除**（依赖全部下沉到各 app/web-core/core pyproject） | 全量 `npm install && npm run build` 验证无缺依赖 |
| `build/`（bundle-plugin/bundle-module/bundle-worker 脚本） | 保留并核对 | `npm run build` 链（build:worker/plugins/module）路径更新到新目录；若 render-worker 归属 workbench（src/workers 已迁 M10），脚本内路径同步 |
| `scripts/serve.sh` | 终态核对 | M07 已改 `python -m topoone.supervisor.cli`；`stop`/pidfile 逻辑回归 |
| `.github/`（CI 配置） | **更新** | 构建/测试命令改新路径；grep `backend-core`、`plugins/`、`src/` 引用 |
| `docs/` 中指向旧路径的文档（usage-guide-*.md 等） | 路径引用更新 | 仅改路径，不改内容 |

`.gitignore` 追加：`apps/*/dist/`、`apps/*/server/static/`（architect 产物）、`packages/web-core/dist-portal/`、`.pytest_cache/`、`node_modules/.vite-*`。

## 4. 根 package.json 终态脚本

```json
{
  "workspaces": ["packages/web-core", "apps/workbench", "apps/docs", "apps/chat", "apps/architect"],
  "scripts": {
    "dev": "concurrently -n core,workbench,docs,chat,architect \"npm run serve:core\" \"npm run dev:workbench\" \"npm run dev:docs\" \"npm run dev:chat\" \"npm run dev:architect\"",
    "serve:core": "bash scripts/serve.sh foreground",
    "dev:workbench": "npm run dev -w @topo/app-workbench",
    "dev:docs": "npm run dev -w @topo/app-docs",
    "dev:chat": "npm run dev -w @topo/app-chat",
    "dev:architect": "npm run dev -w @topo/app-architect",
    "build": "npm run build:core && npm run build:portal && npm run build:apps",
    "build:core": "node build/bundle-worker.mjs && node build/bundle-plugin.mjs && node build/bundle-module.mjs",
    "build:portal": "npm run build:portal -w @topo/web-core",
    "build:apps": "npm run build -w @topo/app-workbench -w @topo/app-docs -w @topo/app-chat -w @topo/app-architect",
    "test": "npm run test:py && npm run test:fe",
    "test:py": "python -m pytest packages/core/tests apps/docs/tests apps/chat/tests apps/architect/tests apps/workbench/tests -v",
    "test:fe": "npm run test -w @topo/app-workbench -w @topo/app-docs -w @topo/app-chat && npm run test -w @topo/web-core",
    "type-check": "npm run typecheck --workspaces --if-present",
    "lint": "eslint . --ext .vue,.js,.jsx,.cjs,.mjs,.ts,.tsx --ignore-path .gitignore",
    "setup": "bash scripts/setup.sh",
    "status": "python -m topoone.supervisor.cli status",
    "serve": "bash scripts/serve.sh"
  }
}
```

`scripts/setup.sh`（新增）：创建/复用 `.venv` → `pip install -e packages/core -e apps/*/server`（含依赖）→ `npm install`（workspaces）→ 输出后续 `npm run dev` 指引。

## 5. 执行任务

### 任务 14.1 脚本与配置终态
- 按 §4 重写根 package.json；新增 `scripts/setup.sh`
- `build/*.mjs` 路径更新（worker 源 → `apps/workbench/src/workers`；plugins → `packages/core/topoone/plugins`）
- `.github/` CI 更新
- **验证**：`npm install && npm run build` 全量成功；`npm run test` 全绿

### 任务 14.2 过渡代码删除
- gateway 静态 legacy 回退（M06 任务 6.2 的回退分支）删除
- 各 `sys.path.insert` 引导残留 grep 清零（`grep -rn "sys.path.insert" packages/ apps/` 应仅剩合理项并逐一确认）
- §3 清单逐项删除（每项独立可回退：先 grep 引用再删）
- **验证**：每删一项跑 G6（9 进程）+ G7（SPA 可达）；全删后全量回归

### 任务 14.3 文档更新
- README.md / README.en.md：目录结构（新结构图）、安装（setup.sh 一键）、运行（`npm run dev` / `topo serve`）、开发（per-app dev/test）、子项目说明（4 子项目 + 核心框架边界）、MCP 接入命令变更（若 M08 涉及）
- `docs/plan/remove-electron-architecture.md` 顶部追加"后续：工程拆分见 docs/plan/split/"指引
- **验证**：文档内命令全部实际跑通一遍（README 命令逐条执行）

### 任务 14.4 最终验收（8 项门禁，remove-electron §4）
1. `topo serve` 全 9 进程健康（含 runner 3458 + agent 3482 + llm 3484）
2. `/api/rpc` 抽查 `analysis.runTask` 全链路（导入→解析→社区→LLM 摘要，经网关命名空间路由 → kb/llm）
3. `/ws/events` 任务/导入进度推送 + llm 流式（浏览器端）
4. web-ui 手动 smoke（5 个 SPA entry 全可达 + SPA 间互跳）
5. 后端 pytest（packages/core + apps/*/tests）+ 前端 vitest（各 app + web-core）全绿
6. architect workbench 经 `3456/architect` 可达 + `/ws/kb-analysis` 提取流式正常（LLM 经 llm 服务）
7. coding agent 执行进度可见（runner 3458 可达，agent pipeline 可用）
8. 鉴权生效：非本机访问 3456 被拒；无 token → 401
- 附加：全新 venv `pip install -e packages/core` + `npm install && npm run build` 冷启动冒烟（M08 已做，本步终态复核）
- **验证**：8 项全过后，README §7 全部模块状态置 ✅，本拆分宣告完成

## 6. 验收标准

1. 仓库目录 = 总纲 README §2 目标结构（无过渡目录/双份配置）
2. 8 项验收门全过
3. `git status` 干净，无垃圾文件
4. README 命令逐条可执行

## 7. 风险与注意

| 风险 | 缓解 |
|---|---|
| 根 package.json dependencies 下沉误删 | 任务 14.1 全量 build + 各 app `vite build` 双重验证；缺依赖报错即补 |
| CI 更新遗漏（.github 工作流引用旧路径） | grep `backend-core|plugins/reports|src/` in .github/ 全覆盖 |
| 删除顺序错误（先删 static 回退后 app dist 未构建） | 14.2 严格按"先构建产物就绪 → 再删回退 → 再删 legacy"顺序 |
| 用户本地环境（~/.topocode 数据、systemd 模板、外部 MCP 配置）不受影响 | 拆分零数据迁移（共享 DB 路径不变）；外部命令变更（MCP 接入路径）在 README changelog 明示 |
