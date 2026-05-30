/** Settings Store - 设置配置管理 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ModelConfigItem, AgentConfigItem, SkillConfigItem, UsageStatItem } from '@/types/ipc'
import type { SupportedLocale } from '@/i18n'
import { ipc } from '@/services/ipc'
import { useStatusStore } from '@/stores/status'
import i18n from '@/i18n'

export const useSettingsStore = defineStore('settings', () => {
  // State
  const models = ref<ModelConfigItem[]>([])
  const agents = ref<AgentConfigItem[]>([])
  const skills = ref<SkillConfigItem[]>([])
  const bindings = ref<Record<string, string>>({})
  const activeTab = ref<'ai' | 'general' | 'theme' | 'templates' | 'about'>('ai')
  const loading = ref(false)
  const locale = ref<SupportedLocale>('zh-CN')
  const usageStats = ref<UsageStatItem[]>([])
  const usageStatsLoading = ref(false)

  // General settings
  const fontSize = ref(14)
  const autoSaveInterval = ref(60)
  const projectPageSize = ref(50)

  // 从 localStorage 恢复每页数量
  try {
    const saved = localStorage.getItem('projectPageSize')
    if (saved) {
      const val = parseInt(saved, 10)
      if ([20, 50, 100].includes(val)) projectPageSize.value = val
    }
  } catch {}

  function setProjectPageSize(size: number) {
    if ([20, 50, 100].includes(size)) {
      projectPageSize.value = size
      localStorage.setItem('projectPageSize', String(size))
    }
  }


  const backendStatus = ref<'connected' | 'disconnected'>('disconnected')
  const pythonMemoryLimit = ref(4096)
  const memoryLimitPending = ref(false)

  // ZMQ 端口设置
  const zmqDealerPort = ref(5671)
  const zmqPubPort = ref(5680)
  const dealerPortStatus = ref<'available' | 'in-use' | null>(null)
  const pubPortStatus = ref<'available' | 'in-use' | null>(null)

  // Init locale
  function initLocale() {
    try {
      const saved = localStorage.getItem('locale') as SupportedLocale
      if (saved && (saved === 'zh-CN' || saved === 'en-US')) {
        locale.value = saved
        i18n.global.locale.value = saved
      }
    } catch {}
  }

  // Switch locale
  function setLocale(newLocale: SupportedLocale) {
    locale.value = newLocale
    i18n.global.locale.value = newLocale
    localStorage.setItem('locale', newLocale)
  }

  // Actions
  async function loadSettings() {
    loading.value = true
    try {
      const rawModels = await ipc.settings.getModels()
      models.value = rawModels.map(normalizeModel)
      agents.value = await ipc.settings.getAgents()
      skills.value = await ipc.settings.getSkills()
      bindings.value = await ipc.settings.getBindings()
    } finally {
      loading.value = false
    }
  }

  async function addModel(params: {
    name: string
    provider: string
    model: string
    url: string
    type: string
    temperature?: number
    maxTokens?: number
    isDefault?: boolean
  }) {
    const raw = await ipc.settings.addModel(params)
    const model = normalizeModel(raw)
    models.value.push(model)
    return model
  }

  function normalizeModel(raw: any): ModelConfigItem {
    return {
      id: raw.id,
      name: raw.name,
      provider: raw.provider,
      model: raw.model,
      url: raw.url,
      type: raw.type,
      status: raw.status,
      isDefault: raw.isDefault ?? Boolean(raw.is_default ?? false),
      temperature: raw.temperature,
      maxTokens: raw.maxTokens ?? raw.max_tokens,
      apiKey: raw.apiKey || raw.api_key || '',
      latency: raw.latency,
      maxRequestsPerDay: raw.maxRequestsPerDay ?? raw.max_requests_per_day ?? 0,
      maxTokensPerDay: raw.maxTokensPerDay ?? raw.max_tokens_per_day ?? 0,
    }
  }

  async function updateModel(params: {
    id: string
    name?: string
    provider?: string
    model?: string
    url?: string
    temperature?: number
    maxTokens?: number
    isDefault?: boolean
    apiKey?: string
  }) {
    const raw = await ipc.settings.updateModel(params)
    const model = normalizeModel(raw)
    const idx = models.value.findIndex(m => m.id === params.id)
    if (idx >= 0) models.value[idx] = model
    // 如果设为默认，清除其他模型的默认标记
    if (params.isDefault) {
      models.value.forEach(m => {
        if (m.id !== params.id) m.isDefault = false
      })
    }
    return model
  }

  async function removeModel(id: string) {
    await ipc.settings.removeModel(id)
    const idx = models.value.findIndex(m => m.id === id)
    if (idx >= 0) models.value.splice(idx, 1)
  }

  async function waitBackendReady(maxWait = 8000): Promise<boolean> {
    const start = Date.now()
    while (Date.now() - start < maxWait) {
      try {
        const st = await ipc.backend.getStatus()
        if (st?.status === 'running') return true
      } catch {}
      await new Promise(r => setTimeout(r, 500))
    }
    return false
  }

  async function testModel(id: string) {
    // 等待后端就绪后再测试，避免启动过程中误判
    await waitBackendReady()
    const result = await ipc.settings.testModel(id)
    if (result && result.status) {
      const idx = models.value.findIndex(m => m.id === id)
      if (idx >= 0) {
        models.value[idx] = { ...models.value[idx], status: result.status, latency: result.latency }
      }
    }
    return result
  }

  async function addAgent(params: { name: string; path: string; args: string }) {
    const agent = await ipc.settings.addAgent(params)
    agents.value.push(agent)
    return agent
  }

  async function updateAgent(params: { id: string; path?: string; args?: string }) {
    const agent = await ipc.settings.updateAgent(params)
    const idx = agents.value.findIndex(a => a.id === params.id)
    if (idx >= 0) agents.value[idx] = agent
    return agent
  }

  async function removeAgent(id: string) {
    await ipc.settings.removeAgent(id)
    const idx = agents.value.findIndex(a => a.id === id)
    if (idx >= 0) agents.value.splice(idx, 1)
  }

  async function detectAgent(id: string) {
    const result = await ipc.settings.detectAgent(id)
    const agent = agents.value.find(a => a.id === id)
    if (agent) {
      agent.status = result.status as any
      agent.version = result.version
    }
    return result
  }

  async function updateSkill(params: { id: string; enabled: boolean }) {
    const skill = await ipc.settings.updateSkill(params)
    const idx = skills.value.findIndex(s => s.id === params.id)
    if (idx >= 0) skills.value[idx] = skill
    return skill
  }

  async function updateBindings(params: { bindings: Record<string, string> }) {
    bindings.value = await ipc.settings.updateBindings(params)
    return bindings.value
  }

  function setActiveTab(tab: 'models' | 'agents' | 'skills' | 'general' | 'about') {
    activeTab.value = tab
  }

  async function setPythonMemoryLimit(limit: number) {
    pythonMemoryLimit.value = limit
    memoryLimitPending.value = true
    try {
      await window.api.backend.setMemoryLimit(limit)
    } catch (_) {}
  }

  async function loadPythonMemoryLimit() {
    try {
      const limit = await window.api.backend.getMemoryLimit()
      if (typeof limit === 'number' && limit > 0) pythonMemoryLimit.value = limit
      memoryLimitPending.value = false
    } catch (_) {}
  }

  // Restart backend
  async function restartBackend() {
    try {
      // 保存 HTTP 配置后重启
      try {
        const st = useStatusStore()
        await ipc.backend.setHttpConfig?.({ host: st.httpHost, port: st.httpPort })
      } catch {}
      const result = await ipc.backend.restart()
      const ok = result?.status === 'running'
      backendStatus.value = ok ? 'connected' : 'disconnected'
      if (ok) {
        memoryLimitPending.value = false
        useStatusStore().setBackendStatus(result)
      }
    } catch {
      backendStatus.value = 'disconnected'
    }
  }

  // 测试端口可用性
  async function testPort(type: 'dealer' | 'pub') {
    const port = type === 'dealer' ? zmqDealerPort.value : zmqPubPort.value
    try {
      // 通过后端测试端口
      const result = await ipc.backend.testPort(port)
      if (type === 'dealer') {
        dealerPortStatus.value = result.available ? 'available' : 'in-use'
      } else {
        pubPortStatus.value = result.available ? 'available' : 'in-use'
      }
    } catch {
      // 如果后端不可用，标记为未知
      if (type === 'dealer') {
        dealerPortStatus.value = null
      } else {
        pubPortStatus.value = null
      }
    }
  }

    // ==================== 模型用量统计 ====================

    async function loadUsageStats(modelId?: string, startDate?: string, endDate?: string) {
      usageStatsLoading.value = true
      try {
        usageStats.value = await ipc.model.getUsageStats(modelId, startDate, endDate)
      } finally {
        usageStatsLoading.value = false
      }
    }

    async function deleteUsageStat(id: number) {
      await ipc.model.deleteUsageStats(id)
      usageStats.value = usageStats.value.filter(s => s.id !== id)
    }

    async function deleteUsageStatsBatch(ids: number[]) {
      await ipc.model.deleteUsageStatsBatch(ids)
      usageStats.value = usageStats.value.filter(s => !ids.includes(s.id))
    }

    async function deleteUsageStatsByCondition(params: { modelId?: string; startDate?: string; endDate?: string }) {
      await ipc.model.deleteUsageStatsByCondition(params)
      await loadUsageStats()
    }

  return {
    models,
    agents,
    skills,
    bindings,
    activeTab,
    loading,
    locale,
    zmqDealerPort,
    zmqPubPort,
    dealerPortStatus,
    pubPortStatus,
    testPort,
    fontSize,
    autoSaveInterval,
    projectPageSize,
    setProjectPageSize,

    backendStatus,
    initLocale,
    setLocale,
    loadSettings,
    addModel,
    updateModel,
    removeModel,
    testModel,
    addAgent,
    updateAgent,
    removeAgent,
    detectAgent,
    updateSkill,
    updateBindings,
    setActiveTab,
    restartBackend,
    pythonMemoryLimit,
    memoryLimitPending,
    setPythonMemoryLimit,
    loadPythonMemoryLimit,
    usageStats,
    usageStatsLoading,
    loadUsageStats,
    deleteUsageStat,
    deleteUsageStatsBatch,
    deleteUsageStatsByCondition,
  }
})
