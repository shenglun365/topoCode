<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  BoltIcon, AdjustmentsHorizontalIcon, CubeTransparentIcon, ChevronDownIcon, ChevronRightIcon,
  ArrowPathIcon, ClipboardDocumentIcon, ClipboardDocumentCheckIcon, SparklesIcon,
} from '@heroicons/vue/24/outline'
import type { SemanticAsset, SemanticAssetKind, SemanticAssetLevel } from '@/types'
import { semanticAssetService } from '@/services/semantic-asset-service'

const { t } = useI18n()

const kind = ref<SemanticAssetKind | ''>('')
const level = ref<SemanticAssetLevel | ''>('')
const q = ref('')
const items = ref<SemanticAsset[]>([])
const loading = ref(false)
const extracting = ref(false)
const reconciling = ref(false)
const statusCounts = ref<Record<string, number>>({})
const expanded = reactive<Record<string, boolean>>({})

const kinds: { value: SemanticAssetKind; label: string }[] = [
  { value: 'structure', label: t('semanticAssets.kind.structure') },
  { value: 'behavior', label: t('semanticAssets.kind.behavior') },
  { value: 'rule', label: t('semanticAssets.kind.rule') },
  { value: 'contract', label: t('semanticAssets.kind.contract') },
]

const levels: { value: SemanticAssetLevel; label: string }[] = [
  { value: 'high', label: t('semanticAssets.level.high') },
  { value: 'medium', label: t('semanticAssets.level.medium') },
  { value: 'low', label: t('semanticAssets.level.low') },
]

async function load() {
  loading.value = true
  try {
    items.value = await semanticAssetService.search(q.value, kind.value || undefined, undefined, level.value || undefined)
  } finally {
    loading.value = false
  }
}

async function extract() {
  extracting.value = true
  try {
    const res = await semanticAssetService.extractAll(kinds.map((k) => k.value))
    if (res.error) console.warn('[semantic] extract:', res.error)
    await load()
  } finally {
    extracting.value = false
  }
}

function toggle(id: string) {
  expanded[id] = !expanded[id]
}

async function reconcile() {
  reconciling.value = true
  try {
    await semanticAssetService.reconcile(true)
    await load()
  } finally {
    reconciling.value = false
  }
}

async function refreshOne(a: SemanticAsset) {
  try {
    const res = await semanticAssetService.refreshAsset(a.id)
    if (res.asset) {
      const i = items.value.findIndex((x) => x.id === a.id)
      if (i >= 0) items.value[i] = { ...items.value[i], ...res.asset }
    } else if (res.status === 'deleted') {
      const i = items.value.findIndex((x) => x.id === a.id)
      if (i >= 0) items.value[i] = { ...items.value[i], status: 'deleted', needsUpdate: 1 }
    }
  } catch (err: any) {
    console.warn('[semantic] refresh failed:', err)
  }
}

function usable(a: SemanticAsset): boolean {
  return a.status !== 'stale' && a.status !== 'deleted' && !a.needsUpdate
}

onMounted(async () => {
  await load()
  semanticAssetService.status().then((s) => { statusCounts.value = s.counts }).catch(() => {})
})

function kindIcon(k: SemanticAsset['kind']) {
  if (k === 'behavior') return BoltIcon
  if (k === 'rule') return AdjustmentsHorizontalIcon
  if (k === 'contract') return ArrowPathIcon
  return CubeTransparentIcon
}

async function copyAsset(a: SemanticAsset) {
  const lines = [`${a.name} (${kinds.find((x) => x.value === a.kind)?.label ?? a.kind})`, `ID: ${a.id}`, a.desc]
  if (a.astRefs?.length) {
    lines.push('')
    lines.push(...a.astRefs.slice(0, 10).map((r) => `${r.file}:L${r.startLine}-L${r.endLine} ${r.symbol}`))
  }
  const text = lines.join('\n')
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return
    }
  } catch {
    // fallthrough
  }
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  try {
    document.execCommand('copy')
  } catch {
    /* ignore */
  }
  document.body.removeChild(ta)
}
</script>

