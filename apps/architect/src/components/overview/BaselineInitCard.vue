<script setup lang="ts">
/**
 * 概览页「KB 基线就绪」卡片 —— 三通道状态识别 + 初始化按钮组:
 * - git: 未初始化工作目录 → 「初始化 git」(按钮点击即授权, topocode 身份首提交)
 * - codegraph: CLI/连接/新鲜度 → 「同步索引」(ensure_synced 自动 init 首建)
 * - KB 基线: 六态就绪状态 → 「冷启动/继续就绪」(自动关联/挂载/命名, 含 initGit 授权)
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { CircleStackIcon, BoltIcon, CodeBracketIcon, ArrowPathIcon } from '@heroicons/vue/24/outline'
import { projectService } from '@/services/project-service'
import { semanticAssetService, type BaselineReadiness, type CodegraphStatus, type NamingStatus } from '@/services/semantic-asset-service'
import type { GitInfoLite } from '@/types'

const { t } = useI18n()

const git = ref<GitInfoLite | null>(null)
const cg = ref<CodegraphStatus | null>(null)
const kb = ref<BaselineReadiness | null>(null)
const naming = ref<NamingStatus | null>(null)
let namingPoll: ReturnType<typeof setInterval> | null = null

function stopNamingPoll() {
  if (namingPoll) { clearInterval(namingPoll); namingPoll = null }
}
async function loadNaming() {
  naming.value = await semanticAssetService.namingStatus(kb.value?.taskId).catch(() => null)
  if (naming.value?.naming?.status === 'running' && !namingPoll) {
    namingPoll = setInterval(() => { void loadNaming() }, 5000)
  }
  if (naming.value?.naming?.status !== 'running') stopNamingPoll()
}
const gitBusy = ref(false)
const cgBusy = ref(false)
const cgMsg = ref('')
const kbBusy = ref(false)
const kbMsg = ref('')
const namingBusy = ref(false)

const kbStateText = computed(() => {
  const st = kb.value?.state
  if (st === 'ready') return t('overviewHome.baselineInit.kbReady')
  if (st === 'analyzing') return t('overviewHome.baselineInit.kbAnalyzing')
  if (st === 'importing') return t('overviewHome.baselineInit.kbImporting')
  if (st === 'no_analysis') return t('overviewHome.baselineInit.kbNoAnalysis')
  if (st === 'unmounted') return t('overviewHome.baselineInit.kbUnmounted')
  return t('overviewHome.baselineInit.kbNoProject')
})

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
onMounted(() => { loadAll(); void autoSyncCg(); setTimeout(() => void loadNaming(), 400) })
onUnmounted(stopNamingPoll)

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

/** KB 基线更新: 仅发起请求(knowledge.pullRequest), 基线管理页确认执行后过期消除。 */
async function updateBaseline() {
  kbMsg.value = ''
  try {
    const r = await semanticAssetService.symbolSync()
    kbMsg.value = r?.message || ''
  } catch (e: any) {
    kbMsg.value = e?.message || String(e)
  }
}

const namingText = computed(() => {
  const n = naming.value?.naming
  if (!n?.status) {
    // 存量任务无命名记录(特性前创建): 就绪即显示"未执行过命名", 否则按钮被藏
    return kb.value?.state === 'ready' ? t('overviewHome.baselineInit.namingNotRun') : ''
  }
  if (n.status === 'running') return t('overviewHome.baselineInit.namingRunning')
  if (n.status === 'done') {
    return n.named ? `${t('overviewHome.baselineInit.namingDone')} ${n.named}` : t('overviewHome.baselineInit.namingNone')
  }
  return `${t('overviewHome.baselineInit.namingFail')}: ${(n.error || n.reason || '').slice(0, 80)}`
})

