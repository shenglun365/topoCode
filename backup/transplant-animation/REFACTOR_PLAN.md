# 纯前端动画库重构方案

> 目标: 将当前前后端分离架构重构为纯前端动画库，新代码置于 `transplant/` 目录下
> 包名: `@topocode/topo-animation`

---

## 一、重构目标

### 1.1 核心变化

| 维度 | 当前架构 | 目标架构 |
|------|---------|---------|
| 编译 | 后端 Fastify + Redis 缓存 | 前端直接编译（Tokenizer → Parser → AST → Instructions） |
| 运行时 | 前端执行指令 | 保持不变（InstructionExecutor → StateMachine → Renderer） |
| 渲染 | SVG(D3) / Canvas(PixiJS) | 保持不变，增强 TopoScript 支持 |
| 部署 | Docker Compose (app + compiler + redis) | 单 NPM 包，零后端依赖 |
| 通信 | HTTP REST API | 无（纯函数调用） |
| 脚本语言 | TOPOSCRIPT / DOT+ / TS API | 统一 TopoScript DSL + TS API（合并原 TOPOSCRIPT 所有语法） |
| 包名 | `@topocode/animation-engine` | `@topocode/topo-animation`（新包） |

### 1.2 保留 vs 废弃

**保留复用（从 client/src/）:**
- `core/types.ts` — 核心类型定义
- `core/instructions/` — 30+ 指令类型 + InstructionExecutor
- `core/StateMachine.ts` — 状态机
- `renderer/` — SVGRenderer + CanvasRenderer + 主题系统
- `runtime/TimelineController.ts` — 播放控制
- `script/ScriptBuilder.ts` — 链式 API
- `utils/easing.ts` — 缓动函数
- `group/` — 分组系统
- `extensions/` — 扩展系统

**从后端迁移到前端:**
- `compiler-service/src/compiler/toposcript/` — TOPOSCRIPT 编译器（lexer/parser/generator/semantic）
- `compiler-service/src/compiler/shared/instruction/` — 指令工厂
- DOT+ 编译器暂不迁移（Q2: 优先 TopoScript）

**废弃:**
- Fastify HTTP 服务、Redis 缓存、Docker 部署、HTTP 客户端、Mock 回退

---

## 二、目标目录结构

