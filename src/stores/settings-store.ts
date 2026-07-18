import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { SupportedLocale } from '@/i18n'
import type { ImportConfig } from '@/types/ipc'
import { ipc } from '@/services/ipc'
import { useStatusStore } from '@/stores/status'
import { useAnalysisStore } from '@/stores/analysis'
import i18n from '@/i18n'

const DEFAULT_RESOURCE_DIR = ''

export const useSettingsStore = defineStore('settings', () => {
  const activeTab = ref<'ai' | 'general' | 'theme' | 'templates' | 'about' | 'import' | 'agent'>('ai')
  const loading = ref(false)
  const locale = ref<SupportedLocale>('zh-CN')
  const fontSize = ref(14)
  const autoSaveInterval = ref(60)
  const projectPageSize = ref(50)

  // 资源项目目录
  const resourceProjectsDir = ref(localStorage.getItem('resourceProjectsDir') || DEFAULT_RESOURCE_DIR)
  const resourceDirHistory = ref<string[]>(JSON.parse(localStorage.getItem('resourceDirHistory') || '[]'))
  function setResourceProjectsDir(dir: string, autoMigrate = false) {
    resourceProjectsDir.value = dir
    localStorage.setItem('resourceProjectsDir', dir)
    // 更新历史（去重，保留最近 5 条）
    const hist = resourceDirHistory.value.filter(d => d !== dir)
    hist.unshift(dir)
    resourceDirHistory.value = hist.slice(0, 5)
    localStorage.setItem('resourceDirHistory', JSON.stringify(resourceDirHistory.value))
    // 通知后端
    if (window.api?.backend?.setResourceDir) {
      window.api.backend.setResourceDir(dir).catch((e: any) =>
        console.warn('[settings] setResourceDir failed:', e)
      )
    }
  }
  function restoreResourceDir(index: number) {
    const dir = resourceDirHistory.value[index]
    if (dir) setResourceProjectsDir(dir)
  }

  // 导入配置
  const importConfig = ref<ImportConfig>({
    ignoreMode: 'strict',
    customPatterns: [],
    extraIgnoreFiles: [],
  })
  const importConfigLoading = ref(false)

  try {
    const saved = localStorage.getItem('projectPageSize')
    if (saved) { const val = parseInt(saved, 10); if ([20, 50, 100].includes(val)) projectPageSize.value = val }
  } catch (e) { console.warn('Failed to load projectPageSize', e) }

  const backendStatus = ref<'connected' | 'disconnected'>('disconnected')
  const pythonMemoryLimit = ref(4096)
  const memoryLimitPending = ref(false)
  const zmqDealerPort = ref(5671)
  const zmqPubPort = ref(5680)
  const dealerPortStatus = ref<'available' | 'in-use' | null>(null)
  const pubPortStatus = ref<'available' | 'in-use' | null>(null)

  function setProjectPageSize(size: number) {
    if ([20, 50, 100].includes(size)) { projectPageSize.value = size; localStorage.setItem('projectPageSize', String(size)) }
  }

  function initLocale() {
    try {
      const saved = localStorage.getItem('locale') as SupportedLocale
      if (saved && (saved === 'zh-CN' || saved === 'en-US')) { locale.value = saved; i18n.global.locale.value = saved }
    } catch (e) { console.warn('Failed to load locale', e) }
  }

  function setLocale(newLocale: SupportedLocale) {
    locale.value = newLocale; i18n.global.locale.value = newLocale; localStorage.setItem('locale', newLocale)
  }

  function setActiveTab(tab: 'ai' | 'general' | 'theme' | 'templates' | 'about' | 'import' | 'agent') {
    activeTab.value = tab
  }

  const restartState = ref<'idle' | 'restarting' | 'success' | 'error'>('idle')
  const restartErrorMsg = ref('')

  const hasRunningTasks = computed(() => {
    const analysisStore = useAnalysisStore()
    return analysisStore.taskStats.running + analysisStore.taskStats.pending > 0
  })

  async function restartBackend() {
    if (hasRunningTasks.value) {
      restartState.value = 'error'
      const count = useAnalysisStore().taskStats.running + useAnalysisStore().taskStats.pending
      restartErrorMsg.value = i18n.global.t('common.restartBlockedTasks', { count })
      setTimeout(() => { if (restartState.value !== 'restarting') restartState.value = 'idle' }, 4000)
      return
    }
    restartState.value = 'restarting'
    restartErrorMsg.value = ''
    try {
      try {
        const st = useStatusStore()
        const cfg = { host: st.httpHost, port: st.httpPort }
        await Promise.all([
          ipc.backend.setHttpConfig(cfg),
          ipc.backend.saveHttpConfig(cfg).catch((e: any) => console.warn('Failed to persist http config', e)),
        ])
      } catch (e) { console.warn('Failed to set http config on restart', e) }
      const result = await ipc.backend.restart()
      const ok = result?.status === 'running'
      backendStatus.value = ok ? 'connected' : 'disconnected'
      if (ok) {
        memoryLimitPending.value = false
        restartState.value = 'success'
      } else {
        restartState.value = 'error'
        restartErrorMsg.value = result?.status || 'Unknown'
      }
    } catch (e: unknown) {
      backendStatus.value = 'disconnected'
      restartState.value = 'error'
      restartErrorMsg.value = (e as Error).message || String(e)
    }
    setTimeout(() => { if (restartState.value !== 'restarting') restartState.value = 'idle' }, 3000)
  }

  async function setPythonMemoryLimit(limit: number) {
    pythonMemoryLimit.value = limit; memoryLimitPending.value = true
    try { await (ipc.backend as any).setMemoryLimit(limit) } catch (e) { console.warn('Failed to set python memory limit', e) }
  }

  async function loadPythonMemoryLimit() {
    try {
      const limit = await (ipc.backend as any).getMemoryLimit()
      if (typeof limit === 'number' && limit > 0) pythonMemoryLimit.value = limit
      memoryLimitPending.value = false
    } catch (e) { console.warn('Failed to load python memory limit', e) }
  }

  async function testPort(type: 'dealer' | 'pub') {
    const port = type === 'dealer' ? zmqDealerPort.value : zmqPubPort.value
    try {
      const result = await ipc.backend.testPort(port)
      if (type === 'dealer') dealerPortStatus.value = result.available ? 'available' : 'in-use'
      else pubPortStatus.value = result.available ? 'available' : 'in-use'
    } catch {
      if (type === 'dealer') dealerPortStatus.value = null
      else pubPortStatus.value = null
    }
  }

  async function loadImportConfig() {
    importConfigLoading.value = true
    try {
      importConfig.value = await ipc.settings.getImportConfig()
    } catch (e) {
      console.warn('Failed to load import config', e)
    } finally {
      importConfigLoading.value = false
    }
  }

  async function saveImportConfig(params: { ignoreMode?: string; customPatterns?: string[]; extraIgnoreFiles?: string[] }) {
    importConfigLoading.value = true
    try {
      importConfig.value = await ipc.settings.setImportConfig(params)
    } catch (e) {
      console.warn('Failed to save import config', e)
      throw e
    } finally {
      importConfigLoading.value = false
    }
  }

  return {
    activeTab, loading, locale, fontSize, autoSaveInterval, projectPageSize,
    backendStatus, pythonMemoryLimit, memoryLimitPending,
    zmqDealerPort, zmqPubPort, dealerPortStatus, pubPortStatus,
    importConfig, importConfigLoading,
    resourceProjectsDir, resourceDirHistory,
    setProjectPageSize, initLocale, setLocale, setActiveTab,
    restartBackend, restartState, restartErrorMsg, hasRunningTasks,
    setPythonMemoryLimit, loadPythonMemoryLimit, testPort,
    loadImportConfig, saveImportConfig,
    setResourceProjectsDir, restoreResourceDir,
  }
})
