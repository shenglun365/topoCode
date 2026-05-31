import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import type { BackendStatus, StatusBarState } from '@/types'

export const useStatusStore = defineStore('status', () => {
  // State
  const backend = reactive<BackendStatus>({
    status: 'stopped',
  })
  const astStatus = ref('')
  const gitBranch = ref('')
  const aiModel = ref('')
  const encoding = ref('UTF-8')
  const zoom = ref(100)
  const httpPort = ref(3456)
  const httpHost = ref('127.0.0.1')

  // Getters
  const statusBar = reactive<StatusBarState>({
    get backend() { return backend },
    get astStatus() { return astStatus.value },
    get gitBranch() { return gitBranch.value },
    get aiModel() { return aiModel.value },
    get encoding() { return encoding.value },
    get zoom() { return zoom.value },
  })

  // Actions
  function setBackendStatus(status: BackendStatus, skipHttpConfig = false) {
    backend.status = status.status
    backend.pid = status.pid
    backend.port = status.port
    backend.error = status.error
    if (!skipHttpConfig) {
      if (status.httpPort) httpPort.value = status.httpPort
      if (status.httpHost) httpHost.value = status.httpHost
    }
  }

  function setAstStatus(status: string) {
    astStatus.value = status
  }

  function setGitBranch(branch: string) {
    gitBranch.value = branch
  }

  function setAiModel(model: string) {
    aiModel.value = model
  }

  function setZoom(z: number) {
    zoom.value = z
  }

  function zoomIn() {
    zoom.value = Math.min(200, zoom.value + 10)
  }

  function zoomOut() {
    zoom.value = Math.max(50, zoom.value - 10)
  }

  return {
    backend,
    astStatus,
    gitBranch,
    aiModel,
    encoding,
    zoom,
    statusBar,
    setBackendStatus,
    setAstStatus,
    setGitBranch,
    setAiModel,
    setZoom,
    zoomIn,
    zoomOut,
    httpPort,
    httpHost,
  }
})
