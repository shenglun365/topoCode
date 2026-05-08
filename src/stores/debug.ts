/** Debug Event Log Store */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface DebugLog {
  time: string
  source: string
  message: string
}

export const useDebugStore = defineStore('debug', () => {
  const logs = ref<DebugLog[]>([])
  const maxLogs = 50

  function log(source: string, message: string) {
    const now = new Date()
    const time = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}.${now.getMilliseconds().toString().padStart(3, '0')}`
    logs.value.unshift({ time, source, message })
    // 限制日志数量
    if (logs.value.length > maxLogs) {
      logs.value = logs.value.slice(0, maxLogs)
    }
  }

  function clear() {
    logs.value = []
  }

  return {
    logs,
    log,
    clear,
  }
})
