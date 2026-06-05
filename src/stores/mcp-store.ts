import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

export type MCPState = 'stopped' | 'starting' | 'running' | 'error'

export interface MCPStatus {
  state: MCPState
  pid?: number
  port?: number
  error?: string
}

export const useMCPStore = defineStore('mcp', () => {
  const state = ref<MCPState>('stopped')
  const pid = ref<number | undefined>()
  const port = ref<number | undefined>()
  const error = ref<string | undefined>()

  const isRunning = computed(() => state.value === 'running')
  const statusText = computed(() => {
    const map: Record<MCPState, string> = {
      stopped: '已停止',
      starting: '启动中',
      running: '运行中',
      error: '异常',
    }
    return map[state.value] || state.value
  })

  function setStatus(s: MCPStatus) {
    state.value = s.state
    pid.value = s.pid
    port.value = s.port
    error.value = s.error
  }

  function reset() {
    state.value = 'stopped'
    pid.value = undefined
    port.value = undefined
    error.value = undefined
  }

  return {
    state, pid, port, error,
    isRunning, statusText,
    setStatus, reset,
  }
})
