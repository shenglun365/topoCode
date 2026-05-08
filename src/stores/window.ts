import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

export interface WindowInfo {
  id: number
  title: string
  isFocused: boolean
}

export const useWindowStore = defineStore('window', () => {
  const windows = ref<WindowInfo[]>([])
  const currentWindowId = ref(0)
  const maxWindows = ref(3)

  const windowCount = computed(() => windows.value.length)
  const canCreateMore = computed(() => windowCount.value < maxWindows.value)

  async function init() {
    if (window.api && window.api.window) {
      windows.value = await window.api.window.list()
      maxWindows.value = await window.api.window.getMaxCount()
      currentWindowId.value = window.api.window.getId?.() || 0
    }
  }

  async function refresh() {
    if (window.api && window.api.window) {
      windows.value = await window.api.window.list()
    }
  }

  async function createNewWindow() {
    if (!canCreateMore.value) return null
    if (window.api && window.api.window) {
      const id = await window.api.window.create()
      if (id) {
        await refresh()
      }
      return id
    }
    return null
  }

  async function closeWindow(windowId: number) {
    if (window.api && window.api.window) {
      await window.api.window.close(windowId)
      await refresh()
    }
  }

  async function focusWindow(windowId: number) {
    if (window.api && window.api.window) {
      await window.api.window.focus(windowId)
      await refresh()
    }
  }

  async function broadcast(channel: string, data: any) {
    if (window.api && window.api.window) {
      await window.api.window.broadcast(channel, data)
    }
  }

  return {
    windows,
    currentWindowId,
    maxWindows,
    windowCount,
    canCreateMore,
    init,
    refresh,
    createNewWindow,
    closeWindow,
    focusWindow,
    broadcast,
  }
})
