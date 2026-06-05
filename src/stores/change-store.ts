import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { createLogger } from '@/utils/logger'

const logger = createLogger('change')

export interface CommitInfo {
  hash: string
  timestamp: string
  message: string
  author: string
  hasSnapshot?: boolean
}

export interface ChangeReport {
  fromCommit: string
  toCommit: string
  summary: {
    filesChanged: number
    symbolsAdded: number
    symbolsModified: number
    symbolsRemoved: number
    riskScore: number
    riskLevel: string
  }
  files?: Array<{
    filePath: string
    changeType: string
    symbols?: Array<{
      name: string
      kind: string
      changeType: string
      risk: string
    }>
  }>
  dependencies?: Array<{
    filePath: string
    dependency: string
    changeType: string
  }>
  impact?: {
    impactedFiles: string[]
    testFilesImpacted: string[]
    highRiskChanges: Array<{ filePath: string; reason: string }>
    impactCount: number
    testImpactCount: number
  }
}

export interface SymbolHistoryEntry {
  commit: string
  timestamp: string
  symbol: Record<string, unknown>
}

export const useChangeStore = defineStore('change', () => {
  const commits = ref<CommitInfo[]>([])
  const selectedFromCommit = ref<string>('')
  const selectedToCommit = ref<string>('')
  const changeReport = ref<ChangeReport | null>(null)
  const symbolHistory = ref<SymbolHistoryEntry[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const pollingInterval = ref<ReturnType<typeof setInterval> | null>(null)

  const hasData = computed(() => commits.value.length > 0)

  const currentRiskLevel = computed(() => changeReport.value?.summary.riskLevel ?? 'none')

  async function fetchCommits(maxCount = 20) {
    loading.value = true
    error.value = null
    try {
      const result = await (window.api as any)?.mcp?.call?.('get_version_history', { maxCount })
      if (result?.commits) {
        commits.value = result.commits.map((c: Record<string, unknown>) => ({
          hash: c.hash as string,
          timestamp: c.timestamp as string,
          message: c.message as string,
          author: c.author as string,
          hasSnapshot: c.hasSnapshot as boolean,
        }))
        if (commits.value.length > 0 && !selectedFromCommit.value) {
          selectedFromCommit.value = commits.value.length > 1 ? commits.value[1].hash : commits.value[0].hash
          selectedToCommit.value = commits.value[0].hash
        }
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? (e as Error).message : String(e)
      logger.error('fetchCommits failed', msg)
      error.value = msg
    } finally {
      loading.value = false
    }
  }

  async function fetchChangeReport(fromCommit?: string, toCommit?: string, scope = 'full') {
    loading.value = true
    error.value = null
    try {
      const result = await (window.api as any)?.mcp?.call?.('get_changes', {
        fromCommit: fromCommit || selectedFromCommit.value,
        toCommit: toCommit || selectedToCommit.value,
        scope,
      })
      if (result) {
        changeReport.value = result as ChangeReport
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? (e as Error).message : String(e)
      logger.error('fetchChangeReport failed', msg)
      error.value = msg
    } finally {
      loading.value = false
    }
  }

  async function fetchSymbolHistory(symbolName: string, filePath: string, maxVersions = 10) {
    loading.value = true
    error.value = null
    try {
      const result = await (window.api as any)?.mcp?.call?.('track_symbol_history', {
        symbolName,
        filePath,
        maxVersions,
      })
      if (result?.history) {
        symbolHistory.value = result.history as SymbolHistoryEntry[]
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? (e as Error).message : String(e)
      logger.error('fetchSymbolHistory failed', msg)
      error.value = msg
    } finally {
      loading.value = false
    }
  }

  function selectCommits(from: string, to: string) {
    selectedFromCommit.value = from
    selectedToCommit.value = to
  }

  function startPolling(intervalMs = 30000) {
    stopPolling()
    pollingInterval.value = setInterval(() => {
      fetchCommits()
    }, intervalMs)
  }

  function stopPolling() {
    if (pollingInterval.value) {
      clearInterval(pollingInterval.value)
      pollingInterval.value = null
    }
  }

  return {
    commits,
    selectedFromCommit,
    selectedToCommit,
    changeReport,
    symbolHistory,
    loading,
    error,
    hasData,
    currentRiskLevel,
    fetchCommits,
    fetchChangeReport,
    fetchSymbolHistory,
    selectCommits,
    startPolling,
    stopPolling,
  }
})
