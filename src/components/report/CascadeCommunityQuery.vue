<script setup lang="ts">
/**
 * 级联社区查询 — 单行多组自定义下拉
 *
 * L0 ~ L4 每组一个下拉面板, 上一级选中决定下一级待选范围.
 * 支持多选、全选/反选、搜索.
 */

import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  FunnelIcon,
  CheckCircleIcon,
} from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'
const { showId, componentId } = useComponentId('RP-013')


const { t } = useI18n()

const props = defineProps<{
  taskId: string
  edgeType?: string
}>()

const emit = defineEmits<{
  query: [params: CascadeQueryParams]
}>()

export interface CascadeItem {
  id: string
  label: string
  parentCommId: string | null
  nodeCount: number
  qualityScore: number
}

export interface CascadeQueryParams {
  selectedIds: string[]
  selectedLevels: Record<string, string[]>
}

// 原始数据
const allItems = ref<Record<string, CascadeItem[]>>({})
const loading = ref(false)

// 每级选中
const selectedPerLevel = ref<Record<string, string[]>>({})

// 展开的下拉
const openLevel = ref<string | null>(null)

// 级联锁定 — 上级"选中且收拢"后, 下级才可点击
const lockedLevels = ref<Set<string>>(new Set())

// 每级搜索
const searchPerLevel = ref<Record<string, string>>({})

// 统计
const stats = ref<{ communityCount: number; nodeCount: number; edgeCount: number } | null>(null)

// 可用层级
const levelNames = computed(() => Object.keys(allItems.value).sort())

// 加载
async function loadCascadeLevels() {
  if (!props.taskId) return
  loading.value = true
  try {
    const result = await window.api.analysis.getCascadeLevels(props.taskId, props.edgeType)
    allItems.value = {}
    selectedPerLevel.value = {}
    searchPerLevel.value = {}
    for (const level of (result.levels || [])) {
      allItems.value[level.lv] = level.items || []
      selectedPerLevel.value[level.lv] = []
      searchPerLevel.value[level.lv] = ''
    }
  } catch (e) {
    console.error('[CascadeQuery] load failed:', e)
  } finally {
    loading.value = false
  }
}

// 过滤后的选项
function getFilteredOptions(lv: string): CascadeItem[] {
  const items = allItems.value[lv] || []
  const lvNum = parseInt(lv.replace('L', ''))

  // L0 返回全部
  if (lvNum === 0) {
    const search = searchPerLevel.value[lv] || ''
    if (search) {
      const q = search.toLowerCase()
      return items.filter(i => i.id.toLowerCase().includes(q) || i.label.toLowerCase().includes(q))
    }
    return items
  }

  // L1+ 按父级过滤
  const parentLv = `L${lvNum - 1}`
  const parentSelected = selectedPerLevel.value[parentLv] || []
  if (parentSelected.length === 0) return []

  let filtered = items.filter(i => parentSelected.includes(i.parentCommId || ''))

  // 搜索过滤
  const search = searchPerLevel.value[lv] || ''
  if (search) {
    const q = search.toLowerCase()
    filtered = filtered.filter(i => i.id.toLowerCase().includes(q) || i.label.toLowerCase().includes(q))
  }

  return filtered
}

// 上级变化清空下级 (仅当上级为空且下级有选中时)
watch(selectedPerLevel, (newVal) => {
  const levels = Object.keys(newVal).sort()
  for (let i = 0; i < levels.length; i++) {
    const lv = levels[i]
    if (!newVal[lv] || newVal[lv].length === 0) {
      for (let j = i + 1; j < levels.length; j++) {
        const depLv = levels[j]
        // 只清空有选中项的下级，避免初始化时无限循环
        if (selectedPerLevel.value[depLv] && selectedPerLevel.value[depLv].length > 0) {
          selectedPerLevel.value[depLv] = []
          searchPerLevel.value[depLv] = ''
        }
      }
      // 上级清空时解锁本级和所有下级
      unlockDownstream(lv)
    }
  }
  updateStats()
}, { deep: true })

// 统计
async function updateStats() {
  const ids = getAllSelectedIds()
  if (ids.length === 0) {
    stats.value = { communityCount: 0, nodeCount: 0, edgeCount: 0 }
    return
  }
  try {
    const firstLv = levelNames.value[0] || 'L0'
    stats.value = await window.api.analysis.getQueryStats({
      taskId: props.taskId,
      edgeType: props.edgeType,
      commLv: firstLv,
      commIds: ids,
      depth: 1,
    })
  } catch (e) {
    console.error('[CascadeQuery] stats failed:', e)
  }
}

