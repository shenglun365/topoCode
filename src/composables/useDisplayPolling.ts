import { ref, onMounted, onUnmounted, onActivated, onDeactivated } from 'vue'
import { displayDispatcher, type DisplayPollConfig } from '@/services/display-dispatcher'

export function useDisplayPolling(key: string, config: DisplayPollConfig) {
  const isActive = ref(false)

  const wrappedConfig: DisplayPollConfig = {
    ...config,
    onData: (data: any) => {
      config.onData?.(data)
    },
    onError: (err: any) => {
      config.onError?.(err)
    },
  }

  function doRegister() {
    if (!displayDispatcher.has(key)) {
      displayDispatcher.register(key, wrappedConfig)
    } else {
      displayDispatcher.resume(key)
    }
    isActive.value = true
  }

  function doUnregister() {
    displayDispatcher.unregister(key)
    isActive.value = false
  }

  onMounted(doRegister)
  onUnmounted(doUnregister)
  onActivated(() => {
    displayDispatcher.resume(key)
    isActive.value = true
  })
  onDeactivated(() => {
    displayDispatcher.pause(key)
    isActive.value = false
  })

  return { isActive }
}
