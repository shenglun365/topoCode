/**
 * 资产工作区 · 基线对比域（MS6-W1 自 AssetManagementWorkspace.vue 搬移，纯移动零逻辑改动）。
 * 三视图 diff（基线 lastHead → 工作区）+ 任意 head 对比 + 待提取闭环 + 变更标记族。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppDialog } from '@/composables/useAppDialog'
import { semanticAssetService } from '@/services/semantic-asset-service'
import type { AssetCompareResult, BaselineDiff } from '@/services/semantic-asset-service'
import { gitService, type GitLogEntry } from '@/services/git-service'
import type { SemanticAsset } from '@/types'
import type { WsDeps } from './useAssetCore'

export function useAssetDiff(D: WsDeps) {
  const { t } = useI18n()
  const dialog = useAppDialog()
  const core = D.core
  const items = core.items as Ref<SemanticAsset[]>
  const treeComps = core.treeComps

  // ---- 基线对比模式（三视图 diff：基线 lastHead → 工作区 变更文件集）----
  const diffMode = ref(false)
  const diffLoading = ref(false)
  const baselineDiffData = ref<BaselineDiff | null>(null)

  async function loadBaselineDiff() {
    diffLoading.value = true
    try {
      baselineDiffData.value = await semanticAssetService.baselineDiff()
    } catch {
      baselineDiffData.value = null
    } finally {
      diffLoading.value = false
    }
  }

  function toggleDiffMode() {
    diffMode.value = !diffMode.value
    if (diffMode.value) {
      loadBaselineDiff()
      void loadCommitOptions()
      void runCompare()
    }
  }

  // ---- 任意 head 对 vs head/工作区 资产/组件对比(基准缺省=KB 基线 baselineCommit；缓存态) ----
  const cmpBase = ref('')            // '' = KB 基线(baselineCommit)
  const cmpTarget = ref('worktree')  // 'worktree' = 工作区(含未提交/未跟踪)
  const commitOptions = ref<GitLogEntry[]>([])
  const baselineSha = ref('')
  const compareData = ref<AssetCompareResult | null>(null)
  const compareError = ref('')
  /** 非阻断弱提示(基线图谱落后等)——区别于 compareError(真错误)。 */
  const compareHint = ref('')
  const compareLoading = ref(false)

  async function loadCommitOptions() {
    const res = await gitService.commitLog(50)
    commitOptions.value = res.entries
    baselineSha.value = res.baseline
  }

  async function runCompare() {
    compareLoading.value = true
    compareError.value = ''
    compareHint.value = ''
    try {
      compareData.value = await semanticAssetService.assetCompare(
        cmpBase.value || undefined,
        cmpTarget.value || 'worktree',
      ) ?? null
    } catch (e) {
      compareData.value = null
      compareError.value = e instanceof Error && e.message ? e.message : t('assetMgmt.diff.cmpFailed')
    } finally {
      compareLoading.value = false
    }
  }

  // ---- 提取闭环：待提取文件(目标侧无资产匹配) → 按文件范围补提(分批) → 重新对比 ----
  const extractingPending = ref(false)
  /** 可经工作区提取锚定的待提取子集(目标侧内容==工作区内容；旧响应无此字段时回退全集)。 */
  const pendingExtractable = computed(() => {
    const p = compareData.value?.assets.pending
    if (!p) return []
    return p.extractable?.length ? p.extractable : (p.extractableCount === 0 ? [] : p.files)
  })

  async function extractPendingAndRecompare() {
    const files = pendingExtractable.value
    if (!files.length) return
    if (!(await dialog.confirm(t('assetMgmt.diff.extractConfirm', { n: files.length })))) return
    extractingPending.value = true
    let extracted = 0
    const noCandidateFiles: string[] = []
    try {
      const BATCH = 10
      for (let i = 0; i < files.length; i += BATCH) {
        const res = await semanticAssetService.extract({ type: 'files', files: files.slice(i, i + BATCH) })
        extracted += res?.count ?? 0
        // 基线图谱落后仅为比对口径提示——提取候选来自符号源(CLI 索引/native 实时)，
        // 不受其影响，完整执行不中断(此前误作硬拦截，实测误挡正常提取 2026-09-29)
        if (res?.indexStale) {
          compareHint.value = t('assetMgmt.diff.extractBaselineHint', { n: res.staleCount ?? 0 })
        }
        // 零产出逐文件归因：纯常量表/re-export 桶/启动脚本本就无可提取符号(正确语义)
        for (const ef of res?.emptyFiles ?? []) {
          if (!noCandidateFiles.includes(ef.file)) noCandidateFiles.push(ef.file)
        }
      }
    } catch (e) {
      // 失败即止：保留错误信息(不再自动重比冲掉)，用户可手动「重新对比」
      compareError.value = e instanceof Error && e.message ? e.message : t('assetMgmt.diff.cmpFailed')
      extractingPending.value = false
      return
    } finally {
      extractingPending.value = false
    }
    if (!extracted) {
      // 全程零产出：若逐文件归因为"无可提取类别符号"(纯常量/桶文件/启动脚本)
      // 则属正确语义——明示跳过清单而非笼统报错；否则维持通用提示
      compareError.value = noCandidateFiles.length
        ? `${t('assetMgmt.diff.extractNoCandidates', { n: noCandidateFiles.length })} ${noCandidateFiles.slice(0, 4).map((f) => f.split('/').pop()).join('、')}${noCandidateFiles.length > 4 ? '…' : ''}`
        : t('assetMgmt.diff.extractZero')
      return
    }
    await Promise.all([core.loadSemantic(), runCompare()])
  }

  /** 变更文件 → 类别 快查表（语义行徽标 / 图谱节点着色用）。
   *  选了对比对(base/target)后跟随所选口径(默认对=基线→工作区，与 baselineDiff 一致)。 */
  const changedFileMap = computed<Map<string, 'added' | 'modified' | 'deleted'>>(() => {
    const m = new Map<string, 'added' | 'modified' | 'deleted'>()
    const d = compareData.value ?? baselineDiffData.value
    if (!d) return m
    for (const p of d.files.added) m.set(p, 'added')
    for (const p of d.files.modified) m.set(p, 'modified')
    for (const p of d.files.deleted) m.set(p, 'deleted')
    return m
  })

  /** 资产变更标记：任一 astRef 文件 ∈ 变更集 → 返回类别（工作区态优先）。
   *  ⚠️ 模板勿直接调用本函数：它遍历 astRefs，行内多次调用会重复求值；
   *  请用 changeMarkById（每资产仅算一次）。 */
  function assetChangeMark(a: SemanticAsset): 'added' | 'modified' | 'deleted' | '' {
    if (!diffMode.value) return ''
    const files = a.astRefs?.map((r) => r.file) ?? []
    let mark: 'added' | 'modified' | 'deleted' | '' = ''
    for (const f of files) {
      const c = changedFileMap.value.get(f)
      if (c === 'added') return 'added'
      if (c === 'deleted') { mark = 'deleted'; continue }
      if (c === 'modified') { if (mark !== 'deleted') mark = 'modified' }
    }
    return mark
  }

  /** 资产 id → 变更类别（语义行徽标渲染入口：diffMode/变更集变化时统一重算一次）。
   *  对比口径(compare)优先：资产级 side/strong 判定精确到符号段，文件级口径仅兜底。 */
  const cmpBucketById = computed<Map<string, 'modified' | 'added' | 'deleted'>>(() => {
    const m = new Map<string, 'modified' | 'added' | 'deleted'>()
    const c = compareData.value
    if (!diffMode.value || !c) return m
    for (const a of c.assets.changed) m.set(a.id, 'modified')
    for (const a of c.assets.new) m.set(a.id, 'added')
    for (const a of c.assets.removed) m.set(a.id, 'deleted')
    return m
  })

  const changeMarkById = computed<Map<string, 'added' | 'modified' | 'deleted'>>(() => {
    const m = new Map<string, 'added' | 'modified' | 'deleted'>()
    if (!diffMode.value) return m
    const buckets = cmpBucketById.value
    for (const a of items.value) {
      const mark = buckets.get(a.id) ?? assetChangeMark(a)
      if (mark) m.set(a.id, mark)
    }
    return m
  })

  /** 基线对比 · 文件级变化归属：文件(树侧路径) → {changed,new,removed}(按首锚点归属)。
   *  compare 资产经 items 反查(锚点路径与树同基准)；结果供文件行彩色计数 chip。 */
  const diffFileCounts = computed<Map<string, { changed: number; added: number; deleted: number }>>(() => {
    const m = new Map<string, { changed: number; added: number; deleted: number }>()
    if (!diffMode.value) return m
    const byId = new Map(items.value.map((x) => [x.id, x]))
    const buckets = cmpBucketById.value
    for (const [id, bucket] of buckets) {
      const a = byId.get(id)
      const f = a?.astRefs?.[0]?.file || ''
      if (!f) continue
      const e = m.get(f) ?? { changed: 0, added: 0, deleted: 0 }
      if (bucket === 'modified') e.changed += 1
      else if (bucket === 'added') e.added += 1
      else e.deleted += 1
      m.set(f, e)
    }
    return m
  })

  /** 待提取/新增文件集合(compare 的 git 路径可能是 workDir 相对) → 双向后缀匹配树侧路径。 */
  function treeFileOf(cmpFile: string): string {
    const u = diffFileUniverse.value
    if (u.has(cmpFile)) return cmpFile
    for (const f of u) {
      if (f.endsWith('/' + cmpFile) || cmpFile.endsWith('/' + f)) return f
    }
    return ''
  }
  const pendingFileSet = computed<Set<string>>(() => {
    const s = new Set<string>()
    if (diffMode.value && compareData.value) {
      for (const f of compareData.value.assets.pending.files) {
        const t = treeFileOf(f)
        if (t) s.add(t)
      }
    }
    return s
  })
  const addedFileSet = computed<Set<string>>(() => {
    const s = new Set<string>()
    if (diffMode.value && compareData.value) {
      for (const f of compareData.value.files.added) {
        const t = treeFileOf(f)
        if (t) s.add(t)
      }
    }
    return s
  })
  /** 文件匹配全集(树侧锚点 ∪ 组件 owns)，供后缀对齐反查。 */
  const diffFileUniverse = computed<Set<string>>(() => {
    const s = new Set<string>()
    for (const a of items.value) {
      const f = a.astRefs?.[0]?.file
      if (f) s.add(f)
    }
    for (const c of treeComps.value) for (const f of c.owns) s.add(f)
    return s
  })

  /** diff 徽标文案（markAdded/markModified/markDeleted）；空 mark 返回空串。 */
  function diffMarkLabel(mark?: 'added' | 'modified' | 'deleted'): string {
    if (!mark) return ''
    return t(`assetMgmt.diff.mark${mark[0].toUpperCase()}${mark.slice(1)}`)
  }

  /** 图谱节点变更标记（按节点锚点文件）。SemanticGraphView 节点含 anchor 文件。 */
  const changedFilesForGraph = computed<Set<string>>(() => new Set(changedFileMap.value.keys()))

  /** 变更文件总数（工具栏徽标）。 */
  const totalChanged = computed(() => {
    const c = baselineDiffData.value?.counts
    return c ? c.added + c.modified + c.deleted : 0
  })

  return {
    diffMode, diffLoading, baselineDiffData, loadBaselineDiff, toggleDiffMode,
    cmpBase, cmpTarget, commitOptions, baselineSha, compareData, compareError, compareHint, compareLoading,
    loadCommitOptions, runCompare,
    extractingPending, pendingExtractable, extractPendingAndRecompare,
    changedFileMap, assetChangeMark, cmpBucketById, changeMarkById, diffFileCounts,
    treeFileOf, pendingFileSet, addedFileSet, diffFileUniverse,
    diffMarkLabel, changedFilesForGraph, totalChanged,
  }
}

import type { Ref } from 'vue'
