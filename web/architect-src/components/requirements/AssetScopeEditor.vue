<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowPathIcon, CheckIcon, CubeIcon, PlusIcon, Squares2X2Icon, XMarkIcon,
} from '@heroicons/vue/24/outline'
import type { AssetScopeItem, AssetType, FormDraft } from '@/types'
import { ownerOf, resolveAsset } from '@/services/asset-validator'

const { t } = useI18n()
const form = inject<FormDraft>('requirement-form')!

const emit = defineEmits<{ 'open-detail': [assetId: string]; 'open-picker': [] }>()

const coreCount = computed(() => form.assetScope.filter((a) => a.role === 'core').length)

// ---- 数据资产 JSON 数组编辑器(默认收起) ----
const editorOpen = ref(false)
const assetJson = ref('')
const assetJsonError = ref('')
let syncing = false

function serialize(items: AssetScopeItem[]): string {
  return JSON.stringify(
    items.map(({ assetId, assetType, role, file }) => ({ assetId, assetType, role, ...(file ? { file } : {}) })),
    null,
    2,
  )
}

function syncJsonFromForm() {
  assetJson.value = serialize(form.assetScope)
}

onMounted(syncJsonFromForm)
watch(
  () => form.assetScope,
  () => {
    if (!syncing) syncJsonFromForm()
  },
  { deep: true },
)

/** 解析 JSON 文本 → 结构化 assetScope(命中知识库自动补全 type/file)。 */
function applyAssetJson() {
  assetJsonError.value = ''
  let raw: unknown
  try {
    raw = JSON.parse(assetJson.value)
  } catch {
    assetJsonError.value = t('requirement.form.assetJsonError')
    return
  }
  if (!Array.isArray(raw)) {
    assetJsonError.value = t('requirement.form.assetJsonError')
    return
  }
  const items: AssetScopeItem[] = []
  for (const e of raw) {
    const str = typeof e === 'string' ? e : (e as { assetId?: unknown; role?: unknown; assetType?: unknown }).assetId
    if (typeof str !== 'string' || !str.trim()) {
      assetJsonError.value = t('requirement.form.assetJsonError')
      return
    }
    const related = typeof e === 'string' ? str.trim().startsWith('~') : (e as { role?: unknown }).role === 'related'
    const assetId = related ? str.trim().slice(1) : str.trim()
    const hit = resolveAsset(assetId)
    items.push({
      assetId,
      assetType: (hit?.type ?? (e as { assetType?: AssetType }).assetType ?? 'component') as AssetType,
      role: related ? 'related' : 'core',
      source: 'manual',
      file: hit?.file ?? (e as { file?: string }).file,
    })
  }
  const seen = new Set<string>()
  const unique = items.filter((it) => (seen.has(it.assetId) ? false : (seen.add(it.assetId), true)))
  syncing = true
  form.assetScope.splice(0, form.assetScope.length, ...unique)
  syncing = false
  syncJsonFromForm()
}

function onAssetJsonInput() {
  assetJsonError.value = ''
  try {
    const raw = JSON.parse(assetJson.value)
    if (!Array.isArray(raw)) throw new Error('not-array')
  } catch {
    assetJsonError.value = t('requirement.form.assetJsonError')
  }
}

function formatAssetJson() {
  assetJsonError.value = ''
  syncJsonFromForm()
}

const SAMPLE_ASSET_JSON = [
  { assetId: 'c-order', role: 'core' },
  { assetId: 'entity-order', role: 'core' },
  { assetId: 'c-payment', role: 'related' },
  'c-discount',
]
const sampleAssetJsonText = JSON.stringify(SAMPLE_ASSET_JSON, null, 2)

// ---- 数据资产标签化分组显示(组件优先) ----
interface TagItem { assetId: string; name: string; role: 'core' | 'related' }
interface AssetTreeComp { item: TagItem; children: TagItem[] }
const nameOf = (id: string) => resolveAsset(id)?.name ?? id

const assetTree = computed<{ groups: AssetTreeComp[]; orphans: TagItem[] }>(() => {
  const comps = form.assetScope.filter((a) => a.assetType === 'component')
  const children = form.assetScope.filter((a) => a.assetType !== 'component')
  const byOwner = new Map<string, TagItem[]>()
  const orphans: TagItem[] = []
  for (const a of children) {
    const tag: TagItem = { assetId: a.assetId, name: nameOf(a.assetId), role: a.role }
    const o = ownerOf(a.assetId)
    if (o) {
      if (!byOwner.has(o)) byOwner.set(o, [])
      byOwner.get(o)!.push(tag)
    } else {
      orphans.push(tag)
    }
  }
  return {
    groups: comps.map((c) => ({
      item: { assetId: c.assetId, name: nameOf(c.assetId), role: c.role },
      children: byOwner.get(c.assetId) ?? [],
    })),
    orphans,
  }
})

