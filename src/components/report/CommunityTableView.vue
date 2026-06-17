<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CommunityItem } from '@/stores/community-store'
import { useComponentSelectionStore } from '@/stores/component-selection-store'
import { communityLabel } from '@/utils/communityLabel'

const props = defineProps<{
  communities: CommunityItem[]
  edgeType: string
  showGuideButton?: boolean
  taskId?: string
}>()

const emit = defineEmits<{
  'open-community': [item: CommunityItem]
  'drill': [communityId: string]
  'guide-click': []
}>()

const { t } = useI18n()
const selectionStore = useComponentSelectionStore()

const search = ref('')
const sortBy = ref<'name' | 'nodes' | 'files' | 'edges' | 'quality'>('nodes')
const sortDir = ref<'asc' | 'desc'>('desc')
const page = ref(1)
const pageSize = 50

const sorted = computed(() => {
  let list = [...props.communities]
  const q = search.value.trim().toLowerCase()
  if (q) {
    list = list.filter(c => {
      const name = (c.name || '').toLowerCase()
      const id = c.communityId.toLowerCase()
      return name.includes(q) || id.includes(q)
    })
  }
  list.sort((a, b) => {
    const aVal = sortBy.value === 'name' ? (a.name || a.communityId || '')
      : sortBy.value === 'nodes' ? (a.nodeCount || 0)
      : sortBy.value === 'files' ? (a.fileCount || 0)
      : sortBy.value === 'edges' ? (a.edgeCount || 0)
      : (a.qualityScore ?? -1)
    const bVal = sortBy.value === 'name' ? (b.name || b.communityId || '')
      : sortBy.value === 'nodes' ? (b.nodeCount || 0)
      : sortBy.value === 'files' ? (b.fileCount || 0)
      : sortBy.value === 'edges' ? (b.edgeCount || 0)
      : (b.qualityScore ?? -1)
    if (typeof aVal === 'number') {
      return sortDir.value === 'desc' ? (bVal as number) - (aVal as number) : (aVal as number) - (bVal as number)
    }
    return sortDir.value === 'desc' ? (bVal as string).localeCompare(aVal as string) : (aVal as string).localeCompare(bVal as string)
  })
  return list
})

const totalPages = computed(() => Math.max(1, Math.ceil(sorted.value.length / pageSize)))
const paged = computed(() => {
  const s = (page.value - 1) * pageSize
  return sorted.value.slice(s, s + pageSize)
})

