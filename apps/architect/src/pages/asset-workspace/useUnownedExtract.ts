/**
 * 资产工作区 · 未归属文件提取域（MS6-W1 搬移，纯移动零逻辑改动）。
 * 未归属清单 + 单文件/循环批量提取(后端作业轮询) + 跨组件关联。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { semanticAssetService } from '@/services/semantic-asset-service'
import type { UnownedCrossLink, UnownedExtractJob, UnownedFileEntry } from '@/services/semantic-asset-service'
import type { SemanticAsset } from '@/types'
import type { WsDeps } from './useAssetCore'

export function useUnownedExtract(D: WsDeps) {
  const { t } = useI18n()
  const core = D.core

  // ---- 未归属组件文件：清单 + 单文件/循环批量提取 + 跨组件关联 ----
  const unownedFiles = ref<UnownedFileEntry[]>([])
  const unownedMeta = ref<{ unownedCount: number; ownedCount: number; totalFiles: number; truncated: boolean } | null>(null)
  const unownedLoading = ref(false)
  const unownedError = ref('')
  /** 文件(norm path) → 跨组件关联(计数 + 按组件聚合 + 样本)。 */
  const unownedLinks = ref<Map<string, UnownedCrossLink>>(new Map())

  async function loadUnownedFiles() {
    unownedLoading.value = true
    try {
      const r = await semanticAssetService.unownedFiles()
      unownedFiles.value = r.files
      unownedMeta.value = { unownedCount: r.unownedCount, ownedCount: r.ownedCount, totalFiles: r.totalFiles, truncated: !!r.truncated }
      unownedError.value = ''
    } catch (err: any) {
      unownedFiles.value = []
      unownedMeta.value = null
      unownedError.value = err?.message || ''
    } finally {
      unownedLoading.value = false
    }
  }

  async function loadUnownedLinks() {
    try {
      const r = await semanticAssetService.unownedCrossLinks()
      unownedLinks.value = new Map(r.links.map((l) => [l.file, l]))
    } catch {
      unownedLinks.value = new Map()
    }
  }

  /** 单文件提取：完成后刷新未归属清单(该文件 assetCount 变化)与资产列表。
   *  全程写对话区(与组件提取同款 user+assistant 双 turn)——提取是后端异步管线，
   *  不写对话用户看不到任何反馈。 */
  const unownedExtractingOne = ref('')
  async function extractUnownedFile(path: string) {
    if (unownedExtractingOne.value) return
    if (unownedExtracting.value) return
    // 范围确认弹窗（交互提取闭环统一交互）：确认后生成任务开始分析
    const picked = await D.diff.pickScope(t('assetMgmt.unowned.fileScopeTitle', { file: path }), [path])
    if (!picked?.length) return
    unownedExtractingOne.value = path
    try {
      const r = await semanticAssetService.startExtractScope(
        { scopeType: 'files', files: picked },
        { kinds: core.kinds.map((k: { value: string }) => k.value), level: 'implementation' })
      if (!r?.started || !r.job?.id) {
        console.warn('[unowned] extract submit failed:', r?.reason)
        return
      }
      D.chat.refreshAfterExtract()
      await loadUnownedFiles()
    } catch (err: any) {
      console.warn('[unowned] extract failed:', err?.message)
    } finally {
      unownedExtractingOne.value = ''
    }
  }

  // ---- 循环批量提取 = 后端作业(daemon 线程)：页面关闭不影响，进度靠轮询。 ----
  // 纯增量操作(只新增/更新资产)：无需 confirm；中断后重按自动续传(跳过已提取)。
  const unownedJob = ref<UnownedExtractJob | null>(null)
  let unownedJobTimer: ReturnType<typeof setInterval> | null = null
  let unownedJobDoneSeen = -1
  /** 批量作业的对话区 turn 下标(完成后回填摘要)。 */
  const unownedExtracting = computed(() => !!unownedJob.value?.running)

  /** 进度 chip 标题：落库数 + 清单说明(无独立符号不参与提取)。作业缺盘点字段时回退本地清单计数。 */
  const unownedJobHint = computed(() => {
    const j = unownedJob.value
    const unowned = j?.unowned ?? unownedMeta.value?.unownedCount ?? unownedFiles.value.length
    const noSymbols = j?.noSymbols ?? unownedFiles.value.filter((f) => f.extractable === false).length
    return t('assetMgmt.unowned.extractingHint', { saved: j?.saved ?? 0, unowned, noSymbols })
  })

  function stopUnownedJobPolling() {
    if (unownedJobTimer) { clearInterval(unownedJobTimer); unownedJobTimer = null }
  }

  async function pollUnownedJobOnce() {
    try {
      const st = await semanticAssetService.unownedExtractStatus()
      const wasRunning = !!unownedJob.value?.running
      unownedJob.value = st
      // 每批落库后轻量刷新清单(进度可见)；作业结束做全量刷新 + 对话区摘要
      if (st.running) {
        if (st.done !== unownedJobDoneSeen) {
          unownedJobDoneSeen = st.done
          void loadUnownedFiles()
        }
      } else if (wasRunning) {
        stopUnownedJobPolling()
        await Promise.all([loadUnownedFiles(), core.loadSemantic(), core.refreshStatus(), core.loadOverview(), D.framework.loadCoverage()])
      }
    } catch { /* 轮询失败静默，下轮重试 */ }
  }

  function startUnownedJobPolling() {
    stopUnownedJobPolling()
    unownedJobDoneSeen = unownedJob.value?.done ?? -1
    unownedJobTimer = setInterval(pollUnownedJobOnce, 2500)
    void pollUnownedJobOnce()
  }

  async function extractAllUnowned() {
    const r = await semanticAssetService.unownedExtract('start', { batch: 10 })
    if (r.started || r.reason === 'already_running') {
      if (!unownedJob.value?.running) {
        unownedJob.value = { running: true, total: r.total ?? 0, done: 0, saved: 0, batches: 0, errors: [] }
      }
      // 等式盘点：未归属 = 待提取 + 已有资产 + 无独立符号——进度 chip hint 呈现
      startUnownedJobPolling()
    } else if (r.reason === 'nothing_to_extract') {
      console.info('[unowned] nothing to extract',
        { unowned: r.unowned, withAssets: r.withAssets, noSymbols: r.noSymbols })
    } else {
      // 请求失败(服务未启动/后端版本较旧路由缺失/项目根未解析)——不能伪装成"没有待提取"
      console.warn('[unowned] job failed:', r.reason)
      void pollUnownedJobOnce()
    }
  }

  async function stopUnownedExtract() {
    await semanticAssetService.unownedExtract('stop')
    void pollUnownedJobOnce()
  }

  /** 未归属资产行的「关联 N」chip 数据(仅「其它」域资产；锚点文件反查)。 */
  function unownedLinkOf(a: SemanticAsset): UnownedCrossLink | null {
    if (core.componentsOf(a).length) return null
    const file = a.astRefs?.[0]?.file || ''
    return unownedLinks.value.get(file) ?? null
  }

  function unownedLinkTitle(l: UnownedCrossLink): string {
    return l.byComponent.slice(0, 6).map((c) => `${c.component}(${c.count})`).join(' · ')
  }

  /** 资产 id → 跨组件关联(「其它」域资产渲染入口：links 变化时统一重算一次)。 */
  const unownedLinkByAssetId = computed<Map<string, UnownedCrossLink>>(() => {
    const m = new Map<string, UnownedCrossLink>()
    for (const a of core.items.value) {
      const l = unownedLinkOf(a)
      if (l) m.set(a.id, l)
    }
    return m
  })

  return {
    unownedFiles, unownedMeta, unownedLoading, unownedError, unownedLinks,
    loadUnownedFiles, loadUnownedLinks,
    unownedExtractingOne, extractUnownedFile,
    unownedJob, unownedExtracting, unownedJobHint,
    stopUnownedJobPolling, pollUnownedJobOnce, startUnownedJobPolling,
    extractAllUnowned, stopUnownedExtract,
    unownedLinkOf, unownedLinkTitle, unownedLinkByAssetId,
  }
}

import type { Ref } from 'vue'
