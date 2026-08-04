<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { MagnifyingGlassIcon, ArrowsRightLeftIcon, SparklesIcon, DocumentTextIcon, CubeTransparentIcon, ChartBarIcon, CheckCircleIcon, ChevronDownIcon, ChevronUpIcon } from '@heroicons/vue/24/outline'
import MarkdownView from '@/components/MarkdownView.vue'
import { useArchArchitectureStore } from '@/stores/architecture-store'
import { useArchKbQueryStore } from '@/stores/kb-query-store'
import type { KbQueryResult, KbQuerySection, KbQuerySpec } from '@/types'

const { t } = useI18n()
const arch = useArchArchitectureStore()
const kb = useArchKbQueryStore()
kb.load()

const kind = ref<'depends' | 'calls'>('depends')
const selected = ref<string[]>([])
const sections = ref<KbQuerySection[]>(['basic', 'structure', 'flow'])
const note = ref('')
const query = ref('')

const filteredComps = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return arch.components
  return arch.components.filter((c) => c.name.toLowerCase().includes(q) || c.id.toLowerCase().includes(q))
})

function toggleComp(id: string) {
  const i = selected.value.indexOf(id)
  if (i >= 0) selected.value.splice(i, 1)
  else selected.value.push(id)
}

function toggleSection(s: KbQuerySection) {
  const i = sections.value.indexOf(s)
  if (i >= 0) {
    if (sections.value.length > 1) sections.value.splice(i, 1)
  } else {
    sections.value.push(s)
  }
}

async function run() {
  if (!selected.value.length) return
  const spec: KbQuerySpec = {
    kind: kind.value,
    compIds: [...selected.value],
    sections: [...sections.value],
    note: note.value.trim() || undefined,
  }
  await kb.query(spec)
}

const result = computed<KbQueryResult | null>(() => kb.lastResult)

const sectionIcon = {
  basic: DocumentTextIcon,
  structure: CubeTransparentIcon,
  flow: ChartBarIcon,
}

const openResult = ref<Record<string, boolean>>({})
function toggleResult(compId: string) {
  openResult.value[compId] = !openResult.value[compId]
}

const displayResult = computed(() => {
  const r = result.value
  if (!r) return null
  return r
})
</script>

