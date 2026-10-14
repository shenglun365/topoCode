/**
 * 规约视图单源(cv-248) — 规约载荷的字段签名识别 + 宽形态归一 + 分节 MD 组装。
 *
 * 架构原则「载荷形态决定渲染形态」(与后端 cv-246 归属判别同构): 规约 schema
 * 的 JSON 载荷无论出现在哪里(落库后的 specReady 卡 / 模型失格形态的正文),
 * 显示面一律按 MD 分节渲染——字段值内的 markdown 由 MarkdownView 渲染。
 *
 * 两族字段名(schema 契约, 非猜测):
 *   - snapshot 形态(存储/卡自包含载荷): desc/design/allowedScope[]/...
 *   - 传输载荷形态(模型产出): requirementMd/designMd/allowedScopeMd/...
 * 归一化由别名表驱动(与后端 _SPEC_FIELD_ALIASES 同构); 禁止散落的字段名
 * if-else——新字段只改表。
 */
export const SPEC_FIELDS = [
  'title', 'requirementMd', 'designMd', 'allowedScope', 'allowedScopeMd',
  'forbiddenScope', 'forbiddenScopeMd', 'acceptance', 'acceptanceMd',
  'assessmentMd', 'estMin', 'priority',
]

/** 字段别名表(宽形态归一单源): canonical → 依序首个非空别名。 */
const _ALIASES: Record<string, string[]> = {
  title: ['title'],
  desc: ['desc', 'requirementMd', 'requirement'],
  design: ['design', 'designMd'],
  allowedScope: ['allowedScope', 'allowedScopeMd'],
  forbiddenScope: ['forbiddenScope', 'forbiddenScopeMd'],
  acceptance: ['acceptance', 'acceptanceMd'],
  assessmentSummary: ['assessmentSummary', 'assessmentMd'],
  estMin: ['estMin'],
  priority: ['priority'],
}

/** 正文规约载荷识别阈值(字段签名命中数)——低于此不认领(防普通 json 误判)。 */
const SIGNATURE_MIN_HITS = 3

const _FENCE_RE = /```(?:json)?\s*\n?(\{[\s\S]*?\})\s*```/g

/** 正文中的规约载荷提取(字段签名判别; 提取与「写入需求」按钮同源共用)。 */
export function parseSpecPayload(content: string): Record<string, unknown> | null {
  if (!content) return null
  for (const m of (content ?? '').matchAll(_FENCE_RE)) {
    try {
      const obj = JSON.parse(m[1])
      if (obj && typeof obj === 'object') {
        const hits = SPEC_FIELDS.filter((k) => k in obj).length
        if (hits >= SIGNATURE_MIN_HITS) return obj
      }
    } catch { /* 下一个围栏 */ }
  }
  return null
}

const _lines = (v: unknown): string[] => {
  if (Array.isArray(v)) return v.map((x) => String(x).trim()).filter(Boolean)
  const s = String(v ?? '').trim()
  if (!s) return []
  return s.split('\n').map((x) => x.replace(/^[-*]\s*/, '').trim()).filter(Boolean)
}

/** 宽形态归一: 两族字段名 → 快照规范形(纯函数)。 */
export function normalizeSpec(raw: Record<string, unknown>): Record<string, any> {
  const out: Record<string, any> = {}
  for (const [canon, aliases] of Object.entries(_ALIASES)) {
    for (const a of aliases) {
      const v = (raw ?? {})[a]
      if (v === undefined || v === null || v === '') continue
      out[canon] = canon.endsWith('Scope') || canon === 'acceptance'
        ? _lines(v) : (typeof v === 'string' ? v.trim() : v)
      break
    }
  }
  return out
}

export interface SpecView { title: string; priority: string; body: string; hasBody: boolean }

/** 规约载荷 → MD 分节视图(cv-215 specCard 与正文草稿视图共用单源)。 */
export function assembleSpecView(raw: Record<string, unknown>, fallbackTitle = ''): SpecView {
  const p = normalizeSpec(raw)
  const sections: string[] = []
  const desc = String(p.desc || fallbackTitle || '').trim()
  if (desc) sections.push(`## 需求目标\n\n${desc}`)
  // functionalScope: 快照形态专有字段(无别名), 原始直读
  const functional: string[] = Array.isArray(raw.functionalScope) ? raw.functionalScope : []
  if (functional.length) {
    sections.push('## 需求目标清单\n\n' + functional.map((x) => `- ${x}`).join('\n'))
  }
  if (String(p.design || '').trim()) sections.push(`## 方案\n\n${p.design}`)
  if ((p.allowedScope as string[])?.length) {
    sections.push('## 允许改动范围\n\n' + p.allowedScope.map((x: string) => `- ${x}`).join('\n'))
  }
  if ((p.forbiddenScope as string[])?.length) {
    sections.push('## 禁止改动\n\n' + p.forbiddenScope.map((x: string) => `- ${x}`).join('\n'))
  }
  if ((p.acceptance as string[])?.length) {
    sections.push('## 验收标准\n\n' + p.acceptance.map((a: string, i: number) => `${i + 1}. ${a}`).join('\n'))
  }
  if (String(p.assessmentSummary || '').trim()) sections.push(`## 评估摘要\n\n${p.assessmentSummary}`)
  return {
    title: String(p.title || fallbackTitle || ''),
    priority: String(p.priority || ''),
    body: sections.join('\n\n'),
    hasBody: sections.length > 0,
  }
}
