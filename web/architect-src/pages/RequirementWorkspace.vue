<script setup lang="ts">
import { computed, onMounted, provide, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeftIcon, BoltIcon, CheckCircleIcon, ArrowRightIcon, SparklesIcon, PlusIcon, ClipboardDocumentListIcon,
} from '@heroicons/vue/24/outline'
import AnalysisChat from '@/components/requirements/AnalysisChat.vue'
import RequirementForm from '@/components/requirements/RequirementForm.vue'
import { analysisAgent, type KbAnalysisTurn } from '@/services/kb-analysis-agent'
import { validateForm } from '@/services/asset-validator'
import { commitBatch } from '@/services/execution-batch'
import { useArchRequirementStore } from '@/stores/requirement-store'
import { useArchAgentStore } from '@/stores/agent-store'
import { useArchProjectStore } from '@/stores/project-store'
import { useSplitPane } from '@/composables/useSplitPane'
import type { FormDraft, Requirement, RequirementAnalysis } from '@/types'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const store = useArchRequirementStore()
const agentStore = useArchAgentStore()
const projectStore = useArchProjectStore()

/** 未绑定 KB 基线项目(无项目 或 工作目录直开无 KB) → KB 能力降级。 */
const kbDegraded = computed(() => !projectStore.hasBaseline)

function emptyForm(): FormDraft {
  return {
    title: '',
    kind: 'user-story',
    priority: 'P1',
    tags: [],
    basicMd: '',
    assetScope: [],
    assessmentSummary: '',
    estMin: 0,
    specsMd: '',
    implementationPath: '',
    report: undefined,
  }
}

const form = reactive<FormDraft>(emptyForm())
provide('requirement-form', form)

// ---- 左右栏分割(表单 | 对话) ----
const { splitPct, dragging, boxRef: splitBoxRef, onDown: onSplitPointerDown, onMove: onSplitPointerMove, onUp: onSplitPointerUp } = useSplitPane()
const turns = ref<KbAnalysisTurn[]>([])
const busy = ref(false)
const draft = ref<FormDraft | null>(null)
const editingId = ref<string | null>(null)
const analyzed = ref(false)
const committed = ref<'proposal' | 'pool' | null>(null)
const committedReqs = ref<Requirement[]>([])
const seedPreferred = ref<string[]>([])

// ---- 提案多选(需求分析入口)：勾选后逐个分析 ----
const picker = ref(false)
const selected = ref<string[]>([])
const queue = ref<Requirement[]>([])
const queueIndex = ref(0)
const proposals = computed(() => store.proposals.filter((r) => !r.mergedInto))
const batchRunning = computed(() => queue.value.length > 0)
const batchProgress = computed(() => `${queueIndex.value + 1}/${queue.value.length}`)

const kindColor: Record<string, string> = {
  'user-story': 'bg-ctp-sky/15 text-ctp-sky',
  fr: 'bg-ctp-mauve/15 text-ctp-mauve',
  nfr: 'bg-ctp-teal/15 text-ctp-teal',
}
const prioColor: Record<string, string> = {
  P0: 'bg-ctp-red/15 text-ctp-red',
  P1: 'bg-ctp-peach/15 text-ctp-peach',
  P2: 'bg-ctp-overlay0/20 text-ctp-overlay1',
}
const statusColor: Record<string, string> = {
  raw: 'bg-ctp-overlay0/20 text-ctp-overlay1',
  analyzing: 'bg-ctp-blue/15 text-ctp-blue',
  analyzed: 'bg-ctp-green/15 text-ctp-green',
  designed: 'bg-ctp-sky/15 text-ctp-sky',
  planned: 'bg-ctp-teal/15 text-ctp-teal',
  executing: 'bg-ctp-peach/15 text-ctp-peach',
  done: 'bg-ctp-green/15 text-ctp-green',
  cancelled: 'bg-ctp-red/15 text-ctp-red',
}

const validation = computed(() => validateForm(form))
const hasAnalysis = computed(() => analyzed.value || form.assetScope.length > 0)
const canEnterPool = computed(() => validation.value.ok && hasAnalysis.value)

