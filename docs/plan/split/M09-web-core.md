# M09 web-core 前端基建（P1）

> 阶段：P1 | 预估：2–3 d | 前置：M01 | 后续：M10–M13
> 状态：✅ 完成（2026-08-20）
> 与 P2（M02–M05）无依赖，可并行执行。

## 0. 完成记录与计划偏差（2026-08-20）

**验收结果**：src/ 与 web/（非 architect）零交叉 import；`createRealIPC`/`IPCAPI` 定义唯一来源 web-core；
web-core 独立 typecheck 绿；root `vue-tsc --noEmit` 绿；`npm run build` 6 段全绿；`topo serve` 9 进程健康 +
5 SPA dev（5173/5174/5175 + gateway 静态）smoke 通过；vitest 32/32。

**与 §3 文件映射的偏差**（均为依赖链强制上提，方向不变）：
- `src/composables/useComponentId.ts` → web-core：ConfirmDialog 依赖且读 `window.api.env`（属 web-core 契约面）。
- `web/services/render.ts`、`web/services/diagramStateStore.ts`、`web/components/DiagramRebuildDialog.vue` → web-core：
  MermaidViewer/PlantUmlViewer 的硬依赖，留在 web/ 会造成 web-core → web/ 反向 import。
- 图标资源实际位于仓库根 `assets/`（非 `web/`）：`assets/star-logo-mark-v8{,-light}.svg` → `web-core/src/assets/`。

**过渡期保留**：`web/home.html` + `web/entry-home.ts` 重建为薄壳（引用 `@topo/web-core/portal/AppHome.vue`），
供 legacy `vite.web.config.ts` 构建；M11 迁入 apps/docs 后删除。

**包配置**：`exports` 采用按扩展名显式通配（`./types/*` → `./src/types/*.ts` 等），
因 TS 5.9 与 Vite 对无扩展名 exports target 的解析行为不同（TS 不补扩展名、Vite 不做数组 target 回退）。

**typecheck 边界决策**：root tsconfig **不** include `web/`——web/ 存量 58 个类型错误（ChatSession/DocViewer/
useDocState 等，含真实逻辑 bug）属 M11/M12 范围；本模块顺带修复 root 覆盖的 9 个 src/ 存量错误
（FileStatsPanel/PreSummaryFileList/ReportHome/LeftPanel/TopBar/AnalysisPage/HomePage/navigation 等），
使 `npm run type-check` 首次全绿。`@web/*` paths 保留供 M11/M12 按 app 目录 typecheck 使用。

**门户构建**：`vite.config.portal.ts`（writeBundle 重命名 portal.html→home.html；门户无 tailwind 工具类，
禁用 postcss）→ `dist-portal/home.html` + `assets/`。AppHome dev 端口集合更新为 5173/5174/5175/5176。

## 1. 改造目标

建立前端核心基础框架 `@topo/web-core`（`packages/web-core/`）：单一契约源（`types/ipc.ts`）+ 传输层（`ipc.ts`/`browser-api.ts`）+ HTTP 客户端 + i18n 基建 + 共享组件 + 样式变量 + 门户（AppHome），使 5 个 SPA 对共享代码的引用全部收敛到 `@topo/web-core`，**消除 `src/ ↔ web/` 交叉引用**（现状 `HomePortal.vue` 直接 import `@web/AppHome.vue`）。

## 2. 功能边界

**包含（In）**
- 契约源：`types/ipc.ts`（1050 行，IPCAPI 全量方法签名）/ `types/window-api.ts` / `types/zmq.ts`（事件类型）
- 传输层：`services/ipc.ts`（createRealIPC，81 处 `window.api` 引用的实现源）/ `services/browser-api.ts`（window.api 注入）
- HTTP 客户端：`services/api.ts`（token 读取/Bearer 头/统一 fetch，web SPA 共用）
- 域类型：web SPA 共享类型（Project/Task/ChatSession/ModelConfig/Draft/Graph* 等）
- i18n 基建：`createAppI18n(messages)` 工厂 + 语言检测 + web 共享小词表（原 `web/services/i18n.ts`）
- 共享组件：StarLogoMark / AppDialog / ConfirmDialog / MermaidViewer / PlantUmlViewer / useDialog / useToast / useFloatDrag
- 样式：`variables.scss`（各 app vite `additionalData` 注入源）
- 门户：`AppHome.vue`（4 模块卡片页）+ 独立构建产物 `dist-portal/`（gateway 挂载 `/`）

