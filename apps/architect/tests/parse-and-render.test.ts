import { describe, it, expect } from 'vitest'
import { parseMessageBlocks } from '@/services/parse-message-blocks'
import { normalizeMermaid } from '@/composables/useDiagramRenderer'

describe('parseMessageBlocks（AI 消息分块解析）', () => {
  it('纯文本 → 单个 text 块', () => {
    const blocks = parseMessageBlocks('你好，世界')
    expect(blocks).toEqual([{ type: 'text', text: '你好，世界' }])
  })

  it('mermaid 围栏 → mermaid 块，前后文本保留', () => {
    const content = '前置说明\n```mermaid\nflowchart TD\nA-->B\n```\n后置说明'
    const blocks = parseMessageBlocks(content)
    expect(blocks.map((b) => b.type)).toEqual(['text', 'mermaid', 'text'])
    expect((blocks[1] as any).code).toContain('A-->B')
  })

  it('plantuml 围栏 → plantuml 块', () => {
    const blocks = parseMessageBlocks('```plantuml\n@startuml\nA->B\n@enduml\n```')
    expect(blocks.map((b) => b.type)).toEqual(['plantuml'])
  })

  it('diagram 围栏：合法 schema → diagram 块；非法 → 回退 text', () => {
    const schema = JSON.stringify({ type: 'flowchart', nodes: [], edges: [] })
    const blocks = parseMessageBlocks('```diagram\n' + schema + '\n```')
    expect(blocks.map((b) => b.type)).toEqual(['diagram'])

    const bad = parseMessageBlocks('```diagram\nnot json\n```')
    expect(bad.map((b) => b.type)).toEqual(['text'])
  })
})

describe('normalizeMermaid（渲染前清理，单一源委托 web-core）', () => {
  it('移除节点名与 [ 间空格', () => {
    expect(normalizeMermaid('A [标签] --> B')).toBe('A[标签] --> B')
  })

  it('移除 style 指令行', () => {
    expect(normalizeMermaid('flowchart TD\nA-->B\nstyle A fill:#f00')).not.toContain('style A')
  })

  it('移除 :::class 标记与 <br>', () => {
    const out = normalizeMermaid('A:::box --> B<br/>C')
    expect(out).not.toContain(':::')
    expect(out).not.toContain('<br')
  })

  it('移除行尾空白', () => {
    expect(normalizeMermaid('A-->B   ')).toBe('A-->B')
  })
})
