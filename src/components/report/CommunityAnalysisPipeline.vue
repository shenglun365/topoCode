<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useProjectStore } from '@/stores/project'
import { useSettingsStore } from '@/stores/settings'
import {
  PlayIcon,
  StopIcon,
  ArrowPathIcon,
  FunnelIcon,
} from '@heroicons/vue/24/outline'
import { useReportStore } from '@/stores/report'

const { t } = useI18n()
const projectStore = useProjectStore()
const settingsStore = useSettingsStore()
const reportStore = useReportStore()

const props = defineProps<{ taskId: string; projectId?: string }>()
const emit = defineEmits<{
  completed: [summaries: Array<{ communityId: string; level: string; edgeType: string; name: string; summary: string; mermaid?: string; plantuml?: string }>]
  viewCommunityMD: [params: { communityId: string; name: string; summary: string; mermaid?: string; plantuml?: string }]
}>()

const modelId = computed(() => settingsStore.models.find(m => m.isDefault)?.id)
const pid = computed(() => props.projectId || projectStore.selectedProjectId)

const taskState = computed(() => reportStore.tasks[props.taskId])

// View preferences (local, not in store)
const edgeTypeOptions = [
  { type: 'INCLUDE', label: t('report.pipeline.edgeInclude') },
  { type: 'CALL', label: t('report.pipeline.edgeCall') },
] as const
const selectedEdgeType = ref('INCLUDE')
const selectedLevel = ref('L0')

interface LevelInfo { lv: string; count: number; analyzed: number }
const availableLevels = ref<LevelInfo[]>([])

const loading = ref(true)
const loadError = ref<string | null>(null)
const batchSize = ref(3)

const searchQuery = ref('')
const currentPage = ref(1)
const pageSize = 100

// Derived from store communities
const communities = computed(() => taskState.value?.communities || [])

const searchedCommunities = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return displayCommunities.value
  return displayCommunities.value.filter(c => {
    const id = fmtCommId(c.communityId).toLowerCase()
    const name = (c.name || '').toLowerCase()
    const pName = (c.parentName || '').toLowerCase()
    return id.includes(q) || name.includes(q) || pName.includes(q)
  })
})

const totalPages = computed(() => Math.max(1, Math.ceil(searchedCommunities.value.length / pageSize)))
const pagedCommunities = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return searchedCommunities.value.slice(start, start + pageSize)
})

watch(searchQuery, () => { currentPage.value = 1 })

const analyzedCommIds = computed(() => {
  const ids = new Set<string>()
  if (taskState.value) {
    for (const [k, v] of Object.entries(taskState.value.llmResults)) {
      if (v.name) ids.add(k)
    }
  }
  return ids
})

interface SortRule { field: string; desc: boolean }
const sortHistory = ref<SortRule[]>([])

function hasAnalysis(commId: string): boolean {
  return analyzedCommIds.value.has(commId)
}

function lookupName(commId: string): string | undefined {
  if (!taskState.value) return undefined
  return taskState.value.llmResults[commId]?.name || taskState.value.llmResults[commId]?.nameManual
}

const selectedCount = computed(() => {
  const n = communities.value.filter(t => t.selected).length
  console.log(`[CommunityAI] selectedCount=${n}`)
  return n
})
const completedCount = computed(() => communities.value.filter(t => t.status === 'completed').length)
const errorCount = computed(() => communities.value.filter(t => t.status === 'error').length)
const totalCount = computed(() => {
  const n = communities.value.length
  console.log(`[CommunityAI] totalCount=${n} completed=${communities.value.filter(t => t.status === 'completed').length} error=${communities.value.filter(t => t.status === 'error').length} pending=${communities.value.filter(t => t.status === 'pending').length} running=${communities.value.filter(t => t.status === 'running').length}`)
  return n
})
const overallProgress = computed(() => {
  const done = completedCount.value + errorCount.value
  const pct = totalCount.value > 0 ? Math.round((done / totalCount.value) * 100) : 0
  console.log(`[CommunityAI] overallProgress done=${done} total=${totalCount.value} pct=${pct}`)
  return pct
})

