import { describe, expect, it } from 'vitest'
import { diffLines, diffStat } from '@/utils/diff-lines'

describe('diffLines 行级比对（需求草稿批E）', () => {
  it('相同文本全上下文行', () => {
    const out = diffLines('a\nb\nc', 'a\nb\nc')
    expect(out.map((l) => l.type)).toEqual(['ctx', 'ctx', 'ctx'])
    expect(diffStat(out)).toEqual({ added: 0, removed: 0 })
  })

  it('增删改行标记与行号', () => {
    const out = diffLines('保持\n旧A\n旧B\n尾', '保持\n新A\n尾')
    const marks = out.map((l) => `${l.type}:${l.text}`).join('|')
    // 旧A/旧B 被删，新A 新增；尾保持
    expect(marks).toBe('ctx:保持|del:旧A|del:旧B|add:新A|ctx:尾')
    expect(diffStat(out)).toEqual({ added: 1, removed: 2 })
    // 行号连续性：ctx 行双号推进，add/del 单号
    const ctxTail = out[out.length - 1]
    expect(ctxTail.oldNo).toBe(4)   // 旧文本第 4 行「尾」
    expect(ctxTail.newNo).toBe(3)   // 新文本第 3 行「尾」
  })

  it('空文本与纯新增', () => {
    expect(diffLines('', 'x\ny').filter((l) => l.type === 'add')).toHaveLength(2)
    expect(diffLines('x\ny', '').filter((l) => l.type === 'del')).toHaveLength(2)
    // '' vs '' 单上下文行（split 语义）
    expect(diffLines('', '')).toEqual([{ type: 'ctx', text: '', oldNo: 1, newNo: 1 }])
  })
})
