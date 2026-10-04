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
import { CircleStackIcon, BoltIcon, CodeBracketIcon, ArrowPathIcon } from '@heroicons/vue/24/outline'
import { projectService } from '@/services/project-service'
import { semanticAssetService, type CollectGraphStatus } from '@/services/semantic-asset-service'
import type { GitInfoLite } from '@/types'

const { t } = useI18n()

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
function loadAll() {
  void loadGit(); void loadCg(); void loadBase()
}
onMounted(() => { loadAll(); void autoSyncCg() })

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

/** 基线刷新(数据主权批E): 本地编排 采集→分组→命名, 轮询至终态。 */
async function refreshBaseline() {
  baseBusy.value = true
  baseMsg.value = t('overviewHome.baselineInit.baseRefreshing')
  try {
    const r = await semanticAssetService.baselineRefresh()
    if (!r?.started) {
      baseMsg.value = r?.reason || r?.message || ''
      return
    }
    // 轮询编排作业直至终态(240 轮 × 2.5s = 10 分钟上限)
    for (let i = 0; i < 240; i++) {
      await new Promise((res) => setTimeout(res, 2500))
      const st = await semanticAssetService.baselineRefreshStatus().catch(() => undefined)
      const job = st?.latest
      if (job?.status === 'done' || job?.status === 'error' || job?.status === 'cancelled') break
      if (job?.message) baseMsg.value = job.message
    }
    await loadBase(); await loadCg()
    const st = await semanticAssetService.baselineRefreshStatus().catch(() => undefined)
    baseMsg.value = st?.latest?.status === 'error'
      ? (st.latest?.error || t('overviewHome.baselineInit.baseFailed'))
      : ''
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
      <span v-if="git?.isRepo" class="text-ctp-green font-mono">
        {{ git.branch || 'main' }}<span v-if="git.dirty" class="text-ctp-peach"> · {{ t('overviewHome.dirty') }}</span>
      </span>
      <span v-else class="text-ctp-peach">{{ t('overviewHome.baselineInit.gitMissing') }}</span>
      <span v-if="cg?.state?.head" class="font-mono text-ctp-overlay0" :title="cg.state.head">{{ cg.state.head.slice(0, 7) }}</span>
      <span v-if="baselineBehind" class="text-ctp-peach shrink-0">
        {{ t('overviewHome.baselineInit.baselineBehind', { n: cg?.state?.staleCount ?? 0 }) }}
      </span>
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
      <span v-if="!cg?.cli" class="text-ctp-peach">{{ t('overviewHome.baselineInit.cgNoCli') }}</span>
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
        <span v-if="base?.anchor?.at" class="font-mono text-ctp-overlay0" :title="fmtAnchorTime(base.anchor.at)">
          · {{ base.anchor.head?.slice(0, 7) }}
        </span>
      </span>
      <span v-else class="text-ctp-peach">{{ t('overviewHome.baselineInit.baseUnset') }}</span>
      <span v-if="baseMsg" class="text-ctp-overlay0 truncate max-w-[16rem]" :title="baseMsg">{{ baseMsg }}</span>
      <span class="flex-1" />
      <button
        class="btn !py-1 !px-3 !text-xs"
        :class="baselineSet ? 'btn-ghost' : 'btn-primary'"
        :disabled="baseBusy"
        @click="refreshBaseline"
      ><ArrowPathIcon v-if="baseBusy" class="w-3.5 h-3.5 animate-spin" />{{ baseBusy ? t('overviewHome.baselineInit.working') : (baselineSet ? t('overviewHome.baselineInit.baseRefresh') : t('overviewHome.baselineInit.baseInit')) }}</button>
    </div>
  </section>
</template>