<template>
  <div class="space-y-3">
    <div class="flex items-center gap-2 flex-wrap">
      <input
        v-model="q"
        class="input !py-1.5 !text-xs w-64"
        :placeholder="t('semanticAssets.searchPlaceholder')"
        @keydown.enter="load"
      >
      <select
        v-model="kind"
        class="input !py-1.5 !text-xs w-auto"
        @change="load"
      >
        <option value="">{{ t('semanticAssets.allKinds') }}</option>
        <option
          v-for="k in kinds"
          :key="k.value"
          :value="k.value"
        >{{ k.label }}</option>
      </select>
      <select
        v-model="level"
        class="input !py-1.5 !text-xs w-auto"
        @change="load"
      >
        <option value="">{{ t('semanticAssets.allLevels') }}</option>
        <option
          v-for="l in levels"
          :key="l.value"
          :value="l.value"
        >{{ l.label }}</option>
      </select>
      <button
        class="btn btn-ghost !py-1.5"
        :disabled="loading"
        @click="load"
      >
        <ArrowPathIcon class="w-3.5 h-3.5" />{{ t('semanticAssets.search') }}
      </button>
      <span
        v-if="statusCounts.stale || statusCounts.needsUpdate"
        class="chip bg-ctp-yellow/15 text-ctp-yellow"
      >{{ t('semanticAssets.needsUpdate') }}: {{ statusCounts.needsUpdate ?? 0 }}</span>
      <span
        v-if="statusCounts.deleted"
        class="chip bg-ctp-red/15 text-ctp-red"
      >{{ t('semanticAssets.deleted') }}: {{ statusCounts.deleted }}</span>
      <span class="flex-1" />
      <button
        class="btn btn-ghost !py-1.5"
        :disabled="reconciling"
        @click="reconcile"
      >
        <ArrowPathIcon
          v-if="!reconciling"
          class="w-3.5 h-3.5"
        />
        <ArrowPathIcon
          v-else
          class="w-3.5 h-3.5 animate-spin"
        />{{ reconciling ? t('semanticAssets.reconciling') : t('semanticAssets.reconcile') }}
      </button>
      <button
        class="btn btn-primary !py-1.5"
        :disabled="extracting"
        @click="extract"
      >
        <SparklesIcon
          v-if="!extracting"
          class="w-3.5 h-3.5"
        />
        <ArrowPathIcon
          v-else
          class="w-3.5 h-3.5 animate-spin"
        />{{ extracting ? t('semanticAssets.extracting') : t('semanticAssets.extractAll') }}
      </button>
    </div>

    <div
      v-if="items.length"
      class="space-y-1.5"
    >
      <div
        v-for="a in items"
        :key="a.id"
        class="panel overflow-hidden"
      >
        <div class="flex items-center gap-1.5 px-2.5 py-2">
          <component
            :is="kindIcon(a.kind)"
            class="w-4 h-4 text-ctp-mauve shrink-0"
          />
          <span class="chip !text-[9px] bg-ctp-mauve/15 text-ctp-mauve shrink-0">
            {{ t(`semanticAssets.kind.${a.kind}`) }}
          </span>
          <span
            v-if="a.level && a.level !== 'medium'"
            class="chip !text-[9px] shrink-0"
            :class="a.level === 'high' ? 'bg-ctp-peach/15 text-ctp-peach' : 'bg-ctp-sky/15 text-ctp-sky'"
          >{{ t(`semanticAssets.level.${a.level}`) }}</span>
          <span class="text-xs font-medium text-ctp-text truncate">{{ a.name }}</span>
          <span class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext0">
            {{ a.source ?? 'live' }}
          </span>
          <span
            v-if="a.needsUpdate || a.status === 'stale'"
            class="chip !text-[9px] bg-ctp-yellow/15 text-ctp-yellow"
          >{{ t('semanticAssets.needsUpdate') }}</span>
          <span
            v-else-if="a.status === 'deleted'"
            class="chip !text-[9px] bg-ctp-red/15 text-ctp-red"
          >{{ t('semanticAssets.deleted') }}</span>
          <span
            v-else-if="a.change === 'added'"
            class="chip !text-[9px] bg-ctp-green/15 text-ctp-green"
          >{{ t('semanticAssets.added') }}</span>
          <span
            v-else-if="a.change === 'modified'"
            class="chip !text-[9px] bg-ctp-yellow/15 text-ctp-yellow"
          >{{ t('semanticAssets.modified') }}</span>
          <span class="flex-1" />
          <span class="text-[10px] text-ctp-overlay0 whitespace-nowrap">
            {{ a.astRefs?.length ?? 0 }} AST
          </span>
          <button
            v-if="!usable(a)"
            class="text-ctp-yellow hover:text-ctp-peach p-0.5"
            :title="t('semanticAssets.refresh')"
            @click="refreshOne(a)"
          >
            <ArrowPathIcon class="w-3.5 h-3.5" />
          </button>
          <button
            class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
            :title="t('semanticAssets.copy')"
            @click="copyAsset(a)"
          >
            <ClipboardDocumentIcon class="w-3.5 h-3.5" />
          </button>
          <button
            class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
            :title="t('semanticAssets.expand')"
            @click="toggle(a.id)"
          >
            <ChevronDownIcon
              v-if="expanded[a.id]"
              class="w-3.5 h-3.5"
            />
            <ChevronRightIcon
              v-else
              class="w-3.5 h-3.5"
            />
          </button>
        </div>
        <p class="px-2.5 pb-2 text-[11px] text-ctp-subtext0 whitespace-pre-wrap">
          {{ a.desc }}
        </p>
        <div
          v-if="expanded[a.id]"
          class="border-t border-ctp-surface0 px-2.5 py-2 space-y-2 text-[11px]"
        >
          <div v-if="a.detail?.fields?.length">
            <div class="flex items-center gap-1 font-medium text-ctp-mauve mb-1">
              <ClipboardDocumentCheckIcon class="w-3 h-3" />{{ t('semanticAssets.fields') }}
            </div>
            <table class="w-full text-[11px]">
              <tbody>
                <tr
                  v-for="f in a.detail.fields"
                  :key="f.name"
                  class="border-b border-ctp-surface0/50 last:border-0"
                >
                  <td class="py-0.5 pr-3 font-mono text-ctp-text">{{ f.name }}</td>
                  <td class="py-0.5 pr-3 text-ctp-overlay0">{{ f.type ?? '—' }}</td>
                  <td class="py-0.5 text-ctp-subtext0">{{ f.semantic }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-if="a.detail?.steps?.length">
            <div class="font-medium text-ctp-mauve mb-1">{{ t('semanticAssets.steps') }}</div>
            <div
              v-for="(s, si) in a.detail.steps"
              :key="si"
              class="flex items-center gap-2 py-0.5"
            >
              <span class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay1 shrink-0">{{ s.order ?? si + 1 }}</span>
              <span class="text-ctp-subtext0">{{ s.semantic }}</span>
              <span
                v-if="s.astRefs?.length"
                class="text-[10px] text-ctp-overlay0 font-mono"
              >@{{ s.astRefs[0].file }}:L{{ s.astRefs[0].startLine }}</span>
            </div>
          </div>
          <div v-if="a.detail?.branches?.length">
            <div class="font-medium text-ctp-mauve mb-1">{{ t('semanticAssets.branches') }}</div>
            <div
              v-for="(b, bi) in a.detail.branches"
              :key="bi"
              class="py-0.5"
            >
              <span class="font-mono text-ctp-text">if {{ b.condition ?? '?' }}</span>
              <span class="text-ctp-subtext0"> → {{ b.then ?? '—' }}</span>
              <span
                v-if="b.else"
                class="text-ctp-subtext0"
              > / else {{ b.else }}</span>
            </div>
          </div>
          <div v-if="a.detail?.invariants?.length">
            <div class="font-medium text-ctp-mauve mb-1">{{ t('semanticAssets.invariants') }}</div>
            <div
              v-for="(iv, ii) in a.detail.invariants"
              :key="ii"
              class="py-0.5 text-ctp-subtext0"
            >• {{ iv }}</div>
          </div>
          <div v-if="a.astRefs?.length">
            <div class="font-medium text-ctp-mauve mb-1">AST 锚点</div>
            <div
              v-for="(r, ri) in a.astRefs"
              :key="ri"
              class="py-0.5 font-mono text-[10px] text-ctp-overlay0"
            >{{ r.file }}:L{{ r.startLine }}-L{{ r.endLine }} <span class="text-ctp-subtext0">{{ r.symbol }}</span></div>
          </div>
        </div>
      </div>
    </div>

    <div
      v-else-if="!loading"
      class="panel flex items-center justify-center gap-2 py-8 text-xs text-ctp-overlay1"
    >
      <CubeTransparentIcon class="w-5 h-5 text-ctp-overlay1/60" />{{ t('semanticAssets.empty') }}
    </div>
  </div>
</template>