function toggleSort(col: typeof sortBy.value) {
  if (sortBy.value === col) { sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc' }
  else { sortBy.value = col; sortDir.value = 'desc' }
  page.value = 1
}

function sortIcon(col: typeof sortBy.value): string {
  if (sortBy.value !== col) return '\u2195'
  return sortDir.value === 'desc' ? '\u25BC' : '\u25B2'
}

function statusLabel(s: string): string {
  const m: Record<string, string> = { completed: '\u2713', running: '\u2022', queued: '\u25CB', error: '\u2717', skipped: '-', pending: '\u25CC' }
  return m[s] || s
}

watch(search, () => { page.value = 1 })

function handleRowClick(c: CommunityItem) {
  if (selectionStore.selecting) {
    selectionStore.toggle({
      id: c.communityId,
      type: 'community',
      name: communityLabel(c),
      taskId: props.taskId || '',
      metadata: {
        nodeCount: c.nodeCount,
        fileCount: c.fileCount,
        qualityScore: c.qualityScore ?? undefined,
      },
    })
    return
  }
  emit('open-community', c)
}

function handleRowDblClick(c: CommunityItem) {
  if (selectionStore.selecting) return
  emit('drill', c.communityId)
}
</script>

<template>
  <div class="ctv-container">
    <div class="ctv-toolbar">
      <input
        v-model="search"
        type="text"
        :placeholder="t('report.searchCommunity', '搜索...')"
        class="ctv-search"
      >
      <span class="ctv-total">{{ sorted.length }} {{ t('report.l0Communities', '个社区') }}</span>
    </div>
    <div class="ctv-table-wrap">
      <table class="ctv-table">
        <thead>
          <tr>
            <th class="ctv-th-status" />
            <th
              class="ctv-th-name sortable"
              :class="{ active: sortBy === 'name' }"
              @click="toggleSort('name')"
            >
              {{ t('report.communityArchitecture', '组件') }} <span class="sort-icon">{{ sortIcon('name') }}</span>
            </th>
            <th
              class="ctv-th-num sortable"
              :class="{ active: sortBy === 'nodes' }"
              @click="toggleSort('nodes')"
            >
              {{ t('report.nodes', '节点') }} <span class="sort-icon">{{ sortIcon('nodes') }}</span>
            </th>
            <th
              class="ctv-th-num sortable"
              :class="{ active: sortBy === 'files' }"
              @click="toggleSort('files')"
            >
              {{ t('report.files', '文件') }} <span class="sort-icon">{{ sortIcon('files') }}</span>
            </th>
            <th
              class="ctv-th-num sortable"
              :class="{ active: sortBy === 'edges' }"
              @click="toggleSort('edges')"
            >
              {{ t('report.edges', '边') }} <span class="sort-icon">{{ sortIcon('edges') }}</span>
            </th>
            <th
              class="ctv-th-num sortable"
              :class="{ active: sortBy === 'quality' }"
              @click="toggleSort('quality')"
            >
              {{ t('report.qualityScore', '质量') }} <span class="sort-icon">{{ sortIcon('quality') }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="c in paged"
            :key="c.id"
            class="ctv-row"
            :class="{
              completed: c.status === 'completed',
              selected: selectionStore.isSelected(c.communityId),
              selecting: selectionStore.selecting,
            }"
            @click="handleRowClick(c)"
            @dblclick="handleRowDblClick(c)"
          >
            <td
              class="ctv-td-status"
              :title="c.status"
            >
              {{ statusLabel(c.status) }}
            </td>
            <td
              class="ctv-td-name"
              :title="c.communityId"
            >
              {{ communityLabel(c) }}
            </td>
            <td class="ctv-td-num">
              {{ c.nodeCount }}
            </td>
            <td class="ctv-td-num">
              {{ c.fileCount }}
            </td>
            <td class="ctv-td-num">
              {{ c.edgeCount }}
            </td>
            <td class="ctv-td-num">
              <span
                v-if="c.qualityScore != null"
                :class="{ 'qual-high': c.qualityScore > 0.7, 'qual-mid': c.qualityScore > 0.3 && c.qualityScore <= 0.7, 'qual-low': c.qualityScore <= 0.3 }"
              >
                {{ (c.qualityScore * 100).toFixed(0) }}%
              </span>
              <span v-else>-</span>
            </td>
          </tr>
          <tr v-if="paged.length === 0">
            <td
              colspan="6"
              class="ctv-empty"
            >
              {{ t('report.noSearchResults', '无匹配') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div
      v-if="totalPages > 1"
      class="ctv-pagination"
    >
      <button
        class="btn btn-ghost btn-xs"
        :disabled="page <= 1"
        @click="page--"
      >
        {{ t('common.prev', '上一页') }}
      </button>
      <span class="ctv-page">{{ page }} / {{ totalPages }}</span>
      <button
        class="btn btn-ghost btn-xs"
        :disabled="page >= totalPages"
        @click="page++"
      >
        {{ t('common.next', '下一页') }}
      </button>
    </div>
    <button
      v-if="showGuideButton !== false"
      class="ctv-guide-btn"
      @click="emit('guide-click')"
    >
      <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.25 12.76c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 0 1 1.037-.443 48.282 48.282 0 0 0 5.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z" /></svg>
    </button>
  </div>
</template>

<style scoped>
.ctv-container { display: flex; flex-direction: column; flex: 1; overflow: hidden; position: relative; }
.ctv-toolbar { display: flex; align-items: center; gap: 0.5rem; padding: 0.35rem 0; flex-shrink: 0; }
.ctv-search {
  flex: 1; max-width: 220px; padding: 0.2rem 0.5rem; font-size: 0.75rem;
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: 0.375rem; color: var(--text-primary); outline: none;
}
.ctv-search:focus { border-color: var(--accent); }
.ctv-total { font-size: 0.75rem; color: var(--text-muted); flex-shrink: 0; }
.ctv-table-wrap { flex: 1; overflow-y: auto; }
.ctv-table { width: 100%; border-collapse: collapse; font-size: 0.75rem; }
.ctv-table th {
  position: sticky; top: 0; z-index: 1; background: var(--bg-secondary);
  text-align: left; padding: 0.35rem 0.5rem; font-weight: 600; color: var(--text-muted);
  border-bottom: 2px solid var(--border); white-space: nowrap;
}
.ctv-table td { padding: 0.3rem 0.5rem; border-bottom: 1px solid var(--border); }
.ctv-th-status { width: 24px; text-align: center; }
.ctv-th-name { min-width: 100px; }
.ctv-th-num { width: 56px; }
.sortable { cursor: pointer; user-select: none; }
.sortable:hover { color: var(--text-primary); }
.sortable.active { color: var(--accent, #7c3aed); }
.sort-icon { font-size: 0.6rem; margin-left: 2px; }
.ctv-row { cursor: pointer; }
.ctv-row:hover { background: var(--bg-secondary); }
.ctv-row.selecting { cursor: copy; }
.ctv-row.selected { background: color-mix(in srgb, #22c55e 10%, transparent); outline: 1px solid #22c55e; }
.ctv-row.completed .ctv-td-name { color: var(--accent, #7c3aed); }
.ctv-td-status { text-align: center; color: var(--text-muted); }
.ctv-td-name { color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 200px; }
.ctv-td-num { color: var(--text-muted); font-family: var(--font-mono); text-align: right; }
.qual-high { color: #22c55e; }
.qual-mid { color: #eab308; }
.qual-low { color: #ef4444; }
.ctv-empty { text-align: center; color: var(--text-muted); padding: 1rem; font-style: italic; }
.ctv-pagination { display: flex; align-items: center; justify-content: center; gap: 0.5rem; padding: 0.35rem 0; flex-shrink: 0; }
.ctv-page { font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono); }
.ctv-guide-btn {
  position: absolute; bottom: 12px; right: 12px; z-index: 211;
  width: 32px; height: 32px; padding: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 1rem;
  background: var(--bg-primary); color: var(--accent);
  border: 1px solid var(--accent); border-radius: 50%;
  cursor: pointer; transition: all 0.15s;
}
.ctv-guide-btn:hover {
  background: var(--accent); color: #fff;
  box-shadow: 0 0 8px rgba(124, 58, 237, 0.4);
}
</style>