const displayCommunities = computed(() => {
  let list = communities.value.filter(c => c.edgeType === selectedEdgeType.value && c.level === selectedLevel.value)
  console.log(`[CommunityAI] displayCommunities edgeType=${selectedEdgeType.value} level=${selectedLevel.value} all=${communities.value.length} filtered=${list.length}`)
  if (selectedLevel.value === 'L1') {
    list = list.filter(c => hasAnalysis(c.parentId || ''))
  } else if (selectedLevel.value === 'L2') {
    list = list.filter(c => hasAnalysis(c.parentId || ''))
  }
  for (const c of list) {
    if (c.parentId) c.parentName = lookupName(c.parentId)
  }
  if (sortHistory.value.length > 0) {
    list = [...list].sort((a, b) => {
      for (const rule of sortHistory.value) {
        const va = String(a[rule.field as keyof typeof a] ?? '')
        const vb = String(b[rule.field as keyof typeof b] ?? '')
        const na = parseFloat(va)
        const nb = parseFloat(vb)
        const cmp = !isNaN(na) && !isNaN(nb) ? na - nb : va.localeCompare(vb)
        if (cmp !== 0) return rule.desc ? -cmp : cmp
      }
      return 0
    })
  }
  return list
})

function sortBy(field: string) {
  const idx = sortHistory.value.findIndex(s => s.field === field)
  if (idx >= 0) {
    const existing = sortHistory.value[idx]
    if (idx === 0) {
      existing.desc = !existing.desc
    } else {
      sortHistory.value.splice(idx, 1)
      sortHistory.value.unshift(existing)
    }
  } else {
    sortHistory.value.unshift({ field, desc: true })
  }
}

function sortIcon(field: string): string {
  const s = sortHistory.value.find(r => r.field === field)
  if (!s) return ''
  const idx = sortHistory.value.indexOf(s)
  return s.desc ? `▼${idx + 1}` : `▲${idx + 1}`
}

function fmtCommId(id: string): string {
  return id.replace(/^comm-[^-]+-/, '')
}

watch([selectedEdgeType, selectedLevel], () => { refreshDisplay() })

function updateAvailableLevels() {
  const edge = selectedEdgeType.value
  const lvSet = new Set<string>()
  for (const c of communities.value) {
    if (c.edgeType === edge) lvSet.add(c.level)
  }
  availableLevels.value = ['L0', 'L1', 'L2']
    .filter(lv => lvSet.has(lv))
    .map(lv => {
      const items = communities.value.filter(c => c.edgeType === edge && c.level === lv)
      return { lv, count: items.length, analyzed: items.filter(c => c.status === 'completed').length }
    })
  console.log(`[CommunityAI] updateAvailableLevels edge=${edge} lvs=${availableLevels.value.map(l=>l.lv+'('+l.count+'/'+l.analyzed+')').join(',')}`)
  if (!lvSet.has(selectedLevel.value) && availableLevels.value.length > 0) {
    selectedLevel.value = availableLevels.value[0].lv
  }
}

function refreshDisplay() { updateAvailableLevels() }

function switchEdgeType(type: string) {
  if (type === selectedEdgeType.value) return
  selectedEdgeType.value = type
  updateAvailableLevels()
  if (availableLevels.value.length > 0) selectedLevel.value = availableLevels.value[0].lv
}

function toggleSelect(id: string) {
  if (taskState.value?.communityRunning) return
  reportStore.toggleSelect(props.taskId, id)
}

function statusBadgeClass(status: string): string {
  switch (status) {
    case 'completed': return 'badge-success'
    case 'running': case 'queued': return 'badge-info'
    case 'error': return 'badge-error'
    default: return 'badge-muted'
  }
}

function statusLabel(status: string): string {
  switch (status) {
    case 'completed': return t('common.completed')
    case 'running': return t('common.running')
    case 'queued': return t('common.queued')
    case 'error': return t('common.error')
    default: return t('common.pending')
  }
}

