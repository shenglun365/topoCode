/**
 * 资产工作区 · 更新提取(同步)域（MS6-W1 搬移，纯移动零逻辑改动）。
 * 变化量计划 → 确认 → 快照批量作业(后端) + 轮询接管。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { semanticAssetService } from '@/services/semantic-asset-service'
import type { ExtractPlanResult, SyncExtractJob } from '@/services/semantic-asset-service'
import type { WsDeps } from './useAssetCore'
import type { Ref } from 'vue'

export function useSyncExtract(D: WsDeps) {
  const { t } = useI18n()
  const core = D.core
  const turns = D.chat.turns as Ref<{ role: string; content: string }[]>

  // ---- 更新语义资产(原「校验并提取」)：变化量计划 → 用户确认 → 快照批量作业(后端，页面关闭不影响) ----
  const syncPlan = ref<ExtractPlanResult | null>(null)
  const syncPlanOpen = ref(false)
  const syncPlanLoading = ref(false)
  const syncJob = ref<SyncExtractJob | null>(null)
  let syncJobTimer: ReturnType<typeof setInterval> | null = null
  let syncJobDoneSeen = -1
  /** 作业对应对话区 turn 下标(完成后回填摘要)。 */
  const syncJobChatIdx = ref(-1)

  const syncExtracting = computed(() => !!syncJob.value?.running)

  async function planSyncExtract() {
    if (syncPlanLoading.value || syncExtracting.value) return
    syncPlanLoading.value = true
    try {
      syncPlan.value = await semanticAssetService.extractPlan()
      const p = syncPlan.value
      if (!p.toExtract && !p.deleted && !p.invalidated) {
        turns.value.push({ role: 'assistant', content: t('assetMgmt.sync.noChange') })
      } else if (!p.toExtract) {
        // 只有失效(删除文件)没有待提取：校验结果直接告知
        turns.value.push({ role: 'assistant', content: t('assetMgmt.sync.invalidatedOnly', { n: p.invalidated, d: p.deleted }) })
        await Promise.all([core.loadSemantic(), core.refreshStatus()])
      } else {
        syncPlanOpen.value = true
      }
    } catch (e: any) {
      turns.value.push({ role: 'assistant', content: e?.message || t('assetMgmt.sync.planFailed') })
    } finally {
      syncPlanLoading.value = false
    }
  }

  function cancelSyncExtract() {
    syncPlanOpen.value = false
  }

  async function confirmSyncExtract() {
    syncPlanOpen.value = false
    const p = syncPlan.value
    turns.value.push({ role: 'user', content: t('assetMgmt.sync.chatUser') })
    const idx = turns.value.push({ role: 'assistant', content: t('assetMgmt.compExtractRunning') }) - 1
    const r = await semanticAssetService.syncExtract('start', { batch: 10 })
    if (r.started) {
      syncJob.value = { running: true, total: r.total ?? 0, done: 0, saved: 0, batches: 0, errors: [] }
      syncJobChatIdx.value = idx
      turns.value[idx].content = t('assetMgmt.sync.chatStart', {
        n: r.total ?? 0, batches: p?.batchesEstimate ?? Math.ceil((r.total ?? 0) / 10),
        added: p?.added ?? 0, modified: p?.modified ?? 0,
        never: p?.neverExtracted ?? 0, stale: p?.staleOnly ?? 0,
      })
      startSyncJobPolling()
    } else if (r.reason === 'already_running') {
      turns.value[idx].content = t('assetMgmt.sync.chatBusy')
      syncJobChatIdx.value = idx
      startSyncJobPolling()
    } else if (r.reason === 'unowned_running') {
      turns.value[idx].content = t('assetMgmt.sync.chatUnownedBusy')
    } else {
      turns.value[idx].content = r.message || t('assetMgmt.sync.chatFailed')
    }
  }

  function stopSyncJobPolling() {
    if (syncJobTimer) { clearInterval(syncJobTimer); syncJobTimer = null }
  }

  async function pollSyncJobOnce() {
    try {
      const st = await semanticAssetService.syncExtractStatus()
      const wasRunning = !!syncJob.value?.running
      syncJob.value = st
      if (st.running) {
        if (st.done !== syncJobDoneSeen) {
          syncJobDoneSeen = st.done
          void core.loadSemantic()
        }
      } else if (wasRunning) {
        stopSyncJobPolling()
        if (syncJobChatIdx.value >= 0) {
          const errs = st.errors ?? []
          let msg = st.stopped
            ? t('assetMgmt.sync.chatStopped', { done: st.done, saved: st.saved })
            : t('assetMgmt.sync.chatDone', { done: st.done, saved: st.saved })
          if (errs.length) {
            msg += '\n' + t('assetMgmt.unowned.chatJobErrors')
            for (const e of errs.slice(0, 3)) msg += `\n· ${e.error}`
          }
          turns.value[syncJobChatIdx.value].content = msg
          syncJobChatIdx.value = -1
        }
        await Promise.all([core.loadSemantic(), core.refreshStatus(), core.loadOverview(), D.framework.loadCoverage(), D.unowned.loadUnownedFiles()])
      }
    } catch { /* 轮询失败静默，下轮重试 */ }
  }

  function startSyncJobPolling() {
    stopSyncJobPolling()
    syncJobDoneSeen = syncJob.value?.done ?? -1
    syncJobTimer = setInterval(pollSyncJobOnce, 2500)
    void pollSyncJobOnce()
  }

  async function stopSyncExtract() {
    await semanticAssetService.syncExtract('stop')
    void pollSyncJobOnce()
  }

  return {
    syncPlan, syncPlanOpen, syncPlanLoading, syncJob, syncJobChatIdx, syncExtracting,
    planSyncExtract, cancelSyncExtract, confirmSyncExtract,
    stopSyncJobPolling, pollSyncJobOnce, startSyncJobPolling, stopSyncExtract,
  }
}
