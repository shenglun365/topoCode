<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  BoltIcon, AdjustmentsHorizontalIcon, CubeTransparentIcon, ChevronDownIcon, ChevronRightIcon,
  ArrowPathIcon, ClipboardDocumentIcon, ClipboardDocumentCheckIcon,
  PencilIcon, CheckIcon, XMarkIcon, ScissorsIcon, ArrowsRightLeftIcon, PlusIcon, TrashIcon,
} from '@heroicons/vue/24/outline'
import type { SemanticAsset, SemanticAssetKind, SemanticAssetLevel } from '@/types'
import { semanticAssetService } from '@/services/semantic-asset-service'

const { t } = useI18n()

const kind = ref<SemanticAssetKind | ''>('')
/** 默认仅展示实现层(业务层+逻辑层暂停再生，仅保留展示)。 */
const level = ref<SemanticAssetLevel | ''>('implementation')
const q = ref('')
const items = ref<SemanticAsset[]>([])
const loading = ref(false)
const reconciling = ref(false)
const statusCounts = ref<Record<string, number>>({})
const expanded = reactive<Record<string, boolean>>({})

const kinds: { value: SemanticAssetKind; label: string }[] = [
  { value: 'entity', label: t('semanticAssets.kind.entity') },
  { value: 'contract', label: t('semanticAssets.kind.contract') },
  { value: 'state', label: t('semanticAssets.kind.state') },
  { value: 'rule', label: t('semanticAssets.kind.rule') },
  { value: 'process', label: t('semanticAssets.kind.process') },
  { value: 'decision', label: t('semanticAssets.kind.decision') },
]

const levels: { value: SemanticAssetLevel; label: string }[] = [
  { value: 'business', label: t('semanticAssets.level.business') },
  { value: 'logic', label: t('semanticAssets.level.logic') },
  { value: 'implementation', label: t('semanticAssets.level.implementation') },
]

