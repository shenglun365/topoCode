import type {
  Frame, FrameDiff, OrderStrategy, SceneElement, TimelineItem, TimelineSpec, TransitionSpec,
} from './types';
import { animDebug, animDebugOn, shortKey } from './debug';

function defaultTransition(cls: TimelineItem['cls'], el: SceneElement): TransitionSpec {
  switch (cls) {
    case 'enter':
      if (el.kind === 'edge') return { type: 'drawIn', durationMs: 500, easing: 'ease' };
      if (el.kind === 'label' || el.kind === 'shape') return { type: 'fade', durationMs: 300, easing: 'ease' };
      return { type: 'scale', durationMs: 350, easing: 'ease-out' };
    case 'exit':
      return { type: 'fade', durationMs: el.kind === 'edge' ? 350 : 300, easing: 'ease' };
    case 'move':
      return { type: 'slide', durationMs: 500, easing: 'ease-in-out' };
    case 'update':
      return { type: 'morph', durationMs: 500, easing: 'ease' };
    case 'text':
      return { type: 'textCross', durationMs: 350, easing: 'ease' };
    case 'style':
    default:
      return { type: 'fade', durationMs: 300, easing: 'ease' };
  }
}

export function resolveOrder(order?: OrderStrategy): (a: SceneElement, b: SceneElement) => number {
  if (typeof order === 'function') return order;
  switch (order) {
    case 'reverse':
      return (a, b) => b.z - a.z;
    case 'position':
      return (a, b) => a.bbox.x - b.bbox.x || a.bbox.y - b.bbox.y;
    case 'degree':
      // capture 依据端点关系 BFS 回填 depth（边为 d+0.5，随源节点后、目标节点前）；
      // 无端点信息时全体 depth 相等 → 自然退化为文档序
      return (a, b) => (a.depth ?? 1e9) - (b.depth ?? 1e9) || a.source.docIndex - b.source.docIndex;
    case 'doc':
    default:
      return (a, b) => a.z - b.z;
  }
}

/**
 * 过渡编排（docs/engine-design.md §8）：
 * 槽位顺序 exit → update → move → text → style → enter，槽间 overlap 交叠，
 * enter 槽内按 order 策略排序并 stagger 错峰。
 */
export function buildTimeline(diff: FrameDiff, frame: Frame | undefined, stepMs: number): TimelineSpec {
  const opts = frame?.opts ?? {};
  const overlap = opts.overlap ?? 0.5;
  const cmp = resolveOrder(opts.order);

  // 几何 morph 边与 move 节点共享同一时槽（并行补间）：节点 lerp 与路径端点 lerp 同
  // delay/duration/easing ⇒ 线端始终贴住移动节点（"连线随节点拉伸"）；纯样式 update 仍独立先行走位
  const moveGroup = [
    ...diff.move.map((mv) => ({ el: mv.el, prev: mv.prev, ownCls: 'move' as const })),
    ...diff.update.filter((u) => u.geom && u.morphable).map((u) => ({ el: u.next, prev: u.prev, ownCls: 'update' as const })),
  ];
  const slotDefs: { cls: TimelineItem['cls']; items: { el: SceneElement; prev?: SceneElement; ownCls?: TimelineItem['cls'] }[] }[] = [
    { cls: 'exit', items: diff.exit.map((el) => ({ el })) },
    { cls: 'update', items: diff.update.filter((u) => !(u.geom && u.morphable)).map((u) => ({ el: u.next, prev: u.prev })) },
    { cls: 'move', items: moveGroup },
    { cls: 'text', items: diff.text.map((t) => ({ el: t.el, prev: t.prevEl })) },
    { cls: 'enter', items: diff.enter.map((el) => ({ el })) },
  ];

  const items: TimelineItem[] = [];
  let cursor = 0;
  for (const slot of slotDefs) {
    const list = [...slot.items].sort((a, b) => cmp(a.el, b.el));
    if (list.length === 0) continue;
    const stagger = slot.cls === 'enter' ? (opts.staggerMs ?? 60) : 0;
    let slotDur = 0;
    for (let i = 0; i < list.length; i++) {
      const it = list[i]!;
      const tcls = it.ownCls ?? slot.cls;
      let transition = opts.transitions?.[tcls] ?? defaultTransition(tcls, it.el);
      // morph 边并入 move 槽：easing/时长对齐 slide，保证端点同步
      if (it.ownCls === 'update' && opts.transitions?.move === undefined) {
        const mv = opts.transitions?.move ?? defaultTransition('move', it.el);
        transition = { type: 'morph', durationMs: transition.durationMs, easing: mv.easing };
      }
      const delayMs = cursor + i * stagger;
      items.push({
        key: it.el.key,
        cls: it.ownCls ?? slot.cls,
        kind: it.el.kind,
        el: it.el,
        prev: it.prev,
        delayMs,
        transition,
      });
      slotDur = Math.max(slotDur, i * stagger + transition.durationMs);
    }
    cursor += slotDur * (1 - Math.min(Math.max(overlap, 0), 1));
  }

  if (animDebugOn()) {
    animDebug(`timeline items=[${items.map((i) => `${i.cls}:${shortKey(i.key)}@${i.delayMs}ms/${i.transition.durationMs}ms{${i.transition.type}}`).join(' ')}]`);
  }
  const totalMs = items.reduce((m, it) => Math.max(m, it.delayMs + it.transition.durationMs), 0);
  const frameMs = opts.durationMs ?? Math.max(totalMs + 200, stepMs);
  return { items, totalMs, frameMs };
}