**不包含（Out）**
- 任何域内业务组件（project/analysis/knowledge/report/chat 域组件 → 各 app）
- workbench 的 i18n 词表（25 命名空间文件 → 留 M10 workbench）
- 可视化引擎 `src/lib/topo-animation/`（→ workbench）

**依赖方向**：web-core → 无内部依赖（只依赖 vue/pinia/vue-i18n 等三方）；被 4 个 app 依赖。web-core 内禁止 import `apps/*`。

## 3. 源码归属（文件映射）

### 3.1 来自 `src/`（workbench 上提）

| 现有路径 | 目标路径 |
|---|---|
| `src/types/ipc.ts` | `packages/web-core/src/types/ipc.ts` |
| `src/types/window-api.ts` | `packages/web-core/src/types/window-api.ts` |
| `src/types/zmq.ts` | `packages/web-core/src/types/zmq.ts` |
| `src/services/ipc.ts` | `packages/web-core/src/services/ipc.ts` |
| `src/services/browser-api.ts` | `packages/web-core/src/services/browser-api.ts` |
| `src/utils/{http,logger,device-id,time,fileColors,statusBadge}.ts` | `packages/web-core/src/utils/`（同名） |
| `src/styles/{variables,global}.scss` | `packages/web-core/src/styles/` |
| `src/components/shared/ConfirmDialog.vue` | `packages/web-core/src/components/ConfirmDialog.vue` |
| `src/i18n/index.ts`（工厂部分） | `packages/web-core/src/i18n/setup.ts`（`createAppI18n` + detectLocale + localeNames） |

`src/types/index.ts`、`src/i18n/{zh-CN,en-US}/**`（25+25 词表）留 workbench（M10）；其内部引用改为 `@topo/web-core/...`。

### 3.2 来自 `web/`（共享件上提）

| 现有路径 | 目标路径 |
|---|---|
| `web/services/api.ts`（186 行） | `packages/web-core/src/services/api.ts` |
| `web/types/index.ts`（106 行） | `packages/web-core/src/types/domain.ts` |
| `web/services/i18n.ts` | `packages/web-core/src/i18n/web-locales.ts` |
| `web/components/StarLogoMark.vue` | `packages/web-core/src/components/StarLogoMark.vue` |
| `web/components/shared/AppDialog.vue` | `packages/web-core/src/components/AppDialog.vue` |
| `web/components/MermaidViewer.vue` | `packages/web-core/src/components/MermaidViewer.vue` |
| `web/components/PlantUmlViewer.vue` | `packages/web-core/src/components/PlantUmlViewer.vue` |
| `web/composables/{useDialog,useToast,useFloatDrag}.ts` | `packages/web-core/src/composables/`（同名）（useDialog/useToast 确认被 DocViewer+ChatSession 双用；useFloatDrag 同查） |
| `web/AppHome.vue` | `packages/web-core/src/portal/AppHome.vue` |
| `web/entry-home.ts` | `packages/web-core/src/portal/main.ts` |
| `web/home.html` | `packages/web-core/portal.html`（web-core 自有 vite 构建入口） |
| `web/star-logo-mark*.svg`（门户/各页引用的图标资源） | `packages/web-core/src/assets/`（被 app 引用的资源随 M10–M13 校正 import 路径） |

### 3.3 测试

| 现有路径 | 目标路径 |
|---|---|
| `tests/unit/utils/{fileColors,time,logger,statusBadge}.test.ts` | `packages/web-core/tests/`（4 文件） |

## 4. 包配置（`packages/web-core/package.json`）

```json
{
  "name": "@topo/web-core",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "main": "src/index.ts",
  "types": "src/index.ts",
  "exports": {
    ".": "./src/index.ts",
    "./types/*": "./src/types/*",
    "./services/*": "./src/services/*",
    "./utils/*": "./src/utils/*",
    "./components/*": "./src/components/*",
    "./composables/*": "./src/composables/*",
    "./i18n/*": "./src/i18n/*",
    "./styles/*": "./src/styles/*",
    "./portal/*": "./src/portal/*"
  },
  "scripts": { "build:portal": "vite build", "typecheck": "vue-tsc --noEmit" },
  "dependencies": { "vue": "3.5.13", "vue-i18n": "9.14.5" }
}
```

- `src/index.ts`：聚合导出（createAppI18n、api 客户端、types re-export）
- 源包模式（不预编译）：app 的 vite 直接编译其 TS；`vite build` 时随 app 打包
- 门户构建：`vite.config.portal.ts`（root 包目录，input `portal.html`，outDir `dist-portal/`，产物 `home.html` + `assets/`）

