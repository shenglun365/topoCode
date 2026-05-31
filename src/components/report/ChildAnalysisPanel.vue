<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useProjectStore } from '@/stores/project'
import { useSettingsStore } from '@/stores/settings'
import {
  PlayIcon,
  StopIcon,
  ArrowPathIcon,
} from '@heroicons/vue/24/outline'
import { useReportStore } from '@/stores/report'

const { t } = useI18n()
const projectStore = useProjectStore()
const settingsStore = useSettingsStore()
const reportStore = useReportStore()

const props = defineProps<{
  taskId: string
  parentLevel: string
  parentCommId: string
  edgeType: string
  projectId?: string
}>()

const emit = defineEmits<{
  viewCommunityMD: [params: {
    communityId: string
    level: string
    edgeType: string
    parentLevel?: string
    parentCommId?: string
    name: string
    summary: string
    mermaid?: string
    plantuml?: string
  }]
}>()

const stateKey = computed(() => reportStore.buildChildStateKey(props.parentLevel, props.parentCommId, props.edgeType))
const childLevel = computed(() => `L${parseInt(props.parentLevel[1]) + 1}`)

const modelId = computed(() => settingsStore.models.find(m => m.isDefault)?.id)
const pid = computed(() => props.projectId || projectStore.selectedProjectId)

const childState = computed(() => reportStore.tasks[props.taskId]?.analysisStates[stateKey.value])

const loading = ref(true)
const loadError = ref<string | null>(null)
const batchSize = ref(3)
const searchQuery = ref('')
const currentPage = ref(1)
const pageSize = 100

const communities = computed(() => childState.value?.communities || [])

const searchedCommunities = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return communities.value
  return communities.value.filter(c => {
    const id = fmtCommId(c.communityId).toLowerCase()
    const name = (c.name || '').toLowerCase()
    return id.includes(q) || name.includes(q)
  })
})

const totalPages = computed(() => Math.max(1, Math.ceil(searchedCommunities.value.length / pageSize)))
const pagedCommunities = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return searchedCommunities.value.slice(start, start + pageSize)
})

watch(searchQuery, () => { currentPage.value = 1 })

const selectedCount = computed(() => communities.value.filter(c => c.selected).length)
const completedCount = computed(() => communities.value.filter(c => c.status === 'completed').length)
const errorCount = computed(() => communities.value.filter(c => c.status === 'error').length)
const totalCount = computed(() => communities.value.length)

const overallProgress = computed(() => {
  const done = completedCount.value + errorCount.value
  return totalCount.value > 0 ? Math.round((done / totalCount.value) * 100) : 0
})

const isRunning = computed(() => childState.value?.running || false)
const isPaused = computed(() => childState.value?.paused || false)
const errorLogs = computed(() => childState.value?.errorLogs || [])

function fmtCommId(id: string): string {
  return id.replace(/^comm-[^-]+-/, '')
}

function toggleSelect(commId: string) {
  reportStore.toggleChildSelect(props.taskId, stateKey.value, commId)
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
  if (!modelId.value || !pid.value) return
  await reportStore.analyzeChildSelected(props.taskId, stateKey.value, modelId.value, batchSize.value, pid.value)
}

async function retryTask(commId: string) {
  if (!modelId.value || !pid.value) return
  await reportStore.retryChildTask(props.taskId, stateKey.value, commId, modelId.value, pid.value)
}

function stopAnalysis() {
  reportStore.stopChildAnalysis(props.taskId, stateKey.value)
}

function viewMD(community: any) {
  emit('viewCommunityMD', {
    communityId: community.communityId,
    level: community.level,
    edgeType: community.edgeType,
    parentLevel: childLevel.value,
    parentCommId: community.communityId,
    name: community.name || fmtCommId(community.communityId),
    summary: community.summary || '',
    mermaid: community.mermaid,
    plantuml: community.plantuml,
  })
}