```
transplant/
├── package.json                    # 新包 @topocode/topo-animation
├── tsconfig.json
├── vite.config.ts
├── vitest.config.ts
├── rollup.config.mjs               # CJS + ESM + UMD
│
├── src/
│   ├── index.ts                    # 公共 API 桶导出
│   │
│   ├── core/                       # 核心类型 + 状态机
│   │   ├── types.ts                # NodeState, EdgeState, AnimationState, StateDelta
│   │   ├── StateMachine.ts         # StateDelta[] → AnimationState[]
│   │   ├── instructions/
│   │   │   ├── InstructionTypes.ts # 30+ 指令类型定义
│   │   │   ├── InstructionFactory.ts # 指令工厂
│   │   │   └── InstructionExecutor.ts # 指令 → StateDelta 执行器
│   │   ├── MetadataUtils.ts        # 元数据工具
│   │   └── group-types.ts          # 组类型
│   │
│   ├── compiler/                   # 前端编译器（统一 TopoScript，合并原 TOPOSCRIPT 语法）
│   │   ├── TopoTokenizer.ts        # 词法分析器（合并架构文档 + 原 TOPOSCRIPT 词法）
│   │   ├── TopoParser.ts           # 语法分析器（递归下降，合并两种语法）
│   │   ├── TopoAST.ts              # TopoScript AST 类型定义（统一对齐）
│   │   ├── TopoSemanticChecker.ts  # 语义检查器（从后端迁移）
│   │   ├── TopoCodeGenerator.ts    # AST → AnimationInstruction[]
│   │   ├── plugin/                 # TopoScript 插件系统（Q3: 变量/函数/条件，逐步实现）
│   │   │   ├── PluginInterface.ts  # 插件接口定义
│   │   │   ├── VariableScope.ts    # 变量作用域管理
│   │   │   ├── FunctionRegistry.ts # 函数注册与调用
│   │   │   └── ConditionEngine.ts  # 条件语句引擎
│   │   └── compile.ts              # 统一编译入口
│   │
│   ├── animator/                   # 动画播放器（架构文档中的 TopoAnimator）
│   │   ├── TopoAnimator.ts         # 序列播放器（play/pause/stop/seek）
│   │   ├── StepPlayer.ts           # 单步执行器
│   │   └── Effects.ts              # 动画效果（fade/scale/flow/glow）
│   │
│   ├── renderer/                   # 渲染器
│   │   ├── IRenderer.ts            # 渲染器接口
│   │   ├── svg/
│   │   │   └── SVGRenderer.ts      # D3.js SVG 渲染器
│   │   ├── canvas/
│   │   │   └── CanvasRenderer.ts   # PixiJS Canvas 渲染器
│   │   ├── theme/
│   │   │   └── defaultTheme.ts     # 主题系统
│   │   └── layout/                 # 布局算法（Q4: 优先复用 D3，无则自实现）
│   │       ├── force.ts            # 力导向布局（复用 D3 forceSimulation）
│   │       ├── hierarchy.ts        # 树形布局（复用 D3 tree）
│   │       ├── grid.ts             # 网格布局（自实现）
│   │       └── circular.ts         # 环形布局（自实现）
│   │
│   ├── runtime/                    # 运行时
│   │   ├── TimelineController.ts   # 时间轴控制
│   │   ├── EventEmitter.ts         # 事件系统
│   │   └── ScriptBuilder.ts        # 链式 API
│   │
│   ├── group/                      # 分组系统
│   │   └── GroupSystem.ts
│   │
│   ├── extensions/                 # 扩展系统
│   │   ├── shapes/                 # 自定义形状
│   │   ├── events/                 # 事件触发器
│   │   └── macros/                 # 宏扩展
│   │
│   ├── export/                     # 导出功能（Q6: 静态图片 + HTML 动画）
│   │   ├── exportImage.ts          # 静态图片导出（PNG/SVG）
│   │   ├── exportHTML.ts           # 自包含 HTML 导出（引用 CDN @topocode/topo-animation）
│   │   └── exportJSON.ts           # 动画数据导出（JSON）
│   │
│   ├── utils/                      # 工具函数
│   │   ├── easing.ts               # 缓动函数
│   │   ├── error.ts                # 错误类型
│   │   └── logger.ts               # 日志
│   │
│   └── testing/                    # 测试工具
│       └── mockData.ts             # Mock 数据
│
├── tests/
│   ├── compiler/
│   │   ├── TopoParser.test.ts
│   │   ├── TopoTokenizer.test.ts
│   │   └── compile.test.ts
│   ├── animator/
│   │   └── TopoAnimator.test.ts
│   ├── renderer/
│   │   ├── SVGRenderer.test.ts
│   │   └── layout.test.ts
│   └── core/
│       ├── StateMachine.test.ts
│       └── InstructionExecutor.test.ts
│
├── examples/                       # 示例
│   ├── basic.html                  # 基础示例
│   ├── toposcript.html             # TopoScript 示例
│   └── api.html                    # TypeScript API 示例
│
└── docs/
    ├── API.md                      # API 文档
    ├── TOPOSCRIPT.md               # TopoScript 语言参考
    └── MIGRATION.md                # 从旧版本迁移指南
```

---

## 三、TopoScript DSL 设计

### 3.1 语法规范（Q9: 统一架构文档 + 原 TOPOSCRIPT，合并词法/语法/语义）

TopoScript 支持两种语法风格，编译器统一解析为同一 AST：

**风格 A: 架构文档风格（`topo.xxx({...})`）**
```javascript
topo.scene({
  name: "Request Flow",
  layout: "force-directed",   // | "hierarchy" | "grid" | "circular"
  width: 1200,
  height: 800,
  renderer: "d3",             // | "pixi" | "auto"
  fps: 30,                    // Q10: 帧率配置（10-60，默认10）
})

topo.node({
  id: "gateway",
  label: "API Gateway",
  type: "service",            // | "database" | "queue" | "external" | "custom"
  shape: "rect",              // | "circle" | "diamond" | "hexagon"
  style: { fill: "#4A90D9", stroke: "#2C5F8D", radius: 8 },
})

topo.edge({ source: "gateway", target: "auth", label: "authenticate" })

topo.sequence({
  name: "Flow",
  autoPlay: true,
  loop: false,
  steps: [
    { type: "enter", targets: ["gateway"], effect: "fade-scale", duration: 500 },
    { type: "flow", path: ["gateway", "auth"], duration: 2000 },
    { type: "highlight", targets: ["gateway"], duration: 800 },
    { type: "wait", duration: 1500 },
    { type: "reset", targets: ["gateway"] },
  ],
})
```

**风格 B: 原 TOPOSCRIPT 风格（`node A at (x,y)`）**
```
#TOPOSCRIPT v1.0

node A at (100, 100) label "Node A" style { fill: "#4A90D9" }
node B at (200, 100) label "Node B"
edge A -> B label "connects"

animate {
  enter A duration 500
  enter B duration 500 delay 300
  highlight A duration 800
  wait 1500
  reset A
}
```

