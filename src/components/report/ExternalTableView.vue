<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { HashtagIcon } from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'
import { communityIdLabel } from '@/utils/communityLabel'

interface ExternalItem {
  package?: string
  name?: string
  fileCount?: number
  count?: number
  files: string[]
  communities?: Array<{ communityId: string; name?: string }>
}

interface ExpandedComm {
  communityId: string
  name?: string
  fileCount: number
  files: string[]
}

const props = defineProps<{
  items: ExternalItem[]
  edgeType: string
}>()

const { t } = useI18n()
const { showId, componentId } = useComponentId('ET-001')

const search = ref('')
const sortBy = ref<'name' | 'count' | 'communities'>('count')
const sortDir = ref<'asc' | 'desc'>('desc')
const page = ref(1)
const pageSize = 50
const expanded = ref<Set<string>>(new Set())

const drillCommState = ref<{ parentItem: ExternalItem; items: ExpandedComm[] } | null>(null)

const sorted = computed(() => {
  let list = [...props.items]
  const q = search.value.trim().toLowerCase()
  if (q) {
    list = list.filter(i => {
      const key = (i.package || i.name || '').toLowerCase()
      return key.includes(q)
    })
  }
  list.sort((a, b) => {
    const aKey = a.package || a.name || ''
    const bKey = b.package || b.name || ''
    const aVal: number | string = sortBy.value === 'count' ? (a.fileCount || a.count || 0)
      : sortBy.value === 'communities' ? ((a.communities || []).length)
      : aKey.toLowerCase()
    const bVal: number | string = sortBy.value === 'count' ? (b.fileCount || b.count || 0)
      : sortBy.value === 'communities' ? ((b.communities || []).length)
      : bKey.toLowerCase()
    if (typeof aVal === 'number' && typeof bVal === 'number') {
      return sortDir.value === 'desc' ? bVal - aVal : aVal - bVal
    }
    const aStr = String(aVal)
    const bStr = String(bVal)
    return sortDir.value === 'desc' ? bStr.localeCompare(aStr) : aStr.localeCompare(bStr)
  })
  return list
})

const totalPages = computed(() => Math.max(1, Math.ceil(sorted.value.length / pageSize)))
const paged = computed(() => {
  const start = (page.value - 1) * pageSize
  return sorted.value.slice(start, start + pageSize)
})

const commTotalPages = computed(() => {
  if (!drillCommState.value) return 1
  return Math.max(1, Math.ceil(drillCommState.value.items.length / pageSize))
})
const pagedComms = computed(() => {
  if (!drillCommState.value) return []
  const start = (page.value - 1) * pageSize
  return drillCommState.value.items.slice(start, start + pageSize)
})

function handleDrill(item: ExternalItem) {
  const communities = item.communities || []
  if (communities.length === 0) return
  const expanded: ExpandedComm[] = []
  const seen = new Set<string>()
  for (const c of communities) {
    if (seen.has(c.communityId)) continue
    seen.add(c.communityId)
    expanded.push({
      communityId: c.communityId,
      name: c.name,
      fileCount: 0,
      files: [],
    })
  }
  drillCommState.value = { parentItem: item, items: expanded }
  page.value = 1
}

function handleRollUp() {
  drillCommState.value = null
  page.value = 1
}

function toggleSort(col: 'name' | 'count' | 'communities') {
  if (sortBy.value === col) {
    sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  } else {
    sortBy.value = col
    sortDir.value = 'desc'
  }
}

function toggleExpand(id: string) {
  if (expanded.value.has(id)) {
    expanded.value.delete(id)
  } else {
    expanded.value.add(id)
  }
}

function sortIcon(col: string): string {
  if (sortBy.value !== col) return '\u2195'
  return sortDir.value === 'desc' ? '\u25BC' : '\u25B2'
}

function itemKey(item: ExternalItem): string {
  return item.package || item.name || ''
}

function itemCount(item: ExternalItem): number {
  return item.fileCount || item.count || 0
}

function commDisplay(c: { communityId: string; name?: string }): string {
  return c.name ? c.name : communityIdLabel(c.communityId)
}

watch(search, () => { page.value = 1 })
</script>