async function load() {
  loading.value = true
  try {
    items.value = await semanticAssetService.search(q.value, kind.value || undefined, undefined, level.value || undefined)
  } finally {
    loading.value = false
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

// ── 就地改名（认知层编辑；main-KB 关联项目后端 409 拒绝） ──

const renamingId = ref('')
const renameValue = ref('')
const renameBusy = ref(false)

function startRename(a: SemanticAsset) {
  renamingId.value = a.id
  renameValue.value = a.name
}

function cancelRename() {
  renamingId.value = ''
  renameValue.value = ''
}

async function submitRename(a: SemanticAsset) {
  const name = renameValue.value.trim()
  if (!name || name === a.name || renameBusy.value) return
  renameBusy.value = true
  try {
    const res = await semanticAssetService.renameAsset(a.id, name)
    const i = items.value.findIndex((x) => x.id === a.id)
    if (i >= 0) items.value[i] = { ...items.value[i], ...res.asset }
    cancelRename()
  } catch (err: any) {
    alert(err?.message || String(err))
  } finally {
    renameBusy.value = false
  }
}

// ── 拆分（按锚点组拆出新资产；原行留痕 splitInto） ──

const splittingId = ref('')
const splitParts = ref<{ name: string; anchorKeys: string }[]>([])
const splitBusy = ref(false)

function startSplit(a: SemanticAsset) {
  splittingId.value = a.id
  const refs = a.astRefs?.length ? a.astRefs : []
  splitParts.value = refs.length
    ? refs.map((r, i) => ({ name: `${a.name} ${i + 1}`, anchorKeys: `${r.file}:${r.symbol}` }))
    : [{ name: '', anchorKeys: '' }]
  if (!expanded[a.id]) expanded[a.id] = true
}

function cancelSplit() {
  splittingId.value = ''
  splitParts.value = []
}

function addSplitPart() {
  splitParts.value.push({ name: '', anchorKeys: '' })
}

function removeSplitPart(idx: number) {
  splitParts.value.splice(idx, 1)
}

function anchorKeysOf(a: SemanticAsset): string[] {
  return (a.astRefs ?? []).map((r) => `${r.file}:${r.symbol}`).filter(Boolean)
}

async function submitSplit(a: SemanticAsset) {
  if (splitBusy.value) return
  const parts = splitParts.value
    .map((p) => ({
      name: p.name.trim(),
      anchorKeys: p.anchorKeys.split(',').map((s) => s.trim()).filter(Boolean),
    }))
    .filter((p) => p.name)
  if (parts.length < 1) { alert(t('semanticAssets.splitHint')); return }
  const all = new Set(anchorKeysOf(a))
  for (const p of parts) {
    if (!p.anchorKeys.length) { alert(`${p.name}: ${t('semanticAssets.partAnchors')}`); return }
    if (!p.anchorKeys.every((k) => all.has(k))) {
      alert(`${p.name}: ${t('semanticAssets.partAnchors')}`); return
    }
  }
  splitBusy.value = true
  try {
    await semanticAssetService.splitAsset(a.id, parts)
    cancelSplit()
    await load()
  } catch (err: any) {
    alert(err?.message || String(err))
  } finally {
    splitBusy.value = false
  }
}

// ── 合并（多选 → 锚点并入保留项；其余留痕删除 mergedInto） ──

const selectedIds = ref<string[]>([])
const mergeInto = ref('')
const mergeName = ref('')
const mergeBusy = ref(false)

function toggleSelect(id: string) {
  const i = selectedIds.value.indexOf(id)
  if (i >= 0) selectedIds.value.splice(i, 1)
  else selectedIds.value.push(id)
  if (mergeInto.value && !selectedIds.value.includes(mergeInto.value)) mergeInto.value = ''
}

const selectedAssets = computed(() =>
  selectedIds.value.map((id) => items.value.find((x) => x.id === id)).filter(Boolean) as SemanticAsset[])

function submitMerge() {
  if (mergeBusy.value || selectedIds.value.length < 2) return
  const into = mergeInto.value || selectedIds.value[0]
  mergeBusy.value = true
  semanticAssetService.mergeAssets(into, selectedIds.value, mergeName.value.trim())
    .then(async () => {
      selectedIds.value = []
      mergeInto.value = ''
      mergeName.value = ''
      await load()
    })
    .catch((err: any) => alert(err?.message || String(err)))
    .finally(() => { mergeBusy.value = false })
}

onMounted(async () => {
  await load()
  semanticAssetService.status().then((s) => { statusCounts.value = s.counts }).catch(() => {})
})

function kindIcon(k: SemanticAsset['kind']) {
  if (k === 'process') return BoltIcon
  if (k === 'decision') return AdjustmentsHorizontalIcon
  if (k === 'contract') return ArrowPathIcon
  if (k === 'state') return AdjustmentsHorizontalIcon
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
    </div>

    <!-- A3 合并操作条：勾选 ≥2 个资产后出现 -->
    <div
      v-if="selectedIds.length >= 2"
      class="panel border-ctp-sapphire/30 flex flex-wrap items-center gap-2 px-2.5 py-2"
    >
      <ArrowsRightLeftIcon class="w-4 h-4 text-ctp-sapphire shrink-0" />
      <span class="text-xs font-medium text-ctp-text">
        {{ t('semanticAssets.merge') }} · {{ selectedIds.length }} {{ t('semanticAssets.selected') }}
      </span>
      <label class="text-[11px] text-ctp-subtext0 ml-2">{{ t('semanticAssets.mergeTarget') }}</label>
      <select
        v-model="mergeInto"
        class="input !py-1 !text-xs w-52"
      >
        <option
          v-for="sa in selectedAssets"
          :key="sa.id"
          :value="sa.id"
        >{{ sa.name }}</option>
      </select>
      <input
        v-model="mergeName"
        class="input !py-1 !text-xs w-48"
        :placeholder="t('semanticAssets.mergeName')"
      >
      <button
        class="btn btn-sm btn-blue"
        :disabled="mergeBusy"
        @click="submitMerge"
      >
        {{ mergeBusy ? t('common.loading') : t('semanticAssets.merge') }}
      </button>
      <button class="btn btn-sm btn-ghost" @click="selectedIds = []; mergeInto = ''; mergeName = ''">
        <XMarkIcon class="w-3.5 h-3.5" />
      </button>
      <span class="text-[10px] text-ctp-overlay0 basis-full">{{ t('semanticAssets.mergeHint') }}</span>
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
          <input
            v-if="usable(a)"
            type="checkbox"
            class="accent-ctp-sapphire shrink-0"
            :checked="selectedIds.includes(a.id)"
            :title="t('semanticAssets.merge')"
            @change="toggleSelect(a.id)"
          >
          <component
            :is="kindIcon(a.kind)"
            class="w-4 h-4 text-ctp-mauve shrink-0"
          />
          <span class="chip !text-[9px] bg-ctp-mauve/15 text-ctp-mauve shrink-0">
            {{ t(`semanticAssets.kind.${a.kind}`) }}
          </span>
          <span
            v-if="a.level"
            class="chip !text-[9px] shrink-0"
            :class="a.level === 'business' ? 'bg-ctp-peach/15 text-ctp-peach' : a.level === 'implementation' ? 'bg-ctp-sky/15 text-ctp-sky' : 'bg-ctp-surface0 text-ctp-subtext0'"
          >{{ t(`semanticAssets.level.${a.level}`) }}</span>
          <template v-if="renamingId === a.id">
            <input
              v-model="renameValue"
              class="input !py-0.5 !text-xs w-44"
              @keydown.enter="submitRename(a)"
              @keydown.esc="cancelRename"
            >
            <button
              class="text-ctp-green hover:opacity-70 p-0.5"
              :disabled="renameBusy"
              @click="submitRename(a)"
            >
              <CheckIcon class="w-3.5 h-3.5" />
            </button>
            <button
              class="text-ctp-overlay0 hover:text-ctp-text p-0.5"
              :disabled="renameBusy"
              @click="cancelRename"
            >
              <XMarkIcon class="w-3.5 h-3.5" />
            </button>
          </template>
          <span v-else class="text-xs font-medium text-ctp-text truncate">{{ a.name }}</span>
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
            v-if="usable(a)"
            class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
            :title="t('semanticAssets.rename')"
            @click="startRename(a)"
          >
            <PencilIcon class="w-3.5 h-3.5" />
          </button>
          <button
            v-if="usable(a)"
            class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
            :title="t('semanticAssets.split')"
            @click="splittingId === a.id ? cancelSplit() : startSplit(a)"
          >
            <ScissorsIcon class="w-3.5 h-3.5" />
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
          <!-- A3 拆分编辑器 -->
          <div
            v-if="splittingId === a.id"
            class="border border-ctp-sapphire/25 bg-ctp-sapphire/5 rounded-lg p-2 space-y-2"
          >
            <div class="flex items-center gap-1.5">
              <ScissorsIcon class="w-3.5 h-3.5 text-ctp-sapphire" />
              <span class="font-medium text-ctp-text">{{ t('semanticAssets.split') }}</span>
            </div>
            <p class="text-[10px] text-ctp-overlay0">{{ t('semanticAssets.splitHint') }}</p>
            <div
              v-for="(p, pi) in splitParts"
              :key="pi"
              class="flex items-center gap-1.5"
            >
              <span class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay1 shrink-0">{{ pi + 1 }}</span>
              <input
                v-model="p.name"
                class="input !py-0.5 !text-xs w-40"
                :placeholder="t('semanticAssets.partName')"
              >
              <input
                v-model="p.anchorKeys"
                class="input !py-0.5 !text-xs flex-1 font-mono"
                :placeholder="t('semanticAssets.partAnchors')"
              >
              <button
                class="text-ctp-overlay0 hover:text-ctp-red p-0.5"
                :disabled="splitParts.length <= 1"
                @click="removeSplitPart(pi)"
              >
                <TrashIcon class="w-3.5 h-3.5" />
              </button>
            </div>
            <div class="flex items-center gap-1.5">
              <button class="btn btn-xs btn-ghost" @click="addSplitPart">
                <PlusIcon class="w-3 h-3" />{{ t('semanticAssets.addPart') }}
              </button>
              <span class="flex-1" />
              <button class="btn btn-xs btn-ghost" :disabled="splitBusy" @click="cancelSplit">
                {{ t('common.cancel') }}
              </button>
              <button class="btn btn-xs btn-blue" :disabled="splitBusy" @click="submitSplit(a)">
                {{ splitBusy ? t('common.loading') : t('semanticAssets.split') }}
              </button>
            </div>
          </div>
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
          <div v-if="a.detail?.states?.length">
            <div class="font-medium text-ctp-mauve mb-1">{{ t('semanticAssets.states') }}</div>
            <div class="flex flex-wrap gap-1">
              <span
                v-for="(st, si) in a.detail.states"
                :key="si"
                class="chip !text-[10px] bg-ctp-surface0 text-ctp-subtext0"
              >{{ st.name }}<template v-if="st.initial"> · <span class="text-ctp-green">{{ t('semanticAssets.stateInitial') }}</span></template><template v-if="st.final"> · <span class="text-ctp-red">{{ t('semanticAssets.stateFinal') }}</span></template></span>
            </div>
          </div>
          <div v-if="a.detail?.transitions?.length">
            <div class="font-medium text-ctp-mauve mb-1">{{ t('semanticAssets.transitions') }}</div>
            <div
              v-for="(tr, ti) in a.detail.transitions"
              :key="ti"
              class="py-0.5 font-mono text-[10px] text-ctp-overlay0"
            >{{ tr.from ?? '?' }} → {{ tr.to ?? '?' }}<template v-if="tr.event"> on {{ tr.event }}</template><template v-if="tr.condition"> [{{ tr.condition }}]</template></div>
          </div>
          <div v-if="a.tags?.length || a.detail?.tags?.length">
            <div class="font-medium text-ctp-mauve mb-1">{{ t('semanticAssets.tags') }}</div>
            <div class="flex flex-wrap gap-1">
              <span
                v-for="(tg, tgi) in (a.tags ?? a.detail!.tags ?? [])"
                :key="tgi"
                class="chip !text-[9px] bg-ctp-blue/15 text-ctp-blue"
              >{{ tg }}</span>
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
            <div class="font-medium text-ctp-mauve mb-1">{{ t('semanticAssets.astAnchor') }}</div>
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
