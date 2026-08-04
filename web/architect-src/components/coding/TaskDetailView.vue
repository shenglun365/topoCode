<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  BoltIcon, PlayIcon, RocketLaunchIcon, PlusIcon, CubeIcon,
  ArrowPathRoundedSquareIcon, ShieldCheckIcon, ArrowUturnLeftIcon, ExclamationTriangleIcon,
  CheckCircleIcon, XCircleIcon, CheckIcon, ChatBubbleOvalLeftEllipsisIcon, ArrowLeftIcon, MapIcon,
} from '@heroicons/vue/24/outline'
import { useArchRequirementStore } from '@/stores/requirement-store'
import { useArchTaskStore } from '@/stores/task-store'
import { useArchAgentStore } from '@/stores/agent-store'
import { useArchStagingStore } from '@/stores/staging-store'
import { useArchGitSyncStore } from '@/stores/git-sync-store'
import { useSplitPane } from '@/composables/useSplitPane'
import TaskTree from '@/components/coding/TaskTree.vue'
import AgentSessionPanel from '@/components/coding/AgentSessionPanel.vue'
import CodeChangePanel from '@/components/coding/CodeChangePanel.vue'
import SessionStatsPanel from '@/components/coding/SessionStatsPanel.vue'
import PoolSelectDialog from '@/components/coding/PoolSelectDialog.vue'

const props = defineProps<{ execId: string }>()
const emit = defineEmits<{ close: []; replaced: [] }>()

const { t } = useI18n()
const requirement = useArchRequirementStore()
const task = useArchTaskStore()
const agent = useArchAgentStore()
const staging = useArchStagingStore()
const git = useArchGitSyncStore()
staging.load()

// ---- 左右分割 ----
const { splitPct, dragging, boxRef: splitBoxRef, onDown: onSplitPointerDown, onMove: onSplitPointerMove, onUp: onSplitPointerUp } = useSplitPane({ max: 70, min: 32 })

const exec = computed(() => task.findExecution(props.execId))
const selectedSession = computed(() => agent.byExecution[props.execId])
const plan = computed(() => exec.value ? requirement.planById(exec.value.planId) : undefined)
const tree = computed(() => exec.value ? task.taskPlan(exec.value.planId) : undefined)
const treeHist = computed(() => {
  if (!plan.value?.taskPlanId) return []
  return task.treeHistory[plan.value.taskPlanId] ?? []
})
const reqs = computed(() => (exec.value?.reqIds ?? []).map((id) => requirement.byId(id)).filter((r): r is NonNullable<typeof r> => !!r))

const baselineBusy = ref(false)
const baselineWarn = ref(false)
const pickerOpen = ref(false)
const expandedReqs = ref<string[]>([])

const execStatusColor: Record<string, string> = {
  created: 'bg-ctp-surface0 text-ctp-subtext0',
  running: 'bg-ctp-blue/15 text-ctp-blue',
  accepting: 'bg-ctp-yellow/15 text-ctp-yellow',
  done: 'bg-ctp-green/15 text-ctp-green',
  failed: 'bg-ctp-red/15 text-ctp-red',
  blocked: 'bg-ctp-red/15 text-ctp-red',
  stopped: 'bg-ctp-red/15 text-ctp-red',
}
const connColor: Record<string, string> = {
  unknown: 'bg-ctp-surface0 text-ctp-overlay1',
  ok: 'bg-ctp-green/15 text-ctp-green',
  fail: 'bg-ctp-red/15 text-ctp-red',
}
const prioColor: Record<string, string> = {
  P0: 'bg-ctp-red/15 text-ctp-red',
  P1: 'bg-ctp-peach/15 text-ctp-peach',
  P2: 'bg-ctp-overlay0/20 text-ctp-overlay1',
}

const execTitle = computed(() => plan.value?.title ?? exec.value?.planId ?? props.execId)

async function openSession() {
  if (!exec.value) return
  const s = await agent.openSession(exec.value.id)
  if (s) agent.select(s.id)
}
function runCurrent() {
  if (selectedSession.value) agent.runTask(selectedSession.value.id)
}
function runNext() { agent.runNextPending() }
function runAll() { agent.runAll() }

