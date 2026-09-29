import type { FrameOp, SceneElement, SceneSpec } from '../core/types';
import { unionBox, zeroBox } from '../core/types';
import { pathBbox, translateCommands } from '../core/path';
import { estimateTextBox } from '../core/text';

export interface ApplyError {
  index: number;
  op: string;
  message: string;
}

const isEl = (v: unknown): v is Partial<SceneElement> =>
  !!v && typeof v === 'object';

/** 轻量校验：返回错误列表，空数组=合法 */
export function validateOps(ops: FrameOp[]): ApplyError[] {
  const errs: ApplyError[] = [];
  if (!Array.isArray(ops)) return [{ index: -1, op: '*', message: 'ops 必须为数组' }];
  ops.forEach((op, i) => {
    if (!op || typeof op !== 'object') { errs.push({ index: i, op: String(op), message: '非对象' }); return; }
    switch (op.op) {
      case 'add':
        if (!isEl(op.el) || typeof (op.el as SceneElement).key !== 'string')
          errs.push({ index: i, op: 'add', message: '缺少 el.key' });
        break;
      case 'remove':
      case 'move':
        if (typeof (op as { key?: unknown }).key !== 'string')
          errs.push({ index: i, op: op.op, message: '缺少 key' });
        break;
      case 'update':
        if (!('key' in op) || !op.patch) errs.push({ index: i, op: 'update', message: '缺 key/patch' });
        break;
      case 'text':
        if (typeof (op as { key?: unknown }).key !== 'string' || typeof (op as { content?: unknown }).content !== 'string')
          errs.push({ index: i, op: 'text', message: '缺 key/content' });
        break;
      default:
        errs.push({ index: i, op: String((op as { op: string }).op), message: '未知 op' });
    }
  });
  return errs;
}

function sourceOf(el: SceneElement, backend: string, i: number): SceneElement['source'] {
  const key = el.key;
  return el.source?.backend === backend && el.source.sel
    ? el.source
    : { backend, docIndex: i, sel: `[data-ta-key="${key.replace(/["\\]/g, '')}"]` };
}

/**
 * 增量执行（docs/engine-design.md §4，M3）：
 * 把 FrameOp[] 施加到上一帧 SceneSpec，产生新 spec —— 纯数据操作，零重绘。
 * 未命中 key 的 op 记警告并跳过（静默降级）。
 */
export function applyOps(prev: SceneSpec, ops: FrameOp[], warn: (m: string) => void = () => undefined): SceneSpec {
  const els: SceneElement[] = prev.elements.map((e) => ({
    ...e,
    bbox: { ...e.bbox },
    paths: e.paths.map((p) => ({ d: p.d.map((c) => ({ ...c })), style: { ...p.style } })),
    text: e.text.map((t) => ({ ...t, box: { ...t.box }, style: { ...t.style } })),
    style: { ...e.style },
  }));
  const idx = new Map(els.map((e, i) => [e.key, i]));

  const bboxOf = (el: SceneElement): void => {
    let b: ReturnType<typeof zeroBox> | null = null;
    for (const p of el.paths) { const pb = pathBbox(p.d); b = b ? unionBox(b, pb) : pb; }
    for (const t of el.text) b = b ? unionBox(b, t.box) : { ...t.box };
    if (b) el.bbox = b;
  };

  for (const op of ops) {
    if (op.op === 'add') {
      const raw = op.el;
      if (idx.has(raw.key)) { warn(`add: key ${raw.key} 已存在，忽略`); continue; }
      const el: SceneElement = {
        key: raw.key, kind: raw.kind ?? 'node', bbox: raw.bbox ?? zeroBox(),
        paths: raw.paths ?? [], text: raw.text ?? [], style: raw.style ?? {},
        z: els.length, source: sourceOf(raw as SceneElement, prev.backend, els.length),
      };
      bboxOf(el);
      idx.set(el.key, els.length);
      els.push(el);
    } else if (op.op === 'remove') {
      const i = idx.get(op.key);
      if (i === undefined) { warn(`remove: 未找到 ${op.key}`); continue; }
      els.splice(i, 1);
      reindex(els, idx);
    } else if (op.op === 'update') {
      const i = idx.get(op.key);
      if (i === undefined) { warn(`update: 未找到 ${op.key}`); continue; }
      const el = els[i]!;
      if (op.patch.style) Object.assign(el.style, op.patch.style);
      if (op.patch.paths) el.paths = op.patch.paths.map((p) => ({ d: p.d, style: { ...el.style, ...p.style } }));
      if (op.patch.bbox) el.bbox = { ...op.patch.bbox };
      bboxOf(el);
    } else if (op.op === 'text') {
      const i = idx.get(op.key);
      if (i === undefined) { warn(`text: 未找到 ${op.key}`); continue; }
      const el = els[i]!;
      const size = parseFloat(el.style['font-size'] ?? '14') || 14;
      const t0 = el.text[0];
      const anchor = t0?.anchor ?? 'middle';
      const x = t0?.x ?? el.bbox.x + el.bbox.width / 2;
      const y = t0?.y ?? el.bbox.y + el.bbox.height / 2;
      el.text = [{ content: op.content, x, y, anchor, box: estimateTextBox(op.content, x, y, anchor, size), style: t0?.style ?? {} }];
      bboxOf(el);
    } else if (op.op === 'move') {
      const i = idx.get(op.key);
      if (i === undefined) { warn(`move: 未找到 ${op.key}`); continue; }
      const el = els[i]!;
      const dx = op.to.x - el.bbox.x;
      const dy = op.to.y - el.bbox.y;
      el.paths = el.paths.map((p) => ({ d: translateCommands(p.d, dx, dy), style: p.style }));
      el.text = el.text.map((t) => {
        const nx = t.x + dx;
        const ny = t.y + dy;
        const size = parseFloat(t.style['font-size'] ?? '14') || 14;
        return { ...t, x: nx, y: ny, box: estimateTextBox(t.content, nx, ny, t.anchor, size) };
      });
      bboxOf(el);
    }
  }
  els.forEach((e, i) => { e.z = i; });
  return { ...prev, elements: els };
}

function reindex(els: SceneElement[], idx: Map<string, number>): void {
  idx.clear();
  els.forEach((e, i) => idx.set(e.key, i));
}
