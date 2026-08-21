<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  XMarkIcon, SparklesIcon, ArrowPathIcon, ArrowsRightLeftIcon,
} from '@heroicons/vue/24/outline'
import DiagramCard from '@/components/diagram/DiagramCard.vue'
import { structuresToMermaid } from '@/utils/diagram-gen'
import { designService } from '@/services/design-service'
import type {
  CompareResult, DesignDataChange, DesignSemanticChange,
  ErTable, RequirementAnalysis, RequirementDesign,
} from '@/types'

/**
 * 方向2/3：设计方案面板。
 *  - 数据层增删改查(dataChanges CRUD 表)
 *  - 接口/流程层(interfaceChanges) / 语义层(semanticChanges)
 *  - 落地步骤 + 图形化修改方案(现状 ER | 目标 ER 差异着色)
 *  - 变更对比(planned 计划态 / actual 实施后实际偏差)
 */

const props = defineProps<{
  open: boolean
  reqId: string
  analysis?: RequirementAnalysis
  canExecute?: boolean
}>()
const emit = defineEmits<{ close: []; execute: [] }>()

const { t } = useI18n()

type DesignTab = 'data' | 'interface' | 'semantic' | 'steps' | 'diagram' | 'compare'
const tab = ref<DesignTab>('data')

const design = ref<RequirementDesign | null>(null)
const beforeTables = ref<ErTable[]>([])
const afterTables = ref<ErTable[]>([])
const generating = ref(false)
const genError = ref('')

const compareResult = ref<CompareResult | null>(null)
const compareMode = ref<'planned' | 'actual'>('planned')
const comparing = ref(false)

watch(
  () => props.open,
  (v) => {
    if (!v) return
    reset()
    load()
  },
)

function reset() {
  design.value = null
  beforeTables.value = []
  afterTables.value = []
  genError.value = ''
  compareResult.value = null
  tab.value = 'data'
}

async function load() {
  try {
    const res = await designService.getDesign(props.reqId)
    if (res.design) {
      design.value = res.design
      beforeTables.value = res.beforeTables ?? []
      afterTables.value = res.afterTables ?? []
    }
  } catch {
    // 读取失败静默，显示生成 CTA
  }
}

async function generate() {
  generating.value = true
  genError.value = ''
  try {
    const res = await designService.design(props.reqId, props.analysis)
    design.value = res.design
    beforeTables.value = res.beforeTables ?? []
    afterTables.value = res.afterTables ?? []
    tab.value = 'data'
  } catch (err) {
    genError.value = err instanceof Error ? err.message : '生成失败'
  } finally {
    generating.value = false
  }
}

async function runCompare(mode: 'planned' | 'actual') {
  compareMode.value = mode
  comparing.value = true
  try {
    compareResult.value = await designService.compare(props.reqId, mode)
  } finally {
    comparing.value = false
  }
}

// ── 展示辅助 ──
const actionColor: Record<string, string> = {
  create: 'bg-ctp-green/15 text-ctp-green',
  alter: 'bg-ctp-yellow/15 text-ctp-yellow',
  extend: 'bg-ctp-blue/15 text-ctp-blue',
  drop: 'bg-ctp-red/15 text-ctp-red',
}
const actionLabel = (a: string) => t(`design.action.${a}`) || a

const summary = computed(() => {
  if (!design.value) return null
  return {
    create: (design.value.dataChanges ?? []).filter((d) => d.action === 'create').length,
    alter: (design.value.dataChanges ?? []).filter((d) => d.action === 'alter' || d.action === 'extend').length,
    drop: (design.value.dataChanges ?? []).filter((d) => d.action === 'drop').length,
    sem: (design.value.semanticChanges ?? []).length,
    itf: (design.value.interfaceChanges ?? []).length,
  }
})

const colSummary = computed(() => {
  const out: Record<string, { added: number; removed: number; modified: number }> = {}
  for (const tid of Object.keys(compareResult.value?.columnDiffs ?? {})) {
    const d = compareResult.value!.columnDiffs![tid]
    out[tid] = { added: d.added.length, removed: d.removed.length, modified: d.modified.length }
  }
  return out
})

