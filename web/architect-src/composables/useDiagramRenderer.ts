import plantumlEncoder from 'plantuml-encoder'
import { useArchSettingsStore } from '@/stores/settings-store'

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

export function buildPlantUmlUrl(code: string): string {
  const settings = useArchSettingsStore()
  const encoded = plantumlEncoder.encode(code)
  const base = settings.plantumlServer.replace(/\/+$/, '')
  return `${base}/svg/${encoded}`
}

export function normalizeMermaid(code: string): string {
  return code
    .replace(/\b([A-Za-z_]\w*)\s+\[/g, '$1[')
    .replace(/\[([^[\]]*?)\(([^()]*)\)([^[\]]*?)\]/g, '[$1$2$3]')
    .replace(/^\s*style\s+.*$/gm, '')
    .replace(/[ \t]+$/gm, '')
}
