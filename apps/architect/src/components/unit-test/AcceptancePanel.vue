<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ClipboardDocumentCheckIcon, PlayIcon, ChevronDownIcon, ChevronRightIcon,
  LightBulbIcon, WrenchScrewdriverIcon, ClipboardDocumentIcon, Square2StackIcon,
  ClipboardDocumentListIcon,
} from '@heroicons/vue/24/outline'
import {
  contractService,
  type AcceptanceFact, type AcceptanceOpinion, type AcceptanceReport,
  type AcceptanceReportDetail, type ContractItem, type ContractPackage,
  type DualDiagramResult, type AuthorizationResult,
} from '@/services/contract-service'
import { namingService } from '@/services/naming-service'
import { useArchUnitTestStore } from '@/stores/unit-test-store'
import { XMarkIcon, BeakerIcon } from '@heroicons/vue/24/outline'
import { toMermaid } from '@topo/graph-kernel'
import DiagramCard from '@/components/diagram/DiagramCard.vue'

const { t } = useI18n()
const unitTest = useArchUnitTestStore()

/** A1 经验回写提示：打回后后端后台归纳出 pending 规约提案，引导到命名规约页确认。 */
const rejectionHint = ref('')

// ── A7 验收条目关联单测（引用关系，任意状态可改） ──

function linkedOf(itemId: string): string[] {
  return itemsById[itemId]?.acceptance?.linkedTests ?? []
}

async function setLinked(itemId: string, linked: string[]) {
  try {
    const row = await contractService.setLinkedTests(itemId, linked)
    itemsById[itemId] = row
  } catch (err: any) {
    console.warn('[acceptance] 关联单测失败:', err?.message)
  }
}

function addLinkedTest(itemId: string, testId: string) {
  if (!testId) return
  const cur = linkedOf(itemId)
  if (cur.includes(testId)) return
  setLinked(itemId, [...cur, testId])
}

function removeLinkedTest(itemId: string, testId: string) {
  setLinked(itemId, linkedOf(itemId).filter((x) => x !== testId))
}

const unitTests = computed(() => unitTest.tests)

// ── B2 双图对照（期望 vs 实际；复用共享 IR 渲染，差异用既有 style 高亮） ──

const dualItem = ref<ContractItem | null>(null)
const dual = ref<DualDiagramResult | null>(null)
const dualBusy = ref(false)
const dualError = ref('')

async function openDual(item: ContractItem) {
  dualItem.value = item
  dual.value = null
  dualError.value = ''
  dualBusy.value = true
  try {
    dual.value = await contractService.dualDiagram(item.id)
  } catch (err: any) {
    dualError.value = err?.message || t('localAcceptance.dualFailed')
  } finally {
    dualBusy.value = false
  }
}

function closeDual() {
  dualItem.value = null
  dual.value = null
  dualError.value = ''
}

const dualExpectedCode = computed(() => {
  if (!dual.value) return ''
  try { return toMermaid(dual.value.expected).code } catch { return '' }
})
const dualActualCode = computed(() => {
  if (!dual.value) return ''
  try { return toMermaid(dual.value.actual).code } catch { return '' }
})

// ── C1 可授权清单（Z 轴 × mode=auto 细则：哪些可自动授权、哪些必须人工） ──

const authItem = ref<ContractItem | null>(null)
const auth = ref<AuthorizationResult | null>(null)
const authBusy = ref(false)
const authError = ref('')

async function openAuth(item: ContractItem) {
  authItem.value = item
  auth.value = null
  authError.value = ''
  authBusy.value = true
  try {
    auth.value = await contractService.authorization(item.id)
  } catch (err: any) {
    authError.value = err?.message || t('localAcceptance.authFailed')
  } finally {
    authBusy.value = false
  }
}

function closeAuth() {
  authItem.value = null
  auth.value = null
  authError.value = ''
}

const packages = ref<ContractPackage[]>([])
const pkgId = ref('')
const reports = ref<AcceptanceReport[]>([])
const loading = ref(false)
const running = ref(false)
const runError = ref('')

const expanded = reactive<Record<string, boolean>>({})
const details = reactive<Record<string, AcceptanceReportDetail>>({})
const itemsById = reactive<Record<string, ContractItem>>({})

