/**
 * 资产工作区 · 认知框架域（MS6-W1 搬移，纯移动零逻辑改动）。
 * 框架即配置：概览面板数据 + 标准变更确认流 + 按需提取 + 覆盖度投影 + 引用拷贝。
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppDialog } from '@/composables/useAppDialog'
import { semanticAssetService } from '@/services/semantic-asset-service'
import type { CoverageInfo, FrameworkPreview, FrameworkResult } from '@/services/semantic-asset-service'
import { copyText } from '@/utils/clipboard'
import type { WsDeps } from './useAssetCore'
import type { Ref } from 'vue'

export function useFramework(D: WsDeps) {
  const { t } = useI18n()
  const dialog = useAppDialog()
  const core = D.core
  const turns = D.chat.turns as Ref<{ role: string; content: string; assets?: any[] }[]>

  // ── M1 认知框架（框架即配置；概览 tab 面板 + 标准变更确认流） ──

  const frameworkInfo = ref<FrameworkResult | null>(null)
  const coverageInfo = ref<CoverageInfo | null>(null)
  const fwLoading = ref(false)
  const fwSwitching = ref(false)
  const fwPreview = ref<FrameworkPreview | null>(null)

  async function loadFramework() {
    fwLoading.value = true
    try {
      frameworkInfo.value = await semanticAssetService.getFramework()
    } catch {
      frameworkInfo.value = null
    } finally {
      fwLoading.value = false
    }
  }

  async function loadCoverage() {
    try {
      coverageInfo.value = await semanticAssetService.coverage()
    } catch {
      coverageInfo.value = null
    }
  }

  /** 标准变更确认流：preview(dry-run) → 设计者确认 → switch（整体作废+命名不迁移）。 */
  async function switchTier(tier: 'low' | 'mid' | 'high') {
    if (fwSwitching.value) return
    try {
      fwPreview.value = await semanticAssetService.previewFrameworkChange()
      const pv = fwPreview.value
      const dist = Object.entries(pv.byKind ?? {})
        .map(([k, n]) => `${t(`assetMgmt.kind.${k}`)}×${n}`)
        .join(', ') || '0'
      const msg = t('assetMgmt.framework.confirmMsg', { n: pv.voidedAssets, dist })
      if (!(await dialog.confirm(msg))) return
      fwSwitching.value = true
      await semanticAssetService.switchFramework(tier)
      await Promise.all([loadFramework(), core.loadSemantic(), core.loadOverview(), loadCoverage(), core.refreshStatus()])
    } catch (e: any) {
      await dialog.alert(e?.message || t('assetMgmt.framework.switchFailed'))
    } finally {
      fwSwitching.value = false
    }
  }

  /** 按需提取：确定性直调 REST(不走对话模型——小模型可能不按工具协议执行而编造报告)。
   *  过程与结果以对话回合呈现；完成后刷新资产数据。 */
  async function askExtractComponent(key: string, name: string) {
    if (D.chat.extractBusy.value) return
    turns.value.push({ role: 'user', content: t('assetMgmt.compExtractUser', { name, key }) })
    const idx = turns.value.push({ role: 'assistant', content: t('assetMgmt.compExtractRunning') }) - 1
    D.chat.extractBusy.value = true
    const ac = new AbortController(); D.chat.extractAbort.value = ac
    try {
      const res = await semanticAssetService.extract(
        { type: 'comm', key },
        core.kinds.map((k: { value: string }) => k.value),
        { level: 'implementation' },
      )
      const n = res.count ?? res.assets?.length ?? 0
      if (res.error) {
        turns.value[idx].content = `${t('assetMgmt.compExtractFailed')}\n${res.error}`
        const cands: { id: string; name: string }[] = (res as { candidates?: { id: string; name: string }[] }).candidates ?? []
        if (cands.length) {
          turns.value[idx].content += '\n' + t('assetMgmt.compExtractCandidates')
          for (const c of cands.slice(0, 8)) turns.value[idx].content += `\n· ${c.name} (${c.id})`
        }
      } else {
        turns.value[idx].content = res.degraded
          ? (res.reason === 'index_missing' || (res.source && res.source !== 'codegraph')
              ? t('assetMgmt.compExtractDegradedIndex', { n })
              : t('assetMgmt.compExtractDegraded', { n }))
          : t('assetMgmt.compExtractDone', { n })
        turns.value[idx].assets = res.assets ?? []
      }
      // 数据变更 → 刷新列表/状态/覆盖度(与对话提取联动同口径)
      D.chat.refreshAfterExtract()
    } catch (err: any) {
      turns.value[idx].content = err?.name === 'AbortError'
        ? t('requirement.chat.semanticStopped')
        : (err?.message || t('assetMgmt.batchFailed'))
    } finally {
      D.chat.extractAbort.value = null
      D.chat.extractBusy.value = false
    }
  }

  /** 组件覆盖状态（概览覆盖度数据投影到语义 tab 组头）；无数据返回 '' 不渲染。 */
  function compCoverage(compId: string): 'full' | 'partial' | 'none' | '' {
    const c = coverageInfo.value?.components?.find((x) => x.componentId === compId)
    return c?.coverage ?? ''
  }

  const copiedKey = ref('')
  let copiedTimer: ReturnType<typeof setTimeout> | null = null
  async function copyCompRef(key: string, name: string, id: string) {
    const ok = await copyText(core.compRefText(name, id))
    if (ok) {
      copiedKey.value = key
      if (copiedTimer) clearTimeout(copiedTimer)
      copiedTimer = setTimeout(() => { copiedKey.value = '' }, 1500)
    }
  }

  return {
    frameworkInfo, coverageInfo, fwLoading, fwSwitching, fwPreview,
    loadFramework, loadCoverage, switchTier, askExtractComponent,
    compCoverage, copiedKey, copyCompRef,
  }
}
