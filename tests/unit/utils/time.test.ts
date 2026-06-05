import { describe, it, expect } from 'vitest'
import { formatRelativeTime, formatDateTime, formatFileSize } from '@/utils/time'

describe('formatRelativeTime', () => {
  it('returns empty string for null/undefined', () => {
    expect(formatRelativeTime(null)).toBe('')
    expect(formatRelativeTime(undefined)).toBe('')
  })

  it('returns "刚刚" for less than 1 minute', () => {
    const now = new Date().toISOString()
    expect(formatRelativeTime(now)).toBe('刚刚')
  })

  it('returns minutes ago for < 60 min', () => {
    const past = new Date(Date.now() - 5 * 60000).toISOString()
    expect(formatRelativeTime(past)).toBe('5分钟前')
  })

  it('returns hours ago for < 24h', () => {
    const past = new Date(Date.now() - 3 * 3600000).toISOString()
    expect(formatRelativeTime(past)).toBe('3小时前')
  })

  it('returns days ago for < 30d', () => {
    const past = new Date(Date.now() - 7 * 86400000).toISOString()
    expect(formatRelativeTime(past)).toBe('7天前')
  })

  it('returns months ago for >= 30d', () => {
    const past = new Date(Date.now() - 60 * 86400000).toISOString()
    expect(formatRelativeTime(past)).toBe('2个月前')
  })
})

describe('formatDateTime', () => {
  it('returns empty string for null/undefined', () => {
    expect(formatDateTime(null)).toBe('')
    expect(formatDateTime(undefined)).toBe('')
  })

  it('formats date string to YYYY-MM-DD HH:mm', () => {
    const result = formatDateTime('2026-06-01T14:30:00')
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/)
  })
})

describe('formatFileSize', () => {
  it('formats bytes', () => {
    expect(formatFileSize(500)).toBe('500 B')
  })

  it('formats KB', () => {
    expect(formatFileSize(2048)).toBe('2.0 KB')
  })

  it('formats MB', () => {
    expect(formatFileSize(3 * 1024 * 1024)).toBe('3.0 MB')
  })
})
