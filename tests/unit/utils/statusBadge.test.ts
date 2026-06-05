import { describe, it, expect } from 'vitest'
import {
  getTaskStatusLabel,
  getTaskStatusColor,
  getBackendStatusLabel,
  getBackendStatusColor,
} from '@/utils/statusBadge'

describe('getTaskStatusLabel', () => {
  it('returns Chinese label for known statuses', () => {
    expect(getTaskStatusLabel('done')).toBe('完成')
    expect(getTaskStatusLabel('running')).toBe('运行中')
    expect(getTaskStatusLabel('pending')).toBe('等待中')
    expect(getTaskStatusLabel('modified')).toBe('已修改')
    expect(getTaskStatusLabel('error')).toBe('失败')
    expect(getTaskStatusLabel('cancelled')).toBe('已取消')
  })

  it('falls back to raw status for unknown', () => {
    expect(getTaskStatusLabel('unknown' as any)).toBe('unknown')
  })
})

describe('getTaskStatusColor', () => {
  it('returns CSS variable for known statuses', () => {
    expect(getTaskStatusColor('done')).toContain('--success')
    expect(getTaskStatusColor('running')).toContain('--accent')
    expect(getTaskStatusColor('error')).toContain('--error')
  })

  it('falls back for unknown status', () => {
    expect(getTaskStatusColor('unknown' as any)).toContain('--text-muted')
  })
})

describe('getBackendStatusLabel', () => {
  it('returns Chinese label for backend statuses', () => {
    expect(getBackendStatusLabel('running')).toBe('运行中')
    expect(getBackendStatusLabel('stopped')).toBe('已停止')
    expect(getBackendStatusLabel('error')).toBe('异常')
  })
})

describe('getBackendStatusColor', () => {
  it('returns CSS variable for known statuses', () => {
    expect(getBackendStatusColor('running')).toContain('--success')
    expect(getBackendStatusColor('stopped')).toContain('--text-muted')
    expect(getBackendStatusColor('error')).toContain('--error')
  })
})