async function checkBaseline() {
  if (!exec.value || !plan.value) return
  baselineBusy.value = true
  const head = await git.head()
  baselineBusy.value = false
  const ok = head.commit === plan.value.baseCommit && !head.dirty
  baselineWarn.value = !ok
  if (ok) {
    const s = selectedSession.value ?? await openSession()
    if (s) await agent.runTask(s.id)
  }
}
async function resetBaseline() {
  if (!exec.value || !plan.value) return
  baselineBusy.value = true
  await git.resetToBase(plan.value.baseCommit)
  baselineBusy.value = false
  baselineWarn.value = false
}
function reflow() {
  if (!exec.value) return
  requirement.reflowPlan(exec.value.planId)
  agent.removeByTask(exec.value.id)
  task.removeExecution(exec.value.id)
  emit('replaced')
}
function passAcceptance() {
  if (exec.value) task.passAcceptance(exec.value.id)
}

// ---- 追加需求(添加需求池项并入当前执行) ----
function addFromPicker(ids: string[]) {
  if (!exec.value) return
  ids.forEach((id) => {
    const r = requirement.byId(id)
    if (r) task.appendFromPool(exec.value!.id, r)
  })
}
function toggleExpanded(id: string) {
  const i = expandedReqs.value.indexOf(id)
  if (i >= 0) expandedReqs.value.splice(i, 1)
  else expandedReqs.value.push(id)
}
</script>