**两种风格可混用**，编译器统一输出 `AnimationInstruction[]`。

### 3.2 AST → 指令映射

| TopoScript 步骤 | 生成的 AnimationInstruction |
|----------------|---------------------------|
| `topo.node({...})` | `addNode` |
| `topo.edge({...})` | `addEdge` |
| `enter` | `fadeIn` + `scaleTo` |
| `draw-edge` | `addEdge` (带动画) |
| `flow` | `particle` |
| `highlight` | `highlight` + `glow` |
| `reset` | `clearHighlight` |
| `wait` | `wait` |
| `exit` | `fadeOut` + `removeNode` |
| `morph` | `moveTo` + `scaleTo` |

---

## 四、数据流

```
TopoScript 源码 / TypeScript API
       │
       ▼
┌─────────────────────────────────┐
│  compile()                       │
│  ├─ TopoParser                   │
│  │  ├─ TopoTokenizer (词法)      │
│  │  └─ TopoParser (语法 → AST)   │
│  └─ TopoCodeGenerator (AST → 指令)│
└──────────────┬──────────────────┘
               │
               ▼
       AnimationInstruction[]
               │
               ▼
┌─────────────────────────────────┐
│  InstructionExecutor             │
│  (指令 → StateDelta[])           │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│  StateMachine                    │
│  (StateDelta[] → AnimationState[])│
└──────────────┬──────────────────┘
               │
         ┌─────┴──────┐
         ▼            ▼
   SVGRenderer  CanvasRenderer
         │            │
         ▼            ▼
       SVG        WebGL Canvas
```

---

## 五、公共 API 设计

```typescript
// 核心导出
import {
  // 编译
  compile,              // compile(script: string, type: 'toposcript'|'dotplus'|'api') => AnimationInstruction[]

  // 引擎
  AnimationEngine,      // 统一引擎（编译 + 执行 + 渲染）

  // 构建
  ScriptBuilder,        // 链式 API

  // 渲染
  SVGRenderer,
  CanvasRenderer,

  // 动画
  TopoAnimator,         // 序列播放器

  // 主题
  defaultTheme,
  darkTheme,
  oceanTheme,

  // 导出（Q6: 静态图片 + HTML 动画）
  exportImage,       // PNG/SVG 静态图片
  exportHTML,        // 自包含 HTML（引用 CDN @topocode/topo-animation）
  exportJSON,        // 动画数据 JSON

  // 类型
  type AnimationInstruction,
  type AnimationState,
  type NodeState,
  type EdgeState,
} from '@topocode/topo-animation'

// 使用示例
const engine = new AnimationEngine({
  container: document.getElementById('stage'),
  renderer: 'svg',        // | 'canvas'
  theme: defaultTheme,
})

// 方式1: TopoScript
engine.load(`
  topo.scene({ name: "Demo", layout: "grid" })
  topo.node({ id: "A", label: "Node A" })
  topo.node({ id: "B", label: "Node B" })
  topo.edge({ source: "A", target: "B" })
  topo.sequence({ steps: [
    { type: "enter", targets: ["A", "B"], duration: 500 },
  ]})
`)

// 方式2: TypeScript API
engine.load(
  new ScriptBuilder()
    .addNode('A', { position: [100, 100], label: 'A' })
    .addNode('B', { position: [200, 100], label: 'B' })
    .addEdge('A', 'B')
    .fadeIn(['A', 'B'], { duration: 500 })
    .compile()
)

// 播放控制
engine.play()
engine.pause()
engine.stop()
engine.seek(50)  // 跳转到 50%

// 导出（Q6）
engine.exportImage('png')      // 导出当前帧为 PNG
engine.exportImage('svg')      // 导出当前帧为 SVG
engine.exportHTML()            // 导出自包含 HTML（引用 CDN）
engine.exportJSON()            // 导出动画数据
```

---

## 六、实施阶段

### Phase 1: 核心基础设施
1. 初始化 `transplant/` 项目（package.json, tsconfig, 构建配置）
2. 迁移核心类型（`core/types.ts`, `core/group-types.ts`）
3. 迁移指令系统（`core/instructions/`）
4. 迁移 StateMachine
5. 迁移 InstructionExecutor

### Phase 2: 编译器（Q9: 合并两种 TopoScript 语法）
6. 实现 TopoTokenizer（合并架构文档 + 原 TOPOSCRIPT 词法）
7. 实现 TopoParser（递归下降，支持两种语法风格）
8. 实现 TopoSemanticChecker（从后端迁移）
9. 实现 TopoCodeGenerator（AST → Instructions）
10. 统一编译入口 `compile.ts`