## 5. 执行任务

### 任务 9.1 包骨架
- 建 `packages/web-core/`（package.json 见 §4 + tsconfig 继承根 + `src/` 目录 + `src/index.ts`）
- `npm install` 验证 workspace 链接
- **验证**：`node -e "require.resolve('@topo/web-core')"` 成功

### 任务 9.2 文件迁移
- `git mv` §3 全部文件到 `packages/web-core/`
- 包内 import 改为相对路径；`ipc.ts` 对 `types/ipc.ts` 的引用改包内相对
- `src/index.ts` 聚合导出
- **验证**：`vue-tsc --noEmit`（web-core 自身）通过

### 任务 9.3 引用方改造（src/ + web/ 全部 SPA 文件）
- 全仓替换 import：
  - `@/types/ipc` / `@/services/ipc` / `@/services/browser-api` → `@topo/web-core/types/ipc` / `@topo/web-core/services/ipc` / `@topo/web-core/services/browser-api`（src/ 侧；注意 src 的 `@` 别名仍指向自身 src，仅被迁文件改包名引用）
  - `@web/services/api` → `@topo/web-core/services/api`；`@web/types` → `@topo/web-core/types/domain`；`@web/components/{MermaidViewer,PlantUmlViewer,StarLogoMark}` → `@topo/web-core/components/...`；`@web/components/shared/AppDialog` → `@topo/web-core/components/AppDialog`；`@web/composables/useDialog` 等 → `@topo/web-core/composables/...`
  - `src/pages/HomePortal.vue`：`@web/AppHome.vue` → `@topo/web-core/portal/AppHome.vue`
- 各 vite config 增加 `@topo/web-core` 解析（workspaces 下 node_modules 软链自动解析，通常无需 alias；scss `additionalData` 的 `@/styles/variables.scss` 改为 `@topo/web-core/styles/variables.scss`）
- **验证**：G4（root `vue-tsc --noEmit` 覆盖 src/+web/，若 tsconfig include 未覆盖则按 app 目录分别跑）+ G5（`npm run build` 旧脚本全量构建成功）

### 任务 9.4 门户独立构建
- web-core `vite.config.portal.ts` + `portal.html`；`npm run build:portal` → `dist-portal/home.html`
- 临时让 gateway 的 `/` 静态源指向 `dist-portal`（M06 前的过渡：仍走 legacy `plugins/reports/static/home.html`；本任务只保证**可构建**，gateway 切换在 M06/M10 完成）
- **验证**：`dist-portal/` 产物存在且 `home.html` 引用 `assets/*.js`

### 任务 9.5 回归
- 5 SPA dev smoke（5173/5174/5175 + gateway 静态）：门户 4 卡片可点击跳转
- G4+G5+G7 全过
- **验证**：全绿后提交；README §7 更新 M09 状态

## 6. 验收标准

1. `src/` 与 `web/` 之间**零交叉 import**（grep 断言：`src/**` 中无 `@web/`；`web/**` 中无 `@/` 指向 src）
2. 共享件唯一来源：`git grep "createRealIPC\|IPCAPI"` 仅 web-core 有定义
3. G4/G5/G7 全过；5 SPA 功能不变（重点：workbench 的 window.api 81 处引用、web SPA 的 token 读取、门户跳转）
4. web-core 独立 typecheck 通过，无对 `apps/*` 的 import

## 7. 风险与注意

| 风险 | 缓解 |
|---|---|
| `types/ipc.ts` 1050 行契约源被 workbench 大量深路径 import（`@/types/ipc` 逐符号） | 包 `exports` 暴露 `./types/*` 深路径，import 语句只改前缀不改符号 |
| `@topo/web-core` 在 vite dev 下走 node_modules 软链到源 TS，HMR 行为 | 软链源包 + `optimizeDeps.exclude`（若出现依赖预构建问题）；smoke 时验证 HMR |
| scss `additionalData` 改包路径后各 app 构建差异 | 3 个现有 vite config（M10–M13 各自接管前）统一在任务 9.3 修改并全量 build |
| 门户 AppHome 的 dev 端口感知逻辑（5173/5174/5175 硬编码） | M13 起 architect 迁 5176 → 本任务同步把端口集合改为 `['5173','5174','5175','5176']` 并核对 workbenchHref 逻辑 |
| web-core 词表与 workbench 词表 key 冲突 | 两者独立实例（createAppI18n 各传各的 messages），不合并词表 |