async function rerunNaming() {
  namingBusy.value = true
  try {
    await semanticAssetService.namingRerun(kb.value?.taskId)
    await loadNaming()
  } finally {
    namingBusy.value = false
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
    await loadKb(); await loadCg(); await loadNaming()
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

    <!-- git -->
    <div class="flex items-center gap-3 py-2 border-t border-ctp-surface0 text-xs">
      <CodeBracketIcon class="w-4 h-4 text-ctp-blue shrink-0" />
      <span class="w-20 text-ctp-overlay1 shrink-0">git</span>
      <span v-if="git?.isRepo" class="text-ctp-green font-mono">
        {{ git.branch || 'main' }}<span v-if="git.dirty" class="text-ctp-peach"> · {{ t('overviewHome.dirty') }}</span>
      </span>
      <span v-else class="text-ctp-peach">{{ t('overviewHome.baselineInit.gitMissing') }}</span>
      <button
        v-if="git && !git.isRepo"
        class="btn !py-1 !px-3 !text-xs ml-auto"
        :disabled="gitBusy"
        @click="initGit"
      ><ArrowPathIcon v-if="gitBusy" class="w-3.5 h-3.5 animate-spin" />{{ gitBusy ? t('overviewHome.baselineInit.working') : t('overviewHome.baselineInit.gitInit') }}</button>
    </div>

    <!-- codegraph -->
    <div class="flex items-center gap-3 py-2 border-t border-ctp-surface0 text-xs">
      <BoltIcon class="w-4 h-4 text-ctp-yellow shrink-0" />
      <span class="w-20 text-ctp-overlay1 shrink-0">codegraph</span>
      <span v-if="!cg?.cli" class="text-ctp-peach">{{ t('overviewHome.baselineInit.cgNoCli') }}</span>
      <span v-else-if="cg?.corePid" class="text-ctp-green">
        {{ t('overviewHome.baselineInit.cgLinked') }} {{ cg?.native?.nodes ?? 0 }} {{ t('overviewHome.baselineInit.cgNodes') }}
        <span v-if="cg?.state?.stale" class="text-ctp-peach"> · {{ t('overviewHome.baselineInit.cgStale') }}</span>
      </span>
      <span v-else class="text-ctp-overlay0">{{ t('overviewHome.baselineInit.cgIdle') }}</span>
      <span v-if="cgMsg" class="text-ctp-overlay0 truncate max-w-[16rem]" :title="cgMsg">{{ cgMsg }}</span>
      <button
        v-if="cg?.cli"
        class="btn !py-1 !px-3 !text-xs ml-auto"
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
      <span v-if="kbMsg" class="text-ctp-overlay0 truncate max-w-[16rem]">{{ kbMsg }}</span>
      <span
        v-if="namingText"
        class="truncate max-w-[22rem]"
        :class="naming?.naming?.status === 'error' ? 'text-ctp-peach' : 'text-ctp-overlay0'"
        :title="naming?.naming?.error || ''"
      >{{ t('overviewHome.baselineInit.namingLabel') }}: {{ namingText }}</span>
      <button
        v-if="kb?.state === 'ready' && naming?.naming?.status !== 'running'"
        class="btn !py-1 !px-3 !text-xs"
        :disabled="namingBusy"
        @click="rerunNaming"
      ><ArrowPathIcon v-if="namingBusy" class="w-3.5 h-3.5 animate-spin" />{{ namingBusy ? t('overviewHome.baselineInit.working') : t('overviewHome.baselineInit.namingRerun') }}</button>
      <button
        class="btn !py-1 !px-3 !text-xs ml-auto"
        :class="kb?.state === 'ready' ? 'btn-ghost' : 'btn-primary'"
        :disabled="kbBusy"
        @click="driveKb"
      ><ArrowPathIcon v-if="kbBusy" class="w-3.5 h-3.5 animate-spin" />{{ kbBusy ? t('overviewHome.baselineInit.working') : (kb?.state === 'ready' ? t('overviewHome.baselineInit.kbRerun') : t('overviewHome.baselineInit.kbStart')) }}</button>
    </div>
  </section>
</template>
