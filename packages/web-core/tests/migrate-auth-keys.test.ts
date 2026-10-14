import { describe, it, expect, beforeEach } from 'vitest'
import { migrateLegacyAuthKeys } from '../src/services/token'

describe('migrateLegacyAuthKeys (MS3-U3)', () => {
  beforeEach(() => localStorage.clear())

  it('旧键 → 新键迁移并清理旧键', () => {
    localStorage.setItem('topocode_token', 'tok-1')
    localStorage.setItem('topocode_user', '{"id":"u1"}')
    migrateLegacyAuthKeys()
    expect(localStorage.getItem('topocode:token')).toBe('tok-1')
    expect(localStorage.getItem('topocode:user')).toBe('{"id":"u1"}')
    expect(localStorage.getItem('topocode_token')).toBeNull()
    expect(localStorage.getItem('topocode_user')).toBeNull()
  })

  it('新键已有值时不覆盖, 仅清理旧键', () => {
    localStorage.setItem('topocode_token', 'legacy')
    localStorage.setItem('topocode:token', 'fresh')
    migrateLegacyAuthKeys()
    expect(localStorage.getItem('topocode:token')).toBe('fresh')
    expect(localStorage.getItem('topocode_token')).toBeNull()
  })

  it('无旧键时零操作', () => {
    migrateLegacyAuthKeys()
    expect(localStorage.getItem('topocode:token')).toBeNull()
  })
})
