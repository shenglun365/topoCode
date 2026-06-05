import { describe, it, expect } from 'vitest'

describe('project smoke test', () => {
  it('vitest is configured with jsdom', () => {
    expect(typeof window).toBe('object')
    expect(typeof document).toBe('object')
  })

  it('basic math works', () => {
    expect(1 + 1).toBe(2)
  })

  it('ES module imports resolve @ alias', async () => {
    const { formatFileSize } = await import('@/utils/time')
    expect(formatFileSize(1024)).toBe('1.0 KB')
  })
})
