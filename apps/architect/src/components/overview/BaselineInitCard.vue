<script setup lang="ts">
/**
 * 概览页「基线设定」卡片 —— 三通道状态识别 + 操作按钮组:
 * - git: 仓库状态 + HEAD + 基线落后提示 → 「初始化 git / 更新基线」
 * - codegraph: CLI 索引新鲜度 → 「同步索引」(ensure_synced 检测+init/sync)
 * - 基线设定: 自管基线锚(arch.graphBaseline) + 图谱计数 → 「刷新基线」
 *   (本地编排 采集→分组→命名, 数据主权批E)
 * 组件命名状态展示在「组件变更情况」面板(ProjectOverviewPage)。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDownIcon, CircleStackIcon, BoltIcon, CodeBracketIcon, ArrowPathIcon } from '@heroicons/vue/24/outline'
import { projectService } from '@/services/project-service'
import { semanticAssetService, type CollectGraphStatus } from '@/services/semantic-asset-service'
import type { GitCommitInfo } from '@/types'
import type { GitInfoLite } from '@/types'

const { t } = useI18n()
const emit = defineEmits(['refreshed'])

const git = ref<GitInfoLite | null>(null)
const cg = ref<Awaited<ReturnType<typeof semanticAssetService.codegraphStatus>> | null>(null)
const base = ref<CollectGraphStatus | null>(null)

const gitBusy = ref(false)
const cgBusy = ref(false)
const cgMsg = ref('')
const baseBusy = ref(false)
const baseMsg = ref('')

/** 基线已设定 = 自管锚存在。 */
const baselineSet = computed(() => !!base.value?.anchor?.head)

function fmtAnchorTime(at?: number) {
  if (!at) return ''
  try { return new Date(at).toLocaleString() } catch { return '' }
}

// ── 基线锚定选单(数据主权批E): 基线行点击 → 基线后提交探测列表 → 选定锚定 ──
const anchorHead = ref('')
const pickerOpen = ref(false)
const pickerLoading = ref(false)
const pickerList = ref<GitCommitInfo[]>([])

/** 打开探测列表: 基线(since=当前锚 head)后提交, 最新 10 条, 滚动选单。 */
async function openPicker() {
  pickerOpen.value = !pickerOpen.value
  if (!pickerOpen.value) return
  pickerLoading.value = true
  try {
    const git = await projectService.gitInfo()
    pickerList.value = (git?.log ?? []).filter((c) => c.hash !== base.value?.anchor?.head)
  } catch {
    pickerList.value = []
  } finally {
    pickerLoading.value = false
  }
}

function pickAnchor(c: GitCommitInfo) {
  anchorHead.value = c.hash
  pickerOpen.value = false
  baseMsg.value = t('overviewHome.baselineInit.anchorPicked', { msg: c.message.slice(0, 24) })
}

function clearAnchor() {
  anchorHead.value = ''
}