### Phase 2.5: TopoScript 插件系统（Q3: 逐步实现）
11. 定义 `TopoScriptPlugin` 接口
12. 实现变量作用域管理（`let x = 10`）
13. 实现函数定义和调用（`func drawNode(id) { ... }`）
14. 实现条件语句（`if (status == 'error') { ... }`）
15. 实现循环语句（`for (let i = 0; i < n; i++) { ... }`）

### Phase 3: 渲染器
16. 迁移 SVGRenderer（D3.js，默认为首选渲染器）
17. 迁移 CanvasRenderer（PixiJS，大规模节点优化）
18. 迁移主题系统
19. 实现布局算法（Q4: 力导向/树形复用 D3，网格/环形自实现）

### Phase 4: 动画播放器
20. 实现 TopoAnimator（序列播放）
21. 实现 StepPlayer（单步执行）
22. 实现 Effects（fade/scale/flow/glow）
23. 迁移 TimelineController
24. 实现帧率控制（Q10: 脚本配置，10-60FPS，默认10）

### Phase 5: 统一引擎
25. 实现 AnimationEngine（编译 + 执行 + 渲染一体化）
26. 实现 ScriptBuilder（链式 API）
27. 实现组系统
28. 实现扩展系统

### Phase 6: 导出 & 工具（Q6: 静态图片 + HTML 动画）
29. 实现静态图片导出（PNG/SVG）
30. 实现 HTML 导出（引用 CDN @topocode/topo-animation）
31. 实现 JSON 数据导出
32. 缓动函数、错误处理、日志

### Phase 7: 测试 & 文档
33. 单元测试覆盖（Vitest）
34. 示例页面
35. API 文档
36. 迁移指南

---

## 七、已确认决策（人工确认完成）

| # | 决策项 | 确认结果 | 影响 |
|---|--------|---------|------|
| Q1 | 包名称 | `@topocode/topo-animation`（新包名） | import 路径、NPM 发布 |
| Q2 | DOT+ 编译器 | 暂不迁移，优先 TopoScript | 减少初期工作量 |
| Q3 | TopoScript 插件 | 预留接口 + 逐步实现（变量/函数/条件） | Phase 2.5 新增 |
| Q4 | 布局算法 | 优先复用 D3，无则自实现 | 力导向/树形用 D3，网格/环形自实现 |
| Q5 | 双渲染器 | 保留 SVG + Canvas，SVG 为默认 | 两个都迁移 |
| Q6 | 导出功能 | 取消 GIF，改为静态图片 + HTML 动画 | exportImage/exportHTML/exportJSON |
| Q7 | 原 client/ 处理 | 保留参考不做变化，transplant 移植到新项目 | Git 历史保留 |
| Q8 | 测试框架 | Vitest | 与原项目生态一致 |
| Q9 | TopoScript 统一 | 同一语言，合并两种语法风格 | 词法/语法/语义统一对齐 |
| Q10 | 动画帧率 | 脚本预定义配置，10-60FPS，默认10 | SceneConfig.fps，引擎限制上限60 |

---

## 八、技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| D3 + PixiJS 同时依赖 | 包体积增大 | Tree-shaking + 可选导入 |
| 两种 TopoScript 语法合并 | 词法/语法复杂度增加 | 先实现风格A，逐步支持风格B |
| 插件系统实现复杂度 | 作用域/函数调用管理复杂 | Phase 2.5 逐步实现，先变量后函数 |
| 布局算法性能 | 大规模节点卡顿 | 虚拟渲染 + Web Worker |
| HTML 导出 CDN 依赖 | 离线环境不可用 | 支持内联模式（增大文件体积） |

---

## 九、成功标准

- [ ] `transplant/` 可独立构建（CJS + ESM + UMD）
- [ ] TopoScript 解析器支持两种语法风格（架构文档 + 原 TOPOSCRIPT）
- [ ] 指令系统覆盖 30+ 指令类型
- [ ] SVG + Canvas 双渲染器可用（SVG 为默认）
- [ ] TopoScript 插件系统支持变量/函数/条件（Phase 2.5）
- [ ] 帧率控制可通过脚本配置（10-60FPS）
- [ ] 静态图片导出（PNG/SVG）+ HTML 导出可用
- [ ] 单元测试覆盖率 > 80%（Vitest）
- [ ] 示例页面可正常运行
- [ ] 包体积 < 200KB (gzip, 不含 D3/PixiJS)
