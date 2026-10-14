import { describe, it, expect } from 'vitest'

describe('project smoke test', () => {
  it('vitest is configured with jsdom', () => {
    expect(typeof window).toBe('object')
    expect(typeof document).toBe('object')
  })

  it('basic math works', () => {
    expect(1 + 1).toBe(2)
  })

  it('ES module imports resolve @ alias and @topo/web-core package', async () => {
    const { flattenTree } = await import('@/utils/flattenTree')
    expect(typeof flattenTree).toBe('function')
    const { commonZh } = await import('@topo/web-core/i18n/common')
    expect(commonZh.loading.length).toBeGreaterThan(0)
  })
})
