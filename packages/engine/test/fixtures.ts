export function svgDoc(inner: string, w = 400, h = 400): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">${inner}</svg>`;
}
export interface NodeOpts {
  name?: string;
  id?: string;
  fill?: string;
  translate?: boolean;
}

/** 一个 rect+text 的节点，默认绝对坐标；translate=true 时用 g[transform] 包裹 */
export function nodeG(x: number, y: number, label: string, o: NodeOpts = {}): string {
  const nameAttr = o.name ? ` data-name="${o.name}"` : '';
  const idAttr = o.id ? ` id="${o.id}"` : '';
  const fill = o.fill ?? '#e3f2fd';
  if (o.translate) {
    return `<g class="node"${nameAttr}${idAttr} transform="translate(${x} ${y})">`
      + `<rect x="0" y="0" width="80" height="40" style="fill:${fill};stroke:#2196f3;stroke-width:1"/>`
      + `<text x="40" y="25" text-anchor="middle" font-size="14">${label}</text></g>`;
  }
  return `<g class="node"${nameAttr}${idAttr}>`
    + `<rect x="${x}" y="${y}" width="80" height="40" style="fill:${fill};stroke:#2196f3;stroke-width:1"/>`
    + `<text x="${x + 40}" y="${y + 25}" text-anchor="middle" font-size="14">${label}</text></g>`;
}

export function edgePath(x1: number, y1: number, x2: number, y2: number, id?: string): string {
  return `<g class="edge"${id ? ` id="${id}"` : ''}>`
    + `<path d="M ${x1} ${y1} L ${x2} ${y2}" style="stroke:#999999;stroke-width:1"/>`
    + `</g>`;
}

export function edgeCurve(x1: number, y1: number, x2: number, y2: number): string {
  const mx = (x1 + x2) / 2;
  return `<g class="edge"><path d="M ${x1} ${y1} C ${mx} ${y1 - 40} ${mx} ${y2 - 40} ${x2} ${y2}" `
    + `style="stroke:#999999;stroke-width:1"/></g>`;
}

export function titleGroup(name: string, inner: string): string {
  return `<g><title>${name}</title>${inner}</g>`;
}

export function anonRect(x: number, y: number, w = 40, h = 20, fill = '#cccccc'): string {
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill}" stroke="#000000" stroke-width="1"/>`;
}

export async function settle(fn: () => boolean, timeoutMs = 3000, msg = 'settle timeout'): Promise<void> {
  const t0 = Date.now();
  while (!fn()) {
    if (Date.now() - t0 > timeoutMs) throw new Error(msg);
    await new Promise((r) => setTimeout(r, 10));
  }
}

export function flush(times = 6): Promise<void> {
  let p = Promise.resolve();
  for (let i = 0; i < times; i++) p = p.then(() => new Promise((r) => setTimeout(r, 0)));
  return p;
}
