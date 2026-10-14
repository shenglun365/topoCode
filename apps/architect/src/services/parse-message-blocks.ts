/** 消息内容解析：把 ```mermaid / ```plantuml / ```diagram 围栏块从纯文本/Markdown 中拆出。
 *
 * 与 web/services/parseContent.ts 同构（KB chat 的构图能力），供 architect 各对话
 * (资产/需求 AnalysisChat) 渲染图表。返回顺序块：
 *   - text     : 围栏外的 Markdown 文本(原样返回，由调用方渲染)
 *   - mermaid  : ```mermaid 围栏内代码
 *   - plantuml : ```plantuml 围栏内代码
 *   - diagram  : ```diagram 围栏内 JSON(DiagramSchema IR)，由前端动画层转成 mermaid/plantuml
 * 流式输出中未闭合的围栏按文本处理，待围栏闭合后重新解析即成为图表块。
 */
import type { DiagramSchema } from '@topo/graph-kernel/core/types.ts'

export type ChatMessageBlock =
  | { type: 'text'; text: string }
  | { type: 'mermaid'; code: string }
  | { type: 'plantuml'; code: string }
  | { type: 'diagram'; schema: DiagramSchema }

/** 与 capabilities 的 DIAGRAM_TYPES 对齐(用于校验 IR 的 type，非法则降级为文本)。 */
const DIAGRAM_TYPES = [
  'flowchart', 'activity', 'sequence', 'state', 'class', 'er', 'usecase', 'component', 'architecture', 'gantt', 'pie',
] as const

const DIAGRAM_FENCE_RE = /```(mermaid|plantuml|diagram)[ \t]*\r?\n([\s\S]*?)```/g

/** 解析 ```diagram 围栏内的 JSON 为 DiagramSchema；非法/缺 type 返回 null(调用方降级为文本)。 */
function parseDiagramSchema(body: string): DiagramSchema | null {
  try {
    const raw = JSON.parse(body)
    if (!raw || typeof raw !== 'object' || typeof raw.type !== 'string') return null
    if (!(DIAGRAM_TYPES as readonly string[]).includes(raw.type)) return null
    return { ...raw, version: 1 } as DiagramSchema
  } catch {
    return null
  }
}

export function parseMessageBlocks(content: string): ChatMessageBlock[] {
  const blocks: ChatMessageBlock[] = []
  let lastIndex = 0
  let m: RegExpExecArray | null

  while ((m = DIAGRAM_FENCE_RE.exec(content ?? '')) !== null) {
    const before = (content ?? '').slice(lastIndex, m.index)
    if (before.trim()) blocks.push({ type: 'text', text: before })
    const body = m[2].trim()
    if (m[1] === 'diagram') {
      const schema = parseDiagramSchema(body)
      if (schema) blocks.push({ type: 'diagram', schema })
      else if (body) blocks.push({ type: 'text', text: body })
    } else if (body) {
      blocks.push({ type: m[1] as 'mermaid' | 'plantuml', code: body })
    }
    lastIndex = m.index + m[0].length
  }

  const after = (content ?? '').slice(lastIndex)
  if (after.trim()) blocks.push({ type: 'text', text: after })

  if (!blocks.length && content?.trim()) blocks.push({ type: 'text', text: content })
  return blocks
}
