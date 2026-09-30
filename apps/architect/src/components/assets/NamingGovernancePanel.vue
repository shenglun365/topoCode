<script setup lang="ts">
import { useAppDialog } from '@/composables/useAppDialog'
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  BookOpenIcon, PlusIcon, TrashIcon, CheckIcon, MagnifyingGlassIcon,
  SparklesIcon, DocumentArrowDownIcon, ArchiveBoxIcon,
} from '@heroicons/vue/24/outline'
import {
  namingService,
  type ConventionScenario, type ConventionStatus, type GlossaryTerm,
  type NamingConvention,
} from '@/services/naming-service'

const { t } = useI18n()
const dialog = useAppDialog()

const sub = ref<'conventions' | 'glossary'>('conventions')

// ── 命名规约 ──────────────────────────────────────────────────

const convStatus = ref<ConventionStatus | 'all'>('all')
const conventions = ref<NamingConvention[]>([])
const convLoading = ref(false)
const convBusy = ref('')

const SCENARIOS: ConventionScenario[] = ['extract', 'accept', 'naming', 'general']

const newConv = reactive({ ruleText: '', scenarios: [] as ConventionScenario[] })

function toggleScenario(s: ConventionScenario) {
  const i = newConv.scenarios.indexOf(s)
  if (i >= 0) newConv.scenarios.splice(i, 1)
  else newConv.scenarios.push(s)
}

async function loadConventions() {
  convLoading.value = true
  try {
    conventions.value = await namingService.conventions(convStatus.value)
  } catch {
    conventions.value = []
  } finally {
    convLoading.value = false
  }
}

async function addConvention() {
  if (!newConv.ruleText.trim() || !newConv.scenarios.length || convBusy.value) return
  convBusy.value = 'add'
  try {
    await namingService.createConvention({
      ruleText: newConv.ruleText.trim(),
      scenarios: [...newConv.scenarios],
    })
    newConv.ruleText = ''
    newConv.scenarios = []
    await loadConventions()
  } catch (err: any) {
    console.warn('[naming] 规约创建失败:', err?.message)
  } finally {
    convBusy.value = ''
  }
}

async function setConvStatus(c: NamingConvention, status: ConventionStatus) {
  if (convBusy.value) return
  convBusy.value = c.id
  try {
    await namingService.updateConvention(c.id, { status })
    await loadConventions()
  } catch (err: any) {
    console.warn('[naming] 规约状态更新失败:', err?.message)
  } finally {
    convBusy.value = ''
  }
}

async function removeConvention(c: NamingConvention) {
  if (convBusy.value) return
  convBusy.value = c.id
  try {
    await namingService.deleteConvention(c.id)
    await loadConventions()
  } catch (err: any) {
    console.warn('[naming] 规约删除失败:', err?.message)
  } finally {
    convBusy.value = ''
  }
}

function convStatusCls(s?: string): string {
  const map: Record<string, string> = {
    pending: 'bg-ctp-yellow/15 text-ctp-yellow',
    active: 'bg-ctp-green/15 text-ctp-green',
    pending_review: 'bg-ctp-peach/15 text-ctp-peach',
    disabled: 'bg-ctp-surface0 text-ctp-subtext1',
  }
  return map[s ?? 'active'] ?? map.active
}

// ── 术语表 ────────────────────────────────────────────────────

const glossaryQ = ref('')
const terms = ref<GlossaryTerm[]>([])
const glossaryLoading = ref(false)
const glossaryBusy = ref('')
const importPath = ref('')

const newTerm = reactive({ term: '', definition: '' })

async function loadTerms() {
  glossaryLoading.value = true
  try {
    terms.value = await namingService.glossary(glossaryQ.value.trim())
  } catch {
    terms.value = []
  } finally {
    glossaryLoading.value = false
  }
}

async function addTerm() {
  if (!newTerm.term.trim() || glossaryBusy.value) return
  glossaryBusy.value = 'add'
  try {
    await namingService.createTerm({ term: newTerm.term.trim(), definition: newTerm.definition.trim() })
    newTerm.term = ''
    newTerm.definition = ''
    await loadTerms()
  } catch (err: any) {
    console.warn('[naming] 术语添加失败:', err?.message)
  } finally {
    glossaryBusy.value = ''
  }
}

async function removeTerm(term: GlossaryTerm) {
  if (glossaryBusy.value) return
  glossaryBusy.value = term.id
  try {
    await namingService.deleteTerm(term.id)
    await loadTerms()
  } catch (err: any) {
    console.warn('[naming] 术语删除失败:', err?.message)
  } finally {
    glossaryBusy.value = ''
  }
}

async function doImport() {
  if (!importPath.value.trim() || glossaryBusy.value) return
  glossaryBusy.value = 'import'
  try {
    const res = await namingService.importTerms(importPath.value.trim())
    importPath.value = ''
    await dialog.alert(t('naming.imported', { n: res.imported, path: res.sourceRef }))
    await loadTerms()
  } catch (err: any) {
    await dialog.alert(err?.message || String(err))
  } finally {
    glossaryBusy.value = ''
  }
}