function preferredIds(): string[] | undefined {
  return seedPreferred.value.length ? [...seedPreferred.value] : undefined
}
/** 提交种子：基本信息正文 basicMd 作为内容文本(agent 检索用 desc；入池/提案写入 remarks)。 */
function seed() {
  return {
    id: editingId.value ?? undefined,
    title: form.title.trim(),
    desc: form.basicMd,
    priority: form.priority,
    preferredAssetIds: preferredIds(),
    basicMd: form.basicMd,
  }
}
function base() {
  return {
    title: form.title.trim() || '未命名需求',
    desc: form.basicMd,
    priority: form.priority,
    kind: form.kind,
    preferredAssetIds: preferredIds(),
  }
}
function emptyAssessment(): RequirementAnalysis['assessment'] {
  return {
    necessity: { grade: 'medium', reason: '' },
    atomicity: { independent: true, reason: '' },
    acceptability: { ok: true, reason: '' },
  }
}
/** 由表单 + agent 报告(report)合成需求分析；手动起草时 report 为空 → 精简 analysis。 */
function analysisFromForm(): RequirementAnalysis {
  const rep = form.report
  return {
    functionalScope: rep?.functionalScope ?? [],
    entityBoundary: rep?.entityBoundary ?? [],
    feasibility: { ok: rep?.feasibility.ok ?? true, reason: rep?.feasibility.reason ?? '', estMin: form.estMin },
    assetScope: structuredClone(form.assetScope),
    assessment: rep?.assessment ?? emptyAssessment(),
    assessmentSummary: form.assessmentSummary,
    specsMd: form.specsMd,
    implementationPath: form.implementationPath,
    changes: rep?.changes ?? [],
    steps: rep?.steps ?? [],
  }
}

onMounted(async () => {
  await store.load()
  const q = route.query
  if (typeof q.id === 'string') {
    const seed = store.byId(q.id)
    if (seed) {
      loadActive(seed)
      if (!seed.analysis) await startClarify()
    }
  } else if (q.pending === '1') {
    picker.value = true
  }
})

/** 将某个提案装入当前分析会话(清空聊天，必要时重新澄清)。 */
function loadActive(r: Requirement) {
  editingId.value = r.id
  seedPreferred.value = [...(r.preferredAssetIds ?? [])]
  form.title = r.title
  form.priority = r.priority
  form.kind = r.kind
  form.tags = []
  const a = r.analysis
  analyzed.value = !!a
  form.basicMd = r.remarks ?? r.desc
  form.assetScope = structuredClone(a?.assetScope ?? [])
  form.assessmentSummary = a?.assessmentSummary ?? ''
  form.estMin = a?.feasibility.estMin ?? 0
  form.specsMd = a?.specsMd ?? ''
  form.implementationPath = a?.implementationPath ?? ''
  form.report = a ? structuredClone(a) : undefined
  turns.value = []
  draft.value = null
  committed.value = null
  committedReqs.value = []
}

function toggleSelect(id: string) {
  const i = selected.value.indexOf(id)
  if (i >= 0) selected.value.splice(i, 1)
  else selected.value.push(id)
}

/** 开始批量分析：按选中顺序逐个澄清 → 出草案 → 确认 → 入池。 */
function startBatch() {
  const list = selected.value.map((id) => store.byId(id)).filter((r): r is Requirement => !!r)
  if (!list.length) return
  picker.value = false
  queue.value = list
  queueIndex.value = 0
  loadActive(queue.value[0])
  startClarify()
}

async function startClarify() {
  if (!form.title.trim() || busy.value) return
  busy.value = true
  try {
    const res = await analysisAgent.clarify(base())
    turns.value = res.turns
    draft.value = null
  } finally {
    busy.value = false
  }
}

async function collect(answers: Record<string, string>, note?: string) {
  if (busy.value) return
  busy.value = true
  try {
    const res = await analysisAgent.collect({ turns: turns.value, base: base(), answers, note })
    turns.value = res.turns
    if (res.formDraft) draft.value = res.formDraft
  } finally {
    busy.value = false
  }
}
function onAnswers(answers: Record<string, string>) { collect(answers) }
function onSend(text: string) { collect({}, text) }

/** 用户确认草案 → 整份替换右栏表单；可继续多轮迭代。 */
function confirmDraft() {
  if (!draft.value) return
  Object.assign(form, structuredClone(draft.value))
  analyzed.value = true
  draft.value = null
}

/**
 * 保存到提案。
 * 规则：勾选 1 条 → 就地更新该提案(含已分析内容)；
 *       勾选多条 → 新建一条提案，relatedTo=本次勾选源集合，并标记源提案 mergedInto(避免重复处理)。
 */
function saveToProposal() {
  const analysis = hasAnalysis.value ? analysisFromForm() : undefined
  const multi = batchRunning.value && queue.value.length > 1
  const r = store.saveProposal(
    multi
      ? { title: form.title.trim(), desc: form.basicMd, priority: form.priority, preferredAssetIds: preferredIds(), basicMd: form.basicMd, relatedTo: queue.value.map((x) => x.id) }
      : seed(),
    analysis,
  )
  if (multi) {
    const src = queue.value.find((x) => x.id === editingId.value)
    if (src) store.markMerged(src.id, r.id)
  }
  editingId.value = r.id
  committedReqs.value = [r]
  if (batchRunning.value) {
    queueIndex.value += 1
    if (queueIndex.value < queue.value.length) {
      loadActive(queue.value[queueIndex.value])
      startClarify()
      return
    }
    queue.value = []
    queueIndex.value = 0
  }
  committed.value = 'proposal'
}