onMounted(async () => {
  loading.value = true
  loadError.value = null
  try {
    await reportStore.loadChildCommunities(props.taskId, props.parentLevel, props.parentCommId, props.edgeType)
  } catch (e: any) {
    loadError.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="child-analysis-panel">
    <div class="cap-header">
      <div class="cap-title-row">
        <span class="cap-title">{{ childLevel }} {{ t('report.pipeline.childAnalysis') }}</span>
        <span class="cap-edge-tag">{{ props.edgeType }}</span>
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
      <div class="clist-search">
        <input v-model="searchQuery" type="text" :placeholder="t('common.search')" class="search-input">
      </div>

      <div class="cap-tasklist">
        <div v-if="searchedCommunities.length === 0" class="cap-empty">{{ t('report.pipeline.noCommunities') }}</div>

        <template v-else>
          <div class="clist-header">
            <span class="clist-title">
              {{ childLevel }} ({{ searchedCommunities.length }})
            </span>
            <div class="clist-actions">
              <button class="btn btn-ghost btn-xs" :disabled="isRunning" @click="reportStore.selectChildIncomplete(props.taskId, stateKey)">
                {{ t('common.selectIncomplete') }}
              </button>
              <button class="btn btn-ghost btn-xs" :disabled="isRunning" @click="reportStore.deselectAllChild(props.taskId, stateKey)">
                {{ t('common.reset') }}
              </button>
            </div>
          </div>

          <div class="clist-table">
            <div class="clist-row clist-th">
              <span class="clist-check" />
              <span class="clist-id">{{ t('report.pipeline.communityId') }}</span>
              <span class="clist-nodes">{{ t('report.pipeline.nodes') }}</span>
              <span class="clist-edges">{{ t('report.pipeline.edges') }}</span>
              <span class="clist-score">{{ t('report.pipeline.quality') }}</span>
              <span class="clist-status">{{ t('common.status') }}</span>
              <span class="clist-actions-col" />
            </div>

            <div
              v-for="task in pagedCommunities"
              :key="task.id"
              :class="['clist-row', `clist-${task.status}`]"
              @click="toggleSelect(task.communityId)"
            >
              <span class="clist-check" @click.stop="toggleSelect(task.communityId)">
                <input type="checkbox" :checked="task.selected" class="clist-cb">
              </span>
              <span class="clist-id" :title="task.communityId">
                <span class="id-text">{{ fmtCommId(task.communityId) }}</span>
                <span
                  v-if="task.name && task.status === 'completed'"
                  class="id-name clickable"
                  @click.stop="viewMD(task)"
                >{{ task.name }}</span>
                <span v-else-if="task.name" class="id-name">{{ task.name }}</span>
              </span>
              <span class="clist-nodes">{{ task.nodeCount }}</span>
              <span class="clist-edges">{{ task.edgeCount }}</span>
              <span class="clist-score">
                <span v-if="task.qualityScore != null" class="score-val">{{ task.qualityScore.toFixed(3) }}</span>
                <span v-else class="score-na">&mdash;</span>
              </span>
              <span class="clist-status">
                <span :class="['badge', statusBadgeClass(task.status)]">{{ statusLabel(task.status) }}</span>
              </span>
              <span class="clist-actions-col" @click.stop>
                <button
                  v-if="task.status === 'error'"
                  class="btn btn-ghost btn-xs"
                  :title="t('common.retry')"
                  @click="retryTask(task.communityId)"
                >
                  <ArrowPathIcon class="w-3 h-3" />
                </button>
              </span>
            </div>
          </div>

          <div v-if="totalPages > 1" class="clist-pagination">
            <button class="btn btn-ghost btn-xs" :disabled="currentPage <= 1" @click="currentPage--">{{ t('common.prev') }}</button>
            <span class="page-info">{{ currentPage }} / {{ totalPages }}</span>
            <button class="btn btn-ghost btn-xs" :disabled="currentPage >= totalPages" @click="currentPage++">{{ t('common.next') }}</button>
          </div>
        </template>
      </div>

      <div v-if="errorLogs.length > 0" class="cap-error-logs">
        <div class="error-log-header">
          <span class="error-log-title">{{ t('common.error') }} ({{ errorLogs.length }})</span>
          <button class="btn btn-ghost btn-xs" @click="reportStore.clearChildErrorLogs(props.taskId, stateKey)">{{ t('common.clear') }}</button>
        </div>
        <div v-for="(msg, i) in errorLogs.slice(0, 10)" :key="i" class="error-log-item">{{ msg }}</div>
      </div>

      <div class="cap-bottom">
        <div class="cap-batch">
          <span class="batch-label">{{ t('report.pipeline.batchSize') }}:</span>
          <select v-model.number="batchSize" class="batch-select" :disabled="isRunning">
            <option v-for="n in [1,2,3,5,10]" :key="n" :value="n">{{ n }}</option>
          </select>
        </div>
        <div class="cap-bottom-actions">
          <button v-if="isRunning" class="btn btn-error btn-sm" @click="stopAnalysis">
            <StopIcon class="w-3 h-3" />
            {{ t('common.stop') }}
          </button>
          <button
            class="btn btn-primary btn-sm"
            :disabled="selectedCount === 0 || isRunning"
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
.child-analysis-panel {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-secondary);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  font-size: 12px;
  height: 100%;
}
.cap-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px; border-bottom: 1px solid var(--border); background: var(--bg-tertiary);
}
.cap-title-row { display: flex; align-items: center; gap: 6px; }
.cap-title { font-weight: 600; color: var(--text-primary); }
.cap-edge-tag { font-size: 8px; padding: 0 4px; border-radius: 3px; background: var(--bg-primary); color: var(--text-muted); font-family: var(--font-mono); }
.cap-stats { font-size: 10px; color: var(--text-muted); font-family: var(--font-mono); }
.cap-progress { display: flex; align-items: center; gap: 6px; }
.progress-bar { width: 80px; height: 5px; background: var(--bg-primary); border-radius: 3px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.3s; }
.progress-text { font-size: 9px; color: var(--text-muted); font-family: var(--font-mono); min-width: 24px; }
.cap-loading { padding: 20px; text-align: center; color: var(--text-muted); }
.cap-error { padding: 20px; text-align: center; color: var(--error); font-size: 11px; }
.clist-search { padding: 6px 12px; border-bottom: 1px solid var(--border); }
.search-input {
  width: 100%; padding: 4px 8px; font-size: 11px; border: 1px solid var(--border);
  border-radius: 4px; background: var(--bg-primary); color: var(--text-primary); outline: none;
  box-sizing: border-box;
}
.search-input:focus { border-color: var(--accent); }
.cap-tasklist { flex: 1; overflow-y: auto; }
.cap-empty { padding: 20px; text-align: center; color: var(--text-muted); font-size: 11px; }
.clist-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 12px; border-bottom: 1px solid var(--border);
}
.clist-title { font-size: 11px; font-weight: 600; color: var(--text-secondary); display: flex; align-items: center; gap: 6px; }
.clist-table { display: flex; flex-direction: column; gap: 1px; padding: 0 12px 4px; }
.clist-row {
  display: grid;
  grid-template-columns: 24px 1fr 48px 48px 52px 60px 28px;
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
.clist-status { display: flex; justify-content: center; }
.badge {
  font-size: 8px; padding: 1px 5px; border-radius: 4px; font-weight: 500; white-space: nowrap;
}
.badge-success { background: color-mix(in srgb, var(--success) 15%, transparent); color: var(--success); }
.badge-info { background: color-mix(in srgb, var(--accent) 15%, transparent); color: var(--accent); }
.badge-error { background: color-mix(in srgb, var(--error) 15%, transparent); color: var(--error); }
.badge-muted { background: var(--bg-tertiary); color: var(--text-muted); }
.clist-actions-col { display: flex; justify-content: center; }
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
.cap-error-logs {
  border-top: 1px solid var(--border);
  padding: 6px 12px;
  max-height: 120px;
  overflow-y: auto;
}
.error-log-header {
  display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;
}
.error-log-title { font-size: 10px; font-weight: 600; color: var(--error); }
.error-log-item {
  font-size: 9px; color: var(--error); font-family: var(--font-mono);
  padding: 2px 0; border-bottom: 1px solid color-mix(in srgb, var(--border) 50%, transparent);
  word-break: break-all;
}
</style>
