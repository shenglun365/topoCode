/**
 * 验收收据（receipt，借 Archify 2.16 artifact checks + SHA-256 收据，docs/engine-design.md §23）：
 * 封闭检查清单跑在 Document/Graph 上，给出机器可判定的验收面 —— 「0 error 才许宣称成功」。
 *
 * checks（按 animation 定位取舍）：
 *   frame/nonempty   每帧结构区非空                          error
 *   frame/renders    帧源文可被后端渲染（backend 缺省=skip）  error
 *   diff/finite      捕获 bbox 无 NaN/Infinity               error
 *   keys/unique      帧内 baseKey 无重复                      warning
 *                    （数据源图常有同名节点，capture 已按 #n 序号消重不破坏渲染；
 *                     仅提示同名元素无法互相配对、过渡退化为 enter/exit）
 *   keys/stability   相邻帧持续键占比 ≥0.5（动画平滑核心指标） warning
 *   dwell/valid      dwellMs≥0；auto=false 帧 info 提示      error/info
 */

import type { AnimBackend } from '../backends';
import { capture, genericRules } from '../core/capture';
import { baseKeyOf } from '../core/layout';
import { fnv1a } from '../core/key';
import type { StateGraphSpec } from '../story/types';
import { canonicalDoc } from './document';
import type { TopoDocument } from './types';

export type ReceiptSeverity = 'error' | 'warning' | 'info';

export interface ReceiptCheck {
  check: string;
  frame?: string;
  ok: boolean;
  severity: ReceiptSeverity;
  detail?: string;
}

export interface TopoReceipt {
  ok: boolean;
  frames: number;
  edges: number;
  checks: ReceiptCheck[];
  keys: { perFrame: number[]; stability: number[] };
  avgStability: number;
  digest: string;
}

async function digestText(text: string): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (subtle) {
    const buf = await subtle.digest('SHA-256', new TextEncoder().encode(text));
    return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
  }
  return `fnv1a-${fnv1a(text)}`;
}

export async function buildReceipt(
  doc: TopoDocument,
  opts: { graph?: StateGraphSpec; backend?: AnimBackend | null } = {},
): Promise<TopoReceipt> {
  const checks: ReceiptCheck[] = [];
  const perFrame: number[] = [];
  const stability: number[] = [];
  const keySets: Set<string>[] = [];

  for (const f of doc.frames) {
    const nonempty = f.source.trim() !== '';
    checks.push({ check: 'frame/nonempty', frame: f.id, severity: 'error', ok: nonempty, detail: nonempty ? undefined : '结构区为空' });

    if (opts.backend?.render) {
      try {
        const rendered = await opts.backend.render(f.source);
        const cap = capture(rendered, opts.backend.rules ?? genericRules);
        const finite = cap.spec.elements.every((e) =>
          [e.bbox.x, e.bbox.y, e.bbox.width, e.bbox.height].every((v) => Number.isFinite(v)));
        const bases = cap.spec.elements.map((e) => baseKeyOf(e.key));
        const dup = bases.length - new Set(bases).size;
        checks.push({ check: 'frame/renders', frame: f.id, severity: 'error', ok: true });
        checks.push({ check: 'diff/finite', frame: f.id, severity: 'error', ok: finite, detail: finite ? undefined : '存在 NaN/Infinity bbox' });
        checks.push({ check: 'keys/unique', frame: f.id, severity: 'warning', ok: dup === 0, detail: dup ? `${dup} 个重复 baseKey（同名元素不配对，过渡退化 enter/exit）` : undefined });
        perFrame.push(cap.spec.elements.length);
        keySets.push(new Set(bases));
      } catch (e) {
        checks.push({ check: 'frame/renders', frame: f.id, severity: 'error', ok: false, detail: (e as Error).message });
        perFrame.push(0);
        keySets.push(new Set<string>());
      }
    }
  }

  for (let i = 1; i < keySets.length; i++) {
    const a = keySets[i - 1] as Set<string>;
    const b = keySets[i] as Set<string>;
    const max = Math.max(a.size, b.size);
    const inter = max === 0 ? 1 : [...a].filter((k) => b.has(k)).length / max;
    const st = +inter.toFixed(2);
    stability.push(st);
    checks.push({
      check: 'keys/stability', frame: doc.frames[i]?.id, severity: 'warning', ok: st >= 0.5,
      detail: st >= 0.5 ? `持续键 ${(st * 100).toFixed(0)}%` : `持续键仅 ${(st * 100).toFixed(0)}%：大面积 enter/exit，过渡会闪变——检查相邻帧节点/边命名是否稳定`,
    });
  }

  if (opts.graph) {
    for (const s of opts.graph.states) {
      if (s.dwellMs !== undefined && s.dwellMs < 0) checks.push({ check: 'dwell/valid', frame: s.id, severity: 'error', ok: false, detail: `dwellMs=${s.dwellMs} < 0` });
      else if (s.auto === false) checks.push({ check: 'dwell/valid', frame: s.id, severity: 'info', ok: true, detail: '手动驻留（auto=false）：播放到该帧等待 next' });
    }
  }

  const avgStability = stability.length ? +(stability.reduce((x, y) => x + y, 0) / stability.length).toFixed(2) : 1;
  const ok = checks.every((c) => c.severity !== 'error' || c.ok);
  const digest = await digestText(canonicalDoc(doc));
  return {
    ok,
    frames: doc.frames.length,
    edges: opts.graph?.edges.length ?? Math.max(0, doc.frames.length - 1),
    checks,
    keys: { perFrame, stability },
    avgStability,
    digest,
  };
}
