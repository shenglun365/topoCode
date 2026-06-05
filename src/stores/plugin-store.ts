import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import type { PluginInfoDTO, SuccessResponse } from '@/types/ipc'

export const usePluginStore = defineStore('plugin', () => {
  const plugins = ref<Record<string, PluginInfoDTO>>({})
  const loading = ref(false)
  const error = ref<string | null>(null)

  const pluginList = computed(() => Object.values(plugins.value))
  const loadedPlugins = computed(() => pluginList.value.filter(p => p.loaded))

  async function loadPlugins() {
    loading.value = true
    error.value = null
    try {
      const api = (window as any).api
      if (api?.plugin) {
        plugins.value = await api.plugin.list()
      }
    } catch (e: unknown) {
      error.value = (e as Error).message || 'Failed to load plugins'
    } finally {
      loading.value = false
    }
  }

  async function loadPlugin(name: string): Promise<SuccessResponse> {
    const api = (window as any).api
    const result = await api.plugin.load(name) as unknown as SuccessResponse
    if (result.success) { await loadPlugins() }
    return result
  }

  async function unloadPlugin(name: string): Promise<SuccessResponse> {
    const api = (window as any).api
    const result = await api.plugin.unload(name) as unknown as SuccessResponse
    if (result.success) { await loadPlugins() }
    return result
  }

  async function reloadPlugin(name: string): Promise<SuccessResponse> {
    const api = (window as any).api
    const result = await api.plugin.reload(name) as unknown as SuccessResponse
    if (result.success) { await loadPlugins() }
    return result
  }

  async function installPlugin(name: string): Promise<SuccessResponse> {
    const api = (window as any).api
    const result = await api.plugin.install(name) as unknown as SuccessResponse
    if (result.success) { await loadPlugins() }
    return result
  }

  return {
    plugins,
    loading,
    error,
    pluginList,
    loadedPlugins,
    loadPlugins,
    loadPlugin,
    unloadPlugin,
    reloadPlugin,
    installPlugin,
  }
})
