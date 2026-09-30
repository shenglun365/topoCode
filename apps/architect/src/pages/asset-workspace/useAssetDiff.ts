/**
 * 资产工作区 · 基线对比域（MS6-W1 自 AssetManagementWorkspace.vue 搬移；常驻化改造）。
 * 基准固定 = KB 基线(baselineCommit)；对比目标可选(工作区默认/任意提交)。
 * 三视图 diff 叠加(概览卡/语义行徽标/图谱着色)常驻生效，无开关。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { semanticAssetService } from '@/services/semantic-asset-service'
import type { AssetCompareResult, BaselineDiff } from '@/services/semantic-asset-service'
import { gitService, type GitLogEntry } from '@/services/git-service'
import type { SemanticAsset } from '@/types'
import type { WsDeps } from './useAssetCore'

export function useAssetDiff(D: WsDeps) {
  const { t } = useI18n()
  const core = D.core
  const items = core.items as Ref<SemanticAsset[]>
  const treeComps = core.treeComps

  // ---- 基线对比（常驻：基线 lastHead → 工作区 变更文件集）----
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

  /** 常驻初始化（页面挂载 idle 调用）：变更集 + 提交选项 + 首次对比。 */
  function initCompare() {
    loadBaselineDiff()
    void loadCommitOptions()
    void runCompare()
  }

  // ---- 资产/组件对比：基准固定=KB 基线(baselineCommit)，目标可选(缓存态) ----
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
        undefined,
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

  // ---- 提取范围弹窗（交互提取闭环共用：本域入口 + 按组件/按文件经 ctx 复用） ----
  const scopeModal = ref<{ open: boolean; title: string; files: string[] }>(
    { open: false, title: '', files: [] })
  let scopeResolver: ((files: string[] | null) => void) | null = null
  /** 弹窗选择提取范围；resolve 选中的文件（取消 → null）。 */
  function pickScope(title: string, files: string[]): Promise<string[] | null> {
    scopeModal.value = { open: true, title, files }
    return new Promise((resolve) => { scopeResolver = resolve })
  }
  function confirmScope(files: string[]): void {
    scopeModal.value.open = false
    scopeResolver?.(files)
    scopeResolver = null
  }
  function cancelScope(): void {
    scopeModal.value.open = false
    scopeResolver?.(null)
    scopeResolver = null
  }

  /** 轮询作业至终态（任务中心可见进度；完成/失败分别回执）。 */
  async function waitForJob(jobId: string, timeoutMs = 10 * 60 * 1000): Promise<{ ok: boolean; summary?: string; error?: string }> {
    const t0 = Date.now()
    while (Date.now() - t0 < timeoutMs) {
      await new Promise((r) => setTimeout(r, 2000))
      try {
        const j = await semanticAssetService.getJob(jobId)
        if (!j) break
        if (j.state === 'done') return { ok: true, summary: j.result?.summary }
        if (j.state === 'failed') return { ok: false, error: j.result?.summary || 'failed' }
        if (j.state === 'cancelled' || j.state === 'lost') return { ok: false, error: j.state }
      } catch { /* 轮询失败静默重试 */ }
    }
    return { ok: false, error: 'timeout' }
  }

  /** 提交范围提取作业并等待完成；返回 saved 数（-1 = 失败/未启动）。 */
  async function runScopeJob(files: string[]): Promise<number> {
    const r = await semanticAssetService.startExtractScope({ scopeType: 'files', files })
    const jobId = r?.job?.id
    if (!r?.started || !jobId) {
      compareError.value = t('assetMgmt.diff.cmpFailed')
      return -1
    }
    const done = await waitForJob(jobId)
    if (!done.ok) {
      compareError.value = done.error === 'timeout'
        ? t('assetMgmt.diff.jobTimeout') : (done.error || t('assetMgmt.diff.cmpFailed'))
      return -1
    }
    return 1
  }

  async function extractPendingAndRecompare(preselected?: string[]) {
    let files = preselected
    if (!files) {
      files = pendingExtractable.value
      if (!files.length) return
      files = await pickScope(t('assetMgmt.diff.extractScopeTitle'), files) ?? []
    }
    if (!files.length) return
    extractingPending.value = true
    try {
      // ① 基准侧资产缺失 → 先基线提取（rev=baselineCommit 的结构化作业，rev 内容锚定），
      //    完成后再走目标侧提取与比对（需求：校验基线资产，无则先提取基线再比对）
      const cmp = compareData.value
      if (cmp?.baseAssetsMissing && baselineSha.value) {
        const baselineFiles = files.filter((f) => cmp.files.modified.includes(f))
        if (baselineFiles.length) {
          compareHint.value = t('assetMgmt.diff.baselineExtracting', { n: baselineFiles.length })
          const r = await semanticAssetService.startExtractImpl({ rev: baselineSha.value, files: baselineFiles })
          if (r?.started && r.job?.id) {
            const done = await waitForJob(r.job.id)
            if (!done.ok) {
              compareError.value = done.error === 'timeout'
                ? t('assetMgmt.diff.jobTimeout') : (done.error || t('assetMgmt.diff.cmpFailed'))
              return
            }
          }
          compareHint.value = ''
        }
      }
      // ② 目标侧补提（LLM 范围提取作业；任务中心可见进度）
      const extracted = await runScopeJob(files)
      if (extracted < 0) return
      // ③ 重新对比
      await Promise.all([core.loadSemantic(), runCompare()])
    } catch (e) {
      compareError.value = e instanceof Error && e.message ? e.message : t('assetMgmt.diff.cmpFailed')
    } finally {
      extractingPending.value = false
    }
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

  /** 资产 id → 变更类别（语义行徽标渲染入口：对比数据/变更集变化时统一重算一次）。
   *  对比口径(compare)优先：资产级 side/strong 判定精确到符号段，文件级口径仅兜底。 */
  const cmpBucketById = computed<Map<string, 'modified' | 'added' | 'deleted'>>(() => {
    const m = new Map<string, 'modified' | 'added' | 'deleted'>()
    const c = compareData.value
    if (!c) return m
    for (const a of c.assets.changed) m.set(a.id, 'modified')
    for (const a of c.assets.new) m.set(a.id, 'added')
    for (const a of c.assets.removed) m.set(a.id, 'deleted')
    return m
  })

  const changeMarkById = computed<Map<string, 'added' | 'modified' | 'deleted'>>(() => {
    const m = new Map<string, 'added' | 'modified' | 'deleted'>()
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
    if (compareData.value) {
      for (const f of compareData.value.assets.pending.files) {
        const t = treeFileOf(f)
        if (t) s.add(t)
      }
    }
    return s
  })
  const addedFileSet = computed<Set<string>>(() => {
    const s = new Set<string>()
    if (compareData.value) {
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
    diffLoading, baselineDiffData, loadBaselineDiff, initCompare,
    cmpTarget, commitOptions, baselineSha, compareData, compareError, compareHint, compareLoading,
    loadCommitOptions, runCompare,
    scopeModal, pickScope, confirmScope, cancelScope, waitForJob,
    extractingPending, pendingExtractable, extractPendingAndRecompare,
    changedFileMap, assetChangeMark, cmpBucketById, changeMarkById, diffFileCounts,
    treeFileOf, pendingFileSet, addedFileSet, diffFileUniverse,
    diffMarkLabel, changedFilesForGraph, totalChanged,
  }
}

import type { Ref } from 'vue'
