import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { CrashReport } from '@/types/ipc'

export const useCrashReportStore = defineStore('crashReport', () => {
  const crashes = ref<CrashReport[]>([])
  const showDialog = ref(false)
  const selectedCrash = ref<CrashReport | null>(null)

  const hasCrash = computed(() => crashes.value.length > 0)
  const latestCrash = computed(() => crashes.value.length > 0 ? crashes.value[crashes.value.length - 1] : null)

  let unsubNew: (() => void) | null = null
  let unsubPending: (() => void) | null = null

  function init() {
    const api = (window as any).api
    if (!api?.crash) return

    checkPending()

    unsubNew = api.crash.onNew((report: CrashReport) => {
      const exists = crashes.value.find(c => c.id === report.id)
      if (!exists) {
        crashes.value.push(report)
      }
    })

    unsubPending = api.crash.onPending((list: CrashReport[]) => {
      for (const r of list) {
        const exists = crashes.value.find(c => c.id === r.id)
        if (!exists) {
          crashes.value.push(r)
        }
      }
    })
  }

  async function checkPending() {
    const api = (window as any).api
    if (!api?.crash) return
    try {
      const list = await api.crash.list()
      crashes.value = list || []
    } catch {
      // ignore
    }
  }

  function openCrash(crash: CrashReport) {
    selectedCrash.value = crash
    showDialog.value = true
  }

  function closeDialog() {
    showDialog.value = false
    selectedCrash.value = null
  }

  async function report(crash: CrashReport) {
    const api = (window as any).api
    if (!api?.crash) return
    try {
      await api.crash.report(crash.id)
    } catch {
      // ignore
    }
    crashes.value = crashes.value.filter(c => c.id !== crash.id)
    closeDialog()
  }

  async function dismiss(crash: CrashReport) {
    const api = (window as any).api
    if (!api?.crash) return
    try {
      await api.crash.dismiss(crash.id)
    } catch {
      // ignore
    }
    crashes.value = crashes.value.filter(c => c.id !== crash.id)
    closeDialog()
  }

  function cleanup() {
    unsubNew?.()
    unsubPending?.()
  }

  return {
    crashes, showDialog, selectedCrash,
    hasCrash, latestCrash,
    init, checkPending, openCrash, closeDialog, report, dismiss, cleanup,
  }
})
