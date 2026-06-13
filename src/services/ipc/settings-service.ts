import type {
  ModelConfigDTO, ModelTestResult, AgentConfigDTO,
  AgentDetectResult, SkillConfigDTO, BindingsDTO,
  AgentExecutionDTO,
} from '@/types/ipc'

export interface SettingsService {
  getModels(): Promise<ModelConfigDTO[]>
  addModel(params: {
    name: string; provider: string; model: string; url: string;
    type: string; temperature?: number; maxTokens?: number
  }): Promise<ModelConfigDTO>
  updateModel(params: { id: string; name?: string; temperature?: number; maxTokens?: number }): Promise<ModelConfigDTO>
  removeModel(id: string): Promise<void>
  testModel(id: string): Promise<ModelTestResult>
  getAgents(): Promise<AgentConfigDTO[]>
  addAgent(params: { name: string; path: string; args: string; type?: string }): Promise<AgentConfigDTO>
  updateAgent(params: { id: string; path?: string; args?: string; name?: string; type?: string }): Promise<AgentConfigDTO>
  removeAgent(id: string): Promise<void>
  detectAgent(id: string): Promise<AgentDetectResult>
  executeAgent(params: { id: string; task: string; args?: string; taskId?: string; env?: Record<string, string> }): Promise<{ id: string; agentId: string; command: string; status: string }>
  getAgentExecution(execId: string): Promise<AgentExecutionDTO | { found: false }>
  listAgentExecutions(params?: { agentId?: string; taskId?: string; status?: string; limit?: number }): Promise<AgentExecutionDTO[]>
  cancelAgentExecution(execId: string): Promise<{ cancelled: boolean; message?: string }>
  getSkills(): Promise<SkillConfigDTO[]>
  updateSkill(params: { id: string; enabled: boolean }): Promise<SkillConfigDTO>
  getBindings(): Promise<BindingsDTO>
  updateBindings(params: { bindings: Record<string, string> }): Promise<BindingsDTO>
}

export function createSettingsService(api: any): SettingsService {
  return {
    getModels: async () => {
      return await api.settings.getModels() as ModelConfigDTO[]
    },
    addModel: async (params) => {
      return await api.settings.addModel(params) as ModelConfigDTO
    },
    updateModel: async (params) => {
      return await api.settings.updateModel(params) as ModelConfigDTO
    },
    removeModel: async (id: string) => {
      await api.settings.removeModel(id)
    },
    testModel: async (id: string) => {
      return await api.settings.testModel(id) as ModelTestResult
    },
    getAgents: async () => {
      return await api.settings.getAgents() as AgentConfigDTO[]
    },
    addAgent: async (params) => {
      return await api.settings.addAgent(params) as AgentConfigDTO
    },
    updateAgent: async (params) => {
      return await api.settings.updateAgent(params) as AgentConfigDTO
    },
    removeAgent: async (id: string) => {
      await api.settings.removeAgent(id)
    },
    detectAgent: async (id: string) => {
      return await api.settings.detectAgent(id) as AgentDetectResult
    },
    executeAgent: async (params) => {
      return await api.settings.executeAgent(params)
    },
    getAgentExecution: async (execId: string) => {
      return await api.settings.getAgentExecution(execId)
    },
    listAgentExecutions: async (params) => {
      return await api.settings.listAgentExecutions(params || {}) as AgentExecutionDTO[]
    },
    cancelAgentExecution: async (execId: string) => {
      return await api.settings.cancelAgentExecution(execId)
    },
    getSkills: async () => {
      return await api.settings.getSkills() as SkillConfigDTO[]
    },
    updateSkill: async (params) => {
      return await api.settings.updateSkill(params) as SkillConfigDTO
    },
    getBindings: async () => {
      return await api.settings.getBindings() as BindingsDTO
    },
    updateBindings: async (params) => {
      return await api.settings.updateBindings(params) as BindingsDTO
    },
  }
}
