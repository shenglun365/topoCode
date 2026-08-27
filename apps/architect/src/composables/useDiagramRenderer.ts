/** 图渲染统一入口（收敛到 topoOne 内核）。

mermaid/plantuml 渲染统一经 @topo/web-core/composables/useTopoRender：
- mermaid  主线程 MermaidEngine（catppuccin 主题随 data-theme，见内核 themes）
- plantuml POST {base}/plantuml/svg（gateway /api/topo，sidecar→本地 jar→远程兜底）
规模预判/超限友好提示等纯函数保留于此。
*/

import { renderDiagram } from '@topo/web-core/composables/useTopoRender'

export type DiagramLang = 'mermaid' | 'plantuml' | 'toposcript'

/** 渲染 Mermaid 为 SVG 文本（主线程内核，主题跟随 data-theme）。 */
export async function renderMermaid(code: string): Promise<string> {
  return renderDiagram('mermaid', code)
}

/** 渲染 PlantUML 为 SVG 文本（经 gateway /api/topo，sidecar 优先 + 注入兜底）。 */
export async function renderPlantuml(code: string): Promise<string> {
  return renderDiagram('plantuml', code)
}

export function normalizeMermaid(code: string): string {
  return code
    .replace(/\b([A-Za-z_]\w*)\s+\[/g, '$1[')
    .replace(/\[([^[\]]*?)\(([^()]*)\)([^[\]]*?)\]/g, '[$1$2$3]')
    .replace(/^\s*style\s+.*$/gm, '')
    .replace(/[ \t]+$/gm, '')
}

/** 各渲染器的关系边数上限(不扩容：仅用于超限时给出友好提示，引导缩小数据范围)。 */
export const DIAGRAM_EDGE_LIMITS: Partial<Record<DiagramLang, number>> = {
  mermaid: 500,
  plantuml: 400,
}

/** 粗略统计图源中的关系边数(用于渲染前预判规模，避免直接抛底层报错)。 */
export function countDiagramEdges(lang: DiagramLang, code: string): number {
  if (!code) return 0
  let n = 0
  for (const raw of code.split('\n')) {
    const t = raw.trim()
    if (!t) continue
    if (lang === 'mermaid') {
      // flowchart 边行: `a -->|label| b`；排除 linkStyle/classDef 等样式行。
      if (t.includes('-->') && !t.startsWith('linkStyle') && !t.startsWith('class ')) n++
    } else if (lang === 'plantuml') {
      // 关系行: `n0 --> n1` 或 `n0 -> n1`；排除 skinparam/note/component 等指令行。
      if (/^[A-Za-z_]\w*\s+--?>/.test(t)) n++
    }
  }
  return n
}

/** 判断渲染失败是否由「规模超限」引起(替换为友好提示，而非底层报错)。 */
export function isDiagramSizeError(lang: DiagramLang, message?: string): boolean {
  const m = (message || '').toLowerCase()
  if (lang === 'mermaid') {
    return m.includes('edge limit exceeded') || m.includes('maxedges') || m.includes('text limit')
  }
  if (lang === 'plantuml') {
    return m.includes('414') || m.includes('uri too long')
  }
  return false
}