/** 入需求池(整体写入单条池项)；批量模式入池后继续下一个提案。 */
function enterPool() {
  const v = validation.value
  if (!v.ok) return
  const reqs = [store.finalizeAnalysis(seed(), analysisFromForm())]
  const last = reqs[reqs.length - 1]
  editingId.value = last.id
  if (batchRunning.value) {
    queueIndex.value += 1
    if (queueIndex.value < queue.value.length) {
      loadActive(queue.value[queueIndex.value])
      startClarify()
      return
    }
    queue.value = []
    queueIndex.value = 0
  }
  committed.value = 'pool'
  committedReqs.value = reqs
}

function resetWorkspace() {
  Object.assign(form, emptyForm())
  turns.value = []
  draft.value = null
  editingId.value = null
  analyzed.value = false
  committed.value = null
  committedReqs.value = []
  picker.value = false
  selected.value = []
  queue.value = []
  queueIndex.value = 0
  router.replace({ path: '/workbench/requirements/analysis', query: { new: '1' } })
}

/** 入池后「立即执行」：合成批次 + 创建 coding agent 会话(拆分项一并入批次)。 */
async function executeNow() {
  const reqs = committedReqs.value.length ? committedReqs.value : []
  if (!reqs.length) return
  const { exec } = await commitBatch(reqs, 'opencode')
  await agentStore.openSession(exec.id)
  router.push({ path: '/workbench/execute' })
}

function backToList() {
  router.push({ path: '/workbench/requirements', query: { tab: committed.value === 'pool' ? 'pool' : 'proposal' } })
}
</script>

