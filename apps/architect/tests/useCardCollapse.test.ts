import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useCardCollapse } from '@/composables/useCardCollapse'

describe('useCardCollapse(信息卡收起/展开统一状态源 + localStorage 持久化)', () => {
  beforeEach(() => {
    localStorage.clear()
    useCardCollapse()._resetForTest()
  })

  it('无覆盖时回落 auto 规则(默认展开/默认收起两态)', () => {
    const c = useCardCollapse()
    expect(c.isCollapsed('msg:a')).toBe(false)
    expect(c.isCollapsed('msg:a', true)).toBe(true)
  })

  it('toggle 写覆盖并优先于 auto', () => {
    const c = useCardCollapse()
    c.toggle('msg:a')                      // 默认展开 → 用户收起
    expect(c.isCollapsed('msg:a')).toBe(true)
    c.toggle('task:t', true)               // 默认收起卡 → 用户展开(覆盖 false)
    expect(c.isCollapsed('task:t', true)).toBe(false)
  })

  it('覆盖与 auto 一致时清除覆盖项(存储只留「与默认不同」)', () => {
    const c = useCardCollapse()
    c.toggle('msg:a', true)                // 默认收起, 切到展开=false 与 auto 相异 → 保留
    expect(JSON.parse(localStorage.getItem('topo:card-collapsed') || '{}')['msg:a']).toBe(false)
    c.toggle('msg:a', true)                // 切回收起 = 与 auto 一致 → 清除
    expect(JSON.parse(localStorage.getItem('topo:card-collapsed') || '{}')['msg:a']).toBeUndefined()
  })

  it('持久化: 模拟刷新(重载模块)后读回覆盖', async () => {
    const c = useCardCollapse()
    c.toggle('task:t1')                    // 收起覆盖(true 落存储)
    c.toggle('msg:b', true)                // 默认收起 → 展开覆盖(false 落存储)
    vi.resetModules()
    const { useCardCollapse: fresh } = await import('@/composables/useCardCollapse')
    expect(fresh().isCollapsed('task:t1')).toBe(true)
    expect(fresh().isCollapsed('msg:b', true)).toBe(false)  // 覆盖优先于 auto
    expect(fresh().isCollapsed('msg:never', true)).toBe(true) // 无覆盖回落 auto
  })

  it('容量修剪: 超上限丢弃最旧覆盖', () => {
    const c = useCardCollapse()
    for (let i = 0; i < 505; i++) c.toggle(`msg:k${i}`)
    const raw = JSON.parse(localStorage.getItem('topo:card-collapsed') || '{}')
    expect(Object.keys(raw).length).toBeLessThanOrEqual(500)
    expect(raw['msg:k0']).toBeUndefined()
    expect(raw['msg:k504']).toBe(true)
  })
})