async function startAnalysis() {
  console.log(`[CommunityAI] startAnalysis ENTER modelId=${modelId.value} batchSize=${batchSize.value} selectedCount=${selectedCount.value} running=${taskState.value?.communityRunning}`)
  if (!modelId.value) {
    console.log(`[CommunityAI] startAnalysis SKIP no modelId`)
    return
  }
  if (!pid.value) {
    console.log(`[CommunityAI] startAnalysis SKIP no pid`)
    return
  }
  const results = await reportStore.analyzeSelected(props.taskId, modelId.value, batchSize.value, pid.value)
  console.log(`[CommunityAI] startAnalysis DONE results=${results.length}`)
  if (results.length > 0) {
    emit('completed', results)
  }
}

async function retryTask(id: string) {
  const community = communities.value.find(c => c.id === id)
  if (!community) return
  if (!modelId.value) return
  const ok = await reportStore.retryTask(props.taskId, community.communityId, modelId.value, pid.value!)
  if (ok && taskState.value) {
    const c = taskState.value.communities.find(c => c.id === id)
    if (c && c.status === 'completed' && c.name) {
      emit('completed', [{
        communityId: c.communityId, level: c.level, edgeType: c.edgeType,
        name: c.name, summary: c.summary || '',
        mermaid: c.mermaid, plantuml: c.plantuml,
      }])
    }
  }
}

onMounted(async () => {
  console.log(`[CommunityAI] onMounted ENTRY taskId=${props.taskId} projectId=${props.projectId}`)
  loading.value = true
  loadError.value = null
  try {
    await reportStore.loadCommunities(props.taskId, pid.value!)
    updateAvailableLevels()
    console.log(`[CommunityAI] onMounted availableLevels=${availableLevels.value.map(l=>l.lv+'('+l.count+')').join(',')} selectedEdgeType=${selectedEdgeType.value} selectedLevel=${selectedLevel.value}`)
    if (availableLevels.value.length === 0) {
      selectedEdgeType.value = 'INCLUDE'
      selectedLevel.value = 'L0'
    }
  } catch (e: any) {
    console.error('[CAP] load error:', e)
    loadError.value = e?.message || String(e)
  } finally {
    loading.value = false
    console.log(`[CommunityAI] onMounted DONE taskState.communities=${taskState.value?.communities?.length ?? 0}`)
  }
})
</script>

