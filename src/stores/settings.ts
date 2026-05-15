/** Settings Store - 设置配置管理 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ModelConfigItem, AgentConfigItem, SkillConfigItem } from '@/types/ipc'
import type { SupportedLocale } from '@/i18n'
import { ipc } from '@/services/ipc'
import i18n from '@/i18n'

export const useSettingsStore = defineStore('settings', () => {
  // State
  const models = ref<ModelConfigItem[]>([])
  const agents = ref<AgentConfigItem[]>([])
  const skills = ref<SkillConfigItem[]>([])
  const bindings = ref<Record<string, string>>({})
  const activeTab = ref<'ai' | 'agents' | 'skills' | 'general' | 'theme' | 'plugins' | 'about'>('ai')
  const loading = ref(false)
  const locale = ref<SupportedLocale>('zh-CN')

  // General settings
  const fontSize = ref(14)
  const autoSaveInterval = ref(60)
  const kbHttpServer = ref(false)
  const kbHttpPort = ref(3000)
  const backendStatus = ref<'connected' | 'disconnected'>('disconnected')

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
      models.value = await ipc.settings.getModels()
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
  }) {
    const model = await ipc.settings.addModel(params)
    models.value.push(model)
    return model
  }

  async function updateModel(params: {
    id: string
    name?: string
    temperature?: number
    maxTokens?: number
    isDefault?: boolean
  }) {
    const model = await ipc.settings.updateModel(params)
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

  async function testModel(id: string) {
    return await ipc.settings.testModel(id)
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

  // Restart backend
  function restartBackend() {
    // TODO: implement backend restart via IPC
    backendStatus.value = 'disconnected'
    setTimeout(() => {
      backendStatus.value = 'connected'
    }, 2000)
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
    kbHttpServer,
    kbHttpPort,
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
  }
})
