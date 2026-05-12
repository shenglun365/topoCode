/** Debug Event Log Store — 统一日志管理 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { LogLevel, type LogEntry, addLogHandler, createLogger } from '@/utils/logger'

// 扩展 DebugLog 接口，支持级别和数据
export interface DebugLog extends LogEntry {
  // LogEntry 已有 time, level, source, message, data
}

export const useDebugStore = defineStore('debug', () => {
  const logs = ref<DebugLog[]>([])
  const maxLogs = 200
  const filterLevel = ref<LogLevel>(LogLevel.DEBUG)

  // 日志级别名称映射
  const levelNames: Record<LogLevel, string> = {
    [LogLevel.DEBUG]: 'DEBUG',
    [LogLevel.INFO]: 'INFO',
    [LogLevel.WARN]: 'WARN',
    [LogLevel.ERROR]: 'ERROR',
    [LogLevel.NONE]: 'NONE',
  }

  // 注册到统一日志系统
  addLogHandler((entry: LogEntry) => {
    if (entry.level >= filterLevel.value) {
      logs.value.unshift(entry as DebugLog)
      if (logs.value.length > maxLogs) {
        logs.value = logs.value.slice(0, maxLogs)
      }
    }
  })

  // 向后兼容的 log 方法
  function log(source: string, message: string) {
    const now = new Date()
    const time = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}.${now.getMilliseconds().toString().padStart(3, '0')}`
    logs.value.unshift({ time, source, message, level: LogLevel.INFO })
    if (logs.value.length > maxLogs) {
      logs.value = logs.value.slice(0, maxLogs)
    }
  }

  function clear() {
    logs.value = []
  }

  // 导出日志为文本
  function exportLogs(): string {
    return logs.value.map(l =>
      `[${l.time}] [${levelNames[l.level]}] [${l.source}] ${l.message}${l.data ? ` | ${JSON.stringify(l.data)}` : ''}`
    ).join('\n')
  }

  // 设置过滤级别
  function setFilterLevel(level: LogLevel) {
    filterLevel.value = level
  }

  // 创建分类日志器
  function getLogger(source: string) {
    return createLogger(source)
  }

  return {
    logs,
    log,
    clear,
    exportLogs,
    filterLevel,
    setFilterLevel,
    getLogger,
    levelNames,
  }
})
