/**
 * 资产工作区 · 提取联动域（批A：资产页会话移除后保留的最小域）。
 * 会话集成已退役（需求草稿替代，见 DraftDock）；本域仅保留提取防重锁与
 * 去抖刷新（useFramework/useUnownedExtract 经 D.chat 引用）。
 */
import { shallowRef, ref } from 'vue'
import type { WsDeps } from './useAssetCore'

export function useAssetChat(D: WsDeps) {
  const core = D.core

  // ---- 直连提取进度锁（原复用对话 busy/abort，会话引擎化后独立） ----
  const extractBusy = ref(false)
  const extractAbort = shallowRef<AbortController | null>(null)

  // 提取完成 → 主动刷新资产数据（任务化闭环经失效总线触发；此处为
  // 直调/兜底路径的去抖合并刷新）。
  let extractDirty = false
  let extractRefreshTimer: ReturnType<typeof setTimeout> | null = null
  function refreshAfterExtract() {
    extractDirty = false
    if (extractRefreshTimer) { clearTimeout(extractRefreshTimer); extractRefreshTimer = null }
    void Promise.all([core.loadSemantic(), core.refreshStatus(), core.loadOverview(), D.framework.loadCoverage()])
  }
  function markExtracted() {
    extractDirty = true
    if (extractRefreshTimer) clearTimeout(extractRefreshTimer)
    extractRefreshTimer = setTimeout(refreshAfterExtract, 1500)
  }
  function isExtractDirty() {
    return extractDirty
  }

  return {
    extractBusy, extractAbort,
    isExtractDirty, refreshAfterExtract, markExtracted,
  }
}