function getAllSelectedIds(): string[] {
  const ids = new Set<string>()
  for (const lv of Object.keys(selectedPerLevel.value)) {
    for (const id of selectedPerLevel.value[lv]) ids.add(id)
  }
  return Array.from(ids)
}

// 点击外部收拢下拉
function handleClickOutside(e: MouseEvent) {
  if (!openLevel.value) return
  const target = e.target as Node
  const cascadeEl = document.querySelector('.cascade-query-inline') as Element
  if (cascadeEl && !cascadeEl.contains(target)) {
    // 收拢时如果该级有选中项, 则锁定
    const lv = openLevel.value
    if (getSelectedCount(lv) > 0) {
      const next = new Set(lockedLevels.value)
      next.add(lv)
      lockedLevels.value = next
    }
    openLevel.value = null
  }
}

// 全选/反选/清空
function selectAll(lv: string) {
  selectedPerLevel.value[lv] = getFilteredOptions(lv).map(o => o.id)
}
function invertSelection(lv: string) {
  const options = getFilteredOptions(lv)
  const current = selectedPerLevel.value[lv] || []
  selectedPerLevel.value[lv] = options.filter(o => !current.includes(o.id)).map(o => o.id)
}
function clearLevel(lv: string) {
  selectedPerLevel.value[lv] = []
  // 清空后解锁本级和所有下级
  unlockDownstream(lv)
}

// 解锁指定级别及其所有下级
function unlockDownstream(lv: string) {
  const lvNum = parseInt(lv.replace('L', ''))
  const next = new Set(lockedLevels.value)
  for (let i = lvNum; i <= 4; i++) {
    next.delete(`L${i}`)
  }
  lockedLevels.value = next
}

// 检查上级是否已锁定
function isParentLocked(lv: string): boolean {
  const lvNum = parseInt(lv.replace('L', ''))
  if (lvNum === 0) return true // L0 无上级, 始终可用
  const parentLv = `L${lvNum - 1}`
  return lockedLevels.value.has(parentLv)
}

// 切换下拉
function toggleLevel(lv: string) {
  // 上级未锁定则不允许展开下级
  if (!isParentLocked(lv)) return

  if (openLevel.value === lv) {
    // 收拢时: 如果该级有选中项, 则锁定
    if (getSelectedCount(lv) > 0) {
      const next = new Set(lockedLevels.value)
      next.add(lv)
      lockedLevels.value = next
    }
    openLevel.value = null
  } else {
    openLevel.value = lv
  }
}

// 查询
function handleQuery() {
  emit('query', {
    selectedIds: getAllSelectedIds(),
    selectedLevels: { ...selectedPerLevel.value },
  })
}

function getSelectedCount(lv: string): number {
  return (selectedPerLevel.value[lv] || []).length
}

function getTotalCount(lv: string): number {
  return getFilteredOptions(lv).length
}

function getSelectedDisplay(lv: string): string {
  const count = getSelectedCount(lv)
  if (count === 0) return t('report.selectPlaceholder')
  const total = getTotalCount(lv)
  if (count === total) return t('report.selectedAll')
  return `${count}/${total}`
}

onMounted(() => {
  loadCascadeLevels()
  document.addEventListener('click', handleClickOutside)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', handleClickOutside)
})

// 监听 taskId/edgeType 变化，切换 tab 时重新加载数据
watch([() => props.taskId, () => props.edgeType], () => {
  loadCascadeLevels()
})

defineExpose({ loadCascadeLevels })
</script>