/** L3 激活输入 + 修复指令草稿（按 reportId:itemId）。 */
const l3Input = reactive<Record<string, string>>({})
const l3Busy = reactive<Record<string, boolean>>({})
const fixDrafts = reactive<Record<string, string>>({})
const fixBusy = reactive<Record<string, boolean>>({})

const key = (reportId: string, itemId: string) => `${reportId}:${itemId}`

async function loadPackages() {
  try {
    packages.value = await contractService.packages()
    if (!pkgId.value && packages.value.length) pkgId.value = packages.value[0].id
  } catch {
    packages.value = []
  }
}

async function loadReports() {
  if (!pkgId.value) { reports.value = []; return }
  loading.value = true
  try {
    reports.value = await contractService.reports(pkgId.value)
  } catch {
    reports.value = []
  } finally {
    loading.value = false
  }
}

async function loadItems() {
  try {
    const items = await contractService.items()
    for (const it of items) itemsById[it.id] = it
  } catch {
    /* 只读区降级：仅展示 facts */
  }
}

async function toggleReport(r: AcceptanceReport) {
  expanded[r.id] = !expanded[r.id]
  if (expanded[r.id] && !details[r.id]) {
    try {
      details[r.id] = await contractService.reportDetail(r.id)
      await loadItems()
    } catch {
      expanded[r.id] = false
    }
  }
}

async function run() {
  if (!pkgId.value || running.value) return
  running.value = true
  runError.value = ''
  try {
    await contractService.runAcceptance(pkgId.value, 'manual')
    await Promise.all([loadReports(), loadItems()])
  } catch (err: any) {
    runError.value = err?.message || String(err)
  } finally {
    running.value = false
  }
}

async function verdict(itemId: string, v: 'accepted' | 'rejected') {
  try {
    const row = await contractService.verdict(itemId, v)
    itemsById[itemId] = row
    // 刷新当前展开报告的 items 状态
    for (const rid of Object.keys(details)) await loadItems()
    if (v === 'rejected') await peekRejectionProposal()
  } catch (err: any) {
    console.warn('[acceptance] verdict 失败:', err?.message)
  }
}

/** A1：打回后轮询一次后台归纳出的 pending 规约提案（引导设计者到命名规约页确认）。 */
async function peekRejectionProposal() {
  await new Promise((r) => setTimeout(r, 2000))
  try {
    const rows = await namingService.conventions('pending')
    if (rows.length) rejectionHint.value = t('localAcceptance.rejectionInduced')
  } catch {
    /* 提示区降级：不影响判定 */
  }
}

async function activateL3(reportId: string, itemId: string) {
  const k = key(reportId, itemId)
  if (l3Busy[k]) return
  l3Busy[k] = true
  try {
    await contractService.activateL3(reportId, itemId, (l3Input[k] ?? '').trim())
    details[reportId] = await contractService.reportDetail(reportId)
    l3Input[k] = ''
  } catch (err: any) {
    console.warn('[acceptance] L3 激活失败:', err?.message)
  } finally {
    l3Busy[k] = false
  }
}

async function draftFix(reportId: string, itemId: string) {
  const k = key(reportId, itemId)
  if (fixBusy[k]) return
  fixBusy[k] = true
  try {
    const r = await contractService.fixInstruction(itemId)
    fixDrafts[k] = r.instruction
  } catch (err: any) {
    console.warn('[acceptance] 修复指令起草失败:', err?.message)
  } finally {
    fixBusy[k] = false
  }
}

function copyFix(k: string) {
  const text = fixDrafts[k] || ''
  try {
    void navigator.clipboard?.writeText(text)
  } catch {
    /* ignore */
  }
}

function factsOf(rid: string, itemId: string, layer: 'L1' | 'L2'): AcceptanceFact | undefined {
  return (details[rid]?.facts ?? []).find((f) => f.itemId === itemId && f.checkLayer === layer)
}

function itemIdsOf(rid: string): string[] {
  const seen: string[] = []
  for (const f of details[rid]?.facts ?? []) {
    if (!seen.includes(f.itemId)) seen.push(f.itemId)
  }
  return seen
}

function factLines(rid: string, itemId: string): { layer: 'L1' | 'L2'; fact: AcceptanceFact }[] {
  const out: { layer: 'L1' | 'L2'; fact: AcceptanceFact }[] = []
  for (const layer of CHECK_LAYERS) {
    const f = factsOf(rid, itemId, layer)
    if (f) out.push({ layer, fact: f })
  }
  return out
}

