# CONV-02 前端共享内核规约（@topo/web-core）

> 源码根：`packages/web-core/`（npm workspace 包名 `@topo/web-core`）
> 修改方：前端基础组。apps 发现可复用代码 → 提上提需求（§3 准则），不得自行在 web-core 加私有代码。

## 1. 源码范围与模块职责

| 路径 | 职责 |
|---|---|
| `src/services/browser-api.ts` | **RPC + 鉴权客户端（全前端唯一权威实现）**：`POST /api/rpc/{method}`、token 读取（`#token=` 首粘 → localStorage `topocode:token` → Bearer 头 / WS `?token=`）、401 提示 |
| `src/services/api.ts` | 轻量 API 封装（同 token 逻辑） |
| `src/services/token.ts` | token 单一源（R2 修正：browser-api/api 共同 import，勿再复制） |
| `src/services/chat-stream.ts` | chat SSE 流消费助手（R2 修正：`data:` 行协议统一解析） |
| `src/services/ipc.ts` | 历史 IPC 兼容层（Electron 移除后的浏览器实现） |

**传输边界（R2 厘清）**：KB 系（workbench/docs/chat）访问 gateway 一律经 `browser-api`/`api.ts`（token 单一源 `services/token.ts`）；`utils/http.ts` 是 **portal 认证域专用客户端**（独立后端 `VITE_API_BASE`、独立 token `topocode_token` + 懒续期），与 gateway 传输**分域并存、禁止合并**；architect 自带传输（`api-client.ts`）属独立战略范围（见 F3/A5）。`window.api`（`installBrowserAPI`）定位 = web-core IPC 契约的浏览器实现层，KB 系组件/服务可经其订阅事件（`/ws/events`）。
| `src/components/` | 共享组件：`MermaidViewer`、`PlantUmlViewer`、`AppDialog`、`ConfirmDialog`、`StarLogoMark` 等 |
| `src/composables/` | `useDialog`/`useToast`/`useFloatDrag`/`useComponentId` 等 |
| `src/i18n/` | 双语资源 + `setup`/`web-locales`（zh-CN / en-US） |
| `src/portal/` | 门户首页（home.html 源：`AppHome.vue` 等） |
| `src/types/` `src/utils/` `src/assets/` `src/styles/` | 类型/工具/静态资源/共享样式 |
| `vite.config.portal.ts` → `dist-portal/` | 门户构建产物（gateway `/`·`/home` 直接 serve；资产 `/assets/` 挂载） |

## 2. 使用方式（apps 侧）

```ts
// 深导入（当前约定，不经 index.ts 中转）
import { createBrowserAPI, installBrowserAPI } from '@topo/web-core/services/browser-api'
import MermaidViewer from '@topo/web-core/components/MermaidViewer.vue'
import { setupI18n } from '@topo/web-core/i18n/setup'
```

- 依赖声明：app 的 `package.json` 加 `"@topo/web-core": "*"`（workspace 解析，无版本漂移）。
- **token 客户端唯一性**：app 内一切 `/api/rpc` 调用与 WS 连接必须复用 web-core 的 token 逻辑（localStorage key 固定 `topocode:token`，同源共享）。自包含 app（architect）须内嵌等价实现（见 CONV-03 §6 工程清单）。
- 别名：各 app vite 按 workspace 解析，无需自配 alias。

## 3. 上提 / 下沉准则

### 3.1 上提（app → web-core）
满足**全部**条件才上提：
1. **≥2 个 app 实际使用**（或第 3 个子项目立项时的明确复用计划）；
2. 与具体 app 业务解耦（不含 app 专属 store/路由/术语）；
3. 依赖可解析（web-core 不依赖任何 app 的包）。

流程：app 侧保留副本 → web-core 新增 → 各 app 删本地副本改深导入 → 全量 G4+G5+G7 回归 → 提交说明列出上提文件清单。

### 3.2 下沉（web-core → app）
- 仅 1 个 app 使用的代码不得滞留在 web-core（每半年盘点一次导出清单）。
- 下沉 = 反向流程：app 加副本 → web-core 删 → 回归。

### 3.3 禁止
- web-core import 任何 `@topo/app-*`；
- app 之间互相 import 对方 src（复用走上提）；
- 在 web-core 放 app 私有 mock/测试数据。

## 4. 冻结契约

| 契约 | 内容 |
|---|---|
| 导出 API | `src/index.ts` 导出面（types/ipc/browser-api/api/i18n/composables）——删除/改名导出 = 破坏所有 app，须评审 |
| token 行为 | localStorage key `topocode:token`；`#token=` 首粘即存并清 URL；请求带 `Authorization: Bearer`；WS 带 `?token=` |
| 门户 URL | `/`·`/home` → dist-portal/home.html；资产 `/assets/*`（gateway 挂载，CONV-01 §2.3） |
| i18n | 双语键集（zh-CN/en-US 对称），新键必须双语文案 |

## 5. 构建与验证

| 命令 | 说明 |
|---|---|
| `npm run build:portal -w @topo/web-core` | 门户 → `dist-portal/`（`npm run build` 自动含） |
| `npm run typecheck -w @topo/web-core` | vue-tsc |
| `npm run test -w @topo/web-core` | vitest |
| 上提/下沉后 | 全量 `npm run type-check` + `npm run build` + 5 SPA URL 200（G4+G5+G7） |

## 6. 提交前检查清单

- [ ] 新增导出已入 `index.ts`（如需经入口暴露）且无 app 依赖引入
- [ ] 双语 i18n 键对称
- [ ] `typecheck` + `test`（web-core）+ 全量 type-check 绿
- [ ] 门户构建后 `/`·`/home` 资产 200（`/assets/home.*.js`）
- [ ] 上提/下沉：各 app 本地副本已清理，无重复实现
