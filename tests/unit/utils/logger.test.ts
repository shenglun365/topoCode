import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  LogLevel,
  setLogLevel,
  getLogLevel,
  createLogger,
  addLogHandler,
  removeLogHandler,
} from '@/utils/logger'

describe('logger', () => {
  beforeEach(() => {
    setLogLevel(LogLevel.DEBUG)
  })

  it('getLogLevel returns current level', () => {
    setLogLevel(LogLevel.INFO)
    expect(getLogLevel()).toBe(LogLevel.INFO)
  })

  it('createLogger returns logger with source', () => {
    const log = createLogger('test')
    expect(log).toBeDefined()
    expect(typeof log.debug).toBe('function')
    expect(typeof log.info).toBe('function')
    expect(typeof log.warn).toBe('function')
    expect(typeof log.error).toBe('function')
  })

  it('addLogHandler receives log entries', () => {
    const handler = vi.fn()
    addLogHandler(handler)
    const log = createLogger('test')
    log.info('hello')
    expect(handler).toHaveBeenCalledTimes(1)
    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({ level: LogLevel.INFO, source: 'test', message: 'hello' })
    )
  })

  it('removeLogHandler stops receiving entries', () => {
    const handler = vi.fn()
    addLogHandler(handler)
    removeLogHandler(handler)
    const log = createLogger('test')
    log.info('hello')
    expect(handler).not.toHaveBeenCalled()
  })

  it('does not emit below current level', () => {
    const handler = vi.fn()
    addLogHandler(handler)
    setLogLevel(LogLevel.WARN)
    const log = createLogger('test')
    log.debug('should not appear')
    log.info('should not appear')
    expect(handler).not.toHaveBeenCalled()
  })

  it('emits at or above current level', () => {
    const handler = vi.fn()
    addLogHandler(handler)
    setLogLevel(LogLevel.WARN)
    const log = createLogger('test')
    log.warn('warning')
    log.error('error')
    expect(handler).toHaveBeenCalledTimes(2)
  })
})