function removeComponent(compId: string) {
  form.assetScope = form.assetScope.filter((a) => a.assetId !== compId && ownerOf(a.assetId) !== compId)
}

function removeAsset(assetId: string) {
  form.assetScope = form.assetScope.filter((a) => a.assetId !== assetId)
}

// ---- 子资产(数据结构/逻辑处理)手动选择预留弹窗 ----
const childPendingOpen = ref(false)
</script>

<template>
  <div class="panel overflow-hidden">
    <div class="panel-header">
      <span class="flex items-center gap-2">
        <Squares2X2Icon class="w-4 h-4 text-ctp-blue" />{{ t('requirement.form.resourceLogicTitle') }}
      </span>
    </div>
    <div class="p-3 space-y-3">
      <div class="space-y-2">
        <div class="flex items-center justify-between">
          <label class="text-[11px] text-ctp-overlay1">{{ t('requirement.assetScope') }}</label>
          <span class="text-[10px] text-ctp-overlay1">{{ form.assetScope.length }} · {{ coreCount }} {{ t('requirement.assetRole.core') }}</span>
        </div>
        <p class="text-[10px] text-ctp-subtext0">
          {{ t('requirement.form.assetScopeTagHint') }}
        </p>

        <!-- 组件层级(组件优先，子资产从属) -->
        <div class="space-y-2">
          <div
            v-for="g in assetTree.groups"
            :key="g.item.assetId"
            class="space-y-1.5"
          >
            <div class="flex items-center gap-1.5">
              <button
                class="chip cursor-pointer transition-colors"
                :class="g.item.role === 'core' ? 'bg-ctp-blue/15 text-ctp-blue border border-ctp-blue/30' : 'bg-ctp-surface0 text-ctp-subtext0 border border-ctp-surface1'"
                :title="g.item.name"
                @click="emit('open-detail', g.item.assetId)"
              >
                <CubeIcon class="w-3 h-3" />{{ g.item.name }}
                <span
                  v-if="g.item.role === 'core'"
                  class="ml-0.5 text-ctp-peach"
                >★</span>
              </button>
              <button
                class="btn btn-xs btn-ghost !px-1 !py-0.5 text-ctp-overlay1 hover:text-ctp-red transition-colors"
                :title="t('requirement.form.assetDelete')"
                @click="removeComponent(g.item.assetId)"
              >
                <XMarkIcon class="w-3 h-3" />
              </button>
            </div>

            <!-- 子资产(数据结构 / 逻辑处理，从属于组件) -->
            <div class="ml-3 pl-2 border-l border-ctp-surface1 space-y-1">
              <div
                v-if="g.children.length"
                class="flex flex-wrap gap-1.5"
              >
                <button
                  v-for="ch in g.children"
                  :key="ch.assetId"
                  class="chip cursor-pointer transition-colors"
                  :class="ch.role === 'core' ? 'bg-ctp-blue/10 text-ctp-blue border border-ctp-blue/20' : 'bg-ctp-surface0 text-ctp-subtext0 border border-ctp-surface1'"
                  :title="ch.name"
                  @click="emit('open-detail', ch.assetId)"
                >
                  <span class="truncate max-w-[8rem]">{{ ch.name }}</span>
                  <span
                    v-if="ch.role === 'core'"
                    class="ml-0.5 text-ctp-peach"
                  >★</span>
                  <span
                    class="ml-1 text-ctp-overlay1 hover:text-ctp-red"
                    role="button"
                    tabindex="-1"
                    @click.stop="removeAsset(ch.assetId)"
                  >×</span>
                </button>
              </div>
              <button
                class="chip border border-dashed border-ctp-surface1 text-ctp-overlay1 hover:text-ctp-blue hover:border-ctp-blue/40 cursor-pointer transition-colors"
                @click="childPendingOpen = true"
              >
                <PlusIcon class="w-3 h-3" />{{ t('requirement.form.assetChildPlaceholder') }}
              </button>
            </div>
          </div>

          <!-- 组件添加占位(+ 标签) -->
          <div class="flex flex-wrap gap-1.5">
            <button
              class="chip border border-dashed border-ctp-surface1 text-ctp-overlay1 hover:text-ctp-blue hover:border-ctp-blue/40 cursor-pointer transition-colors"
              @click="emit('open-picker')"
            >
              <PlusIcon class="w-3 h-3" />{{ t('requirement.form.assetAddComponent') }}
            </button>
            <span
              v-if="!assetTree.groups.length"
              class="text-[10px] text-ctp-overlay1 self-center"
            >{{ t('requirement.form.assetGroupEmpty') }}</span>
          </div>

          <!-- 未归属资产 -->
          <div
            v-if="assetTree.orphans.length"
            class="space-y-1"
          >
            <div class="flex items-center gap-1.5">
              <span class="text-[10px] font-medium text-ctp-subtext1">{{ t('requirement.form.assetOrphan') }}</span>
              <span class="text-[10px] text-ctp-overlay1">{{ assetTree.orphans.length }}</span>
            </div>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="ch in assetTree.orphans"
                :key="ch.assetId"
                class="chip cursor-pointer transition-colors bg-ctp-surface0 text-ctp-subtext0 border border-ctp-surface1"
                :title="ch.name"
                @click="emit('open-detail', ch.assetId)"
              >
                <span class="truncate max-w-[8rem]">{{ ch.name }}</span>
                <span
                  class="ml-1 text-ctp-overlay1 hover:text-ctp-red"
                  role="button"
                  tabindex="-1"
                  @click.stop="removeAsset(ch.assetId)"
                >×</span>
              </button>
            </div>
          </div>
        </div>

        <!-- JSON 编辑器(默认收起) -->
        <div
          v-if="editorOpen"
          class="space-y-2 pt-1"
        >
          <p class="text-[10px] text-ctp-subtext0">
            {{ t('requirement.form.assetJsonHint') }}
          </p>
          <details class="group">
            <summary class="cursor-pointer select-none text-[10px] text-ctp-sky hover:text-ctp-blue transition-colors">
              {{ t('requirement.form.assetJsonExampleTitle') }}
            </summary>
            <pre class="mt-1.5 rounded-lg bg-ctp-mantle border border-ctp-surface0 p-2 text-[10px] leading-relaxed overflow-x-auto">{{ sampleAssetJsonText }}</pre>
          </details>
          <div class="flex items-center gap-1.5">
            <button
              class="btn btn-sm btn-ghost !py-1"
              :disabled="!assetJson.trim()"
              @click="applyAssetJson"
            >
              <CheckIcon class="w-3.5 h-3.5" />{{ t('requirement.form.assetJsonApply') }}
            </button>
            <button
              class="btn btn-sm btn-ghost !py-1"
              @click="formatAssetJson"
            >
              <ArrowPathIcon class="w-3.5 h-3.5" />{{ t('requirement.form.assetJsonFormat') }}
            </button>
          </div>
          <textarea
            v-model="assetJson"
            rows="7"
            class="input text-[11px] font-mono"
            :class="assetJsonError ? 'border-ctp-red/50' : ''"
            :placeholder="sampleAssetJsonText"
            @input="onAssetJsonInput"
            @blur="applyAssetJson"
          />
          <p
            v-if="assetJsonError"
            class="text-[10px] text-ctp-red"
          >
            {{ assetJsonError }}
          </p>
        </div>
      </div>
      <div class="border-t border-ctp-surface0" />

      <!-- 实现路径 -->
      <div>
        <label class="text-[11px] text-ctp-overlay1">{{ t('requirement.report.path') }}</label>
        <textarea
          v-model="form.implementationPath"
          rows="3"
          class="input mt-1 text-xs"
          :placeholder="t('requirement.report.pathPlaceholder')"
        />
      </div>

      <!-- 规约约束 -->
      <div>
        <label class="text-[11px] text-ctp-overlay1">{{ t('requirement.report.specs') }}</label>
        <textarea
          v-model="form.specsMd"
          rows="3"
          class="input mt-1 text-xs"
          :placeholder="t('requirement.form.specsMdPlaceholder')"
        />
      </div>
    </div>

    <!-- 组件内子资产手动选择预留弹窗 -->
    <div
      v-if="childPendingOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 backdrop-blur-sm p-4"
      @click.self="childPendingOpen = false"
    >
      <div class="panel w-full max-w-md overflow-hidden">
        <div class="panel-header shrink-0">
          <span class="flex items-center gap-2">
            <Squares2X2Icon class="w-4 h-4 text-ctp-blue" />{{ t('requirement.form.assetChildPendingTitle') }}
          </span>
          <button
            class="btn btn-xs btn-ghost"
            @click="childPendingOpen = false"
          >
            <XMarkIcon class="w-3.5 h-3.5" />
          </button>
        </div>
        <div class="p-3 text-xs text-ctp-subtext1">
          {{ t('requirement.form.assetChildPendingNote') }}
        </div>
      </div>
    </div>
  </div>
</template>
