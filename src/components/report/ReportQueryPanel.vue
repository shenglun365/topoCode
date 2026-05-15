<script setup lang="ts">
/**
 * 报告查询条件面板
 *
 * - 社区层级: 下拉选择，动态加载任务实际生成的层级
 * - 社区分组 ID: 多选下拉 / checkbox 列表，支持搜索过滤
 * - 展开深度: 滑块，默认 2，最大 4
 * - 查询按钮: 替换当前视图
 */

import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  FunnelIcon,
  MagnifyingGlassIcon,
  ArrowPathIcon,
} from '@heroicons/vue/24/outline'

const { t } = useI18n()

const props = defineProps<{
  taskId: string
  edgeType?: string
}>()

const emit = defineEmits<{
  query: [params: QueryParams]
}>()

export interface QueryParams {
  commLv: string
  commIds: string[]
  depth: number
}

// 社区层级列表
const availableLevels = ref<string[]>([])
const loadingLevels = ref(false)

// 社区分组列表
const availableGroups = ref<Array<{ id: string; label: string; nodeCount: number }>>([])
const loadingGroups = ref(false)

// 搜索过滤
const groupSearch = ref('')

// 选中状态
const selectedLevel = ref<string>('')
const selectedGroups = ref<string[]>([])
const depth = ref(2)

// 过滤后的分组列表
const filteredGroups = computed(() => {
  if (!groupSearch.value) return availableGroups.value
  const query = groupSearch.value.toLowerCase()
  return availableGroups.value.filter(g =>
    g.id.toLowerCase().includes(query) || g.label.toLowerCase().includes(query)
  )
})

// 加载可用层级
async function loadLevels() {
  console.log('[ReportQueryPanel] loadLevels START taskId=', props.taskId, 'edgeType=', props.edgeType)
  if (!props.taskId) return
  loadingLevels.value = true
  try {
    const result = await window.api.analysis.getAvailableLevels(props.taskId, props.edgeType)
    console.log('[ReportQueryPanel] loadLevels RESULT:', result)
    availableLevels.value = result
    if (!selectedLevel.value && availableLevels.value.length > 0) {
      selectedLevel.value = availableLevels.value[0]
      console.log('[ReportQueryPanel] loadLevels set selectedLevel=', selectedLevel.value)
    }
    console.log('[ReportQueryPanel] loadLevels DONE availableLevels=', JSON.stringify(availableLevels.value), 'selectedLevel=', selectedLevel.value)
  } catch (e) {
    console.error('[ReportQueryPanel] Failed to load levels:', e)
    availableLevels.value = []
  } finally {
    loadingLevels.value = false
  }
}

// 加载分组列表（按选中的层级）
async function loadGroups() {
  console.log('[ReportQueryPanel] loadGroups START taskId=', props.taskId, 'edgeType=', props.edgeType, 'selectedLevel=', selectedLevel.value)
  if (!selectedLevel.value || !props.taskId) return
  loadingGroups.value = true
  try {
    const params = {
      taskId: props.taskId,
      edgeType: props.edgeType || 'CALL',
      commLv: selectedLevel.value,
      commIds: [],
      depth: 1,
    }
    console.log('[ReportQueryPanel] loadGroups calling getCommunityGraph:', JSON.stringify(params))
    const data = await window.api.analysis.getCommunityGraph(params)
    console.log('[ReportQueryPanel] loadGroups RESULT communities count=', data?.communities?.length, 'nodes count=', data?.nodes?.length)
    console.log('[ReportQueryPanel] loadGroups communities:', JSON.stringify((data?.communities || []).map((c: any) => ({ id: c.comm_id, label: c.description, count: c.node_count }))))
    availableGroups.value = (data?.communities || []).map((c: any) => ({
      id: c.comm_id,
      label: c.description || c.comm_id,
      nodeCount: c.node_count || 0,
    }))
    console.log('[ReportQueryPanel] loadGroups DONE availableGroups=', JSON.stringify(availableGroups.value))
  } catch (e) {
    console.error('[ReportQueryPanel] Failed to load groups:', e)
    availableGroups.value = []
  } finally {
    loadingGroups.value = false
  }
}

// 监听层级变化，重新加载分组
watch(selectedLevel, (newVal) => {
  console.log('[ReportQueryPanel] watch selectedLevel changed to:', newVal)
  selectedGroups.value = []
  loadGroups()
})