<template>
  <div class="cascade-query-inline">
  <span v-if="showId" class="cmp-id">{{ componentId }}</span>
    <div v-if="loading" class="loading-hint">
      <span class="text-muted">{{ t('common.loading') }}</span>
    </div>

    <div v-else class="query-row">
      <!-- 每组下拉 -->
      <div
        v-for="lv in levelNames"
        :key="lv"
        class="level-group"
      >
        <!-- 触发按钮 -->
        <div
          class="level-trigger"
          :class="{ 'level-locked': lockedLevels.has(lv), 'level-disabled': !isParentLocked(lv) }"
          @click="toggleLevel(lv)"
        >
          <span class="level-badge">{{ lv }}</span>
          <span class="level-display">{{ getSelectedDisplay(lv) }}</span>
          <span v-if="!isParentLocked(lv)" class="level-disabled-dot" :title="t('report.selectParentFirst')"></span>
          <span v-else class="level-arrow">▾</span>
        </div>

        <!-- 下拉面板 -->
        <div v-if="openLevel === lv" class="level-dropdown-panel">
          <!-- 搜索 -->
          <div class="dropdown-search">
            <input
              type="text"
              :placeholder="t('report.searchGroups')"
              :value="searchPerLevel[lv]"
              @input="searchPerLevel[lv] = ($event.target as HTMLInputElement).value"
              @click.stop
            />
          </div>

          <!-- 操作栏 -->
          <div class="dropdown-actions">
            <button class="action-chip" @click.stop="selectAll(lv)">{{ t('report.all') }}</button>
            <button class="action-chip" @click.stop="invertSelection(lv)">{{ t('report.invert') }}</button>
            <button v-if="getSelectedCount(lv) > 0" class="action-chip clear" @click.stop="clearLevel(lv)">{{ t('common.clear') }}</button>
          </div>

          <!-- 选项列表 -->
          <div class="dropdown-options">
            <div
              v-if="getTotalCount(lv) === 0"
              class="dropdown-empty"
            >
              {{ lv === 'L0' ? t('report.noGroups') : t('report.selectParentFirst') }}
            </div>
            <label
              v-for="item in getFilteredOptions(lv)"
              :key="item.id"
              class="option-item"
              @click.stop
            >
              <input
                type="checkbox"
                :value="item.id"
                v-model="selectedPerLevel[lv]"
              />
              <span class="option-label">{{ item.label }}</span>
              <span class="option-count">{{ item.nodeCount }}</span>
            </label>
          </div>
        </div>
      </div>

      <!-- 查询按钮 -->
      <button
        class="btn btn-primary btn-sm query-btn"
        :disabled="getAllSelectedIds().length === 0"
        @click="handleQuery"
      >
        <FunnelIcon class="w-4 h-4" />
        <span>{{ t('common.query') }}</span>
      </button>
    </div>

    <!-- 统计 -->
    <div v-if="stats && stats.communityCount > 0" class="stats-bar">
      <CheckCircleIcon class="w-3.5 h-3.5 stats-icon" />
      <span class="stats-text">
        {{ t('report.queryStats', { communities: stats.communityCount, nodes: stats.nodeCount, edges: stats.edgeCount }) }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.cascade-query-inline {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
}

.loading-hint {
  padding: 12px;
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
}

.query-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.level-group {
  position: relative;
}

.level-trigger {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-primary);
  cursor: pointer;
  transition: border-color 0.15s;
  min-width: 100px;
}

.level-trigger:hover {
  border-color: var(--accent);
}

.level-trigger.level-locked {
  border-color: var(--success);
  background: color-mix(in srgb, var(--success) 6%, var(--bg-primary));
}

.level-trigger.level-disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.level-trigger.level-disabled:hover {
  border-color: var(--border);
}

.level-disabled-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-muted);
  flex-shrink: 0;
  opacity: 0.5;
}

.level-badge {
  font-size: 9px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--accent);
  color: white;
  flex-shrink: 0;
}

.level-display {
  font-size: 10px;
  color: var(--text-primary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.level-arrow {
  font-size: 10px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.level-dropdown-panel {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 4px;
  width: 260px;
  max-height: 300px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.2);
  z-index: 200;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dropdown-search {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
}

.dropdown-search input {
  width: 100%;
  padding: 3px 6px;
  font-size: 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  outline: none;
}

.dropdown-search input:focus {
  border-color: var(--accent);
}

.dropdown-actions {
  display: flex;
  gap: 4px;
  padding: 4px 8px;
  border-bottom: 1px solid var(--border);
}

.action-chip {
  padding: 1px 6px;
  font-size: 9px;
  border: 1px solid var(--border);
  border-radius: 3px;
  background: var(--bg-secondary);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}

.action-chip:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.action-chip.clear {
  color: var(--error);
  border-color: var(--error);
}

.dropdown-options {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
}

.dropdown-empty {
  padding: 16px;
  text-align: center;
  font-size: 10px;
  color: var(--text-muted);
}

.option-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 6px;
  font-size: 10px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s;
}

.option-item:hover {
  background: var(--bg-hover);
}

.option-item:has(input:checked) {
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}

.option-label {
  flex: 1;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.option-count {
  font-size: 9px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  flex-shrink: 0;
}

.query-btn {
  flex-shrink: 0;
}

.query-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.stats-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  margin-top: 6px;
  background: color-mix(in srgb, var(--success) 6%, transparent);
  border-radius: 4px;
  border: 1px solid color-mix(in srgb, var(--success) 20%, transparent);
}

.stats-icon {
  color: var(--success);
  flex-shrink: 0;
}

.stats-text {
  font-size: 11px;
  color: var(--text-primary);
}
</style>
