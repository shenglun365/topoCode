/**
 * 统一日志系统
 *
 * - 环境变量控制日志级别
 * - 路由到 console 和 debug store
 * - 支持分类和级别过滤
 *
 * 环境变量:
 *   VITE_LOG_LEVEL=DEBUG|INFO|WARN|ERROR
 */

// 日志级别枚举
export enum LogLevel {
  DEBUG = 0,
  INFO = 1,
  WARN = 2,
  ERROR = 3,
  NONE = 4,
}

// 日志条目接口
export interface LogEntry {
  time: string
  level: LogLevel
  source: string
  message: string
  data?: unknown
}

// 从环境变量读取日志级别
function getEnvLogLevel(): LogLevel {
  const envLevel = import.meta.env.VITE_LOG_LEVEL
  if (envLevel) {
    const upper = envLevel.toUpperCase()
    if (upper in LogLevel) {
      return LogLevel[upper as keyof typeof LogLevel]
    }
  }
  // 开发环境默认 DEBUG，生产环境默认 WARN
  return import.meta.env.DEV ? LogLevel.DEBUG : LogLevel.WARN
}

// 全局日志级别
let currentLevel: LogLevel = getEnvLogLevel()

// 日志处理器列表
type LogHandler = (entry: LogEntry) => void
const handlers: LogHandler[] = []

// 设置日志级别
export function setLogLevel(level: LogLevel): void {
  currentLevel = level
}

// 获取当前日志级别
export function getLogLevel(): LogLevel {
  return currentLevel
}

// 添加日志处理器
export function addLogHandler(handler: LogHandler): void {
  handlers.push(handler)
}

// 移除日志处理器
export function removeLogHandler(handler: LogHandler): void {
  const idx = handlers.indexOf(handler)
  if (idx >= 0) {
    handlers.splice(idx, 1)
  }
}

// 格式化时间
function formatTime(): string {
  return new Date().toISOString()
}

// 内部日志输出
function emit(level: LogLevel, source: string, message: string, data?: unknown): void {
  if (level < currentLevel) {
    return
  }

  const entry: LogEntry = {
    time: formatTime(),
    level,
    source,
    message,
    data,
  }

  // 路由到 console
  switch (level) {
    case LogLevel.DEBUG:
      console.debug(`[${source}] ${message}`, data ?? '')
      break
    case LogLevel.INFO:
      console.info(`[${source}] ${message}`, data ?? '')
      break
    case LogLevel.WARN:
      console.warn(`[${source}] ${message}`, data ?? '')
      break
    case LogLevel.ERROR:
      console.error(`[${source}] ${message}`, data ?? '')
      break
  }

  // 路由到自定义处理器
  for (const handler of handlers) {
    try {
      handler(entry)
    }
    catch (e) {
      console.error('[logger] handler error:', e)
    }
  }
}

// Logger 接口
export interface Logger {
  debug(message: string, data?: unknown): void
  info(message: string, data?: unknown): void
  warn(message: string, data?: unknown): void
  error(message: string, data?: unknown): void
}

// 创建分类日志器
export function createLogger(source: string): Logger {
  return {
    debug: (message: string, data?: unknown) => emit(LogLevel.DEBUG, source, message, data),
    info: (message: string, data?: unknown) => emit(LogLevel.INFO, source, message, data),
    warn: (message: string, data?: unknown) => emit(LogLevel.WARN, source, message, data),
    error: (message: string, data?: unknown) => emit(LogLevel.ERROR, source, message, data),
  }
}

// 默认日志器
export const logger = createLogger('app')
