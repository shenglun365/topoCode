<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronRightIcon, CubeIcon, ExclamationTriangleIcon, PlusIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import type { AssetDetail } from '@/types'
import { kbAssetService } from '@/services/kb-assets'
import { useArchProjectStore } from '@/stores/project-store'

const props = defineProps<{ open: boolean; scopedIds: string[] }>()
const emit = defineEmits<{ close: []; add: [assetId: string] }>()

const { t } = useI18n()
const project = useArchProjectStore()

const pickQuery = ref('')
const pickLoading = ref(false)
const pickResults = ref<AssetDetail[]>([])
const pickType = ref<'all' | 'INCLUDE' | 'CALL'>('all')
const pickLevel = ref<'all' | 'L0' | 'L1'>('all')
/** 树状展开集合(父组件 id)。默认只显示根节点，点击父组件逐层展开。 */
const expanded = ref<Set<string>>(new Set())
const isScoped = (id: string) => props.scopedIds.includes(id)

/** 未关联知识库 → 无法读取组件索引。 */
const noKb = () => !project.project?.kbRoot

const filtered = computed(() => {
  let list = pickResults.value
  if (pickType.value !== 'all') {
    list = list.filter((r) => r.edgeType === pickType.value)
  }
  if (pickLevel.value !== 'all') {
    list = list.filter((r) => (r.hierLevel ?? '').toUpperCase() === pickLevel.value)
  }
  return list
})

const typeOptions = computed(() => [
  { value: 'all' as const, label: t('requirement.form.assetPickTypeAll') },
  { value: 'INCLUDE' as const, label: t('requirement.form.assetPickTypeInclude') },
  { value: 'CALL' as const, label: t('requirement.form.assetPickTypeCall') },
])

const levelOptions = computed(() => [
  { value: 'all' as const, label: t('requirement.form.assetPickLevelAll') },
  { value: 'L0' as const, label: 'L0' },
  { value: 'L1' as const, label: 'L1' },
])

interface TreeNode {
  asset: AssetDetail
  children: TreeNode[]
}

/** 按 parentId 构建层级树：父组件存在才归入子树，否则作为根。 */
const tree = computed<TreeNode[]>(() => {
  const list = filtered.value
  const byParent = new Map<string, AssetDetail[]>()
  for (const a of list) {
    if (a.parentId && list.some((x) => x.assetId === a.parentId)) {
      const arr = byParent.get(a.parentId) ?? []
      arr.push(a)
      byParent.set(a.parentId, arr)
    }
  }
  const build = (a: AssetDetail): TreeNode => ({
    asset: a,
    children: (byParent.get(a.assetId) ?? []).map(build),
  })
  return list
    .filter((a) => !a.parentId || !list.some((x) => x.assetId === a.parentId))
    .map(build)
})

interface Row {
  asset: AssetDetail
  depth: number
  hasChildren: boolean
  expanded: boolean
}

/** 展平树为可见行(仅渲染已展开分支)。 */
const visibleRows = computed<Row[]>(() => {
  const rows: Row[] = []
  const walk = (node: TreeNode, depth: number) => {
    const isOpen = expanded.value.has(node.asset.assetId)
    rows.push({ asset: node.asset, depth, hasChildren: node.children.length > 0, expanded: isOpen })
    if (isOpen) {
      for (const c of node.children) walk(c, depth + 1)
    }
  }
  for (const root of tree.value) walk(root, 0)
  return rows
})

async function load(query: string) {
  if (noKb()) {
    pickResults.value = []
    return
  }
  pickLoading.value = true
  try {
    pickResults.value = await kbAssetService.searchComponents(query)
  } catch {
    pickResults.value = []
  } finally {
    pickLoading.value = false
  }
}

function resetExpanded() {
  expanded.value = new Set()
}

watch(
  () => props.open,
  async (v) => {
    if (!v) return
    pickQuery.value = ''
    pickType.value = 'all'
    pickLevel.value = 'all'
    resetExpanded()
    await load('')
  },
)

watch(pickQuery, async (q) => {
  if (!props.open) return
  resetExpanded()
  await load(q)
})

watch([pickType, pickLevel], () => {
  resetExpanded()
})

