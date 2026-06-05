import { ref, onUnmounted } from 'vue'

export function usePolling(callback: () => Promise<void>, intervalMs = 30000) {
  const isPolling = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

  function start() {
    if (timer) return
    isPolling.value = true
    timer = setInterval(() => {
      callback().catch(() => {})
    }, intervalMs)
  }

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
    isPolling.value = false
  }

  function restart() {
    stop()
    start()
  }

  onUnmounted(stop)

  return {
    isPolling,
    start,
    stop,
    restart,
  }
}