<template>
  <div class="grid grid-cols-1 xl:grid-cols-5 gap-4">
    <!-- 查询条件(左) -->
    <div class="xl:col-span-2 space-y-4">
      <div class="panel overflow-hidden">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            <MagnifyingGlassIcon class="w-4 h-4 text-ctp-blue" />{{ t('kbQuery.title') }}
          </span>
          <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ kb.cacheCount }} {{ t('kbQuery.cacheCount') }}</span>
        </div>
        <div class="p-4 space-y-4">
          <!-- 关系类型 -->
          <div>
            <div class="text-[10px] uppercase tracking-wider text-ctp-overlay1 mb-1.5">
              {{ t('kbQuery.relation') }}
            </div>
            <div class="flex items-center gap-1 bg-ctp-crust/60 rounded-lg p-1 w-fit">
              <button
                class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-colors"
                :class="kind === 'depends' ? 'bg-ctp-surface1 text-ctp-text' : 'text-ctp-subtext0 hover:text-ctp-text'"
                @click="kind = 'depends'"
              >
                <ArrowsRightLeftIcon class="w-3.5 h-3.5" />{{ t('kbQuery.depends') }}
              </button>
              <button
                class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-colors"
                :class="kind === 'calls' ? 'bg-ctp-surface1 text-ctp-text' : 'text-ctp-subtext0 hover:text-ctp-text'"
                @click="kind = 'calls'"
              >
                <SparklesIcon class="w-3.5 h-3.5" />{{ t('kbQuery.calls') }}
              </button>
            </div>
            <p class="text-[11px] text-ctp-overlay1 mt-1.5">
              {{ kind === 'depends' ? t('kbQuery.dependsHint') : t('kbQuery.callsHint') }}
            </p>
          </div>

          <!-- 组件选择 -->
          <div>
            <div class="text-[10px] uppercase tracking-wider text-ctp-overlay1 mb-1.5">
              {{ t('kbQuery.components') }} ({{ selected.length }})
            </div>
            <div class="flex items-center gap-1.5 mb-2">
              <MagnifyingGlassIcon class="w-3.5 h-3.5 text-ctp-overlay0 shrink-0" />
              <input
                v-model="query"
                class="bg-ctp-crust/60 border border-ctp-surface0 rounded px-2 py-1 text-xs w-full outline-none focus:border-ctp-blue"
                :placeholder="t('kbQuery.compSearch')"
              >
            </div>
            <div class="max-h-[220px] overflow-auto space-y-0.5 border border-ctp-surface0 rounded-lg p-1.5">
              <label
                v-for="c in filteredComps"
                :key="c.id"
                class="flex items-center gap-2 px-2 py-1 rounded hover:bg-ctp-surface0 cursor-pointer text-xs"
              >
                <input
                  type="checkbox"
                  :checked="selected.includes(c.id)"
                  class="accent-ctp-blue"
                  @change="toggleComp(c.id)"
                >
                <span class="flex-1 text-ctp-text truncate">{{ c.name }}</span>
                <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ c.kind }}</span>
              </label>
              <p
                v-if="!filteredComps.length"
                class="text-[11px] text-ctp-overlay1 px-2 py-2"
              >
                {{ t('kbQuery.noComps') }}
              </p>
            </div>
          </div>

          <!-- 查询范围 -->
          <div>
            <div class="text-[10px] uppercase tracking-wider text-ctp-overlay1 mb-1.5">
              {{ t('kbQuery.scope') }}
            </div>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="(icon, s) in sectionIcon"
                :key="s"
                class="flex items-center gap-1 px-2.5 py-1 rounded-md text-xs transition-colors border"
                :class="sections.includes(s as KbQuerySection)
                  ? 'border-ctp-blue/50 bg-ctp-blue/10 text-ctp-blue'
                  : 'border-ctp-surface0 text-ctp-subtext0 hover:text-ctp-text'"
                @click="toggleSection(s as KbQuerySection)"
              >
                <component
                  :is="icon"
                  class="w-3.5 h-3.5"
                />{{ t(`kbQuery.sections.${s}`) }}
              </button>
            </div>
          </div>

          <!-- 补充说明 -->
          <div>
            <div class="text-[10px] uppercase tracking-wider text-ctp-overlay1 mb-1.5">
              {{ t('kbQuery.note') }}
            </div>
            <textarea
              v-model="note"
              rows="2"
              class="bg-ctp-crust/60 border border-ctp-surface0 rounded px-2 py-1.5 text-xs w-full outline-none focus:border-ctp-blue resize-none"
              :placeholder="t('kbQuery.notePlaceholder')"
            />
          </div>

          <button
            class="btn btn-primary w-full justify-center"
            :disabled="!selected.length || kb.loading"
            @click="run"
          >
            <SparklesIcon class="w-4 h-4" />
            {{ kb.loading ? t('kbQuery.running') : t('kbQuery.run') }}
          </button>

          <p
            v-if="!selected.length"
            class="text-[11px] text-ctp-overlay1"
          >
            {{ t('kbQuery.selectHint') }}
          </p>
        </div>
      </div>
    </div>

    <!-- 查询结果(右) -->
    <div class="xl:col-span-3 space-y-4">
      <div
        v-if="!displayResult"
        class="panel p-8 text-center"
      >
        <SparklesIcon class="w-8 h-8 text-ctp-overlay0 mx-auto mb-2" />
        <p class="text-xs text-ctp-overlay1">
          {{ t('kbQuery.empty') }}
        </p>
      </div>

      <template v-else>
        <div class="panel overflow-hidden">
          <div class="panel-header">
            <span class="flex items-center gap-2">
              <MagnifyingGlassIcon class="w-4 h-4 text-ctp-blue" />{{ t('kbQuery.summary') }}
              <span
                v-if="displayResult.cached"
                class="chip bg-ctp-green/15 text-ctp-green"
              >✓ {{ t('kbQuery.cached') }}</span>
            </span>
            <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono">{{ displayResult.baselineTag }}</span>
          </div>
          <div class="p-4 space-y-3">
            <p class="text-xs text-ctp-subtext1">
              {{ displayResult.summary }}
            </p>
            <div>
              <div class="text-[10px] uppercase tracking-wider text-ctp-overlay1 mb-1.5">
                {{ t('kbQuery.skills') }}
              </div>
              <div class="flex flex-wrap gap-1.5">
                <span
                  v-for="s in displayResult.skills"
                  :key="s.name"
                  class="chip bg-ctp-mauve/10 text-ctp-mauve font-mono"
                  :title="s.detail"
                >
                  {{ s.name }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div
          v-for="cr in displayResult.compResults"
          :key="cr.componentId"
          class="panel overflow-hidden"
        >
          <div
            class="panel-header cursor-pointer select-none"
            @click="toggleResult(cr.componentId)"
          >
            <span class="flex items-center gap-2">
              <CheckCircleIcon class="w-4 h-4 text-ctp-green" />
              <span class="text-sm font-medium text-ctp-text">{{ cr.name }}</span>
              <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ cr.kind }}</span>
            </span>
            <component
              :is="openResult[cr.componentId] ? ChevronUpIcon : ChevronDownIcon"
              class="w-3.5 h-3.5 text-ctp-overlay0"
            />
          </div>
          <div
            v-if="openResult[cr.componentId] !== false"
            class="p-4 space-y-3"
          >
            <MarkdownView :content="cr.relMd" />
            <MarkdownView
              v-if="cr.basicMd"
              :content="cr.basicMd"
            />
            <MarkdownView
              v-if="cr.structureMd"
              :content="cr.structureMd"
            />
            <MarkdownView
              v-if="cr.flowMd"
              :content="cr.flowMd"
            />
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
