/**
 * 资产工作区 · 核心四元组（MS6-W1 自 AssetManagementWorkspace.vue 整块搬移，纯移动零逻辑改动）。
 *
 * data（资产整表/统计/懒加载）+ compTree（组件归属映射）+ scopeFilter（范围筛选/树层级）
 * + semanticTreeRows（目录树行/渲染窗口）——四者内部纠缠（树行读 diff/unowned 状态），
 * 整块保留单一文件；跨域引用经 D 注入袋惰性解析（computed 天然惰性）。
 */
import { computed, reactive, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { BoltIcon, CubeTransparentIcon, AdjustmentsHorizontalIcon, ServerStackIcon } from '@heroicons/vue/24/outline'
import { copyText } from '@/utils/clipboard'
import { useArchArchitectureStore } from '@/stores/architecture-store'
import { semanticAssetService } from '@/services/semantic-asset-service'
import type { SemanticStatsResult } from '@/services/semantic-asset-service'
import { kbAssetService } from '@/services/kb-assets'
import type { AssetDetail, SemanticAsset, SemanticAssetKind, SemanticAssetLevel } from '@/types'

/** 跨域注入袋：各特征域 composable 的返回在此汇合，惰性互引。 */
export interface WsDeps { [k: string]: any }

export interface CompNode { id: string; name: string; parentId?: string; owns: string[]; hierLevel?: string }
export interface SemanticGroup { key: string; name: string; depth: number; assets: SemanticAsset[]; hierLevel?: string }
export type TreeRow = { key: string; t: 'comp' | 'file' | 'asset'; depth: number;
                 g?: SemanticGroup; file?: string; n?: number; a?: SemanticAsset;
                 fk?: string; unowned?: boolean; extractable?: boolean }
export interface CompRow { comp: CompNode; depth: number }

export const OTHER_KEY = '__other__'

export function useAssetCore(D: WsDeps) {
  const { t } = useI18n()
  const arch = useArchArchitectureStore()

  // ---- 资产内容区 ----
  type AssetTab = 'overview' | 'semantic' | 'component' | 'graph'
  const tab = ref<AssetTab>('overview')
  const kind = ref<SemanticAssetKind | ''>('')
  const level = ref<SemanticAssetLevel | ''>('')
  const q = ref('')
  // shallowRef：3776+ 资产整表深代理开销可观；树按整表/整行替换更新，
  // 行内变更(refreshOne/懒加载 detail)后手动克隆数组触发。
  const items = shallowRef<SemanticAsset[]>([])
  const loading = ref(false)
  const statusCounts = ref<Record<string, number>>({})
  const expanded = reactive<Record<string, boolean>>({})
  /** 概览统计(总量/按类别/按粒度/状态)。 */
  const overviewStats = ref<SemanticStatsResult | null>(null)
  const purging = ref(false)

  const kinds: { value: SemanticAssetKind; label: string }[] = [
    { value: 'entity', label: t('assetMgmt.kind.entity') },
    { value: 'contract', label: t('assetMgmt.kind.contract') },
    { value: 'state', label: t('assetMgmt.kind.state') },
    { value: 'rule', label: t('assetMgmt.kind.rule') },
    { value: 'process', label: t('assetMgmt.kind.process') },
    { value: 'decision', label: t('assetMgmt.kind.decision') },
  ]

  const levels: { value: SemanticAssetLevel; label: string }[] = [
    { value: 'business', label: t('assetMgmt.level.business') },
    { value: 'logic', label: t('assetMgmt.level.logic') },
    { value: 'implementation', label: t('assetMgmt.level.implementation') },
  ]

  const statusText = computed(() => {
    const c = statusCounts.value
    return `active ${c.active ?? 0} · stale ${c.stale ?? 0} · deleted ${c.deleted ?? 0}`
  })

  // ---- 组件归属映射 + 组件范围筛选 + 按组件分组 ----

  /** 组件 id 层级推断：comm-<task>-incl|call-<L\d+>-… KB 社区递归细分最深到 L5，
   *  目录 hierLevel 字段缺失时按 id 兜底(实测 catalog 14 组件 hierLevel 全 None)。 */
  function compLevelFromId(id: string | undefined): string | undefined {
    if (!id) return undefined
    return /-(?:incl|call)-(L\d+)-/.exec(id)?.[1]
  }

  /** 组件目录(完整来源，跨 INCLUDE/CALL × L0/L1，与组件列表一致)。 */
  const compCatalog = ref<AssetDetail[]>([])

  async function loadCompCatalog() {
    try {
      compCatalog.value = await kbAssetService.searchComponents('')
    } catch {
      compCatalog.value = []
    }
  }

  /** 树来源：优先组件目录；目录为空(加载失败/降级)时回退架构模型快照；
   *  两者均空(如 KB 冷启动)时，从当前资产 scopeKey(comm-*) 兜底构建，保证筛选菜单不空。 */
  const treeComps = computed<CompNode[]>(() => {
    if (compCatalog.value.length) {
      return compCatalog.value.map((c) => ({ id: c.assetId, name: c.name, parentId: c.parentId ?? undefined, owns: c.owns ?? [], hierLevel: c.hierLevel ?? compLevelFromId(c.assetId) }))
    }
    if (arch.components.length) {
      return arch.components.map((c) => ({ id: c.id, name: c.name, parentId: c.parentId ?? undefined, owns: c.owns ?? [], hierLevel: (c as { hierLevel?: string }).hierLevel ?? compLevelFromId(c.id) }))
    }
    const byId = new Map<string, CompNode>()
    for (const a of items.value) {
      const sk = a.scopeKey
      if (sk && sk.startsWith('comm-') && !byId.has(sk)) {
        byId.set(sk, { id: sk, name: sk, owns: [] })
      }
    }
    return [...byId.values()]
  })

  /** 组件 id → 组件节点(归属/展示用)。 */
  const compById = computed<Map<string, CompNode>>(() => {
    const m = new Map<string, CompNode>()
    for (const c of treeComps.value) m.set(c.id, c)
    return m
  })

  /** 文件 → 拥有它的组件 id 列表(同一文件可被多组件同时拥有，如 INCLUDE/CALL 两套口径)。 */
  const fileToComps = computed(() => {
    const m = new Map<string, string[]>()
    for (const c of treeComps.value) {
      for (const f of c.owns) {
        const arr = m.get(f)
        if (arr) {
          if (!arr.includes(c.id)) arr.push(c.id)
        } else {
          m.set(f, [c.id])
        }
      }
    }
    return m
  })

  /** 语义资产归属组件 id 列表(多归属)：优先资产自带 scopeKey(若为组件) +
   *  meta.scopes 多组件归属(INCLUDE/CALL 共享代码 / business 聚合)；
   *  均未命中组件 → 按首个锚点文件反查全部拥有组件。
   *  返回空 = 无组件归属(归「其它」)。共享代码资产会同时归属多个组件，
   *  保证各组件视角(树分组/关系图)都能看到它。 */
  function componentsOf(a: SemanticAsset): string[] {
    const out: string[] = []
    const add = (cid: string | undefined | null) => {
      if (cid && compById.value.has(cid) && !out.includes(cid)) out.push(cid)
    }
    add(a.scopeKey)
    for (const cid of a.meta?.scopes ?? []) add(cid)
    if (!out.length) {
      const file = a.astRefs?.[0]?.file
      for (const cid of fileToComps.value.get(file) ?? []) add(cid)
    }
    return out
  }

  /** 递归收集子组件 id。 */
  function descendantsOf(id: string): string[] {
    const out: string[] = []
    const stack = [id]
    while (stack.length) {
      const cur = stack.pop()!
      for (const c of treeComps.value) {
        if (c.parentId === cur) {
          out.push(c.id)
          stack.push(c.id)
        }
      }
    }
    return out
  }

  function hasChildren(id: string): boolean {
    return treeComps.value.some((c) => c.parentId === id)
  }

  /** 范围筛选(空 = 全部)：组件 id + 「其它」。 */
  const scopeSel = ref<string[]>([])
  /** 组件树展开态(默认全部展开)。 */
  const compOpen = reactive<Record<string, boolean>>({})
  const filterOpen = ref(false)

  function toggleComp(id: string) {
    const ids = [id, ...descendantsOf(id)]
    const sel = new Set(scopeSel.value)
    const on = sel.has(id)
    for (const i of ids) {
      if (on) sel.delete(i)
      else sel.add(i)
    }
    scopeSel.value = [...sel]
  }

  function toggleOther() {
    const sel = new Set(scopeSel.value)
    if (sel.has(OTHER_KEY)) sel.delete(OTHER_KEY)
    else sel.add(OTHER_KEY)
    scopeSel.value = [...sel]
  }

  function clearScope() {
    scopeSel.value = []
  }

  function toggleOpen(id: string) {
    // 按有效态翻转(而非手动记录)：level<2 下未操作组件有效态=闭，首点即展开
    compOpen[id] = !compExpandState(id)
  }

  /** 树展开级别(工具栏单按钮循环)——只定义列表「默认展开态」，点击时重置手动开合，
   *  此后用户逐组件/逐文件手动开合不受层级限制(手动值 > 层级默认值)：
   *  0 全部收起(只显示顶层组件) → 1 组件展开(所有组件组头) → 2 文件展开(组件+文件) → 3 全部展开(含资产)。 */
  const treeLevel = ref(1)
  const TREE_LEVEL_MAX = 3
  function cycleTreeLevel() {
    treeLevel.value = treeLevel.value >= TREE_LEVEL_MAX ? 0 : treeLevel.value + 1
    // 重置手动开合 → 列表回到该层级的默认展开态
    for (const k of Object.keys(compOpen)) delete compOpen[k]
    for (const k of Object.keys(fileOpen)) delete fileOpen[k]
  }

  /** 组件子节点展开态：手动开合优先；未手动操作时按层级默认(level>=1 展开)。 */
  function compChildrenOpen(cid: string): boolean {
    if (compOpen[cid] === true) return true
    if (compOpen[cid] === false) return false
    return treeLevel.value >= 1
  }

  /** 组件有效展开态(箭头图标与翻转的单一事实源)：
   *  手动值优先；默认 = 有子组件且 level>=1(子头可见) 或 level>=2(文件可见)。
   *  图标态若与内容渲染不同源，就会出现"箭头开、内容闭"的错位。 */
  function compExpandState(cid: string): boolean {
    if (compOpen[cid] === true) return true
    if (compOpen[cid] === false) return false
    return (treeLevel.value >= 1 && hasChildren(cid)) || treeLevel.value >= 2
  }

  /** 文件有效展开态(同上，默认层级 3)。 */
  function fileExpandState(fk: string): boolean {
    if (fileOpen[fk] === true) return true
    if (fileOpen[fk] === false) return false
    return treeLevel.value >= 3
  }
  /** 组件内容(独有文件)展开态：手动展开跨层级生效；默认层级 2。 */
  function compContentOpen(cid: string): boolean {
    return compOpen[cid] === true || (compOpen[cid] !== false && treeLevel.value >= 2)
  }
  /** 组件直属资产展开态：手动展开跨层级生效；默认层级 3。 */
  function compDirectOpen(cid: string): boolean {
    return compOpen[cid] === true || (compOpen[cid] !== false && treeLevel.value >= 3)
  }
  /** 文件下资产展开态：手动展开跨层级生效；默认层级 3。 */
  function fileAssetsOpen(fk: string): boolean {
    return fileOpen[fk] === true || (fileOpen[fk] !== false && treeLevel.value >= 3)
  }

  /** 组件树行(DFS，父在前子在后，含缩进深度)。 */
  const compRows = computed<CompRow[]>(() => {
    const rows: CompRow[] = []
    const walk = (parentId: string | undefined, depth: number) => {
      for (const c of treeComps.value) {
        if (c.parentId !== parentId) continue
        rows.push({ comp: c, depth })
        if (compOpen[c.id] !== false) walk(c.id, depth + 1)
      }
    }
    walk(undefined, 0)
    return rows
  })

  /** 组件 id 层级映射(组件树 → L0/L1，供层级筛选)。 */
  const compHierLevel = computed<Map<string, string>>(() => {
    const m = new Map<string, string>()
    for (const c of treeComps.value) {
      if (c.hierLevel) m.set(c.id, c.hierLevel)
    }
    return m
  })

  /** 目录树行：组件(目录) / 文件 / 资产 三类节点的扁平 DFS 序列。
   *  结构 = 组件按父子层级作目录；文件挂「独有它的」组件节点(own = owns − 直接子组件 owns，
   *  被子组件拥有的文件下放到子组件)；资产挂首锚点文件下，无锚点资产挂组件直属；无归属资产归「其它」。 */
  const fileOpen = reactive<Record<string, boolean>>({})
  const subtreeCount = ref(new Map<string, number>())
  /** 组件是否有可折叠内容(组头箭头渲染依据)；随 semanticTreeRows 重算填充。 */
  const compCollapsible = ref(new Map<string, boolean>())
  /** 基线对比 · 组件子树变化上卷(组头彩色计数 chip)；随 semanticTreeRows 重算填充。 */
  const diffRollup = ref(new Map<string, { changed: number; added: number; deleted: number }>())
  function toggleFileOpen(key: string) {
    fileOpen[key] = !fileExpandState(key)
  }
  function fileBase(p: string): string {
    const i = Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\'))
    return i >= 0 ? p.slice(i + 1) : p
  }

  const semanticTreeRows = computed<TreeRow[]>(() => {
    const sel = new Set(scopeSel.value)
    const all = sel.size === 0
    // 资产分桶：首锚点文件 → byFile；无锚点 → 组件直属 direct；无归属 → other
    const byFile = new Map<string, SemanticAsset[]>()
    const direct = new Map<string, SemanticAsset[]>()
    const otherFiles = new Map<string, SemanticAsset[]>()
    const otherDirect: SemanticAsset[] = []
    for (const a of items.value) {
      const cids = componentsOf(a)
      const file = a.astRefs?.[0]?.file || ''
      if (!cids.length) {
        if (file) {
          const l = otherFiles.get(file) ?? []
          l.push(a)
          otherFiles.set(file, l)
        } else otherDirect.push(a)
        continue
      }
      const cid = a.scopeKey && cids.includes(a.scopeKey) ? a.scopeKey : cids[0]!
      if (file) {
        const l = byFile.get(file) ?? []
        l.push(a)
        byFile.set(file, l)
      } else {
        const l = direct.get(cid) ?? []
        l.push(a)
        direct.set(cid, l)
      }
    }
    const children = new Map<string, CompNode[]>()
    const roots: CompNode[] = []
    for (const c of treeComps.value) {
      const pk = c.parentId ?? ''
      const arr = children.get(pk) ?? []
      arr.push(c)
      children.set(pk, arr)
      if (!c.parentId) roots.push(c)
    }
    const uniqueFiles = (c: CompNode): string[] => {
      const sub = new Set<string>()
      for (const ch of children.get(c.id) ?? []) for (const f of ch.owns) sub.add(f)
      return c.owns.filter((f) => !sub.has(f)).sort()
    }
    // 子树资产总数(组头计数 chip，模板引用)——每次重算填充
    const counts = new Map<string, number>()
    // 组件是否有可折叠内容(子组件/资产/独有文件任一)：组头箭头渲染依据。
    // 零资产纯文件叶子组件(如未提取的 Stream 模块)没有它时箭头不渲染 → 文件行无法收拢。
    const collap = new Map<string, boolean>()
    // 基线对比 · 组件级变化归属：直接归属(资产→componentsOf 多归属，无归属→OTHER)
    // + 子树上卷(父组件头显示整个子树的彩色计数)。文件行计数走 diffFileCounts。
    const diffSums = new Map<string, { changed: number; added: number; deleted: number }>()
    const diffDirect = new Map<string, { changed: number; added: number; deleted: number }>()
    const cmpBucketById: Map<string, 'modified' | 'added' | 'deleted'> = D.diff?.cmpBucketById ?? new Map()
    if (D.diff?.diffMode.value && cmpBucketById.size) {
      const byId = new Map(items.value.map((x) => [x.id, x]))
      for (const [id, bucket] of cmpBucketById) {
        const a = byId.get(id)
        if (!a) continue
        const cids = componentsOf(a)
        for (const cid of (cids.length ? cids : [OTHER_KEY])) {
          const e = diffDirect.get(cid) ?? { changed: 0, added: 0, deleted: 0 }
          if (bucket === 'modified') e.changed += 1
          else if (bucket === 'added') e.added += 1
          else e.deleted += 1
          diffDirect.set(cid, e)
        }
      }
    }
    const diffSub = (c: CompNode): { changed: number; added: number; deleted: number } => {
      const acc = { ...(diffDirect.get(c.id) ?? { changed: 0, added: 0, deleted: 0 }) }
      for (const ch of children.get(c.id) ?? []) {
        const s = diffSub(ch)
        acc.changed += s.changed
        acc.added += s.added
        acc.deleted += s.deleted
      }
      diffSums.set(c.id, acc)
      return acc
    }
    const countSub = (c: CompNode): number => {
      const sub = new Set<string>()
      for (const ch of children.get(c.id) ?? []) for (const f of ch.owns) sub.add(f)
      let n = direct.get(c.id)?.length ?? 0
      for (const f of c.owns) if (!sub.has(f)) n += byFile.get(f)?.length ?? 0
      for (const ch of children.get(c.id) ?? []) n += countSub(ch)
      counts.set(c.id, n)
      return n
    }
    const rows: TreeRow[] = []
    const walk = (c: CompNode, depth: number) => {
      if (!(all || sel.has(c.id))) {
        // 路径节点：自身不渲染，仍下探(选中集可能命中后代)；下探条件与普通组件一致
        if (compChildrenOpen(c.id)) {
          for (const ch of children.get(c.id) ?? []) walk(ch, depth + 1)
        }
        return
      }
      countSub(c)
      collap.set(c.id, (children.get(c.id)?.length ?? 0) > 0
        || (counts.get(c.id) ?? 0) > 0 || uniqueFiles(c).length > 0)
      rows.push({ key: c.id, t: 'comp', depth,
                  g: { key: c.id, name: c.name, depth, assets: [], hierLevel: c.hierLevel } })
      const expand = compChildrenOpen(c.id)     // 子组件
      const content = compContentOpen(c.id)     // 独有文件
      if (!expand && !content) return           // 整支收起(手动关闭或层级默认收起)
      if (expand) {
        for (const ch of children.get(c.id) ?? []) walk(ch, depth + 1)
      }
      if (content) {
        for (const f of uniqueFiles(c)) {
          const fk = c.id + '::' + f
          const list = byFile.get(f) ?? []
          if (hideFileless.value && !list.length) continue
          rows.push({ key: 'f:' + fk, t: 'file', depth: depth + 1, file: f, n: list.length, fk })
          if (fileAssetsOpen(fk)) {
            for (const a of list) rows.push({ key: 'a:' + a.id + ':' + fk, t: 'asset', depth: depth + 2, a })
          }
        }
      }
      if (compDirectOpen(c.id)) {
        for (const a of direct.get(c.id) ?? []) rows.push({ key: 'a:' + a.id, t: 'asset', depth: depth + 1, a })
      }
    }
    for (const r of roots) { walk(r, 0); diffSub(r) }
    // 「未归属」组(单一分组)：KB owns 未覆盖的文件 ∪ 无组件归属的孤儿资产。
    // 文件并集去重——已提取资产挂其锚点文件下(与组件组同构)；仅存在于 owns 缺口
    // 清单的文件显示「未提取」。同受组头开合(compOpen)与树层级(treeLevel)控制。
    // ⚠️ D 为普通对象(非 reactive)，跨域 ref 须显式 .value——MS6-W1 搬移漏改，
    // 孤儿资产为空时 if 不进入而静默失效，非空即 .map 崩(实测 2026-09-29)。
    const unownedFiles: UnownedFileEntryLite[] = D.unowned?.unownedFiles?.value ?? []
    if ((otherFiles.size || otherDirect.length || unownedFiles.length)
        && (all || sel.has(OTHER_KEY))) {
      const fileAssets = new Map<string, SemanticAsset[]>(otherFiles)
      const unownedEntry = new Map(unownedFiles.map((x) => [x.path, x]))
      for (const f of unownedFiles) {
        if (!fileAssets.has(f.path)) fileAssets.set(f.path, [])
      }
      counts.set(OTHER_KEY, fileAssets.size + otherDirect.length)
      collap.set(OTHER_KEY, true)
      diffSums.set(OTHER_KEY, diffDirect.get(OTHER_KEY) ?? { changed: 0, added: 0, deleted: 0 })
      rows.push({ key: OTHER_KEY, t: 'comp', depth: 0,
                  g: { key: OTHER_KEY, name: t('assetMgmt.unownedFiles'), depth: 0, assets: [] } })
      if (compContentOpen(OTHER_KEY)) {
        for (const f of [...fileAssets.keys()].sort()) {
          const fk = OTHER_KEY + '::' + f
          const list = fileAssets.get(f) ?? []
          if (hideFileless.value && !list.length) continue
          rows.push({ key: 'f:' + fk, t: 'file', depth: 1, file: f, n: list.length,
                      fk, unowned: true, extractable: unownedEntry.get(f)?.extractable })
          if (fileAssetsOpen(fk)) {
            for (const a of list) rows.push({ key: 'a:' + a.id + ':' + fk, t: 'asset', depth: 2, a })
          }
        }
      }
      if (compDirectOpen(OTHER_KEY)) {
        for (const a of otherDirect) rows.push({ key: 'a:' + a.id, t: 'asset', depth: 1, a })
      }
    }
    subtreeCount.value = counts
    compCollapsible.value = collap
    diffRollup.value = diffSums
    return rows
  })

  const scopeSummary = computed(() => {
    if (!scopeSel.value.length) return t('assetMgmt.scopeAll')
    // 命中/全量：分母用全库总数(stats)，而非过滤后的列表长(否则恒 x/x 无意义)
    const total = overviewStats.value?.total ?? items.value.length
    return `${items.value.length}/${total}`
  })

  /** 当前筛选的 scope 请求参数(组件 id + 「其它」哨兵)；空=全部。 */
  function scopeParams(): string[] | undefined {
    if (!scopeSel.value.length) return undefined
    const out = [...scopeSel.value]
    return out
  }

  async function loadSemantic() {
    loading.value = true
    try {
      // 树形分组视图(按组件逐层展开)必须全量加载——分页会把组内条目截断到单页，
      // 组头计数与低序组件组显示错误(后端 _grouped_search_items 本就全量排序后返回)。
      // ⚠️ 单页拉全(页大小 10000, cap 20000)：后端本就全量排序后切片，两页各跑一遍
      // 全量(取数+分组+count)纯属重复——实测单请求省 ~1.5s。>10000 时循环仍可续页。
      const PAGE = 10000
      const CAP = 20000
      let all: SemanticAsset[] = []
      let total = 0
      for (let offset = 0; offset < CAP; offset += PAGE) {
        const r = await semanticAssetService.searchPage(q.value, kind.value || undefined, {
          limit: PAGE, offset,
          scope: scopeParams(), level: level.value || undefined,
        })
        all = all.concat(r.items)
        total = r.total
        if (all.length >= total || !r.items.length) break
      }
      items.value = all
    } finally {
      loading.value = false
    }
  }

  /** 概览统计：语义资产总量/类别/粒度/状态。 */
  async function loadOverview() {
    try {
      overviewStats.value = await semanticAssetService.stats()
    } catch {
      overviewStats.value = null
    }
  }

  /** 文件源码资产卡：列表文件行打开(复用图谱卡同批服务/缓存，无图谱联动)。 */
  const fileCard = ref<{ file: string; assets: SemanticAsset[] } | null>(null)
  function openFileCard(file: string) {
    const seen = new Set<string>()
    const assets = items.value.filter((x) => !seen.has(x.id) && (x.astRefs ?? []).some((r) => r.file === file) && seen.add(x.id))
    fileCard.value = { file, assets }
  }
  /** 卡内「在列表定位」：按资产 id 过滤列表并关卡。 */
  function locateAsset(id: string) {
    q.value = id
    onSearch()
    fileCard.value = null
  }

  async function refreshStatus() {
    try {
      const s = await semanticAssetService.status()
      statusCounts.value = s.counts
    } catch {
      /* ignore */
    }
  }

  async function refreshOne(a: SemanticAsset) {
    try {
      const res = await semanticAssetService.refreshAsset(a.id)
      if (res.asset) {
        const i = items.value.findIndex((x) => x.id === a.id)
        if (i >= 0) {
          items.value[i] = { ...items.value[i], ...res.asset }
          items.value = [...items.value]
        }
      } else if (res.status === 'deleted') {
        const i = items.value.findIndex((x) => x.id === a.id)
        if (i >= 0) {
          items.value[i] = { ...items.value[i], status: 'deleted', needsUpdate: 1 }
          items.value = [...items.value]
        }
      }
      await refreshStatus()
    } catch (err: any) {
      console.warn('[asset-mgmt] refresh failed:', err)
    }
  }

  function usable(a: SemanticAsset): boolean {
    return a.status !== 'stale' && a.status !== 'deleted' && !a.needsUpdate
  }

  // 展开卡懒加载 detail：列表(light 模式)不带 detail 大字段；首次展开时
  // 单查 /{id} 回填。detailDone 含"已确认无 detail"的行，避免重复请求。
  const detailLoading = reactive<Record<string, boolean>>({})

  const descLoading = reactive<Record<string, boolean>>({})

  /** 全部展开时行数可达数千，逐行 DOM 令布局/绘制过载 → 前缀窗口渲染：
   * 只挂载前 renderCap 行，滚动接近底部由哨兵增量放行；筛选/搜索使行数收缩时
   * 窗口自动收敛。与 scope/kind/搜索/树层级天然兼容(同源 semanticTreeRows)。 */
  const RENDER_INIT = 400
  const RENDER_STEP = 300
  const renderCap = ref(RENDER_INIT)
  const renderedTreeRows = computed(() => semanticTreeRows.value.slice(0, renderCap.value))
  watch(() => semanticTreeRows.value.length, (n) => {
    if (n < renderCap.value) renderCap.value = Math.max(RENDER_INIT, n)
  })
  const semScrollEl = ref<HTMLElement | null>(null)
  const loadMoreSentinel = ref<HTMLElement | null>(null)

  /** 按需生成功能摘要(分层口径: 批量提取不产 desc)。
   *  fresh 缓存由后端直返；腐烂(需更新)资产后端自动重生成。 */
  async function genDesc(a: SemanticAsset) {
    if (descLoading[a.id]) return
    descLoading[a.id] = true
    try {
      const r = await semanticAssetService.assetDesc(a.id)
      a.desc = r.desc || ''
    } catch { /* 失败留按钮可重试 */ } finally {
      descLoading[a.id] = false
    }
  }
  const detailDone = new Set<string>()
  async function toggle(id: string) {
    expanded[id] = !expanded[id]
    if (!expanded[id] || detailDone.has(id)) return
    const i = items.value.findIndex((x) => x.id === id)
    if (i < 0 || items.value[i]!.detail !== undefined) {
      detailDone.add(id)
      return
    }
    detailLoading[id] = true
    try {
      const full = await semanticAssetService.detail(id)
      const j = items.value.findIndex((x) => x.id === id)
      if (j >= 0) {
        items.value[j] = { ...items.value[j], detail: full?.detail }
        items.value = [...items.value]
      }
    } catch {
      /* 详情加载失败静默：展开块仅缺 fields/steps 等小节 */
    } finally {
      detailDone.add(id)
      detailLoading[id] = false
    }
  }

  /** 范围筛选 · 隐藏无资产文件：文件行(含未提取的未归属文件)无资产时不渲染。 */
  const hideFileless = ref(false)

  function onSearch() {
    if (tab.value === 'graph') return
    if (tab.value === 'overview') {
      loadOverview()
      D.framework?.loadCoverage()
    } else {
      loadSemantic()
    }
  }

  /** 组件元数据（owns/dependsOn 摘要，供组头 tooltip）。 */
  function compMetaText(compId: string): string {
    const c = compById.value.get(compId)
    if (!c) return ''
    const parts: string[] = []
    if (c.owns?.length) parts.push(`owns: ${c.owns.slice(0, 6).join(', ')}${c.owns.length > 6 ? '…' : ''}`)
    if (c.parentId) parts.push(`parent: ${compById.value.get(c.parentId)?.name ?? c.parentId}`)
    return parts.join(' · ')
  }

  // ---- 组件「拷贝/引用 名称+ID」快捷操作（与 KB 组件目录严格同名同 ID，供对话精准对接）----
  /** 统一引用格式：`名称 (comm-…)`——agent 工具按名称/ID 双向可解析。 */
  function compRefText(name: string, id: string): string {
    return `${name} (${id})`
  }

  // ---- 视图辅助(模板直接消费；MS6-W1 自 SFC 移入——树面板共用) ----
  function kindIcon(k: SemanticAsset['kind']) {
    if (k === 'process') return BoltIcon
    if (k === 'decision') return AdjustmentsHorizontalIcon
    if (k === 'contract') return ServerStackIcon
    if (k === 'state') return AdjustmentsHorizontalIcon
    return CubeTransparentIcon
  }

  async function copyAsset(a: SemanticAsset) {
    const lines = [`${a.name} (${a.kind})`, `ID: ${a.id}`, a.desc]
    if (a.astRefs?.length) {
      lines.push('')
      lines.push(...a.astRefs.slice(0, 10).map((r) => `${r.file}:L${r.startLine}-L${r.endLine} ${r.symbol}`))
    }
    await copyText(lines.join('\n'))
  }

  return {
    tab, kind, level, q, items, loading, statusCounts, expanded, overviewStats, purging,
    kinds, levels, statusText,
    compCatalog, loadCompCatalog, treeComps, compById, fileToComps,
    componentsOf, descendantsOf, hasChildren, compLevelFromId,
    scopeSel, compOpen, filterOpen, toggleComp, toggleOther, clearScope, toggleOpen,
    treeLevel, cycleTreeLevel, compChildrenOpen, compExpandState, fileExpandState,
    compContentOpen, compDirectOpen, fileAssetsOpen,
    compRows, compHierLevel, fileOpen, subtreeCount, compCollapsible, diffRollup,
    toggleFileOpen, fileBase, semanticTreeRows, scopeSummary, scopeParams,
    loadSemantic, loadOverview, fileCard, openFileCard, locateAsset,
    refreshStatus, refreshOne, usable, detailLoading, descLoading,
    renderCap, renderedTreeRows, semScrollEl, loadMoreSentinel,
    genDesc, toggle, detailDone, hideFileless, onSearch,
    compMetaText, compRefText, kindIcon, copyAsset,
  }
}

/** 未归属清单条目的最小形状(unowned 域回填前树行计算可先跑)。 */
export interface UnownedFileEntryLite { path: string; extractable?: boolean; [k: string]: unknown }
