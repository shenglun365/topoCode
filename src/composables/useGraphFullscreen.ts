import { computed } from 'vue'
import { usePanelStore } from '@/stores/panel'

export function useGraphFullscreen() {
  const panelStore = usePanelStore()

  const isFullscreen = computed(() => panelStore.isFullscreen)

  function enterFullscreen() {
    panelStore.setFullscreen(true)
  }

  function exitFullscreen() {
    panelStore.setFullscreen(false)
  }

  function toggleFullscreen() {
    panelStore.setFullscreen(!panelStore.isFullscreen)
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape' && panelStore.isFullscreen) {
      exitFullscreen()
    }
  }

  return {
    isFullscreen,
    enterFullscreen,
    exitFullscreen,
    toggleFullscreen,
    onKeydown,
  }
}
