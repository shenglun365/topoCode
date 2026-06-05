import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { AgentConfigDTO, SkillConfigDTO, UsageStatDTO } from '@/types/ipc'
import { ipc } from '@/services/ipc'

export const useAgentUsageStore = defineStore('agentUsage', () => {
  const agents = ref<AgentConfigDTO[]>([])
  const skills = ref<SkillConfigDTO[]>([])
  const usageStats = ref<UsageStatDTO[]>([])
  const usageStatsLoading = ref(false)

  async function loadAgents() {
    agents.value = await ipc.settings.getAgents()
    skills.value = await ipc.settings.getSkills()
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
    if (agent) { agent.status = (result.status ?? undefined) as any; agent.version = result.version }
    return result
  }

  async function updateSkill(params: { id: string; enabled: boolean }) {
    const skill = await ipc.settings.updateSkill(params)
    const idx = skills.value.findIndex(s => s.id === params.id)
    if (idx >= 0) skills.value[idx] = skill
    return skill
  }

  async function loadUsageStats(modelId?: string, startDate?: string, endDate?: string) {
    usageStatsLoading.value = true
    try { usageStats.value = await ipc.model.getUsageStats(modelId, startDate, endDate) }
    finally { usageStatsLoading.value = false }
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
    agents, skills, usageStats, usageStatsLoading,
    loadAgents, addAgent, updateAgent, removeAgent, detectAgent,
    updateSkill,
    loadUsageStats, deleteUsageStat, deleteUsageStatsBatch, deleteUsageStatsByCondition,
  }
})
