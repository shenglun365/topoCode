# @topo/engine

帧式增量图示动画引擎（mermaid / PlantUML / DOT → 逐帧捕获 → keyed diff → SVG/Canvas 增量渲染）。
完整设计见仓库 `docs/engine-design.md`。

## 快速开始

```ts
import {
  createPlayer, createSvgRenderer,
  mermaidRules,
} from '@topo/engine';

const player = await createPlayer({
  host: document.querySelector('#stage')!,
  renderer: createSvgRenderer({ mode: 'reveal' }),
  rules: mermaidRules,
  animation: {
    backend: 'mermaid',
    mode: 'reveal',          // reveal=构建式入场 / transition=帧间形变
    stepMs: 900,
    frames: [
      { svg: '<svg …>…' },    // 每帧一份完整 DSL 快照产物（离线喂入通道）
      { script: [             // 或 FrameScript 增量脚本（零重绘）
        { op: 'add', el: { key: 'ta:generic:name:B', kind: 'node', /* … */ } },
        { op: 'text', key: 'ta:generic:name:A', content: '改名' },
      ] },
    ],
  },
});

player.controller.play();                          // 显式播放（默认展示完整末帧）
player.controller.seek(1);                         // 任意跳步
player.controller.setSpeed(2);                     // 倍速
const off = player.controller.subscribe((s) => …); // { index, playing }
player.staticSvg(2);                               // 导出一帧脱敏静态 SVG（用户无感）
await player.controller.idle();                    // 等待应用链落定（测试/编排用）
player.dispose();                                  // 全部注入痕迹复原
```

真实 DSL 的逐帧渲染由后端完成（mermaid/graphviz 浏览器端、PlantUML 走 `apps/api` 的 `/plantuml/svg` 代理），
产物 SVG 以 `{ svg }` 喂入即可；`backends/` 内的 `mermaidRules/dotRules/plantumlRules` 供 `capture` 规范化。

## 开发

```bash
pnpm --filter @topo/engine test    # vitest（含真实 plantuml/dot 产物回归）
pnpm --filter @topo/engine build   # tsc --noEmit 类型检查
```

依赖策略：本体零运行时依赖；`mermaid`、`@hpcc-js/wasm-graphviz` 等均为宿主可选注入
（浏览器端动态 import 或离线喂 SVG）。
