/** 消息内容解析：把 ```mermaid / ```plantuml 围栏块从纯文本/Markdown 中拆出。
 *
 * 与 web/services/parseContent.ts 同构（KB chat 的构图能力），供 architect 各对话
 * (资产/需求 AnalysisChat) 渲染图表。返回顺序块：
 *   - text     : 围栏外的 Markdown 文本(原样返回，由调用方渲染)
 *   - mermaid  : ```mermaid 围栏内代码
 *   - plantuml : ```plantuml 围栏内代码
 * 流式输出中未闭合的围栏按文本处理，待围栏闭合后重新解析即成为图表块。
 */
export type ChatMessageBlock =
  | { type: 'text'; text: string }
  | { type: 'mermaid'; code: string }
  | { type: 'plantuml'; code: string }

const DIAGRAM_FENCE_RE = /```(mermaid|plantuml)[ \t]*\r?\n([\s\S]*?)```/g

export function parseMessageBlocks(content: string): ChatMessageBlock[] {
  const blocks: ChatMessageBlock[] = []
  let lastIndex = 0
  let m: RegExpExecArray | null

  while ((m = DIAGRAM_FENCE_RE.exec(content ?? '')) !== null) {
    const before = (content ?? '').slice(lastIndex, m.index)
    if (before.trim()) blocks.push({ type: 'text', text: before })
    const code = m[2].trim()
    if (code) blocks.push({ type: m[1] as 'mermaid' | 'plantuml', code })
    lastIndex = m.index + m[0].length
  }

  const after = (content ?? '').slice(lastIndex)
  if (after.trim()) blocks.push({ type: 'text', text: after })

  if (!blocks.length && content?.trim()) blocks.push({ type: 'text', text: content })
  return blocks
}
