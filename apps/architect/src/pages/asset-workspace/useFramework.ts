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

  /** 档位暂不可选（高级自定义模式开发中，暂关闭切换入口）。 */
  function tierUnavailable(tier: 'mid' | 'high'): boolean {
    return tier === 'high'
  }

  /** 标准变更确认流：preview(dry-run) → 设计者确认 → switch（整体作废+命名不迁移）。 */
  async function switchTier(tier: 'mid' | 'high') {
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

  /** 按需提取（范围确认弹窗 → 后台任务）：弹窗列组件 owns 文件(可勾选缩小范围)，
   *  确认后提交 extract_scope 作业。不写对话消息——进度/结果在任务中心，
   *  完成经失效总线自动刷新资产数据。 */
  async function askExtractComponent(key: string, name: string) {
    if (D.chat.extractBusy.value) return
    const comp = core.compById.value.get(key)
    const owns = (comp?.owns ?? []).filter(Boolean)
    if (!owns.length) return
    const picked = await D.diff.pickScope(t('assetMgmt.compExtractScopeTitle', { name }), owns)
    if (!picked) return
    D.chat.extractBusy.value = true
    try {
      // 清除重建 + 粒度提取统一编排（清除→实现→逻辑；进度在任务中心，完成经总线刷新）
      const ok = await D.diff.runExtractPipeline(picked, false)
      if (!ok) await dialog.alert(t('assetMgmt.compExtractFailed'))
    } catch (e: any) {
      await dialog.alert(e?.message || t('assetMgmt.batchFailed'))
    } finally {
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
    loadFramework, loadCoverage, switchTier, tierUnavailable, askExtractComponent,
    compCoverage, copiedKey, copyCompRef,
  }
}
