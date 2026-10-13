/**
 * 核心资产守护 · 图谱高亮纯逻辑(2610)。
 * 三层标记 → 节点匹配器 + svg 后处理(黄描边+★徽标)。
 * 供 graph-view(语义图, asset 层)与 comp-graph(组件/文件图)共用;
 * 数据级「仅核心」过滤由各视图在节点集上自行施加(本文件不做过滤)。
 */

export interface CoreMarkLike {
  targetType: string
  targetId: string
}

/** 标记集合按层分桶。 */
export function coreSets(marks: CoreMarkLike[]): {
  assets: Set<string>
  comps: Set<string>
  files: Set<string>
} {
  const assets = new Set<string>()
  const comps = new Set<string>()
  const files = new Set<string>()
  for (const m of marks) {
    if (m.targetType === 'asset') assets.add(m.targetId)
    else if (m.targetType === 'component') comps.add(m.targetId)
    else if (m.targetType === 'file') files.add(m.targetId)
  }
  return { assets, comps, files }
}

/** 文件层后缀对齐: 分隔符归一(\\→/)后, id 等于标记路径或以 `/path` 结尾(工程根前缀差异容错)。 */
function fileHit(files: Set<string>, id: string): boolean {
  const norm = id.replace(/\\/g, '/')
  if (files.has(id) || files.has(norm)) return true
  for (const f of files) {
    const nf = f.replace(/\\/g, '/')
    if (norm === nf || norm.endsWith('/' + nf)) return true
  }
  return false
}

/** 节点-核心匹配器: asset/component/file 三层命中任一即核心。 */
export function coreNodeMatcher(marks: CoreMarkLike[]): (id: string) => boolean {
  const { assets, comps, files } = coreSets(marks)
  return (id: string) => assets.has(id) || comps.has(id) || fileHit(files, id)
}

/** 图例色(与 catppuccin yellow 一致; 内联供 svg 后处理, 不经 css 变量)。 */
export const CORE_STROKE = '#f9e2af'

/**
 * svg 后处理: 命中核心的 g.node 黄描边 + ★ 徽标; 未命中清理(幂等)。
 * resolveId: g.node 元素 → 资产/组件/文件 id(各视图用各自 clickIds/idMap 反查)。
 * 形状缺失(纯文本节点)时仅做 ★ 徽标。
 */
export function applyCoreHighlight(
  svg: SVGSVGElement,
  resolveId: (g: SVGGElement) => string,
  isCore: (id: string) => boolean,
): void {
  for (const g of Array.from(svg.querySelectorAll<SVGGElement>('g.node'))) {
    const aid = resolveId(g)
    const core = !!aid && isCore(aid)
    const shape = g.querySelector(
      ':scope > polygon, :scope > rect, :scope > circle, :scope > ellipse, :scope > path',
    ) as SVGElement | null
    if (shape) {
      if (core) {
        shape.style.stroke = CORE_STROKE
        shape.style.strokeWidth = '2.5'
      } else {
        shape.style.stroke = ''
        shape.style.strokeWidth = ''
      }
    }
    const star = g.querySelector(':scope > text.core-star')
    if (core && !star) {
      const t = document.createElementNS('http://www.w3.org/2000/svg', 'text')
      t.setAttribute('class', 'core-star')
      t.setAttribute('fill', CORE_STROKE)
      t.setAttribute('font-size', '11')
      t.textContent = '★'
      try {
        const bb = g.getBBox()
        if (bb.width > 0) {
          t.setAttribute('x', String(bb.x + bb.width - 8))
          t.setAttribute('y', String(bb.y + 9))
        }
      } catch {
        /* 未渲染完成时 getBBox 可能抛错——徽标缺坐标仍可见(默认左上) */
      }
      g.appendChild(t)
    } else if (!core && star) {
      star.remove()
    }
  }
}
