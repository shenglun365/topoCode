/**
 * 语义文档 MD 头部剥离 — 与后端 component_name_disambiguation.strip_doc_header 对齐。
 *
 * SubDocViewer 在渲染时合成元数据头部（社区/ID/父组件/结构分析块），
 * 编辑保存时必须剥离，避免头部被固化进 summary 反复累积。
 * 仅精确匹配合成模式，用户正文不受影响。
 */

const RE_HEADING = /^\s*#\s*(?:社区|Community)\s*[:：].*$/
const RE_ID_LINE = /^\s*\*\*ID\*\*\s*[:：].*$/
const RE_PARENT_HEADING = /^\s*##\s*(?:父组件|Parent Component)\s*$/
const RE_STRUCT_HEADING = /^\s*##\s*(?:结构分析|Structural Analysis).*$/
const RE_STRUCT_GROUP = /^\s*###\s*(?:依赖关系|调用关系|Dependency|Call Relationship).*$/
const RE_COMM_LINK = /^\s*-\s*\[[^\]]*\]\(##community:[^)]*\)\s*$/
const RE_HR = /^\s*-{3,}\s*$/

function isSynthesized(line: string): boolean {
  return (
    RE_HEADING.test(line) || RE_ID_LINE.test(line) ||
    RE_PARENT_HEADING.test(line) || RE_STRUCT_HEADING.test(line) ||
    RE_STRUCT_GROUP.test(line) || RE_COMM_LINK.test(line) || RE_HR.test(line)
  )
}

function consumeBlankHr(lines: string[], i: number): number {
  while (i < lines.length) {
    const s = lines[i].trim()
    if (!s || RE_HR.test(lines[i])) i += 1
    else break
  }
  return i
}

export function stripDocHeader(text: string): string {
  if (!text) return text || ''
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const out: string[] = []
  let i = 0
  const n = lines.length
  while (i < n) {
    const line = lines[i]
    if (RE_HEADING.test(line) || RE_ID_LINE.test(line)) { i += 1; continue }
    if (RE_PARENT_HEADING.test(line)) {
      i += 1
      // 父组件块：标题后紧跟一行内容（name — summary 片段）
      while (i < n && !lines[i].trim()) i += 1
      if (i < n && lines[i].trim() && !isSynthesized(lines[i])) i += 1
      i = consumeBlankHr(lines, i)
      continue
    }
    if (RE_STRUCT_HEADING.test(line)) {
      i += 1
      while (i < n) {
        const s = lines[i].trim()
        if (!s || RE_HR.test(lines[i]) || isSynthesized(lines[i])) i += 1
        else break
      }
      i = consumeBlankHr(lines, i)
      continue
    }
    if (RE_HR.test(line)) {
      // 分隔线仅在其后紧跟合成块时丢弃（属于合成块的组成分隔线）
      const j = consumeBlankHr(lines, i + 1)
      if (j < n && isSynthesized(lines[j]) && !RE_HR.test(lines[j])) { i = j; continue }
      out.push(line)
      i += 1
      continue
    }
    out.push(line)
    i += 1
  }
  let cleaned = out.join('\n').replace(/\n{3,}/g, '\n\n')
  // 去除收尾后仍残留的首部空行/分隔线
  while (true) {
    const trimmed = cleaned.replace(/^\s+/, '')
    if (trimmed.startsWith('---')) cleaned = trimmed.slice(3).replace(/^\n+/, '').replace(/^\s+/, '')
    else break
  }
  return cleaned.trim()
}
