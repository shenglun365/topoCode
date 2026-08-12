import { ref } from 'vue'
import { apiGet } from '@/services/api-client'
import { backendUp } from '@/services/backend'
import type { ArchLlmModel, ArchLlmModelsResult } from '@/types'

/** architect 对话模型选择 —— 浏览器持久化：刷新后若保存值仍在模型列表则恢复，否则清除缓存回退默认。 */
const LS_KEY = 'arch_chat_model_id'

export function useChatModel() {
  const chatModelId = ref<string>('')
  const chatModels = ref<ArchLlmModel[]>([])

  function readSaved(): string {
    try {
      return localStorage.getItem(LS_KEY) || ''
    } catch {
      return ''
    }
  }

  function clearSaved() {
    try {
      localStorage.removeItem(LS_KEY)
    } catch {
      /* ignore */
    }
  }

  function persist(id: string) {
    try {
      localStorage.setItem(LS_KEY, id)
    } catch {
      /* ignore */
    }
  }

  async function loadChatModels() {
    if (!(await backendUp())) return
    try {
      const data = await apiGet<ArchLlmModelsResult>('/llm/models')
      chatModels.value = data.models ?? []
      const saved = readSaved()
      if (saved && chatModels.value.some((m) => m.id === saved)) {
        chatModelId.value = saved
      } else {
        clearSaved()
        chatModelId.value = data.modelId ?? ''
      }
    } catch {
      // 后端不可达 → 空
    }
  }

  function onChatModelChange(id: string) {
    chatModelId.value = id
    persist(id)
  }

  return { chatModelId, chatModels, loadChatModels, onChatModelChange }
}