function fmtCommitDate(ts: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return `${d.getMonth() + 1}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** 基线落后(HEAD 领先已设定基线) —— 更新基线按钮的显示条件。 */
const baselineBehind = computed(() =>
  !!cg.value?.state?.stale)

async function loadGit() {
  git.value = await projectService.gitInfo().catch(() => null)
}
async function loadCg() {
  cg.value = await semanticAssetService.codegraphStatus().catch(() => undefined) ?? null
}
async function loadBase() {
  base.value = await semanticAssetService.collectGraphStatus().catch(() => undefined) ?? null
}
/** 静默自动同步: CLI 可用即后台 ensure_synced(检测+init/sync), 完成刷新。 */
async function autoSyncCg() {
  const st = await semanticAssetService.codegraphStatus().catch(() => null)
  if (!st?.cli) return
  await semanticAssetService.codegraphSync().catch(() => null)
  await loadCg()
}
const initialLoaded = ref(false)
async function loadAll() {
  await Promise.allSettled([loadGit(), loadCg(), loadBase()])
  initialLoaded.value = true
}
onMounted(() => { void loadAll(); void autoSyncCg() })

async function initGit() {
  gitBusy.value = true
  try {
    await projectService.initGit()
    await loadGit()
  } finally {
    gitBusy.value = false
  }
}

async function syncCodegraph() {
  cgBusy.value = true
  cgMsg.value = ''
  try {
    // 真同步 codegraph CLI 索引(检测+init/sync, 本地快操作)
    const r = await semanticAssetService.codegraphSync()
    cgMsg.value = r?.synced ? '' : (r?.message || '同步失败')
    await loadCg()
  } catch (e: any) {
    cgMsg.value = e?.message || String(e)
  } finally {
    cgBusy.value = false
  }
}

/** 基线刷新(数据主权批E): 本地编排 采集→分组→命名, 轮询至终态。
 *  anchorHead 可选——把基线锚定到选定提交(缺省=工作区 HEAD)。 */
async function refreshBaseline() {
  baseBusy.value = true
  baseMsg.value = t('overviewHome.baselineInit.baseRefreshing')
  try {
    const r = await semanticAssetService.baselineRefresh(false, anchorHead.value || undefined)
    if (!r?.started) {
      baseMsg.value = r?.reason || r?.message || ''
      return
    }
    // 轮询编排作业直至终态(240 轮 × 2.5s = 10 分钟上限)
    for (let i = 0; i < 240; i++) {
      await new Promise((res) => setTimeout(res, 2500))
      const st = await semanticAssetService.baselineRefreshStatus().catch(() => undefined)
      const job = st?.latest
      if (job?.state === 'done' || job?.state === 'failed' || job?.state === 'cancelled') break
      if (job?.progress?.current) baseMsg.value = job.progress.current
    }
    await loadBase(); await loadCg()
    emit('refreshed')   // 通知父页面重载(概览 diff/组件树/命名状态随新基线更新)
    const st = await semanticAssetService.baselineRefreshStatus().catch(() => undefined)
    const latest = st?.latest
    if (latest?.state === 'failed') {
      const steps = (latest.result?.steps ?? {}) as Record<string, { error?: string }>
      const stepErr = Object.values(steps).find((x) => x?.error)?.error
      const summary = (latest.result as { summary?: string } | undefined)?.summary
      baseMsg.value = stepErr || summary || t('overviewHome.baselineInit.baseFailed')
    } else {
      baseMsg.value = t('overviewHome.baselineInit.baseSet')
    }
  } catch (e: any) {
    baseMsg.value = e?.message || String(e)
  } finally {
    baseBusy.value = false
  }
}
</script>

<template>
  <section class="panel p-5">
    <div class="flex items-center gap-2 mb-4">
      <CircleStackIcon class="w-4 h-4 text-ctp-mauve" />
      <span class="text-sm font-medium text-ctp-text">{{ t('overviewHome.baselineInit.title') }}</span>
      <span class="text-[10px] text-ctp-overlay0">{{ t('overviewHome.baselineInit.desc') }}</span>
    </div>

    <!-- git: 仓库状态 + HEAD + 基线落后(行末: 初始化/更新基线) -->
    <div class="flex items-center gap-3 py-2 border-t border-ctp-surface0 text-xs">
      <CodeBracketIcon class="w-4 h-4 text-ctp-blue shrink-0" />
      <span class="w-20 text-ctp-overlay1 shrink-0">git</span>
      <span v-if="git === null && !initialLoaded" class="text-ctp-overlay0 animate-pulse">{{ t('app.loading') }}</span>
      <span v-else-if="git?.isRepo" class="text-ctp-green font-mono">
        {{ git.branch || 'main' }}<span v-if="git.dirty" class="text-ctp-peach"> · {{ t('overviewHome.dirty') }}</span>
      </span>
      <span v-else class="text-ctp-peach">{{ t('overviewHome.baselineInit.gitMissing') }}</span>
      <span v-if="cg?.state?.head" class="font-mono text-ctp-overlay0" :title="cg.state.head">{{ cg.state.head.slice(0, 7) }}</span>
      <span v-if="baselineBehind" class="text-ctp-peach shrink-0">
        {{ t('overviewHome.baselineInit.baselineBehind', { n: cg?.state?.staleCount ?? 0 }) }}
      </span>
      <span
        v-if="git?.isRepo"
        class="chip shrink-0"
        :class="git?.remoteUrl ? 'bg-ctp-sky/15 text-ctp-sky' : 'bg-ctp-surface0 text-ctp-subtext1'"
        :title="git?.remoteUrl || git?.root"
      >{{ git?.remoteUrl ? t('overviewHome.baselineInit.repoRemote') : t('overviewHome.baselineInit.repoLocal') }}</span>
      <span v-if="baseMsg" class="text-ctp-overlay0 truncate max-w-[16rem]" :title="baseMsg">{{ baseMsg }}</span>
      <span class="flex-1" />
      <button
        v-if="baselineBehind"
        class="btn !py-1 !px-3 !text-xs"
        :disabled="baseBusy"
        @click="refreshBaseline"
      >{{ t('overviewHome.baselineInit.baselineUpdate') }}</button>
      <button
        v-if="git && !git.isRepo"
        class="btn !py-1 !px-3 !text-xs"
        :disabled="gitBusy"
        @click="initGit"
      ><ArrowPathIcon v-if="gitBusy" class="w-3.5 h-3.5 animate-spin" />{{ gitBusy ? t('overviewHome.baselineInit.working') : t('overviewHome.baselineInit.gitInit') }}</button>
    </div>

    <!-- codegraph: 纯 CLI 索引语义(检测+同步; mount 时自动静默同步) -->
    <div class="flex items-center gap-3 py-2 border-t border-ctp-surface0 text-xs">
      <BoltIcon class="w-4 h-4 text-ctp-yellow shrink-0" />
      <span class="w-20 text-ctp-overlay1 shrink-0">codegraph</span>
      <span v-if="cg === null && !initialLoaded" class="text-ctp-overlay0 animate-pulse">{{ t('app.loading') }}</span>
      <span v-else-if="!cg?.cli" class="text-ctp-peach">{{ t('overviewHome.baselineInit.cgNoCli') }}</span>
      <span v-else-if="(cg?.native?.nodes ?? 0) > 0" class="text-ctp-green">
        {{ t('overviewHome.baselineInit.cgLinked') }} {{ cg?.native?.nodes }} {{ t('overviewHome.baselineInit.cgNodes') }}
      </span>
      <span v-else class="text-ctp-overlay0">{{ t('overviewHome.baselineInit.cgIdle') }}</span>
      <span v-if="cgMsg" class="text-ctp-overlay0 truncate max-w-[16rem]" :title="cgMsg">{{ cgMsg }}</span>
      <span class="flex-1" />
      <button
        v-if="cg?.cli"
        class="btn !py-1 !px-3 !text-xs"
        :disabled="cgBusy"
        @click="syncCodegraph"
      ><ArrowPathIcon v-if="cgBusy" class="w-3.5 h-3.5 animate-spin" />{{ cgBusy ? t('overviewHome.baselineInit.working') : t('overviewHome.baselineInit.cgSync') }}</button>
    </div>

    <!-- 基线设定: 自管基线锚(arch.graphBaseline) + 图谱计数 → 刷新基线 -->
    <div class="flex items-center gap-3 py-2 border-t border-ctp-surface0 text-xs">
      <CircleStackIcon class="w-4 h-4 text-ctp-mauve shrink-0" />
      <span class="w-20 text-ctp-overlay1 shrink-0">{{ t('overviewHome.baselineInit.baseRow') }}</span>
      <span v-if="baselineSet" class="text-ctp-green">
        {{ t('overviewHome.baselineInit.baseSet') }}
        <span v-if="(base?.counts?.nodes ?? 0) > 0" class="text-ctp-overlay0">
          · {{ base?.counts?.nodes }} {{ t('overviewHome.baselineInit.baseNodes') }}
          · {{ base?.counts?.edges }} {{ t('overviewHome.baselineInit.baseEdges') }}
        </span>
        <!-- 分支 + 锚定 head(可点击弹出探测选单) -->
        <span class="text-ctp-overlay0"> ·</span>
        <span class="font-mono text-ctp-subtext1">{{ git?.branch || 'main' }}</span>
        <span class="relative">
          <button
            class="font-mono text-ctp-mauve hover:text-ctp-pink underline decoration-dotted underline-offset-2"
            :title="t('overviewHome.baselineInit.anchorPickHint')"
            @click="openPicker"
          >{{ (anchorHead || base?.anchor?.head || '')?.slice(0, 7) }}<ChevronDownIcon class="w-3 h-3 inline ml-0.5" /></button>
          <!-- 探测选单: 基线后提交(最新 10 条, 滚动) -->
          <div
            v-if="pickerOpen"
            class="absolute right-0 top-6 z-30 w-[26rem] max-h-72 overflow-y-auto rounded-lg border border-ctp-surface1 bg-ctp-base shadow-xl"
          >
            <div class="px-3 py-2 text-[10px] text-ctp-overlay1 border-b border-ctp-surface0 sticky top-0 bg-ctp-base">
              {{ t('overviewHome.baselineInit.anchorPickTitle') }}
            </div>
            <p v-if="pickerLoading" class="px-3 py-3 text-xs text-ctp-overlay0">{{ t('app.loading') }}</p>
            <p v-else-if="!pickerList.length" class="px-3 py-3 text-xs text-ctp-overlay0">{{ t('overviewHome.baselineInit.anchorPickEmpty') }}</p>
            <button
              v-for="c in pickerList"
              :key="c.hash"
              class="w-full text-left px-3 py-2 hover:bg-ctp-surface0 border-b border-ctp-surface0/50"
              @click="pickAnchor(c)"
            >
              <div class="flex items-center gap-2">
                <span class="font-mono text-[11px] text-ctp-mauve">{{ c.short }}</span>
                <span v-if="c.isHead" class="chip bg-ctp-blue/15 text-ctp-blue !text-[9px]">HEAD</span>
                <span class="text-[10px] text-ctp-overlay0">{{ fmtCommitDate(c.date) }}</span>
                <span class="text-[10px] text-ctp-overlay0 ml-auto">{{ c.author }}</span>
              </div>
              <div class="text-xs text-ctp-text truncate">{{ c.message }}</div>
            </button>
          </div>
        </span>
        <button
          v-if="anchorHead"
          class="text-[10px] text-ctp-peach hover:underline shrink-0"
          :title="t('overviewHome.baselineInit.anchorClearHint')"
          @click="clearAnchor"
        >{{ t('overviewHome.baselineInit.anchorClear') }}</button>
      </span>
      <span v-else-if="base === null && !initialLoaded" class="text-ctp-overlay0 animate-pulse">{{ t('app.loading') }}</span>
      <span v-else class="text-ctp-peach">{{ t('overviewHome.baselineInit.baseUnset') }}</span>
      <span v-if="baseMsg" class="text-ctp-overlay0 truncate max-w-[16rem]" :title="baseMsg">{{ baseMsg }}</span>
      <span class="flex-1" />
      <button
        class="btn !py-1 !px-3 !text-xs"
        :class="baselineSet ? 'btn-ghost' : 'btn-primary'"
        :disabled="baseBusy"
        :title="anchorHead ? t('overviewHome.baselineInit.anchorActiveHint', { head: anchorHead.slice(0, 7) }) : ''"
        @click="refreshBaseline"
      ><ArrowPathIcon v-if="baseBusy" class="w-3.5 h-3.5 animate-spin" />{{ baseBusy ? t('overviewHome.baselineInit.working') : (baselineSet ? t('overviewHome.baselineInit.baseRefresh') : t('overviewHome.baselineInit.baseInit')) }}</button>
    </div>
  </section>
</template>