<template>
  <div class="h-full flex flex-col min-h-0">
    <!-- 页头 -->
    <div class="shrink-0 flex items-center gap-2 pb-3">
      <button
        class="btn btn-sm btn-ghost"
        @click="emit('close')"
      >
        <ArrowLeftIcon class="w-3.5 h-3.5" />{{ t('common.back') }}
      </button>
      <MapIcon class="w-4 h-4 text-ctp-lavender" />
      <span class="text-sm font-semibold text-ctp-text truncate">{{ execTitle }}</span>
      <span class="chip font-mono bg-ctp-surface0 text-ctp-overlay1 shrink-0">{{ exec?.id }}</span>
      <span
        v-if="exec"
        class="chip shrink-0"
        :class="execStatusColor[exec.status]"
      >{{ t(`execute.execStatus.${exec.status}`) }}</span>
      <span
        v-if="exec"
        class="chip shrink-0 bg-ctp-surface0 text-ctp-subtext0"
      >{{ exec.adapter }}{{ exec.model ? ` · ${exec.model}` : '' }}</span>
      <span
        v-if="exec"
        class="chip shrink-0"
        :class="connColor[exec.connectivity]"
      >{{ t(`execute.conn${exec.connectivity === 'ok' ? 'Ok' : exec.connectivity === 'fail' ? 'Fail' : 'Unknown'}`) }}</span>
    </div>

    <div
      ref="splitBoxRef"
      class="flex-1 min-h-0 flex"
    >
      <!-- 左栏：信息/操作 -->
      <div
        class="min-h-0 overflow-auto space-y-3 pr-1"
        :style="{ width: splitPct + '%' }"
      >
        <!-- 已选需求 -->
        <div class="panel overflow-hidden">
          <div class="panel-header">
            <span class="flex items-center gap-2">
              <CubeIcon class="w-4 h-4 text-ctp-green" />{{ t('execute.selectedReqs') }}
            </span>
            <span class="text-[11px] text-ctp-overlay1">{{ reqs.length }}</span>
            <button
              class="btn btn-xs btn-ghost"
              @click="pickerOpen = true"
            >
              <PlusIcon class="w-3 h-3" />{{ t('execute.addReq') }}
            </button>
          </div>
          <div class="p-2.5 space-y-1.5">
            <div
              v-for="r in reqs"
              :key="r.id"
              class="border border-ctp-surface0 rounded-lg overflow-hidden"
            >
              <button
                class="w-full flex items-center gap-2 px-2.5 py-1.5 text-left transition-colors hover:bg-ctp-surface0/50"
                @click="toggleExpanded(r.id)"
              >
                <span class="font-mono text-[10px] text-ctp-overlay1 shrink-0">{{ r.id }}</span>
                <span class="text-xs text-ctp-text truncate flex-1">{{ r.title }}</span>
                <span
                  class="chip shrink-0"
                  :class="prioColor[r.priority]"
                >{{ r.priority }}</span>
                <span class="shrink-0 text-ctp-overlay1 text-[10px]">{{ expandedReqs.includes(r.id) ? '▾' : '▸' }}</span>
              </button>
              <div
                v-if="expandedReqs.includes(r.id)"
                class="border-t border-ctp-surface0 px-2.5 py-2 space-y-1.5 text-[11px]"
              >
                <p
                  v-if="r.desc"
                  class="text-ctp-subtext1"
                >
                  {{ r.desc }}
                </p>
                <div
                  v-if="r.analysis"
                  class="space-y-1.5"
                >
                  <div
                    v-if="r.analysis.functionalScope?.length"
                    class="text-ctp-subtext1"
                  >
                    {{ t('requirement.functionalScope') }}: {{ r.analysis.functionalScope.join(' · ') }}
                  </div>
                  <div
                    v-if="r.analysis.entityBoundary?.length"
                    class="text-ctp-subtext1"
                  >
                    {{ t('requirement.entityBoundary') }}: {{ r.analysis.entityBoundary.join(' · ') }}
                  </div>
                  <div
                    v-if="r.analysis.assetScope?.length"
                    class="flex flex-wrap gap-1"
                  >
                    <span
                      v-for="a in r.analysis.assetScope"
                      :key="a.assetId"
                      class="chip bg-ctp-crust text-ctp-sapphire font-mono text-[10px]"
                    >{{ a.assetId }}</span>
                  </div>
                  <div
                    v-if="r.analysis.implementationPath"
                    class="text-ctp-overlay1"
                  >
                    {{ t('requirement.report.path') }}: {{ r.analysis.implementationPath }}
                  </div>
                  <div
                    v-if="r.analysis.specsMd"
                    class="text-ctp-overlay1"
                  >
                    {{ t('requirement.report.specs') }}: {{ r.analysis.specsMd }}
                  </div>
                </div>
              </div>
            </div>
            <span
              v-if="!reqs.length"
              class="text-[11px] text-ctp-overlay1"
            >{{ t('execute.noReqs') }}</span>
          </div>
        </div>

        <!-- 任务树 -->
        <div class="panel overflow-hidden">
          <div class="panel-header">
            <span class="flex items-center gap-2">
              <ChatBubbleOvalLeftEllipsisIcon class="w-4 h-4 text-ctp-teal" />{{ t('coding.tasks') }}
            </span>
            <span
              v-if="exec?.treeRevision"
              class="chip bg-ctp-peach/15 text-ctp-peach"
            >R{{ exec.treeRevision }}</span>
          </div>
          <div class="p-2 max-h-72 overflow-auto">
            <TaskTree
              v-if="tree"
              :task="tree"
            />
            <p
              v-else
              class="text-[11px] text-ctp-overlay1 p-2"
            >
              {{ t('execute.noTree') }}
            </p>
            <!-- 旧树历史(缩略保存，供复盘) -->
            <div
              v-if="treeHist.length"
              class="mt-2 border-t border-ctp-surface0 pt-2 space-y-1"
            >
              <div class="text-[10px] text-ctp-overlay1">
                {{ t('execute.treeHistory') }} ({{ treeHist.length }})
              </div>
              <details
                v-for="(h, i) in treeHist"
                :key="i"
                class="group"
              >
                <summary class="cursor-pointer select-none text-[10px] text-ctp-overlay1 hover:text-ctp-text">
                  R{{ i + 1 }} · {{ new Date(h.ts).toLocaleString() }}
                </summary>
                <div class="ml-2 border-l border-ctp-surface1 pl-2 mt-1">
                  <TaskTree
                    :task="h.old"
                    :depth="0"
                  />
                </div>
              </details>
            </div>
          </div>
        </div>

        <!-- 代码变更 -->
        <div class="panel overflow-hidden">
          <div class="panel-header">
            <span class="flex items-center gap-2">
              <ShieldCheckIcon class="w-4 h-4 text-ctp-sky" />{{ t('execute.changes') }}
            </span>
          </div>
          <div class="p-2.5">
            <CodeChangePanel />
          </div>
        </div>

        <!-- 会话统计 -->
        <div class="panel overflow-hidden">
          <div class="panel-header">
            <span class="flex items-center gap-2">
              <BoltIcon class="w-4 h-4 text-ctp-mauve" />{{ t('execute.stats') }}
            </span>
          </div>
          <div class="p-2.5">
            <SessionStatsPanel :stats="selectedSession?.stats ?? exec?.stats" />
          </div>
        </div>

        <!-- 操作 -->
        <div class="panel overflow-hidden">
          <div class="panel-header">
            <span class="flex items-center gap-2">
              <RocketLaunchIcon class="w-4 h-4 text-ctp-lavender" />{{ t('execute.actions') }}
            </span>
          </div>
          <div class="p-2.5 space-y-2">
            <div class="flex flex-wrap gap-1.5">
              <button
                class="btn btn-xs btn-primary"
                :disabled="agent.running || !exec"
                @click="runCurrent"
              >
                <PlayIcon class="w-3 h-3" />{{ t('coding.session') }}
              </button>
              <button
                class="btn btn-xs btn-ghost"
                :disabled="agent.running"
                @click="runNext"
              >
                <PlayIcon class="w-3 h-3" />{{ t('execute.step') }}
              </button>
              <button
                class="btn btn-xs btn-ghost"
                :disabled="agent.running"
                @click="runAll"
              >
                <RocketLaunchIcon class="w-3 h-3" />{{ t('execute.pipeline') }}
              </button>
              <button
                class="btn btn-xs btn-ghost"
                :disabled="!exec"
                @click="openSession"
              >
                <PlusIcon class="w-3 h-3" />{{ t('execute.newSession') }}
              </button>
            </div>
            <div class="flex flex-wrap gap-1.5">
              <button
                class="btn btn-xs btn-ghost"
                :disabled="agent.running || baselineBusy || !exec"
                @click="checkBaseline"
              >
                <ArrowPathRoundedSquareIcon class="w-3 h-3" />{{ t('execute.newRun') }}
              </button>
              <button
                class="btn btn-xs btn-ghost"
                :disabled="baselineBusy || !exec"
                @click="resetBaseline"
              >
                <ArrowPathRoundedSquareIcon class="w-3 h-3" />{{ t('execute.baselineReset') }}
              </button>
              <button
                class="btn btn-xs btn-ghost"
                :disabled="!exec"
                :title="t('execute.reflowHint')"
                @click="reflow"
              >
                <ArrowUturnLeftIcon class="w-3 h-3" />{{ t('execute.reflow') }}
              </button>
            </div>
            <div
              v-if="baselineWarn"
              class="border border-ctp-red/40 bg-ctp-red/10 rounded-lg px-2 py-1.5 text-[11px] text-ctp-red flex items-center gap-1.5"
            >
              <ExclamationTriangleIcon class="w-3.5 h-3.5 shrink-0" />{{ t('execute.baselineWarn') }}
            </div>
            <!-- 验收 -->
            <div
              v-if="exec?.status === 'accepting'"
              class="border border-ctp-yellow/40 bg-ctp-yellow/10 rounded-lg p-2"
            >
              <div class="text-[11px] font-medium text-ctp-yellow mb-1">
                {{ t('execute.acceptanceTitle') }}
              </div>
              <div class="text-[10px] text-ctp-overlay1 mb-1.5">
                {{ staging.compliancePassed }}/{{ staging.compliance.length }} {{ t('execute.acceptanceCheckList') }}
              </div>
              <div class="space-y-1">
                <div
                  v-for="c in staging.compliance"
                  :key="c.id"
                  class="flex items-center gap-1.5 text-[11px]"
                >
                  <CheckCircleIcon
                    v-if="c.pass"
                    class="w-3 h-3 text-ctp-green shrink-0"
                  />
                  <XCircleIcon
                    v-else
                    class="w-3 h-3 text-ctp-red shrink-0"
                  />
                  <span class="truncate">{{ c.name }}</span>
                </div>
              </div>
              <button
                class="btn btn-xs btn-green mt-2 w-full"
                @click="passAcceptance"
              >
                <CheckIcon class="w-3 h-3" />{{ t('execute.acceptancePassBtn') }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 分割线 -->
      <div
        class="w-4 shrink-0 -mx-0.5 flex items-center justify-center cursor-col-resize select-none touch-none group"
        :class="dragging ? 'cursor-col-resize' : ''"
        @pointerdown="onSplitPointerDown"
        @pointermove="onSplitPointerMove"
        @pointerup="onSplitPointerUp"
        @pointercancel="onSplitPointerUp"
        @pointerleave="onSplitPointerUp"
      >
        <div
          class="h-12 w-0.5 rounded-full bg-ctp-overlay1/40 transition-colors group-hover:bg-ctp-blue/60"
          :class="dragging ? '!bg-ctp-blue/70' : ''"
        />
      </div>

      <!-- 右栏：会话 -->
      <div class="min-h-0 flex-1 flex flex-col">
        <AgentSessionPanel
          v-if="selectedSession"
          :session="selectedSession"
        />
        <div
          v-else
          class="panel flex-1 p-10 flex flex-col items-center justify-center gap-3 text-center"
        >
          <ChatBubbleOvalLeftEllipsisIcon class="w-10 h-10 text-ctp-overlay0" />
          <p class="text-sm text-ctp-subtext0">
            {{ t('coding.noSession') }}
          </p>
          <button
            class="btn btn-primary"
            @click="openSession"
          >
            <PlayIcon class="w-4 h-4" />{{ t('coding.session') }}
          </button>
        </div>
      </div>
    </div>

    <PoolSelectDialog
      :open="pickerOpen"
      :selected="[]"
      :title="t('execute.addReq')"
      @update:open="(v) => (pickerOpen = v)"
      @confirm="addFromPicker"
    />
  </div>
</template>