<template>
  <div class="h-full flex flex-col min-h-0">
    <div class="shrink-0 px-5 pt-5">
      <div
        v-if="kbDegraded"
        class="mb-3 flex items-start gap-2 bg-ctp-yellow/10 border border-ctp-yellow/25 rounded-md px-3 py-2"
      >
        <BoltIcon class="w-4 h-4 mt-0.5 shrink-0 text-ctp-yellow" />
        <p class="text-xs text-ctp-subtext1">
          {{ t('requirement.degradedHint') }}
        </p>
      </div>
      <div class="flex items-center gap-3">
        <button
          class="btn btn-sm btn-ghost"
          @click="backToList"
        >
          <ArrowLeftIcon class="w-4 h-4" />{{ t('requirement.workspace.back') }}
        </button>
        <h2 class="text-sm font-semibold text-ctp-text">
          {{ t('requirement.workspace.title') }}
        </h2>
        <span
          v-if="editingId"
          class="chip font-mono bg-ctp-surface0 text-ctp-overlay1"
        >{{ editingId }}</span>
        <span
          v-if="batchRunning"
          class="chip bg-ctp-teal/15 text-ctp-teal"
        >{{ t('requirement.workspace.batchProgress', { current: batchProgress }) }}</span>
        <div class="flex-1" />

        <button
          v-if="committed !== 'pool' && !batchRunning"
          class="btn btn-sm btn-ghost"
          :disabled="!form.title.trim() || busy"
          @click="resetWorkspace"
        >
          <PlusIcon class="w-3.5 h-3.5" />{{ t('requirement.workspace.newSession') }}
        </button>
        <button
          v-if="committed !== 'pool'"
          class="btn btn-sm btn-ghost"
          :disabled="!form.title.trim()"
          @click="saveToProposal"
        >
          <CheckCircleIcon class="w-3.5 h-3.5" />{{ t('requirement.workspace.saveProposal') }}
        </button>
        <button
          v-if="committed !== 'pool'"
          class="btn btn-sm btn-green"
          :disabled="!canEnterPool"
          :title="canEnterPool ? '' : t('requirement.workspace.poolDisabledHint')"
          @click="enterPool"
        >
          <BoltIcon class="w-3.5 h-3.5" />{{ t('requirement.workspace.enterPool') }}
        </button>
      </div>

      <div
        v-if="committed"
        class="mt-3 flex items-center gap-3 border border-ctp-green/30 bg-ctp-green/10 rounded-lg px-3 py-2"
      >
        <CheckCircleIcon class="w-4 h-4 text-ctp-green shrink-0" />
        <span class="text-xs font-medium text-ctp-green">
          {{ t(committed === 'pool' ? 'requirement.workspace.committedPool' : 'requirement.workspace.committedProposal') }}
        </span>
        <div class="flex flex-wrap items-center gap-1">
          <span
            v-for="r in committedReqs"
            :key="r.id"
            class="chip font-mono bg-ctp-surface0 text-ctp-overlay1"
          >{{ r.id }}</span>
        </div>
        <div class="flex-1" />
        <button
          v-if="committed === 'pool'"
          class="btn btn-sm btn-primary"
          @click="executeNow"
        >
          <ArrowRightIcon class="w-3.5 h-3.5" />{{ t('requirement.workspace.executeNow') }}
        </button>
        <button
          class="btn btn-sm btn-ghost"
          @click="backToList"
        >
          <ArrowLeftIcon class="w-3.5 h-3.5" />{{ t('requirement.workspace.viewList') }}
        </button>
      </div>
    </div>

    <div
      ref="splitBoxRef"
      class="flex-1 min-h-0 flex px-5 pb-5 pt-4"
    >
      <!-- 左：需求提案多选列表 / 需求表单 -->
      <div
        v-if="picker"
        class="min-h-0 panel overflow-hidden flex flex-col"
        :style="{ width: splitPct + '%' }"
      >
        <div class="panel-header shrink-0">
          <span class="flex items-center gap-2">
            <ClipboardDocumentListIcon class="w-4 h-4 text-ctp-peach" />{{ t('requirement.workspace.pickTitle') }}
          </span>
          <span class="text-[11px] text-ctp-overlay1">{{ selected.length }}/{{ proposals.length }}</span>
        </div>
        <div class="flex-1 min-h-0 overflow-auto p-3 space-y-2">
          <p class="text-[11px] text-ctp-subtext0">
            {{ t('requirement.workspace.pickHint') }}
          </p>
          <div
            v-for="r in proposals"
            :key="r.id"
            class="border rounded-lg p-2.5 flex items-center gap-2 cursor-pointer"
            :class="selected.includes(r.id) ? 'ring-1 ring-ctp-green/40 border-ctp-green/40' : 'border-ctp-surface0 hover:border-ctp-overlay1/50'"
            @click="toggleSelect(r.id)"
          >
            <input
              type="checkbox"
              class="accent-ctp-green shrink-0 pointer-events-none"
              :checked="selected.includes(r.id)"
            >
            <span class="text-[11px] font-mono text-ctp-overlay1 shrink-0">{{ r.id }}</span>
            <span
              class="chip shrink-0"
              :class="kindColor[r.kind]"
            >{{ t(`requirement.kind.${r.kind}`) }}</span>
            <span
              class="chip shrink-0"
              :class="prioColor[r.priority]"
            >{{ r.priority }}</span>
            <span class="text-sm font-medium text-ctp-text truncate flex-1">{{ r.title }}</span>
            <span
              class="chip shrink-0"
              :class="statusColor[r.status]"
            >{{ t(`requirement.status.${r.status}`) }}</span>
          </div>
          <p
            v-if="!proposals.length"
            class="text-xs text-ctp-overlay0 text-center py-6"
          >
            {{ t('common.empty') }}
          </p>
        </div>
        <div class="shrink-0 border-t border-ctp-surface0 p-2.5 flex justify-end">
          <button
            class="btn btn-green"
            :disabled="!selected.length"
            @click="startBatch"
          >
            <BoltIcon class="w-4 h-4" />{{ t('requirement.workspace.analyzeSelected', { n: selected.length }) }}
          </button>
        </div>
      </div>

      <div
        v-else
        class="min-h-0 panel overflow-hidden flex flex-col"
        :style="{ width: splitPct + '%' }"
      >
        <div class="panel-header shrink-0">
          <span class="flex items-center gap-2">
            <BoltIcon class="w-4 h-4 text-ctp-peach" />{{ t('requirement.workspace.formTitle') }}
          </span>
          <button
            class="btn btn-sm btn-blue"
            :disabled="!form.title.trim() || busy"
            @click="startClarify"
          >
            <SparklesIcon class="w-3.5 h-3.5" />{{ busy ? t('requirement.analyzing') : t('requirement.workspace.analyze') }}
          </button>
        </div>
        <div class="flex-1 min-h-0 p-3">
          <RequirementForm />
        </div>
      </div>

      <!-- 分割线：可拖动控制左右可视区域 -->
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

      <!-- 右：知识库对话 -->
      <div class="min-h-0 flex-1 flex flex-col gap-2">
        <div
          v-if="picker"
          class="flex-1 min-h-0 panel overflow-hidden flex flex-col items-center justify-center gap-2 text-center px-6"
        >
          <ClipboardDocumentListIcon class="w-8 h-8 text-ctp-overlay1/50" />
          <p class="text-xs text-ctp-overlay1">
            {{ t('requirement.workspace.pickRightHint') }}
          </p>
        </div>
        <AnalysisChat
          v-else
          class="flex-1 min-h-0"
          :turns="turns"
          :busy="busy"
          @send="onSend"
          @answers="onAnswers"
          @confirm-draft="confirmDraft"
        />
        <p class="text-[10px] text-ctp-overlay0 leading-relaxed">
          {{ t('requirement.workspace.chatHint') }}
        </p>
      </div>
    </div>
  </div>
</template>
