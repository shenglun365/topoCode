import { describe, expect, it } from 'vitest';
import { createCanvasRenderer } from '../src/render/canvas/canvas-renderer';
import { drawElement, drawScene, type Ctx2D } from '../src/render/canvas/draw';
import { capture } from '../src/core/capture';
import { createStoryEngine, createCanvasSceneRenderer } from '../src/story';
import { nodeG, svgDoc } from './fixtures';

function recorder(log: string[]): Ctx2D {
  const noop = (): void => undefined;
  return {
    globalAlpha: 1, fillStyle: '', strokeStyle: '', lineWidth: 1, font: '',
    textAlign: 'left', textBaseline: 'alphabetic', lineDashOffset: 0,
    save: noop, restore: noop, translate: noop, scale: noop,
    beginPath: noop, moveTo: noop, lineTo: noop, bezierCurveTo: noop, closePath: noop,
    fill: () => log.push('fill'), stroke: () => log.push('stroke'),
    fillText: (t: string) => log.push(`text:${t}`),
    setLineDash: noop, clearRect: () => log.push('clear'),
  } as unknown as Ctx2D;
}

const specOf = (s: string) => capture(s).spec;
const svgOf = (s: string) => capture(s).svg as SVGSVGElement;

describe('drawElement / drawScene', () => {
  it('绘制填充、描边与文本', () => {
    const el = specOf(svgDoc(nodeG(10, 10, '甲', { name: 'A' }))).elements[0]!;
    const log: string[] = [];
    drawElement(recorder(log), el);
    expect(log).toContain('fill');
    expect(log).toContain('stroke');
    expect(log).toContain('text:甲');
  });

  it('excludeKeys 精准跳过（stay 不重画的机制基础）', () => {
    const spec = specOf(svgDoc(nodeG(10, 10, '甲', { name: 'A' }) + nodeG(200, 10, '乙', { name: 'B' })));
    const log: string[] = [];
    drawScene(recorder(log), spec, { excludeKeys: new Set(['ta:generic:name:B']) });
    expect(log).toContain('text:甲');
    expect(log).not.toContain('text:乙');
  });

  it('alpha≈0 完全跳过绘制', () => {
    const el = specOf(svgDoc(nodeG(10, 10, '甲', { name: 'A' }))).elements[0]!;
    const log: string[] = [];
    drawElement(recorder(log), el, { alpha: 0 });
    expect(log.length).toBe(0);
  });
});

describe('CanvasRenderer', () => {
  it('setFrame 静态呈现全部元素到基层', () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const base: string[] = [];
    const fx: string[] = [];
    let n = 0;
    const renderer = createCanvasRenderer({ dpr: 1, contextFactory: () => recorder(++n === 1 ? base : fx) });
    renderer.mount(host);
    const src = { spec: specOf(svgDoc(nodeG(10, 10, '甲', { name: 'A' }))), svg: svgOf(svgDoc(nodeG(10, 10, '甲', { name: 'A' }))) };
    renderer.setFrame(src);
    expect(base).toContain('text:甲');
    expect(fx.filter((l) => l !== 'clear')).toEqual([]); // 静态帧不在动态层画内容
    renderer.dispose();
    expect(host.childNodes.length).toBe(0);
  });

  it('hidden 静态帧（reveal -1）什么都不画', () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const base: string[] = [];
    const renderer = createCanvasRenderer({ dpr: 1, contextFactory: () => recorder(base) });
    renderer.mount(host);
    renderer.setFrame({ spec: specOf(svgDoc(nodeG(10, 10, '甲', { name: 'A' }))), svg: svgOf(svgDoc('')) }, { hidden: true });
    expect(base).not.toContain('text:甲');
    renderer.dispose();
  });
});

describe('player + canvas 全链路（离线 SVG 帧）', () => {
  it('三帧链图播完 + applySnapshot：末帧完整入基层', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const base: string[] = [];
    const rd = createCanvasSceneRenderer({ dpr: 1, contextFactory: () => recorder(base) });
    const f1 = svgDoc(nodeG(10, 10, '甲', { name: 'A' }));
    const f2 = svgDoc(nodeG(10, 10, '甲', { name: 'A' }) + nodeG(200, 10, '乙', { name: 'B' }));
    const f3 = svgDoc(nodeG(200, 10, '乙', { name: 'B' }));
    const quick = { staggerMs: 1, transitions: { enter: { type: 'fade' as const, durationMs: 5 }, exit: { type: 'fade' as const, durationMs: 5 } } };
    const eng = await createStoryEngine({
      graph: {
        entry: 'a',
        states: [{ id: 'a', dwellMs: 0, svg: f1 }, { id: 'b', dwellMs: 0, svg: f2 }, { id: 'c', dwellMs: 0, svg: f3 }],
        edges: [
          { from: 'a', to: 'b', choreography: quick },
          { from: 'b', to: 'c', choreography: quick },
        ],
      },
      host, renderer: rd,
    });
    await eng.start();
    base.length = 0;
    rd.applySnapshot(eng.scenes.get('c')!);
    expect(base).toContain('text:乙');
    expect(base).not.toContain('text:甲');
    eng.dispose();
    expect(host.childNodes.length).toBe(0);
  }, 20000);});
