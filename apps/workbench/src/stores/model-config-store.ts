import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ModelConfigDTO } from '@/types/ipc'
import { ipc } from '@/services/ipc'

export const useModelConfigStore = defineStore('modelConfig', () => {
  const models = ref<ModelConfigDTO[]>([])
  const bindings = ref<Record<string, string>>({})

  function normalizeModel(raw: any): ModelConfigDTO {
    return {
      id: raw.id, name: raw.name, provider: raw.provider, model: raw.model, url: raw.url,
      type: raw.type, status: raw.status,
      isDefault: raw.isDefault ?? Boolean(raw.is_default ?? false),
      temperature: raw.temperature, maxTokens: raw.maxTokens ?? raw.max_tokens,
      frequencyPenalty: raw.frequencyPenalty ?? raw.frequency_penalty,
      presencePenalty: raw.presencePenalty ?? raw.presence_penalty,
      apiKey: raw.apiKey || raw.api_key || '', latency: raw.latency,
      maxRequestsPerDay: raw.maxRequestsPerDay ?? raw.max_requests_per_day ?? 0,
      maxTokensPerDay: raw.maxTokensPerDay ?? raw.max_tokens_per_day ?? 0,
      extraConfig: raw.extraConfig
        ?? (raw.extra_config ? (() => { try { return JSON.parse(raw.extra_config) } catch { return undefined } })() : undefined)
        ?? undefined,
    }
  }

  async function loadModels() {
    const rawModels = await ipc.settings.getModels()
    models.value = rawModels.map(normalizeModel)
    bindings.value = await ipc.settings.getBindings() as Record<string, string>
  }

  async function addModel(params: {
    name: string; provider: string; model: string; url: string;
    type: string; temperature?: number; maxTokens?: number; frequencyPenalty?: number; presencePenalty?: number; isDefault?: boolean; extraConfig?: Record<string, unknown>
  }) {
    const raw = await ipc.settings.addModel(params)
    const model = normalizeModel(raw)
    models.value.push(model)
    return model
  }

  async function updateModel(params: {
    id: string; name?: string; provider?: string; model?: string; url?: string;
    temperature?: number; maxTokens?: number; frequencyPenalty?: number; presencePenalty?: number; isDefault?: boolean; apiKey?: string; extraConfig?: Record<string, unknown>
  }) {
    const raw = await ipc.settings.updateModel(params)
    const model = normalizeModel(raw)
    const idx = models.value.findIndex(m => m.id === params.id)
    if (idx >= 0) models.value[idx] = model
    if (params.isDefault) models.value.forEach(m => { if (m.id !== params.id) m.isDefault = false })
    return model
  }

  async function removeModel(id: string) {
    await ipc.settings.removeModel(id)
    const idx = models.value.findIndex(m => m.id === id)
    if (idx >= 0) models.value.splice(idx, 1)
  }

  async function testModel(id: string) {
    const result = await ipc.settings.testModel(id)
    if (result?.status) {
      const idx = models.value.findIndex(m => m.id === id)
      if (idx >= 0) models.value[idx] = { ...models.value[idx], status: result.status as any, latency: result.latency }
    }
    return result
  }

  async function updateBindings(params: { bindings: Record<string, string> }) {
    bindings.value = await ipc.settings.updateBindings(params)
    return bindings.value
  }

  return {
    models, bindings,
    loadModels, addModel, updateModel, removeModel, testModel,
    updateBindings,
  }
})
