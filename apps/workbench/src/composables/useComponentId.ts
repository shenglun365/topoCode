import { ref } from 'vue'

const debugMode = ref(false)

function isDebugEnv(): boolean {
  if (typeof window === 'undefined') return false
  const api = (window as any).api
  if (!api?.env) return false
  return api.env.TOPCODE_UI_DEBUG === '1' || api.env.TOPCODE_UI_DEBUG === 'true'
}

debugMode.value = isDebugEnv()

export function useComponentId(id: string) {
  const showId = debugMode
  return { showId, componentId: id }
}