// 切换 tab（taskId / edgeType 变化）时重新初始化
watch([() => props.taskId, () => props.edgeType], ([newTaskId, newEdgeType], [oldTaskId, oldEdgeType]) => {
  console.log('[ReportQueryPanel] watch props changed: taskId', oldTaskId, '->', newTaskId, 'edgeType', oldEdgeType, '->', newEdgeType)
  availableLevels.value = []
  availableGroups.value = []
  selectedLevel.value = ''
  selectedGroups.value = []
  init()
})

// 执行查询
function handleQuery() {
  if (!selectedLevel.value) return
  emit('query', {
    commLv: selectedLevel.value,
    commIds: selectedGroups.value.length > 0 ? selectedGroups.value : availableGroups.value.map(g => g.id),
    depth: depth.value,
  })
}

// 初始化
function init() {
  console.log('[ReportQueryPanel] init() called, taskId=', props.taskId, 'edgeType=', props.edgeType)
  loadLevels()
}

console.log('[ReportQueryPanel] setup, taskId=', props.taskId, 'edgeType=', props.edgeType)
init()

defineExpose({ init, loadLevels, loadGroups })
</script>

<template>
  <div class="report-query-panel">
    <div class="query-row">
      <!-- 社区层级 -->
      <div class="query-item">
        <label class="query-label">{{ t('report.communityLevel') }}</label>
        <select
          v-model="selectedLevel"
          class="query-select"
          :disabled="loadingLevels"
        >
          <option v-for="level in availableLevels" :key="level" :value="level">
            {{ level }}
          </option>
        </select>
      </div>

      <!-- 展开深度 -->
      <div class="query-item">
        <label class="query-label">{{ t('report.expandDepth') }}: {{ depth }}</label>
        <input
          v-model.number="depth"
          type="range"
          min="1"
          max="4"
          step="1"
          class="query-slider"
        />
      </div>
    </div>

    <!-- 社区分组多选 -->
    <div class="query-item query-groups">
      <label class="query-label">{{ t('report.communityGroups') }}</label>
      <div class="group-search">
        <MagnifyingGlassIcon class="w-4 h-4 search-icon" />
        <input
          v-model="groupSearch"
          type="text"
          class="group-search-input"
          :placeholder="t('report.searchGroups')"
        />
      </div>
      <div class="group-list" :class="{ loading: loadingGroups }">
        <label
          v-for="group in filteredGroups"
          :key="group.id"
          class="group-checkbox"
        >
          <input
            type="checkbox"
            :value="group.id"
            v-model="selectedGroups"
          />
          <span class="group-label">{{ group.label }}</span>
          <span class="group-count">{{ group.nodeCount }} {{ t('report.nodes') }}</span>
        </label>
        <div v-if="filteredGroups.length === 0 && !loadingGroups" class="empty-groups">
          {{ t('report.noGroups') }}
        </div>
      </div>
    </div>

    <!-- 查询按钮 -->
    <div class="query-actions">
      <button class="btn btn-primary btn-sm" @click="handleQuery">
        <FunnelIcon class="w-4 h-4" />
        <span>{{ t('common.query') }}</span>
      </button>
      <button class="btn btn-ghost btn-sm" @click="init">
        <ArrowPathIcon class="w-4 h-4" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.report-query-panel {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
}

.query-row {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 8px;
}

.query-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.query-label {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}

.query-select {
  padding: 3px 8px;
  font-size: 11px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-primary);
  color: var(--text-primary);
  outline: none;
}

.query-select:focus {
  border-color: var(--accent);
}

.query-slider {
  width: 100px;
  accent-color: var(--accent);
}

/* 分组多选 */
.query-groups {
  flex-direction: column;
  align-items: stretch;
  gap: 6px;
}

.group-search {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-primary);
}

.search-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}

.group-search-input {
  flex: 1;
  border: none;
  background: transparent;
  font-size: 11px;
  color: var(--text-primary);
  outline: none;
  min-width: 0;
}

.group-list {
  max-height: 120px;
  overflow-y: auto;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.group-list.loading {
  opacity: 0.5;
}

.group-checkbox {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  font-size: 11px;
  border: 1px solid var(--border);
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}

.group-checkbox:hover {
  border-color: var(--accent);
  background: var(--bg-hover);
}

.group-checkbox:has(input:checked) {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}

.group-label {
  color: var(--text-primary);
}

.group-count {
  color: var(--text-muted);
  font-size: 10px;
}

.empty-groups {
  font-size: 11px;
  color: var(--text-muted);
  padding: 8px;
  text-align: center;
  width: 100%;
}

.query-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
}
</style>
