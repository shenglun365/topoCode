import { apiBaseUrl } from '@/services/api-client'

export type DiagramLang = 'mermaid' | 'plantuml' | 'toposcript'

export interface DiagramBlock {
  id: string
  lang: DiagramLang
  code: string
  title?: string
  svg?: string
  url?: string
  error?: string
  loading?: boolean
}

let mermaidApi: any = null
let mermaidInit = false

async function ensureMermaid(): Promise<any> {
  if (mermaidApi) return mermaidApi
  const mod = await import('mermaid')
  mermaidApi = mod.default
  if (!mermaidInit) {
    mermaidApi.initialize({
      startOnLoad: false,
      securityLevel: 'loose',
      theme: 'dark',
      themeVariables: {
        background: '#181825',
        primaryColor: '#313244',
        primaryTextColor: '#cdd6f4',
        primaryBorderColor: '#45475a',
        secondaryColor: '#1e1e2e',
        tertiaryColor: '#181825',
        lineColor: '#7f849c',
        fontFamily: 'var(--font-sans)',
        fontSize: '13px',
      },
    })
    mermaidInit = true
  }
  return mermaidApi
}

export async function renderMermaid(code: string, id: string): Promise<string> {
  const mermaid = await ensureMermaid()
  const result = await mermaid.render(`md-${id}`, code)
  return result.svg
}

/** 渲染 PlantUML 为 SVG 文本：POST 到 architect 后端 `/diagram/plantuml`，
 * 由后端经 `plantuml_service`(PLANTUML_SERVER，本地 8300)渲染。与 KB AI chat `/api/plantuml` 同构。 */
export async function renderPlantuml(code: string): Promise<string> {
  const resp = await fetch(`${apiBaseUrl()}/diagram/plantuml`, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain' },
    body: code,
  })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    let msg = text?.trim() || `PlantUML server returned ${resp.status}`
    try {
      const j = JSON.parse(text)
      if (j && j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch { /* keep raw text */ }
    throw new Error(msg)
  }
  return resp.text()
}

export function normalizeMermaid(code: string): string {
  return code
    .replace(/\b([A-Za-z_]\w*)\s+\[/g, '$1[')
    .replace(/\[([^[\]]*?)\(([^()]*)\)([^[\]]*?)\]/g, '[$1$2$3]')
    .replace(/^\s*style\s+.*$/gm, '')
    .replace(/[ \t]+$/gm, '')
}
