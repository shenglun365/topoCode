# @topocode/topo-animation API 文档

## 安装

```bash
npm install @topocode/topo-animation
```

## 快速开始

```typescript
import { AnimationEngine } from '@topocode/topo-animation';

const engine = new AnimationEngine({
  container: document.getElementById('stage'),
  renderer: 'svg',  // | 'canvas'
  width: 800,
  height: 600,
});

engine.init();

// 加载 TopoScript
engine.load(`
  topo.node({ id: "A", label: "A" })
  topo.node({ id: "B", label: "B" })
  topo.edge({ source: "A", target: "B" })
  topo.sequence({ steps: [
    { type: "enter", targets: ["A", "B"], duration: 500 }
  ]})
`);

engine.play();
```

## 核心 API

### AnimationEngine

统一动画引擎，整合编译、执行、渲染、播放。

```typescript
interface EngineOptions {
  container: HTMLElement | string;
  renderer?: 'd3' | 'pixi' | 'auto';
  width?: number;
  height?: number;
  theme?: RenderTheme;
  layout?: 'force-directed' | 'hierarchy' | 'grid' | 'circular';
  fps?: number;           // 10-60，默认 10
  autoPlay?: boolean;
  zoom?: boolean;
}
```

**方法:**
- `init()` - 初始化渲染器
- `load(source: string)` - 加载 TopoScript
- `play()` - 播放
- `pause()` - 暂停
- `stop()` - 停止
- `seek(step: number)` - 跳转
- `getRenderer()` - 获取渲染器
- `on(event, handler)` - 事件订阅
- `destroy()` - 销毁

### ScriptBuilder

链式 API 构建动画。

```typescript
import { ScriptBuilder } from '@topocode/topo-animation';

const instructions = new ScriptBuilder()
  .addNode('A', { position: [100, 100], label: 'A' })
  .addNode('B', { position: [200, 200], label: 'B' })
  .addEdge('A', 'B')
  .fadeIn(['A', 'B'])
  .highlight(['A'])
  .wait(1000)
  .clearHighlight()
  .compile();
```

### 编译器

```typescript
import { compile, validate } from '@topocode/topo-animation';

// 编译
const result = compile(`topo.node({ id: "A" })`);
if (result.success) {
  console.log(result.instructions);
}

// 验证
const valid = validate(`topo.node({ id: "A" })`);
```

### 渲染器

```typescript
import { SVGRenderer, CanvasRenderer } from '@topocode/topo-animation';

// SVG (D3.js)
const svgRenderer = new SVGRenderer();
svgRenderer.init({ container, width: 800, height: 600 });
svgRenderer.render(state);

// Canvas (PixiJS)
const canvasRenderer = new CanvasRenderer();
canvasRenderer.init({ container, width: 800, height: 600, fps: 30 });
canvasRenderer.render(state);
```

### 主题

```typescript
import {
  defaultTheme,
  darkTheme,
  oceanTheme,
  forestTheme,
  sunsetTheme,
  monokaiTheme,
} from '@topocode/topo-animation';

const engine = new AnimationEngine({
  container,
  theme: darkTheme,
});
```

### 布局

```typescript
import { applyLayout, forceLayout, gridLayout, circularLayout } from '@topocode/topo-animation';

const laidOutNodes = applyLayout(
  'force-directed',  // | 'hierarchy' | 'grid' | 'circular'
  nodes,
  edges,
  800,
  600
);
```

### 导出

```typescript
import { exportPNG, exportSVG, exportHTML, exportJSON } from '@topocode/topo-animation';

// PNG
const blob = await exportPNG({ renderer: engine.getRenderer() });

// SVG
const svg = exportSVG({ renderer: engine.getRenderer() });

// HTML
const html = exportHTML({ script: source, title: 'My Animation' });

// JSON
const json = exportJSON({ instructions: result.instructions, pretty: true });
```

## TopoScript 语法

### 风格 A: topo.xxx({...})

```javascript
topo.scene({ name: "Demo", layout: "grid", fps: 30 })
topo.node({ id: "A", label: "A", position: [100, 100] })
topo.edge({ source: "A", target: "B" })
topo.sequence({
  steps: [
    { type: "enter", targets: ["A"], duration: 500 },
    { type: "highlight", targets: ["A"], duration: 800 },
    { type: "wait", duration: 1000 },
    { type: "reset", targets: ["A"] }
  ]
})
```

### 风格 B: 声明式

```
node A at (100, 100) label "A"
node B at (200, 200) label "B"
edge A -> B label "connects"

animate {
  enter A duration 500
  highlight A duration 800
  wait 1000
  reset A
}
```

### 动画步骤类型

| 类型 | 说明 |
|------|------|
| `enter` | 节点入场 |
| `exit` | 节点退场 |
| `highlight` | 高亮 |
| `reset` | 重置高亮 |
| `wait` | 等待 |
| `flow` | 数据流 |
| `draw-edge` | 绘制边 |
| `morph` | 变形 |

## 事件

| 事件 | 说明 |
|------|------|
| `play` | 开始播放 |
| `pause` | 暂停 |
| `stop` | 停止 |
| `complete` | 播放完成 |
| `step-change` | 步骤变化 |
| `frame-render` | 帧渲染 |
| `seek` | 跳转 |
| `error` | 错误 |

## 类型

```typescript
// 核心类型
type NodeState = { id, position, label, style, metadata }
type EdgeState = { id, source, target, label, style, metadata }
type AnimationState = { stepIndex, timestamp, nodes, edges, highlights, selections }
type StateDelta = { stepIndex, nodeUpdates, nodeRemovals, edgeUpdates, edgeRemovals }

// 指令类型 (33 种)
type AnimationInstruction =
  | AddNodeInstruction
  | FadeInInstruction
  | HighlightInstruction
  // ... 等 33 种
```