onMounted(() => {
  void loadConventions()
  void loadTerms()
})
</script>

<template>
  <div class="space-y-4">
    <!-- 子 Tab：命名规约 / 术语表 / 命名历史 -->
    <div class="flex items-center gap-1 bg-ctp-crust/60 rounded-lg p-1 w-fit">
      <button
        v-for="s in ([
          { key: 'conventions', label: t('naming.tabConventions'), icon: BookOpenIcon },
          { key: 'glossary', label: t('naming.tabGlossary'), icon: SparklesIcon },
        ] as const)"
        :key="s.key"
        class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors"
        :class="sub === s.key ? 'bg-ctp-surface1 text-ctp-text' : 'text-ctp-subtext0 hover:text-ctp-text'"
        @click="sub = s.key"
      >
        <component :is="s.icon" class="w-4 h-4" />{{ s.label }}
      </button>
    </div>

    <!-- 命名规约（场景标签；agent 按场景加载，禁全量 R7） -->
    <div
      v-if="sub === 'conventions'"
      class="panel overflow-hidden"
    >
      <div class="panel-header">
        <div class="flex items-center gap-2">
          <BookOpenIcon class="w-4 h-4 text-ctp-mauve" />{{ t('naming.conventionsTitle') }}
          <select
            v-model="convStatus"
            class="input !py-1 !px-2 !text-[11px] w-32"
            @change="loadConventions()"
          >
            <option value="all">{{ t('naming.statusAll') }}</option>
            <option value="active">{{ t('naming.status.active') }}</option>
            <option value="pending">{{ t('naming.status.pending') }}</option>
            <option value="pending_review">{{ t('naming.status.pending_review') }}</option>
            <option value="disabled">{{ t('naming.status.disabled') }}</option>
          </select>
          <span v-if="convLoading" class="text-[11px] text-ctp-overlay1">{{ t('common.loading') }}</span>
        </div>
      </div>
      <div class="p-3 space-y-2">
        <p class="text-[11px] text-ctp-overlay1">{{ t('naming.conventionsHint') }}</p>
        <!-- 新增规约 -->
        <div class="border border-ctp-surface0 rounded-md p-2.5 space-y-2">
          <input
            v-model="newConv.ruleText"
            class="input !py-1.5 text-xs"
            :placeholder="t('naming.rulePlaceholder')"
            @keyup.enter="addConvention"
          >
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="text-[10px] text-ctp-overlay0">{{ t('naming.scenarios') }}</span>
            <button
              v-for="s in SCENARIOS"
              :key="s"
              class="chip cursor-pointer"
              :class="newConv.scenarios.includes(s) ? 'bg-ctp-mauve/15 text-ctp-mauve' : 'bg-ctp-surface0 text-ctp-subtext0'"
              @click="toggleScenario(s)"
            >{{ t(`naming.scenario.${s}`) }}</button>
            <span class="flex-1" />
            <button
              class="btn btn-xs btn-green"
              :disabled="!newConv.ruleText.trim() || !newConv.scenarios.length || !!convBusy"
              @click="addConvention"
            >
              <PlusIcon class="w-3 h-3" />{{ t('naming.addRule') }}
            </button>
          </div>
        </div>
        <!-- 规约列表 -->
        <div class="space-y-1.5">
          <div
            v-for="c in conventions"
            :key="c.id"
            class="border rounded-md px-2.5 py-2"
            :class="c.status === 'pending' ? 'border-ctp-yellow/30 bg-ctp-yellow/5' : 'border-ctp-surface0'"
          >
            <div class="flex items-center gap-2">
              <span class="flex-1 text-xs text-ctp-text">{{ c.ruleText }}</span>
              <span class="chip !text-[9px] shrink-0" :class="convStatusCls(c.status)">
                {{ t(`naming.status.${c.status}`) }}
              </span>
              <span
                v-if="c.source === 'induced'"
                class="chip !text-[9px] bg-ctp-sky/15 text-ctp-sky shrink-0"
              >{{ t('naming.source.induced') }}</span>
            </div>
            <div class="mt-1 flex flex-wrap items-center gap-1.5">
              <span
                v-for="s in c.scenarios"
                :key="s"
                class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext1"
              >{{ t(`naming.scenario.${s}`) }}</span>
              <span v-if="(c.appliesKinds ?? []).length" class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay1">
                {{ (c.appliesKinds ?? []).join('/') }}
              </span>
              <span class="text-[9px] text-ctp-overlay0">{{ c.author }}</span>
              <span class="flex-1" />
              <button
                v-if="c.status === 'pending'"
                class="btn btn-xs btn-green"
                :disabled="!!convBusy"
                @click="setConvStatus(c, 'active')"
              >
                <CheckIcon class="w-3 h-3" />{{ t('naming.confirmRule') }}
              </button>
              <button
                v-else-if="c.status === 'active'"
                class="btn btn-xs btn-ghost"
                :disabled="!!convBusy"
                @click="setConvStatus(c, 'disabled')"
              >
                {{ t('naming.disableRule') }}
              </button>
              <button
                v-else-if="c.status === 'disabled'"
                class="btn btn-xs btn-ghost"
                :disabled="!!convBusy"
                @click="setConvStatus(c, 'active')"
              >
                {{ t('naming.enableRule') }}
              </button>
              <button
                class="btn btn-xs btn-ghost text-ctp-red"
                :disabled="!!convBusy"
                @click="removeConvention(c)"
              >
                <TrashIcon class="w-3 h-3" />
              </button>
            </div>
          </div>
          <p
            v-if="!conventions.length && !convLoading"
            class="text-[11px] text-ctp-overlay0 text-center py-4"
          >
            {{ t('naming.noConventions') }}
          </p>
        </div>
      </div>
    </div>

    <!-- 术语表（词典，纯参考非约束） -->
    <div
      v-else-if="sub === 'glossary'"
      class="panel overflow-hidden"
    >
      <div class="panel-header">
        <div class="flex items-center gap-2">
          <SparklesIcon class="w-4 h-4 text-ctp-teal" />{{ t('naming.glossaryTitle') }}
          <div class="relative">
            <MagnifyingGlassIcon class="w-3 h-3 absolute left-2 top-1/2 -translate-y-1/2 text-ctp-overlay0" />
            <input
              v-model="glossaryQ"
              class="input !py-1 !pl-7 !px-2 !text-[11px] w-44"
              :placeholder="t('naming.searchTerm')"
              @keyup.enter="loadTerms()"
            >
          </div>
          <span v-if="glossaryLoading" class="text-[11px] text-ctp-overlay1">{{ t('common.loading') }}</span>
        </div>
      </div>
      <div class="p-3 space-y-2">
        <p class="text-[11px] text-ctp-overlay1">{{ t('naming.glossaryHint') }}</p>
        <!-- 新增术语 + 导入 -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-2">
          <div class="border border-ctp-surface0 rounded-md p-2.5 space-y-2">
            <input
              v-model="newTerm.term"
              class="input !py-1.5 text-xs"
              :placeholder="t('naming.termPlaceholder')"
            >
            <input
              v-model="newTerm.definition"
              class="input !py-1.5 text-xs"
              :placeholder="t('naming.definitionPlaceholder')"
              @keyup.enter="addTerm"
            >
            <div class="flex justify-end">
              <button
                class="btn btn-xs btn-green"
                :disabled="!newTerm.term.trim() || !!glossaryBusy"
                @click="addTerm"
              >
                <PlusIcon class="w-3 h-3" />{{ t('naming.addTerm') }}
              </button>
            </div>
          </div>
          <div class="border border-ctp-surface0 rounded-md p-2.5 space-y-2">
            <input
              v-model="importPath"
              class="input !py-1.5 text-xs font-mono"
              :placeholder="t('naming.importPlaceholder')"
            >
            <div class="flex items-center justify-between">
              <span class="text-[10px] text-ctp-overlay0">{{ t('naming.importHint') }}</span>
              <button
                class="btn btn-xs btn-blue"
                :disabled="!importPath.trim() || !!glossaryBusy"
                @click="doImport"
              >
                <DocumentArrowDownIcon class="w-3 h-3" />
                {{ glossaryBusy === 'import' ? t('naming.importing') : t('naming.import') }}
              </button>
            </div>
          </div>
        </div>
        <!-- 术语列表 -->
        <div class="space-y-1">
          <div
            v-for="term in terms"
            :key="term.id"
            class="flex items-center gap-2 border-b border-ctp-surface0 last:border-0 py-1.5"
          >
            <span class="text-xs font-medium text-ctp-text w-32 truncate">{{ term.term }}</span>
            <span
              v-if="(term.alias ?? []).length"
              class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext1 shrink-0"
            >{{ term.alias?.join(' / ') }}</span>
            <span class="flex-1 text-[11px] text-ctp-subtext0 truncate">{{ term.definition }}</span>
            <span
              v-if="term.sourceRef"
              class="chip !text-[9px] bg-ctp-sky/15 text-ctp-sky shrink-0 font-mono"
            >{{ term.sourceRef }}</span>
            <button
              class="text-ctp-overlay0 hover:text-ctp-red transition-colors p-0.5"
              :disabled="!!glossaryBusy"
              @click="removeTerm(term)"
            >
              <TrashIcon class="w-3 h-3" />
            </button>
          </div>
          <p
            v-if="!terms.length && !glossaryLoading"
            class="text-[11px] text-ctp-overlay0 text-center py-4"
          >
            {{ t('naming.noTerms') }}
          </p>
        </div>
      </div>
    </div>

  </div>
</template>
