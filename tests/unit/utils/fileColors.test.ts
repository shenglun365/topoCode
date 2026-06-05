import { describe, it, expect } from 'vitest'
import { getFileColor, getLanguageLabel } from '@/utils/fileColors'

describe('getFileColor', () => {
  it('returns known color for ts', () => {
    expect(getFileColor('ts')).toBe('#3178c6')
  })

  it('returns known color for py', () => {
    expect(getFileColor('py')).toBe('#3572a5')
  })

  it('returns known color for vue', () => {
    expect(getFileColor('vue')).toBe('#42b883')
  })

  it('falls back for unknown extension', () => {
    expect(getFileColor('xyz')).toContain('--text-muted')
  })
})

describe('getLanguageLabel', () => {
  it('returns full name for common extensions', () => {
    expect(getLanguageLabel('ts')).toBe('TypeScript')
    expect(getLanguageLabel('py')).toBe('Python')
    expect(getLanguageLabel('vue')).toBe('Vue')
    expect(getLanguageLabel('go')).toBe('Go')
    expect(getLanguageLabel('rs')).toBe('Rust')
  })

  it('returns uppercase for unknown extension', () => {
    expect(getLanguageLabel('xyz')).toBe('XYZ')
  })
})