function toggleExpand(id: string) {
  const next = new Set(expanded.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  expanded.value = next
}

function onRowClick(r: Row) {
  if (isScoped(r.asset.assetId)) return
  if (r.hasChildren) {
    toggleExpand(r.asset.assetId)
    return
  }
  addComponent(r.asset.assetId)
}

function addComponent(assetId: string) {
  if (isScoped(assetId)) return
  emit('add', assetId)
  emit('close')
}

/** 打开组件知识库文档(viewer，新标签页)。URL 带 ?docId=overall-<taskId> 供面包屑回退。 */
function openDoc(asset: AssetDetail) {
  const taskId = asset.taskId ?? ''
  const url = `/doc?taskId=${encodeURIComponent(taskId)}&docId=${encodeURIComponent(`overall-${taskId}`)}&communityId=${encodeURIComponent(asset.assetId)}&edgeType=${encodeURIComponent(asset.edgeType ?? 'INCLUDE')}`
  window.open(url, '_blank')
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 backdrop-blur-sm p-4"
    @click.self="emit('close')"
  >
    <div class="panel w-full max-w-lg max-h-[75vh] overflow-hidden flex flex-col">
      <div class="panel-header shrink-0">
        <span class="flex items-center gap-2">
          <CubeIcon class="w-4 h-4 text-ctp-blue" />{{ t('requirement.form.assetPickTitle') }}
        </span>
        <button
          class="btn btn-xs btn-ghost"
          @click="emit('close')"
        >
          <XMarkIcon class="w-3.5 h-3.5" />
        </button>
      </div>
      <div
        v-if="noKb()"
        class="p-3"
      >
        <div class="flex flex-col items-center gap-1.5 text-center border border-ctp-peach/30 bg-ctp-peach/5 rounded-lg px-3 py-6">
          <ExclamationTriangleIcon class="w-5 h-5 text-ctp-peach" />
          <p class="text-xs text-ctp-subtext1">{{ t('requirement.form.assetPickNoKb') }}</p>
        </div>
      </div>
      <div
        v-else
        class="p-3 flex flex-col gap-2 min-h-0 flex-1"
      >
        <div class="flex items-center gap-2">
          <input
            v-model="pickQuery"
            class="input flex-1"
            :placeholder="t('requirement.form.assetPickSearch')"
          >
          <select
            v-model="pickType"
            class="input !w-auto !py-1 text-xs shrink-0"
            :title="t('requirement.form.assetPickFilterType')"
          >
            <option
              v-for="o in typeOptions"
              :key="o.value"
              :value="o.value"
            >
              {{ o.label }}
            </option>
          </select>
          <select
            v-model="pickLevel"
            class="input !w-auto !py-1 text-xs shrink-0"
            :title="t('requirement.form.assetPickFilterLevel')"
          >
            <option
              v-for="o in levelOptions"
              :key="o.value"
              :value="o.value"
            >
              {{ o.label }}
            </option>
          </select>
        </div>
        <p
          v-if="pickLoading"
          class="text-xs text-ctp-overlay1"
        >
          {{ t('requirement.form.assetPickLoading') }}
        </p>
        <div
          v-else
          class="min-h-0 overflow-auto space-y-1"
        >
          <p
            v-if="!visibleRows.length"
            class="text-xs text-ctp-overlay1 text-center py-6"
          >
            {{ t('requirement.form.assetPickEmpty') }}
          </p>
          <div
            v-for="r in visibleRows"
            :key="r.asset.assetId"
            class="w-full flex items-start gap-2 rounded-lg border border-ctp-surface0 px-2 py-1.5 text-left transition-colors"
            :class="[
              isScoped(r.asset.assetId) ? 'opacity-50 cursor-default' : 'hover:bg-ctp-surface0/60 cursor-pointer',
            ]"
            :style="{ paddingLeft: `${(r.depth * 16) + 8}px` }"
            @click="onRowClick(r)"
          >
            <span class="w-4 shrink-0 mt-0.5">
              <ChevronRightIcon
                v-if="r.hasChildren"
                class="w-3.5 h-3.5 text-ctp-overlay1 shrink-0 transition-transform"
                :class="r.expanded ? 'rotate-90' : ''"
              />
            </span>
            <CubeIcon class="w-3.5 h-3.5 text-ctp-blue shrink-0 mt-0.5" />
            <span class="min-w-0 flex-1">
              <span class="flex items-center gap-1.5">
                <span class="text-xs font-medium text-ctp-text truncate">{{ r.asset.name }}</span>
                <span class="chip bg-ctp-surface0 text-[10px] shrink-0">{{ t(`architecture.kind.${r.asset.kind ?? 'service'}`) }}</span>
                <span
                  v-if="r.asset.edgeType"
                  class="chip text-[10px] shrink-0"
                  :class="r.asset.edgeType === 'CALL' ? 'bg-ctp-mauve/15 text-ctp-mauve' : 'bg-ctp-sky/15 text-ctp-sky'"
                >{{ r.asset.edgeType === 'CALL' ? t('requirement.form.assetPickTypeCall') : t('requirement.form.assetPickTypeInclude') }}</span>
                <span
                  v-if="r.asset.hierLevel"
                  class="chip bg-ctp-crust text-[10px] shrink-0"
                >{{ r.asset.hierLevel.toUpperCase() }}</span>
              </span>
              <span
                v-if="r.asset.file"
                class="block text-[10px] font-mono text-ctp-overlay1 truncate mt-0.5"
              >{{ r.asset.file }}</span>
              <span class="block flex items-center gap-3 text-[10px] text-ctp-overlay1 mt-0.5">
                <span v-if="r.asset.fileCount !== undefined">{{ r.asset.fileCount }} {{ t('requirement.form.assetPickFiles') }}</span>
                <span v-if="r.asset.dependsOn?.length">{{ r.asset.dependsOn.length }} {{ t('requirement.form.assetPickDeps') }}</span>
                <span v-if="r.asset.parentName && r.depth > 0">
                  {{ t('requirement.form.assetPickParent') }}: <span class="text-ctp-subtext1">{{ r.asset.parentName }}</span>
                </span>
              </span>
            </span>
            <span
              class="ml-auto shrink-0 flex items-center gap-1.5"
            >
              <a
                class="flex items-center gap-0.5 text-[10px] text-ctp-blue hover:underline shrink-0"
                :title="t('requirement.form.assetPickDoc')"
                @click.stop="openDoc(r.asset)"
              >
                <svg
                  class="w-3.5 h-3.5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.5"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178Z"
                  />
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"
                  />
                </svg>
              </a>
              <button
                v-if="!isScoped(r.asset.assetId)"
                class="text-[10px] text-ctp-blue shrink-0 flex items-center gap-0.5 hover:underline"
                :title="t('requirement.form.assetPickAdd')"
                @click.stop="addComponent(r.asset.assetId)"
              >
                <PlusIcon class="w-3 h-3" />{{ t('requirement.form.assetPickAdd') }}
              </button>
              <span
                v-else
                class="text-[10px] text-ctp-green shrink-0"
              >{{ t('requirement.form.assetPickAdded') }}</span>
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
