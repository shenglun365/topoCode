<script setup lang="ts">
/**
 * 概览页「KB 基线就绪」卡片 —— 三通道状态识别 + 初始化按钮组:
 * - git: 仓库状态 + HEAD + 基线落后提示 → 「初始化 git / 更新基线」
 * - codegraph: CLI 索引新鲜度 → 「同步索引」(ensure_synced 检测+init/sync)
 * - KB 基线: 六态就绪状态 → 「冷启动/继续就绪」(自动关联/挂载)
 * 组件命名状态展示在「组件变更情况」面板(ProjectOverviewPage)。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { CircleStackIcon, BoltIcon, CodeBracketIcon, ArrowPathIcon } from '@heroicons/vue/24/outline'
import { projectService } from '@/services/project-service'
import { semanticAssetService, type BaselineReadiness, type CodegraphStatus } from '@/services/semantic-asset-service'
import type { GitInfoLite } from '@/types'

const { t } = useI18n()

const git = ref<GitInfoLite | null>(null)
const cg = ref<CodegraphStatus | null>(null)
const kb = ref<BaselineReadiness | null>(null)

const gitBusy = ref(false)
const cgBusy = ref(false)
const cgMsg = ref('')
const kbBusy = ref(false)
const kbMsg = ref('')

const kbStateText = computed(() => {
  const st = kb.value?.state
  if (st === 'ready') return t('overviewHome.baselineInit.kbReady')
  if (st === 'analyzing') return t('overviewHome.baselineInit.kbAnalyzing')
  if (st === 'importing') return t('overviewHome.baselineInit.kbImporting')
  if (st === 'no_analysis') return t('overviewHome.baselineInit.kbNoAnalysis')
  if (st === 'unmounted') return t('overviewHome.baselineInit.kbUnmounted')
  return t('overviewHome.baselineInit.kbNoProject')
})

/** 基线落后(HEAD 领先已挂载基线版本) —— 更新基线按钮的显示条件。 */
const baselineBehind = computed(() =>
  kb.value?.state === 'ready' && !!cg.value?.state?.stale)

async function loadGit() {
  git.value = await projectService.gitInfo().catch(() => null)
}
async function loadCg() {
  cg.value = await semanticAssetService.codegraphStatus().catch(() => undefined) ?? null
}
/** 静默自动同步: CLI 可用即后台 ensure_synced(检测+init/sync), 完成刷新。 */
async function autoSyncCg() {
  const st = await semanticAssetService.codegraphStatus().catch(() => null)
  if (!st?.cli) return
  await semanticAssetService.codegraphSync().catch(() => null)
  await loadCg()
}
async function loadKb() {
  kb.value = await semanticAssetService.baselineReadiness().catch(() => undefined) ?? null
}
function loadAll() {
  void loadGit(); void loadCg(); void loadKb()
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

/** 基线更新(数据主权批E): 本地编排 采集→分组→命名, 单作业进度。 */
async function updateBaseline() {
  kbMsg.value = ''
  try {
    const r = await semanticAssetService.baselineRefresh()
    kbMsg.value = r?.message || (r?.started ? '已提交' : (r?.reason || ''))
  } catch (e: any) {
    kbMsg.value = e?.message || String(e)
  }
}

async function driveKb() {
  kbBusy.value = true
  kbMsg.value = ''
  try {
    const r = await semanticAssetService.driveBaselineReady((s) => {
      kbMsg.value = `${s?.state ?? ''}${s?.taskId ? ` · ${s.taskId}` : ''} …`
    })
    kbMsg.value = r?.state === 'ready' ? t('overviewHome.baselineInit.kbReady') : (kbMsg.value || r?.state || '')
    await loadKb(); await loadCg()
  } catch (e: any) {
    kbMsg.value = e?.message || String(e)
  } finally {
    kbBusy.value = false
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
      <span v-if="kbMsg" class="text-ctp-overlay0 truncate max-w-[16rem]" :title="kbMsg">{{ kbMsg }}</span>
      <span class="flex-1" />
      <button
        v-if="baselineBehind"
        class="btn !py-1 !px-3 !text-xs"
        :disabled="kbBusy"
        @click="updateBaseline"
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

    <!-- KB 基线 -->
    <div class="flex items-center gap-3 py-2 border-t border-ctp-surface0 text-xs">
      <CircleStackIcon class="w-4 h-4 text-ctp-mauve shrink-0" />
      <span class="w-20 text-ctp-overlay1 shrink-0">KB</span>
      <span :class="kb?.state === 'ready' ? 'text-ctp-green' : 'text-ctp-peach'">
        {{ kbStateText }}
        <span v-if="kb?.taskId" class="font-mono text-ctp-overlay0"> · {{ kb.taskId }}</span>
      </span>
      <span class="flex-1" />
      <button
        class="btn !py-1 !px-3 !text-xs"
        :class="kb?.state === 'ready' ? 'btn-ghost' : 'btn-primary'"
        :disabled="kbBusy"
        @click="driveKb"
      ><ArrowPathIcon v-if="kbBusy" class="w-3.5 h-3.5 animate-spin" />{{ kbBusy ? t('overviewHome.baselineInit.working') : (kb?.state === 'ready' ? t('overviewHome.baselineInit.kbRerun') : t('overviewHome.baselineInit.kbStart')) }}</button>
    </div>
  </section>
</template>