const beforeCode = computed(() => structuresToMermaid(beforeTables.value))
const afterCode = computed(() => structuresToMermaid(afterTables.value))

const dataChanges = computed<DesignDataChange[]>(() => design.value?.dataChanges ?? [])
const semanticChanges = computed<DesignSemanticChange[]>(() => design.value?.semanticChanges ?? [])

function columnsText(ch: DesignDataChange): string {
  const cols = ch.detail?.columns ?? []
  if (!cols.length) return '—'
  return cols.map((c) => `${c.name}:${c.type}${c.pk ? '🔑' : ''}${c.fk ? `→${c.fk}` : ''}`).join('、')
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
  >
    <div class="flex flex-col w-full max-w-5xl max-h-[88vh] rounded-xl bg-ctp-base border border-ctp-surface1 shadow-2xl overflow-hidden">
      <div class="shrink-0 px-4 py-3 border-b border-ctp-surface0">
        <div class="flex items-center gap-2">
          <SparklesIcon class="w-4 h-4 text-ctp-sky" />
          <h3 class="text-sm font-semibold text-ctp-text">
            {{ t('design.title') }}
          </h3>
          <span class="text-[10px] text-ctp-overlay0 hidden md:inline">{{ t('design.subtitle') }}</span>
          <span class="flex-1" />
          <button
            v-if="design"
            class="btn btn-xs btn-ghost"
            :disabled="generating"
            @click="generate"
          >
            <ArrowPathIcon
              class="w-3 h-3"
              :class="generating ? 'animate-spin' : ''"
            />{{ generating ? t('design.running') : t('design.button') }}
          </button>
          <button
            class="btn btn-xs btn-ghost"
            @click="emit('close')"
          >
            <XMarkIcon class="w-3.5 h-3.5" />{{ t('scope.close') }}
          </button>
        </div>
        <div
          v-if="design"
          class="mt-2 flex items-center gap-2"
        >
          <span class="chip bg-ctp-surface0 text-ctp-subtext1 !text-[10px] font-mono">{{ props.reqId }}</span>
          <span
            class="chip bg-ctp-green/15 text-ctp-green !text-[10px]"
          >+{{ summary?.create ?? 0 }} {{ t('design.action.create') }}</span>
          <span
            class="chip bg-ctp-yellow/15 text-ctp-yellow !text-[10px]"
          >~{{ summary?.alter ?? 0 }} {{ t('design.action.alter') }}</span>
          <span
            class="chip bg-ctp-red/15 text-ctp-red !text-[10px]"
          >-{{ summary?.drop ?? 0 }} {{ t('design.action.drop') }}</span>
          <span
            class="chip bg-ctp-blue/15 text-ctp-blue !text-[10px]"
          >{{ summary?.sem ?? 0 }} {{ t('design.tabs.semantic') }}</span>
          <span class="text-[9px] text-ctp-overlay0">{{ t('design.summary') }}</span>
        </div>
      </div>

      <div class="shrink-0 flex items-center gap-1 px-4 py-2 border-b border-ctp-surface0">
        <button
          v-for="tb in ['data', 'interface', 'semantic', 'steps', 'diagram', 'compare'] as const"
          :key="tb"
          class="btn btn-xs"
          :class="tab === tb ? 'btn-blue' : 'btn-ghost'"
          :disabled="!design"
          @click="tab = tb"
        >
          {{ t(`design.tabs.${tb}`) }}
        </button>
      </div>

      <div class="flex-1 min-h-0 overflow-auto p-4">
        <div
          v-if="!design"
          class="h-full flex flex-col items-center justify-center gap-3 text-center"
        >
          <p class="text-xs text-ctp-overlay0 max-w-md">
            {{ t('design.notGenerated') }}
          </p>
          <p
            v-if="genError"
            class="text-xs text-ctp-red"
          >
            {{ genError }}
          </p>
          <button
            class="btn btn-blue"
            :disabled="generating"
            @click="generate"
          >
            <SparklesIcon
              class="w-4 h-4"
              :class="generating ? 'animate-pulse' : ''"
            />{{ generating ? t('design.running') : t('design.generate') }}
          </button>
        </div>

        <!-- 数据层增删改查 -->
        <div
          v-else-if="tab === 'data'"
          class="space-y-2"
        >
          <p
            v-if="!dataChanges.length"
            class="text-xs text-ctp-overlay0"
          >
            {{ t('design.noChanges') }}
          </p>
          <div
            v-for="(ch, i) in dataChanges"
            :key="i"
            class="border border-ctp-surface0 rounded-lg overflow-hidden"
          >
            <div class="flex items-center gap-2 px-2.5 py-1.5 bg-ctp-mantle">
              <span
                class="chip !text-[10px] shrink-0"
                :class="actionColor[ch.action] || 'bg-ctp-surface0 text-ctp-subtext0'"
              >{{ actionLabel(ch.action) }}</span>
              <span class="text-[11px] font-mono text-ctp-text truncate">{{ ch.assetId || ch.name || '—' }}</span>
              <span
                v-if="ch.name"
                class="text-[10px] text-ctp-overlay1 truncate"
              >{{ ch.name }}</span>
              <span
                v-if="ch.assetType"
                class="chip bg-ctp-surface0 text-ctp-subtext0 !text-[9px] font-mono shrink-0"
              >{{ ch.assetType }}</span>
              <span class="flex-1" />
              <span
                v-if="colSummary[ch.assetId || '']"
                class="text-[9px] text-ctp-overlay0 font-mono shrink-0"
              >{{ t('design.diffCols.added') }} {{ colSummary[ch.assetId || ''].added }} · {{ t('design.diffCols.removed') }} {{ colSummary[ch.assetId || ''].removed }} · {{ t('design.diffCols.modified') }} {{ colSummary[ch.assetId || ''].modified }}</span>
            </div>
            <div class="px-2.5 py-1.5">
              <p
                v-if="ch.detail?.desc"
                class="text-[10px] text-ctp-subtext0 mb-1"
              >
                {{ ch.detail.desc }}
              </p>
              <p class="text-[10px] text-ctp-overlay1 font-mono break-all">
                {{ columnsText(ch) }}
              </p>
            </div>
          </div>
        </div>

        <!-- 接口/流程层 -->
        <div
          v-else-if="tab === 'interface'"
          class="space-y-2"
        >
          <div
            v-for="(it, i) in design.interfaceChanges"
            :key="i"
            class="border border-ctp-surface0 rounded-lg px-2.5 py-2"
          >
            <div class="flex items-center gap-2">
              <span class="text-[11px] font-mono text-ctp-text truncate">{{ it.name || it.assetId || '—' }}</span>
              <span
                v-if="it.action"
                class="chip bg-ctp-surface0 text-ctp-subtext0 !text-[9px] shrink-0"
              >{{ it.action }}</span>
              <span class="flex-1" />
              <span
                v-if="it.assetType"
                class="chip bg-ctp-surface0 text-ctp-overlay0 !text-[9px] font-mono shrink-0"
              >{{ it.assetType }}</span>
            </div>
            <div
              v-if="it.detail?.endpoints?.length"
              class="mt-1"
            >
              <div class="text-[10px] font-medium text-ctp-sky mb-0.5">
                {{ t('design.endpoint') }}
              </div>
              <div
                v-for="(ep, ei) in it.detail.endpoints"
                :key="ei"
                class="pl-2 font-mono text-[9px] text-ctp-subtext0"
              >
                {{ ep }}
              </div>
            </div>
            <div
              v-if="it.detail?.flows?.length"
              class="mt-1"
            >
              <div class="text-[10px] font-medium text-ctp-blue mb-0.5">
                {{ t('design.flow') }}
              </div>
              <div
                v-for="(f, fi) in it.detail.flows"
                :key="fi"
                class="pl-2 font-mono text-[9px] text-ctp-subtext0"
              >
                {{ f }}
              </div>
            </div>
            <p
              v-if="it.reason"
              class="mt-1 text-[10px] text-ctp-overlay1"
            >
              {{ t('design.reason') }}：{{ it.reason }}
            </p>
          </div>
          <p
            v-if="!design.interfaceChanges.length"
            class="text-xs text-ctp-overlay0"
          >
            —
          </p>
        </div>

        <!-- 语义层 -->
        <div
          v-else-if="tab === 'semantic'"
          class="space-y-2"
        >
          <div
            v-for="(s, i) in semanticChanges"
            :key="i"
            class="border border-ctp-surface0 rounded-lg px-2.5 py-2 flex items-start gap-2"
          >
            <span
              class="chip !text-[10px] shrink-0 mt-0.5"
              :class="actionColor[s.action || 'modify'] || 'bg-ctp-surface0 text-ctp-subtext0'"
            >{{ actionLabel(s.action || 'modify') }}</span>
            <div class="min-w-0">
              <span class="text-[11px] font-mono text-ctp-text break-all">{{ s.name || s.assetId || '—' }}</span>
              <p
                v-if="s.reason"
                class="text-[10px] text-ctp-overlay1"
              >
                {{ t('design.reason') }}：{{ s.reason }}
              </p>
            </div>
          </div>
          <p
            v-if="!semanticChanges.length"
            class="text-xs text-ctp-overlay0"
          >
            —
          </p>
        </div>

        <!-- 落地步骤 -->
        <div
          v-else-if="tab === 'steps'"
          class="space-y-2"
        >
          <div
            v-for="(s, i) in design.steps"
            :key="i"
            class="border border-ctp-surface0 rounded-lg px-2.5 py-2"
          >
            <div class="flex items-center gap-2">
              <span class="w-5 h-5 rounded-full bg-ctp-surface1 text-ctp-subtext0 text-[10px] flex items-center justify-center shrink-0">{{ i + 1 }}</span>
              <span class="text-[11px] font-medium text-ctp-text truncate">{{ s.title }}</span>
              <span class="flex-1" />
              <span
                v-if="s.estMin"
                class="chip bg-ctp-surface0 text-ctp-subtext0 !text-[9px] font-mono shrink-0"
              >{{ t('design.stepEst') }} {{ s.estMin }}m</span>
            </div>
            <p
              v-if="s.desc"
              class="pl-7 text-[10px] text-ctp-subtext0"
            >
              {{ s.desc }}
            </p>
          </div>
          <div
            v-if="design.landingNote"
            class="border border-ctp-yellow/20 rounded-lg px-2.5 py-2"
          >
            <div class="text-[10px] font-semibold text-ctp-yellow mb-0.5">
              {{ t('design.landingNote') }}
            </div>
            <p class="text-[10px] text-ctp-subtext0 whitespace-pre-wrap">
              {{ design.landingNote }}
            </p>
          </div>
        </div>

        <!-- 图形化修改方案 -->
        <div
          v-else-if="tab === 'diagram'"
          class="space-y-3"
        >
          <DiagramCard
            :title="t('design.before')"
            :diagrams="{ mermaid: beforeCode }"
          />
          <DiagramCard
            :title="`${t('design.after')}（变更着色：绿=新增 红=删除 黄=修改）`"
            :diagrams="{ mermaid: afterCode }"
          />
        </div>

        <!-- 变更对比 -->
        <div
          v-else-if="tab === 'compare'"
          class="space-y-3"
        >
          <div class="flex items-center gap-2 flex-wrap">
            <button
              class="btn btn-xs"
              :class="compareMode === 'planned' ? 'btn-blue' : 'btn-ghost'"
              :disabled="comparing"
              @click="runCompare('planned')"
            >
              <ArrowsRightLeftIcon class="w-3 h-3" />{{ t('design.compare.planned') }}
            </button>
            <button
              class="btn btn-xs"
              :class="compareMode === 'actual' ? 'btn-blue' : 'btn-ghost'"
              :disabled="comparing"
              @click="runCompare('actual')"
            >
              <ArrowPathIcon
                class="w-3 h-3"
                :class="comparing ? 'animate-spin' : ''"
              />{{ t('design.compare.actual') }}
            </button>
            <span class="text-[9px] text-ctp-overlay0">
              {{ compareMode === 'planned' ? t('design.compare.plannedHint') : t('design.compare.actualHint') }}
            </span>
          </div>

          <template v-if="compareResult">
            <div class="flex items-center gap-2">
              <span
                class="chip bg-ctp-green/15 text-ctp-green !text-[10px]"
              >+{{ compareResult.summary.added }}</span>
              <span
                class="chip bg-ctp-yellow/15 text-ctp-yellow !text-[10px]"
              >~{{ compareResult.summary.modified }}</span>
              <span
                class="chip bg-ctp-red/15 text-ctp-red !text-[10px]"
              >-{{ compareResult.summary.removed }}</span>
              <span
                class="chip bg-ctp-blue/15 text-ctp-blue !text-[10px]"
              >{{ compareResult.semanticDiff.summary.create ?? 0 }} {{ t('design.action.create') }} · {{ compareResult.semanticDiff.summary.modify ?? 0 }} {{ t('design.action.alter') }} · {{ compareResult.semanticDiff.summary.drop ?? 0 }} {{ t('design.action.drop') }}（{{ t('design.tabs.semantic') }}）</span>
              <span class="text-[9px] text-ctp-overlay0">{{ t('design.compare.summary') }}</span>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
              <DiagramCard
                :title="`${t('design.before')}`"
                :diagrams="{ mermaid: structuresToMermaid(compareResult.beforeTables) }"
              />
              <DiagramCard
                :title="`${t('design.after')}`"
                :diagrams="{ mermaid: structuresToMermaid(compareResult.afterTables) }"
              />
            </div>

            <div
              v-if="Object.keys(compareResult.columnDiffs ?? {}).length"
              class="border border-ctp-surface0 rounded-lg p-2.5 space-y-1.5"
            >
              <div class="text-[10px] font-semibold text-ctp-subtext1">
                {{ t('design.diffCols.modified') }}
              </div>
              <div
                v-for="(cols, tid) in compareResult.columnDiffs!"
                :key="tid"
                class="text-[10px]"
              >
                <span class="font-mono text-ctp-text">{{ tid }}</span>
                <span class="text-ctp-overlay1">：</span>
                <span
                  v-if="cols.added.length"
                  class="text-ctp-green"
                >+{{ cols.added.map((c) => c.name).join(', ') }}</span>
                <span
                  v-if="cols.removed.length"
                  class="text-ctp-red"
                > -{{ cols.removed.map((c) => c.name).join(', ') }}</span>
                <span
                  v-if="cols.modified.length"
                  class="text-ctp-yellow"
                > ~{{ cols.modified.map((m) => m.name).join(', ') }}</span>
              </div>
            </div>

            <div
              v-if="compareResult.deviations?.length"
              class="border border-ctp-red/20 rounded-lg p-2.5"
            >
              <div class="text-[10px] font-semibold text-ctp-red mb-1.5">
                {{ t('design.compare.deviations') }}
              </div>
              <div
                v-for="(d, i) in compareResult.deviations"
                :key="i"
                class="text-[10px] py-0.5"
              >
                <span class="chip bg-ctp-red/15 text-ctp-red !text-[9px] shrink-0">{{ d.kind }}</span>
                <span class="font-mono text-ctp-text">{{ d.planned }}</span>
                <span class="text-ctp-overlay0">→</span>
                <span class="font-mono text-ctp-subtext1">{{ d.actual }}</span>
                <span class="text-ctp-overlay1">（{{ d.note }}）</span>
              </div>
            </div>
            <p
              v-else-if="compareResult.mode === 'actual'"
              class="text-[10px] text-ctp-green"
            >
              {{ t('design.compare.noDeviations') }}
            </p>
          </template>
        </div>
      </div>

      <div class="shrink-0 border-t border-ctp-surface0 px-4 py-2.5 flex justify-end gap-2">
        <button
          class="btn btn-ghost"
          @click="emit('close')"
        >
          {{ t('scope.close') }}
        </button>
        <button
          v-if="canExecute"
          class="btn btn-primary"
          @click="emit('execute')"
        >
          <ArrowsRightLeftIcon class="w-3.5 h-3.5" />{{ t('requirement.workspace.executeNow') }}
        </button>
      </div>
    </div>
  </div>
</template>