<template>
  <div class="community-analysis-pipeline">
    <div class="cap-header">
      <div class="cap-title-row">
        <FunnelIcon class="w-3.5 h-3.5 icon-funnel" />
        <span class="cap-title">{{ t('report.pipeline.communityAnalysis') }}</span>
        <span class="cap-stats">{{ completedCount }}/{{ totalCount }}</span>
      </div>
      <div class="cap-progress">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: overallProgress + '%' }" />
        </div>
        <span class="progress-text">{{ overallProgress }}%</span>
      </div>
    </div>

    <div v-if="loading" class="cap-loading">{{ t('common.loading') }}...</div>
    <div v-else-if="loadError" class="cap-error">{{ loadError }}</div>

    <template v-else>
      <div class="et-tabs">
        <button
          v-for="et in edgeTypeOptions"
          :key="et.type"
          :class="['et-tab', { active: selectedEdgeType === et.type }]"
          @click="switchEdgeType(et.type)"
        >
          {{ et.label }}
        </button>
      </div>

      <div class="lv-selector">
        <span class="lv-label">{{ t('report.pipeline.granularity') }}:</span>
        <div class="lv-radio-group">
          <label class="lv-radio active">
            <span class="lv-text">L0</span>
          </label>
        </div>
      </div>

      <div class="clist-search">
        <input v-model="searchQuery" type="text" placeholder="搜索组件名称/ID..." class="search-input">
      </div>

      <div class="cap-tasklist">
        <div v-if="searchedCommunities.length === 0" class="cap-empty">{{ t('report.pipeline.noCommunities') }}</div>

        <template v-else>
          <div class="clist-header">
            <span class="clist-title">
              {{ selectedLevel }} ({{ searchedCommunities.length }})
              <span class="clist-edge-tag">{{ selectedEdgeType }}</span>
            </span>
            <div class="clist-actions">
              <button class="btn btn-ghost btn-xs" :disabled="taskState?.communityRunning" @click="reportStore.selectIncomplete(props.taskId)">
                {{ t('common.selectIncomplete') }}
              </button>
              <button class="btn btn-ghost btn-xs" :disabled="taskState?.communityRunning" @click="reportStore.deselectAll(props.taskId)">
                {{ t('common.reset') }}
              </button>
            </div>
          </div>

          <div class="clist-table">
            <div class="clist-row clist-th">
              <span class="clist-check" />
              <span class="clist-id sortable" @click="sortBy('name')">
                {{ t('report.pipeline.communityId') }}
                <span class="sort-icon">{{ sortIcon('name') }}</span>
              </span>
              <span class="clist-nodes sortable" @click="sortBy('nodeCount')">
                {{ t('report.pipeline.nodes') }}
                <span class="sort-icon">{{ sortIcon('nodeCount') }}</span>
              </span>
              <span class="clist-edges sortable" @click="sortBy('edgeCount')">
                {{ t('report.pipeline.edges') }}
                <span class="sort-icon">{{ sortIcon('edgeCount') }}</span>
              </span>
              <span class="clist-score sortable" @click="sortBy('qualityScore')">
                {{ t('report.pipeline.quality') }}
                <span class="sort-icon">{{ sortIcon('qualityScore') }}</span>
              </span>
              <span class="clist-parent sortable" @click="sortBy('parentName')">
                {{ t('report.pipeline.parentComm') }}
                <span class="sort-icon">{{ sortIcon('parentName') }}</span>
              </span>
              <span class="clist-status sortable" @click="sortBy('status')">
                {{ t('common.status') }}
                <span class="sort-icon">{{ sortIcon('status') }}</span>
              </span>
              <span class="clist-actions-col" />
            </div>

            <div
              v-for="task in pagedCommunities"
              :key="task.id"
              :class="['clist-row', `clist-${task.status}`]"
              @click="toggleSelect(task.id)"
            >
              <span class="clist-check" @click.stop="toggleSelect(task.id)">
                <input type="checkbox" :checked="task.selected" class="clist-cb">
              </span>
              <span class="clist-id" :title="task.communityId">
                <span class="id-text">{{ fmtCommId(task.communityId) }}</span>
                <span
                  v-if="task.name && task.status === 'completed'"
                  class="id-name clickable"
                  @click.stop="emit('viewCommunityMD', { communityId: task.communityId, name: task.name, summary: task.summary || '', mermaid: task.mermaid, plantuml: task.plantuml })"
                >{{ task.name }}</span>
                <span v-else-if="task.name" class="id-name">{{ task.name }}</span>
              </span>
              <span class="clist-nodes">{{ task.nodeCount }}</span>
              <span class="clist-edges">{{ task.edgeCount }}</span>
              <span class="clist-score">
                <span v-if="task.qualityScore != null" class="score-val">{{ task.qualityScore.toFixed(3) }}</span>
                <span v-else class="score-na">—</span>
              </span>
              <span class="clist-parent" :title="task.parentName || task.parentId">
                <span v-if="task.parentName" class="parent-name">{{ task.parentName }}</span>
                <span v-else-if="task.parentId" class="parent-id">{{ task.parentId.length > 12 ? task.parentId.slice(0,12)+'…' : task.parentId }}</span>
                <span v-else class="parent-na">—</span>
              </span>
              <span class="clist-status">
                <span :class="['badge', statusBadgeClass(task.status)]">{{ statusLabel(task.status) }}</span>
              </span>
              <span class="clist-actions-col" @click.stop>
                <button
                  v-if="task.status === 'error'"
                  class="btn btn-ghost btn-xs"
                  :title="t('common.retry')"
                  @click="retryTask(task.id)"
                >
                  <ArrowPathIcon class="w-3 h-3" />
                </button>
              </span>
            </div>
          </div>

          <div v-if="totalPages > 1" class="clist-pagination">
            <button class="btn btn-ghost btn-xs" :disabled="currentPage <= 1" @click="currentPage--">上一页</button>
            <span class="page-info">{{ currentPage }} / {{ totalPages }}</span>
            <button class="btn btn-ghost btn-xs" :disabled="currentPage >= totalPages" @click="currentPage++">下一页</button>
          </div>
        </template>
      </div>

      <div class="cap-bottom">
        <div class="cap-batch">
          <span class="batch-label">{{ t('report.pipeline.batchSize') }}:</span>
          <select v-model.number="batchSize" class="batch-select" :disabled="taskState?.communityRunning">
            <option v-for="n in [1,2,3,5,10]" :key="n" :value="n">{{ n }}</option>
          </select>
        </div>
        <div class="cap-bottom-actions">
          <button v-if="taskState?.communityRunning" class="btn btn-error btn-sm" @click="reportStore.stopAnalysis(props.taskId)">
            <StopIcon class="w-3 h-3" />
            {{ t('common.stop') }}
          </button>
          <button
            class="btn btn-primary btn-sm"
            :disabled="selectedCount === 0 || taskState?.communityRunning"
            @click="startAnalysis"
          >
            <PlayIcon class="w-3 h-3" />
            {{ t('report.pipeline.analyzeSelected', { n: selectedCount }) }}
          </button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.community-analysis-pipeline {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-secondary);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  font-size: 12px;
}
.cap-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px; border-bottom: 1px solid var(--border); background: var(--bg-tertiary);
}
.cap-title-row { display: flex; align-items: center; gap: 6px; }
.icon-funnel { color: var(--text-muted); }
.cap-title { font-weight: 600; color: var(--text-primary); }
.cap-stats { font-size: 10px; color: var(--text-muted); font-family: var(--font-mono); }
.cap-progress { display: flex; align-items: center; gap: 6px; }
.progress-bar { width: 80px; height: 5px; background: var(--bg-primary); border-radius: 3px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.3s; }
.progress-text { font-size: 9px; color: var(--text-muted); font-family: var(--font-mono); min-width: 24px; }
.cap-loading { padding: 20px; text-align: center; color: var(--text-muted); }
.cap-error { padding: 20px; text-align: center; color: var(--error); font-size: 11px; }
.et-tabs {
  display: flex; border-bottom: 1px solid var(--border); padding: 0 12px; gap: 0;
}
.et-tab {
  flex: 1; padding: 6px 12px; text-align: center; font-size: 11px; font-weight: 500;
  color: var(--text-muted); background: transparent; border: none; cursor: pointer;
  border-bottom: 2px solid transparent; transition: all 0.15s;
}
.et-tab:hover { color: var(--text-primary); background: var(--bg-tertiary); }
.et-tab.active { color: var(--accent); border-bottom-color: var(--accent); }
.lv-selector {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 12px; border-bottom: 1px solid var(--border); background: var(--bg-tertiary);
}
.lv-label { font-size: 10px; color: var(--text-muted); white-space: nowrap; }
.lv-radio-group { display: flex; gap: 4px; }
.lv-radio {
  display: flex; align-items: center; gap: 4px;
  padding: 2px 8px; border-radius: 4px; cursor: pointer;
  border: 1px solid var(--border); background: var(--bg-primary);
  transition: all 0.15s;
}
.lv-radio:hover { border-color: var(--accent); }
.lv-radio.active { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 10%, transparent); }
.lv-radio input { display: none; }
.lv-text { font-size: 11px; font-weight: 600; color: var(--text-primary); }
.cap-tasklist { flex: 1; overflow-y: auto; max-height: 360px; }
.cap-empty { padding: 20px; text-align: center; color: var(--text-muted); font-size: 11px; }
.clist-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 12px; border-bottom: 1px solid var(--border);
}
.clist-title { font-size: 11px; font-weight: 600; color: var(--text-secondary); display: flex; align-items: center; gap: 6px; }
.clist-edge-tag { font-size: 8px; padding: 0 4px; border-radius: 3px; background: var(--bg-tertiary); color: var(--text-muted); }
.clist-table { display: flex; flex-direction: column; gap: 1px; padding: 0 12px 4px; }
.clist-row {
  display: grid;
  grid-template-columns: 24px 1fr 48px 48px 52px 1fr 60px 28px;
  align-items: center;
  padding: 3px 4px;
  border-radius: 4px;
  cursor: pointer;
  gap: 4px;
  font-size: 10px;
  transition: background 0.1s;
}
.clist-row:hover { background: var(--bg-tertiary); }
.clist-th {
  font-weight: 600; color: var(--text-muted); font-size: 9px; cursor: default;
  padding: 4px; border-bottom: 1px solid var(--border); margin-bottom: 2px;
}
.clist-th:hover { background: transparent; }
.clist-check { display: flex; align-items: center; }
.clist-cb { accent-color: var(--accent); width: 12px; height: 12px; }
.clist-id { display: flex; flex-direction: column; overflow: hidden; min-width: 0; }
.id-text { color: var(--text-primary); font-family: var(--font-mono); font-size: 9px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.id-name { color: var(--text-secondary); font-size: 9px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.id-name.clickable { cursor: pointer; text-decoration: underline; text-decoration-style: dotted; text-underline-offset: 2px; }
.id-name.clickable:hover { color: var(--accent); }
.clist-nodes, .clist-edges, .clist-score { text-align: right; font-family: var(--font-mono); color: var(--text-primary); }
.score-val { color: var(--text-secondary); }
.score-na { color: var(--text-muted); }
.clist-parent { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 0 4px; }
.parent-name { color: var(--text-secondary); font-size: 9px; }
.parent-id { color: var(--text-muted); font-family: var(--font-mono); font-size: 8px; }
.parent-na { color: var(--text-muted); }
.clist-status { display: flex; justify-content: center; }
.sortable { cursor: pointer; user-select: none; display: flex; align-items: center; gap: 2px; }
.sortable:hover { color: var(--text-primary); }
.sort-icon { font-size: 7px; color: var(--accent); font-family: var(--font-mono); }
.badge {
  font-size: 8px; padding: 1px 5px; border-radius: 4px; font-weight: 500; white-space: nowrap;
}
.badge-success { background: color-mix(in srgb, var(--success) 15%, transparent); color: var(--success); }
.badge-info { background: color-mix(in srgb, var(--accent) 15%, transparent); color: var(--accent); }
.badge-error { background: color-mix(in srgb, var(--error) 15%, transparent); color: var(--error); }
.badge-muted { background: var(--bg-tertiary); color: var(--text-muted); }
.clist-actions-col { display: flex; justify-content: center; }
.clist-search { padding: 6px 12px; border-bottom: 1px solid var(--border); }
.search-input {
  width: 100%; padding: 4px 8px; font-size: 11px; border: 1px solid var(--border);
  border-radius: 4px; background: var(--bg-primary); color: var(--text-primary); outline: none;
  box-sizing: border-box;
}
.search-input:focus { border-color: var(--accent); }
.clist-pagination {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  padding: 6px 12px; border-top: 1px solid var(--border);
}
.page-info { font-size: 10px; color: var(--text-muted); font-family: var(--font-mono); }
.cap-bottom {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px; border-top: 1px solid var(--border); background: var(--bg-tertiary);
}
.cap-batch { display: flex; align-items: center; gap: 4px; }
.batch-label { font-size: 10px; color: var(--text-muted); }
.batch-select { font-size: 10px; padding: 2px 4px; border: 1px solid var(--border); border-radius: 4px; background: var(--bg-primary); color: var(--text-primary); }
.cap-bottom-actions { display: flex; gap: 4px; }
</style>
