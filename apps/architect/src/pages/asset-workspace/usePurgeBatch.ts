/**
 * 资产工作区 · 清理与批量管理域（MS6-W1 搬移，纯移动零逻辑改动）。
 * purge(dry-run 确认流) + 选定范围批量 clear(首击预览转确认)。
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppDialog } from '@/composables/useAppDialog'
import { semanticAssetService } from '@/services/semantic-asset-service'
import type { SemanticBatchResult, SemanticPurgeResult } from '@/services/semantic-asset-service'
import type { WsDeps } from './useAssetCore'
import type { Ref } from 'vue'

export function usePurgeBatch(D: WsDeps) {
  const { t } = useI18n()
  const dialog = useAppDialog()
  const core = D.core

  /** 清理确认弹窗状态(先 dry-run 展示影响范围，确认后再真正删除)。 */
  const purgeOpen = ref(false)
  const purgeResult = ref<SemanticPurgeResult | null>(null)
  const purgeBusy = ref(false)

  /** 触发清理：先 dry-run 计算影响范围(需求池引用 + 未完成任务)并弹窗确认。 */
  async function runPurge() {
    if (core.purging.value || purgeBusy.value) return
    core.purging.value = true
    try {
      const res = await semanticAssetService.purge({ staleDays: 7 })
      purgeResult.value = res
      purgeOpen.value = true
    } catch (err: any) {
      console.warn('[purge] impact failed:', err?.message)
      purgeResult.value = null
    } finally {
      core.purging.value = false
    }
  }

  /** 确认清理：真正物理删除 stale/deleted 行，并把受影响需求/任务标记为需重新生成方案。 */
  async function confirmPurge() {
    if (purgeBusy.value) return
    purgeBusy.value = true
    try {
      const res = await semanticAssetService.purge({ staleDays: 7, confirm: true })
      const impact = res.impact
      await Promise.all([core.loadOverview(), core.refreshStatus()])
      purgeOpen.value = false
    } catch (err: any) {
      console.warn('[purge] failed:', err?.message)
    } finally {
      purgeBusy.value = false
    }
  }

  function cancelPurge() {
    purgeOpen.value = false
    purgeResult.value = null
  }

  // ---- 语义资产批量管理(选定组件范围) ----
  const batchOpen = ref(false)
  const batchRunning = ref(false)
  const batchAction = ref<'clear' | ''>('')
  const batchLast = ref('')
  /** clear 前的 dry-run 影响预览(需求池/未完成任务)。 */
  const batchPreview = ref<SemanticBatchResult | null>(null)

  /** 当前组件范围：选中组件 id(空=全部) + 是否含「其它」。 */
  function targetScope() {
    const compIds = core.scopeSel.value.filter((id: string) => id !== '__other__')
    const includeOther = core.scopeSel.value.length === 0 || core.scopeSel.value.includes('__other__')
    return { compIds, includeOther }
  }

  /** 批量范围签名(预览与执行之间范围变化 → 作废预览)。 */
  function batchScopeSig() {
    return JSON.stringify([targetScope(), core.scopeParams()])
  }

  async function runBatch(action: 'clear') {
    if (batchRunning.value) return
    const { compIds, includeOther } = targetScope()
    // 清除 = 物理删除：一击式确认——首击 dry-run 预览影响并把同一按钮转为「确认清除」，再击执行。
    if (!batchPreview.value) {
      const sig = batchScopeSig()
      batchRunning.value = true
      try {
        const scope = core.scopeParams()
        const res = await semanticAssetService.batchManage(action, compIds, {
          includeOther, scope, dryRun: true,
        })
        if (sig !== batchScopeSig()) return
        batchPreview.value = res
        batchAction.value = action
      } catch {
        batchPreview.value = null
        batchAction.value = ''
        batchLast.value = t('assetMgmt.batchFailed')
      } finally {
        batchRunning.value = false
      }
      return
    }
    batchRunning.value = true
    batchAction.value = ''
    try {
      // 与 search 的 scope 语义一致：空=全部；['__other__']=仅其它；组件 id 列表=指定范围。
      const scope = core.scopeParams()
      const res = await semanticAssetService.batchManage(action, compIds, {
        includeOther,
        scope,
      })
      batchLast.value = t('assetMgmt.batchDone', { action: t(`assetMgmt.batchAction.${action}`), n: res.count })
      await Promise.all([core.loadSemantic(), core.refreshStatus()])
      batchOpen.value = false   // 删除完成：刷新列表(上) + 自动关闭批量管理浮窗
    } catch {
      batchLast.value = t('assetMgmt.batchFailed')
    } finally {
      batchRunning.value = false
      batchPreview.value = null
    }
  }

  return {
    purgeOpen, purgeResult, purgeBusy, runPurge, confirmPurge, cancelPurge,
    batchOpen, batchRunning, batchAction, batchLast, batchPreview,
    targetScope, batchScopeSig, runBatch,
  }
}