function opinionsOf(rid: string, itemId: string): AcceptanceOpinion[] {
  return (details[rid]?.opinions ?? []).filter((o) => o.itemId === itemId)
}

function verdictCls(v?: string): string {
  if (v === 'pass') return 'bg-ctp-green/15 text-ctp-green'
  if (v === 'fail') return 'bg-ctp-red/15 text-ctp-red'
  return 'bg-ctp-yellow/15 text-ctp-yellow'
}

function verdictLabel(v?: string): string {
  return v === 'pass' ? t('localAcceptance.pass') : v === 'fail' ? t('localAcceptance.fail') : t('localAcceptance.partial')
}

const CHECK_LAYERS = ['L1', 'L2'] as const

const pkgSelected = computed(() => packages.value.find((p) => p.id === pkgId.value))

onMounted(async () => {
  unitTest.load()
  await loadPackages()
  await loadReports()
})
</script>

<template>
  <div class="h-full flex flex-col min-h-0 gap-3">
    <!-- 工具条：契约包选择 + 触发验收 -->
    <div class="shrink-0 flex flex-wrap items-center gap-2">
      <select
        v-model="pkgId"
        class="input !py-1.5 text-xs w-72"
        @change="loadReports()"
      >
        <option
          v-for="p in packages"
          :key="p.id"
          :value="p.id"
        >
          {{ p.id }} · {{ p.itemIds.length }} {{ t('localAcceptance.items') }} · {{ t(`acceptance.pkgStatus.${p.status}`) }}
        </option>
      </select>
      <button
        class="btn btn-sm btn-blue"
        :disabled="!pkgId || running"
        :title="t('localAcceptance.runHint')"
        @click="run"
      >
        <PlayIcon class="w-3.5 h-3.5" />
        {{ running ? t('localAcceptance.running') : t('localAcceptance.run') }}
      </button>
      <span
        v-if="pkgSelected?.frameworkSnapshot"
        class="chip bg-ctp-surface0 text-ctp-subtext1"
      >
        {{ t('localAcceptance.snapshot') }}: {{ pkgSelected.frameworkSnapshot.activeTier }} v{{ pkgSelected.frameworkSnapshot.version }}
      </span>
      <span v-if="loading" class="text-[11px] text-ctp-overlay1">{{ t('common.loading') }}</span>
    </div>
    <p
      v-if="runError"
      class="shrink-0 text-[11px] text-ctp-red"
    >
      {{ runError }}
    </p>
    <div
      v-if="rejectionHint"
      class="shrink-0 flex items-center gap-2 border border-ctp-mauve/25 bg-ctp-mauve/5 rounded-lg px-2 py-1.5"
    >
      <LightBulbIcon class="w-3.5 h-3.5 text-ctp-mauve shrink-0" />
      <span class="flex-1 text-[11px] text-ctp-text">{{ rejectionHint }}</span>
      <button class="btn btn-xs btn-ghost" @click="rejectionHint = ''">
        <XMarkIcon class="w-3 h-3" />
      </button>
    </div>

    <!-- 报告列表（facts/opinions 分区；判定动作在此区块） -->
    <div class="flex-1 min-h-0 overflow-auto space-y-2">
      <div
        v-for="r in reports"
        :key="r.id"
        class="panel overflow-hidden"
      >
        <button
          class="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-ctp-surface0/40 transition-colors"
          @click="toggleReport(r)"
        >
          <component
            :is="expanded[r.id] ? ChevronDownIcon : ChevronRightIcon"
            class="w-3.5 h-3.5 text-ctp-overlay0 shrink-0"
          />
          <span class="font-mono text-[11px] text-ctp-subtext0">{{ r.id }}</span>
          <span class="chip bg-ctp-surface0 text-ctp-subtext1">{{ r.triggerInfo?.type ?? 'manual' }}</span>
          <template v-if="r.summary">
            <span class="chip bg-ctp-green/15 text-ctp-green">{{ r.summary.pass ?? 0 }} {{ t('localAcceptance.pass') }}</span>
            <span
              v-if="(r.summary.fail ?? 0) > 0"
              class="chip bg-ctp-red/15 text-ctp-red"
            >{{ r.summary.fail }} {{ t('localAcceptance.fail') }}</span>
            <span
              v-if="(r.summary.awaitingHuman ?? 0) > 0"
              class="chip bg-ctp-yellow/15 text-ctp-yellow"
            >{{ r.summary.awaitingHuman }} {{ t('localAcceptance.awaitingHuman') }}</span>
            <span
              v-if="r.summary.degraded"
              class="chip bg-ctp-peach/15 text-ctp-peach"
            >{{ t('localAcceptance.degraded') }}</span>
          </template>
          <span class="flex-1" />
          <span class="text-[10px] text-ctp-overlay0">{{ new Date(r.createdAt).toLocaleString() }}</span>
        </button>

        <div
          v-if="expanded[r.id] && details[r.id]"
          class="border-t border-ctp-surface0 divide-y divide-ctp-surface0"
        >
          <div
            v-for="itemId in itemIdsOf(r.id)"
            :key="itemId"
            class="px-3 py-2"
          >
            <div class="flex items-center gap-2">
              <span class="font-mono text-[11px] text-ctp-text">{{ itemId }}</span>
              <span
                v-if="itemsById[itemId]"
                class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext1 shrink-0"
              >{{ itemsById[itemId].kind }}/{{ itemsById[itemId].level }}</span>
              <span
                v-if="itemsById[itemId]?.target?.file || itemsById[itemId]?.target?.symbol"
                class="font-mono text-[10px] text-ctp-overlay1 truncate"
              >{{ [itemsById[itemId]?.target?.file, itemsById[itemId]?.target?.symbol].filter(Boolean).join('::') }}</span>
              <span class="flex-1" />
              <!-- L1/L2 事实徽标（机械比对，可复现） -->
              <span class="chip !text-[9px] shrink-0" :class="verdictCls(factsOf(r.id, itemId, 'L1')?.verdict)">
                L1 {{ verdictLabel(factsOf(r.id, itemId, 'L1')?.verdict) }}
              </span>
              <span class="chip !text-[9px] shrink-0" :class="verdictCls(factsOf(r.id, itemId, 'L2')?.verdict)">
                L2 {{ verdictLabel(factsOf(r.id, itemId, 'L2')?.verdict) }}
              </span>
              <!-- 设计者判定（唯一判定入口） -->
              <template v-if="itemsById[itemId] && ['confirmed', 'injected', 'verifying'].includes(itemsById[itemId].status)">
                <button class="btn btn-xs btn-green" @click="verdict(itemId, 'accepted')">
                  <ClipboardDocumentCheckIcon class="w-3 h-3" />{{ t('localAcceptance.accept') }}
                </button>
                <button class="btn btn-xs btn-ghost text-ctp-red" @click="verdict(itemId, 'rejected')">
                  {{ t('localAcceptance.reject') }}
                </button>
              </template>
              <span
                v-else-if="itemsById[itemId]"
                class="chip !text-[9px] shrink-0"
                :class="itemsById[itemId].status === 'accepted' ? 'bg-ctp-green/15 text-ctp-green' : 'bg-ctp-red/15 text-ctp-red'"
              >{{ t(`requirement.chat.contractStatus.${itemsById[itemId].status}`) }}</span>
            </div>
            <!-- 证据（事实明细） -->
            <div class="mt-1 space-y-0.5">
              <p
                v-for="line in factLines(r.id, itemId)"
                :key="line.layer"
                class="text-[10px] text-ctp-subtext0 pl-4"
              >
                <span class="font-mono text-ctp-overlay1">{{ line.layer }}</span>
                {{ line.fact.evidence?.detail }}
              </p>
            </div>
            <!-- A7 关联单测（引用关系，任意状态可改） -->
            <div class="mt-1.5 flex items-center gap-1.5 flex-wrap">
              <BeakerIcon class="w-3.5 h-3.5 text-ctp-yellow shrink-0" />
              <span class="text-[10px] text-ctp-subtext0">{{ t('localAcceptance.linkedTests') }}</span>
              <template v-if="linkedOf(itemId).length">
                <span
                  v-for="tid in linkedOf(itemId)"
                  :key="tid"
                  class="inline-flex items-center gap-1 chip !text-[9px] bg-ctp-surface0 text-ctp-subtext1"
                >
                  {{ unitTest.byId(tid)?.name ?? tid }}
                  <button class="text-ctp-overlay1 hover:text-ctp-red" @click="removeLinkedTest(itemId, tid)">
                    <XMarkIcon class="w-2.5 h-2.5" />
                  </button>
                </span>
              </template>
              <select
                v-else
                class="input !py-0.5 !text-[10px] w-44"
                :value="''"
                :disabled="!unitTests.length"
                @change="(e) => addLinkedTest(itemId, (e.target as HTMLSelectElement).value)"
              >
                <option value="">{{ unitTests.length ? t('localAcceptance.linkTestAdd') : t('localAcceptance.linkTestNone') }}</option>
                <option
                  v-for="ut in unitTests"
                  :key="ut.id"
                  :value="ut.id"
                >{{ ut.name }}</option>
              </select>
              <select
                v-if="linkedOf(itemId).length"
                class="input !py-0.5 !text-[10px] w-44"
                :value="''"
                :disabled="!unitTests.length"
                @change="(e) => addLinkedTest(itemId, (e.target as HTMLSelectElement).value)"
              >
                <option value="">{{ t('localAcceptance.linkTestAdd') }}</option>
                <option
                  v-for="ut in unitTests"
                  :key="ut.id"
                  :value="ut.id"
                  :disabled="linkedOf(itemId).includes(ut.id)"
                >{{ ut.name }}</option>
              </select>
            </div>
            <!-- B2 双图对照（期望 vs 实际；复用共享 IR，差异高亮） -->
            <div class="mt-1.5 flex items-center gap-2">
              <button
                class="btn !py-1 !text-[10px] !px-2 flex items-center gap-1.5"
                @click="openDual(itemsById[itemId])"
              >
                <Square2StackIcon class="w-3.5 h-3.5" />
                {{ t('localAcceptance.dualDiagram') }}
              </button>
              <button
                class="btn !py-1 !text-[10px] !px-2 flex items-center gap-1.5"
                @click="openAuth(itemsById[itemId])"
              >
                <ClipboardDocumentListIcon class="w-3.5 h-3.5" />
                {{ t('localAcceptance.authorization') }}
              </button>
            </div>
            <!-- L3 参考意见（人工主判；按需激活模型辅助） -->
            <div class="mt-1.5 space-y-1.5">
              <div class="flex items-center gap-1.5">
                <input
                  v-model="l3Input[key(r.id, itemId)]"
                  class="input !py-1 !text-[10px] flex-1"
                  :placeholder="t('localAcceptance.l3Placeholder')"
                >
                <button
                  class="btn btn-xs btn-ghost shrink-0"
                  :disabled="l3Busy[key(r.id, itemId)]"
                  :title="t('localAcceptance.l3Hint')"
                  @click="activateL3(r.id, itemId)"
                >
                  <LightBulbIcon class="w-3 h-3" />
                  {{ l3Busy[key(r.id, itemId)] ? t('localAcceptance.l3Running') : t('localAcceptance.l3Activate') }}
                </button>
                <button
                  class="btn btn-xs btn-ghost shrink-0"
                  :disabled="fixBusy[key(r.id, itemId)]"
                  :title="t('localAcceptance.fixHint')"
                  @click="draftFix(r.id, itemId)"
                >
                  <WrenchScrewdriverIcon class="w-3 h-3" />
                  {{ fixBusy[key(r.id, itemId)] ? t('localAcceptance.fixRunning') : t('localAcceptance.fixDraft') }}
                </button>
              </div>
              <div
                v-for="op in opinionsOf(r.id, itemId)"
                :key="op.id"
                class="border border-ctp-mauve/20 bg-ctp-mauve/5 rounded-md px-2 py-1.5"
              >
                <div class="flex items-center gap-1.5 text-[9px] text-ctp-overlay1 mb-0.5">
                  <LightBulbIcon class="w-3 h-3 text-ctp-mauve" />
                  L3 {{ t('localAcceptance.opinion') }}
                  <span class="chip !text-[9px] bg-ctp-mauve/15 text-ctp-mauve">{{ t('localAcceptance.confidence') }} {{ Math.round(op.confidence * 100) }}%</span>
                  <span v-if="op.model" class="font-mono">{{ op.model }}</span>
                  <span>{{ new Date(op.createdAt).toLocaleString() }}</span>
                </div>
                <p class="text-[10px] text-ctp-subtext0 whitespace-pre-wrap">{{ op.text }}</p>
              </div>
              <div
                v-if="fixDrafts[key(r.id, itemId)]"
                class="border border-ctp-teal/20 bg-ctp-teal/5 rounded-md px-2 py-1.5"
              >
                <div class="flex items-center gap-1.5 text-[9px] text-ctp-overlay1 mb-0.5">
                  <WrenchScrewdriverIcon class="w-3 h-3 text-ctp-teal" />
                  {{ t('localAcceptance.fixTitle') }}
                  <button class="btn btn-xs btn-ghost !py-0 !px-1.5" @click="copyFix(key(r.id, itemId))">
                    <ClipboardDocumentIcon class="w-3 h-3" />{{ t('localAcceptance.copy') }}
                  </button>
                </div>
                <p class="text-[10px] text-ctp-subtext0 whitespace-pre-wrap">{{ fixDrafts[key(r.id, itemId)] }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>
      <p
        v-if="!reports.length && !loading"
        class="text-xs text-ctp-overlay0 text-center py-10"
      >
        {{ t('localAcceptance.empty') }}
      </p>
    </div>

    <!-- B2 双图对照对话框（期望 vs 实际；复用共享 IR 渲染） -->
    <div
      v-if="dualItem"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      @click.self="closeDual"
    >
      <div class="w-full max-w-5xl max-h-[88vh] flex flex-col rounded-lg border border-ctp-surface1 bg-ctp-mantle overflow-hidden shadow-2xl">
        <div class="shrink-0 flex items-center gap-2 px-4 py-2.5 border-b border-ctp-surface1">
          <Square2StackIcon class="w-4 h-4 text-ctp-sapphire" />
          <span class="text-sm font-medium text-ctp-text1">{{ t('localAcceptance.dualDiagramTitle') }}</span>
          <span v-if="dual?.assetName" class="text-[10px] text-ctp-subtext0 truncate">
            {{ t('localAcceptance.dualActualAsset') }}: {{ dual.assetName }}
          </span>
          <button class="ml-auto text-ctp-overlay1 hover:text-ctp-text1" @click="closeDual">
            <XMarkIcon class="w-4 h-4" />
          </button>
        </div>
        <div class="flex-1 min-h-0 overflow-y-auto p-4 space-y-3">
          <p v-if="dualBusy" class="text-xs text-ctp-overlay0 text-center py-8">{{ t('localAcceptance.loading') }}</p>
          <p v-else-if="dualError" class="text-xs text-ctp-red text-center py-8">{{ dualError }}</p>
          <template v-else-if="dual">
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
              <div class="rounded-md border border-ctp-surface1 bg-ctp-surface0 p-2">
                <div class="flex items-center gap-1.5 mb-1.5 px-1">
                  <span class="text-[10px] font-medium text-ctp-sapphire">{{ t('localAcceptance.dualExpected') }}</span>
                </div>
                <DiagramCard
                  v-if="dualExpectedCode"
                  :title="t('localAcceptance.dualExpected')"
                  :diagrams="{ mermaid: dualExpectedCode }"
                  :allowed-langs="['mermaid']"
                  headerless
                />
                <p v-else class="text-[10px] text-ctp-overlay0 text-center py-6">{{ t('localAcceptance.dualEmptyExpected') }}</p>
              </div>
              <div class="rounded-md border border-ctp-surface1 bg-ctp-surface0 p-2">
                <div class="flex items-center gap-1.5 mb-1.5 px-1">
                  <span class="text-[10px] font-medium text-ctp-teal">{{ t('localAcceptance.dualActual') }}</span>
                </div>
                <DiagramCard
                  v-if="dualActualCode"
                  :title="t('localAcceptance.dualActual')"
                  :diagrams="{ mermaid: dualActualCode }"
                  :allowed-langs="['mermaid']"
                  headerless
                />
                <p v-else class="text-[10px] text-ctp-overlay0 text-center py-6">{{ t('localAcceptance.dualEmptyActual') }}</p>
              </div>
            </div>
            <!-- 差异清单（点击→对应子图高亮节点；此处列差异语义） -->
            <div class="rounded-md border border-ctp-surface1 bg-ctp-surface0 p-3">
              <div class="flex items-center gap-1.5 mb-2">
                <span class="text-[10px] font-medium text-ctp-text1">{{ t('localAcceptance.dualDiffs') }}</span>
                <span class="text-[9px] text-ctp-overlay1">
                  ({{ t('localAcceptance.dualMissing') }}: {{ dual.diffs.filter((d) => d.type === 'missing').length }} ·
                  {{ t('localAcceptance.dualExtra') }}: {{ dual.diffs.filter((d) => d.type === 'extra').length }})
                </span>
              </div>
              <p v-if="!dual.diffs.length" class="text-[10px] text-ctp-teal">{{ t('localAcceptance.dualNoDiff') }}</p>
              <ul v-else class="space-y-1">
                <li
                  v-for="(d, i) in dual.diffs"
                  :key="i"
                  class="flex items-center gap-1.5 text-[10px]"
                >
                  <span
                    class="w-1.5 h-1.5 rounded-full shrink-0"
                    :class="d.type === 'missing' ? 'bg-ctp-red' : 'bg-ctp-yellow'"
                  />
                  <span class="text-ctp-subtext1">{{ d.semantic }}</span>
                  <span class="text-[9px] text-ctp-overlay1">
                    {{ d.type === 'missing' ? t('localAcceptance.dualMissing') : t('localAcceptance.dualExtra') }}
                  </span>
                </li>
              </ul>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- C1 可授权清单对话框（Z 轴 × mode=auto 细则） -->
    <div
      v-if="authItem"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      @click.self="closeAuth"
    >
      <div class="w-full max-w-2xl max-h-[85vh] flex flex-col rounded-lg border border-ctp-surface1 bg-ctp-mantle overflow-hidden shadow-2xl">
        <div class="shrink-0 flex items-center gap-2 px-4 py-2.5 border-b border-ctp-surface1">
          <ClipboardDocumentListIcon class="w-4 h-4 text-ctp-sapphire" />
          <span class="text-sm font-medium text-ctp-text1">{{ t('localAcceptance.authorizationTitle') }}</span>
          <span v-if="auth" class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext1">
            {{ t('localAcceptance.authMode') }}: {{ auth.mode }}
          </span>
          <button class="ml-auto text-ctp-overlay1 hover:text-ctp-text1" @click="closeAuth">
            <XMarkIcon class="w-4 h-4" />
          </button>
        </div>
        <div class="flex-1 min-h-0 overflow-y-auto p-4 space-y-3">
          <p v-if="authBusy" class="text-xs text-ctp-overlay0 text-center py-8">{{ t('localAcceptance.loading') }}</p>
          <p v-else-if="authError" class="text-xs text-ctp-red text-center py-8">{{ authError }}</p>
          <template v-else-if="auth">
            <div
              class="rounded-md border px-3 py-2 text-[11px] flex items-center gap-2"
              :class="auth.autoPassable ? 'border-ctp-teal/30 bg-ctp-teal/5 text-ctp-teal' : 'border-ctp-yellow/30 bg-ctp-yellow/5 text-ctp-yellow'"
            >
              {{ auth.autoPassable
                ? t('localAcceptance.authAutoPassable')
                : t('localAcceptance.authNotAutoPassable') }}
            </div>
            <ul class="space-y-1.5">
              <li
                v-for="c in auth.checks"
                :key="c.id"
                class="rounded-md border border-ctp-surface1 bg-ctp-surface0 px-3 py-2"
              >
                <div class="flex items-center gap-2">
                  <span
                    class="w-1.5 h-1.5 rounded-full shrink-0"
                    :class="c.authorizable ? 'bg-ctp-teal' : 'bg-ctp-yellow'"
                  />
                  <span class="text-[11px] text-ctp-text1 flex-1">{{ c.label }}</span>
                  <span class="text-[9px] font-mono text-ctp-overlay1">{{ c.id }}</span>
                  <span
                    class="chip !text-[9px]"
                    :class="c.authorizable
                      ? 'bg-ctp-teal/10 text-ctp-teal'
                      : 'bg-ctp-yellow/10 text-ctp-yellow'"
                  >
                    {{ c.authorizable ? t('localAcceptance.authAuto') : t('localAcceptance.authHuman') }}
                  </span>
                </div>
                <p v-if="c.note" class="mt-1 text-[10px] text-ctp-subtext0 pl-3.5">{{ c.note }}</p>
              </li>
            </ul>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>