<template>
  <span v-if="showId" class="cmp-id">{{ componentId }}</span>
  <div class="etv-container">
    <template v-if="drillCommState">
      <div class="etv-toolbar">
        <button
          class="etv-rollup-btn"
          :title="t('report.rollUp', '返回上层')"
          @click="handleRollUp"
        >\u2190</button>
        <span class="etv-drill-label">{{ itemKey(drillCommState.parentItem) }}</span>
        <span class="etv-total">{{ drillCommState.items.length }} {{ t('report.l0Communities', '个关联社区') }}</span>
      </div>
      <div class="etv-table-wrap">
        <table class="etv-table">
          <thead>
            <tr>
              <th class="th-name">{{ t('report.communityArchitecture', '组件') }}</th>
              <th class="th-count">{{ t('report.communityIdLabel', '社区ID') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="c in pagedComms"
              :key="c.communityId"
              class="etv-row"
            >
              <td class="td-name" :title="c.communityId">{{ commDisplay(c) }}</td>
              <td class="td-count">{{ c.communityId }}</td>
            </tr>
            <tr v-if="pagedComms.length === 0">
              <td colspan="2" class="etv-empty">{{ t('report.noSearchResults', '无匹配结果') }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="commTotalPages > 1" class="etv-pagination">
        <button class="btn btn-ghost btn-xs" :disabled="page <= 1" @click="page--">{{ t('common.prev', '上一页') }}</button>
        <span class="etv-page">{{ page }} / {{ commTotalPages }}</span>
        <button class="btn btn-ghost btn-xs" :disabled="page >= commTotalPages" @click="page++">{{ t('common.next', '下一页') }}</button>
      </div>
    </template>
    <template v-else>
      <div class="etv-toolbar">
        <input
          v-model="search"
          type="text"
          :placeholder="t('report.searchCommunity', '搜索...')"
          class="etv-search"
        />
        <span class="etv-total">{{ sorted.length }} {{ t('report.items', '条') }}</span>
      </div>
      <div class="etv-table-wrap">
        <table class="etv-table">
          <thead>
            <tr>
              <th class="th-expand"></th>
              <th class="th-name sortable"
                :class="{ active: sortBy === 'name' }"
                @click="toggleSort('name')">
                {{ props.edgeType === 'EXTERNAL_INCLUDE' ? t('report.externalDependency', '外部包') : t('report.externalCall', '外部API') }}
                <span class="sort-icon">{{ sortIcon('name') }}</span>
              </th>
              <th class="th-count sortable"
                :class="{ active: sortBy === 'count' }"
                @click="toggleSort('count')">
                {{ t('report.fileCount', '引用数') }}
                <span class="sort-icon">{{ sortIcon('count') }}</span>
              </th>
              <th class="th-comm sortable"
                :class="{ active: sortBy === 'communities' }"
                @click="toggleSort('communities')">
                {{ t('report.l0Community', '关联社区') }}
                <span class="sort-icon">{{ sortIcon('communities') }}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <template v-for="item in paged" :key="itemKey(item)">
              <tr class="etv-row" @click="toggleExpand(itemKey(item))" @dblclick="handleDrill(item)">
                <td class="td-expand">
                  <span class="expand-icon" :class="{ open: expanded.has(itemKey(item)) }">&#9654;</span>
                </td>
                <td class="td-name" :title="itemKey(item)">{{ itemKey(item) }}</td>
                <td class="td-count">{{ itemCount(item) }}</td>
                <td class="td-comm">
                  <span
                    v-for="c in (item.communities || []).slice(0, 5)"
                    :key="c.communityId"
                    class="comm-chip"
                  >{{ commDisplay(c) }}</span>
                  <span v-if="(item.communities || []).length > 5" class="comm-more">
                    +{{ (item.communities || []).length - 5 }}
                  </span>
                </td>
              </tr>
              <tr v-if="expanded.has(itemKey(item))" class="etv-expand-row">
                <td colspan="4">
                  <div class="etv-expand-content">
                    <div class="expand-section">
                      <span class="expand-label">{{ t('report.files', '引用文件') }} ({{ item.files.length }}):</span>
                      <div class="expand-files">
                        <div v-for="f in item.files.slice(0, 30)" :key="f" class="file-item">{{ f }}</div>
                        <div v-if="item.files.length > 30" class="file-more">... {{ t('report.andMore', '等') }} {{ item.files.length - 30 }} {{ t('report.moreFiles', '个文件') }}</div>
                      </div>
                    </div>
                    <div v-if="(item.communities || []).length > 0" class="expand-section">
                      <span class="expand-label">{{ t('report.allCommunities', '全部关联社区') }}:</span>
                      <div class="expand-communities">
                        <span
                          v-for="c in (item.communities || [])"
                          :key="c.communityId"
                          class="comm-chip"
                        >{{ commDisplay(c) }}</span>
                      </div>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
            <tr v-if="paged.length === 0">
              <td colspan="4" class="etv-empty">{{ t('report.noSearchResults', '无匹配结果') }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="totalPages > 1" class="etv-pagination">
        <button class="btn btn-ghost btn-xs" :disabled="page <= 1" @click="page--">{{ t('common.prev', '上一页') }}</button>
        <span class="etv-page">{{ page }} / {{ totalPages }}</span>
        <button class="btn btn-ghost btn-xs" :disabled="page >= totalPages" @click="page++">{{ t('common.next', '下一页') }}</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.etv-container { display: flex; flex-direction: column; flex: 1; overflow: hidden; }
.etv-toolbar { display: flex; align-items: center; gap: 0.5rem; padding: 0.35rem 0; flex-shrink: 0; }
.etv-search {
  flex: 1; max-width: 240px; padding: 0.2rem 0.5rem; font-size: 0.75rem;
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: 0.375rem; color: var(--text-primary); outline: none;
}
.etv-search:focus { border-color: var(--accent); }
.etv-rollup-btn {
  display: flex; align-items: center; justify-content: center;
  width: 24px; height: 24px; padding: 0; font-size: 0.7rem;
  background: transparent; border: 1px solid transparent;
  border-radius: 0.25rem; color: var(--text-muted); cursor: pointer;
}
.etv-rollup-btn:hover { background: var(--bg-tertiary); color: var(--text-primary); border-color: var(--border); }
.etv-drill-label { font-size: 0.7rem; color: var(--accent, #7c3aed); font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 200px; }
.etv-total { font-size: 0.75rem; color: var(--text-muted); flex-shrink: 0; }
.etv-table-wrap { flex: 1; overflow-y: auto; }
.etv-table { width: 100%; border-collapse: collapse; font-size: 0.75rem; }
.etv-table th {
  position: sticky; top: 0; z-index: 1;
  background: var(--bg-secondary); text-align: left;
  padding: 0.35rem 0.5rem; font-weight: 600; color: var(--text-muted);
  border-bottom: 2px solid var(--border); white-space: nowrap;
}
.etv-table td { padding: 0.3rem 0.5rem; border-bottom: 1px solid var(--border); }
.th-expand { width: 20px; }
.th-name { min-width: 120px; }
.th-count { width: 60px; }
.th-comm { min-width: 160px; }
.sortable { cursor: pointer; user-select: none; }
.sortable:hover { color: var(--text-primary); }
.sortable.active { color: var(--accent, #7c3aed); }
.sort-icon { font-size: 0.6rem; margin-left: 2px; }
.etv-row { cursor: pointer; }
.etv-row:hover { background: var(--bg-secondary); }
.td-expand { text-align: center; }
.expand-icon { display: inline-block; font-size: 0.55rem; color: var(--text-muted); transition: transform 0.15s; }
.expand-icon.open { transform: rotate(90deg); }
.td-name { color: var(--text-primary); font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 280px; }
.td-count { color: var(--text-muted); font-family: var(--font-mono); text-align: right; }
.td-comm { display: flex; flex-wrap: wrap; gap: 0.2rem; }
.comm-chip {
  padding: 0.05rem 0.35rem; font-size: 0.65rem; color: var(--accent, #7c3aed);
  background: var(--bg-accent-subtle, #2d1f5e); border: 1px solid var(--accent, #7c3aed);
  border-radius: 0.25rem; white-space: nowrap;
}
.comm-more { font-size: 0.65rem; color: var(--text-muted); }
.etv-empty { text-align: center; color: var(--text-muted); padding: 1rem; font-style: italic; }

.etv-expand-row td { padding: 0; border-bottom: 2px solid var(--border); background: var(--bg-secondary); }
.etv-expand-content { padding: 0.5rem 0.75rem; display: flex; flex-direction: column; gap: 0.5rem; }
.expand-section { display: flex; flex-direction: column; gap: 0.25rem; }
.expand-label { font-size: 0.7rem; font-weight: 600; color: var(--text-muted); }
.expand-files { display: flex; flex-direction: column; gap: 1px; }
.file-item { font-size: 0.68rem; color: var(--text-primary); font-family: var(--font-mono); padding: 0.05rem 0; }
.file-more { font-size: 0.65rem; color: var(--text-muted); font-style: italic; }
.expand-communities { display: flex; flex-wrap: wrap; gap: 0.25rem; }

.etv-pagination { display: flex; align-items: center; justify-content: center; gap: 0.5rem; padding: 0.35rem 0; flex-shrink: 0; }
.etv-page { font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono); }
</style>
