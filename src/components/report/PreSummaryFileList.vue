<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCommunityStore } from '@/stores/community-store'
import { useProjectStore } from '@/stores/project'
import PreSummaryDetailDialog from './PreSummaryDetailDialog.vue'

const { t } = useI18n()
const communityStore = useCommunityStore()
const projectStore = useProjectStore()

const props = defineProps<{
  taskId: string
}>()

const projectName = computed(() => projectStore.selectedProject?.name || '')
const taskName = computed(() => {
  const tab = projectStore.activeTab
  if (tab?.title) return tab.title
  return props.taskId || ''
})

const BATCHES = ['P0', 'P1', 'P2', 'P4'] as const
type Batch = typeof BATCHES[number]

const activeBatch = ref<Batch>('P0')
const currentPage = ref(1)
const pageSize = 20
const totalFiles = ref(0)
const files = ref<Array<{
  file_path: string; score: number; cross: number; edges: number; size: number;
  is_large: number; quality: number; batch: string
}>>([])
const loading = ref(false)
const searchQuery = ref('')

// Detail dialog state
const showDetail = ref(false)
const detailFilePath = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(totalFiles.value / pageSize)))

const cacheStats = computed(() => {
  const cached = files.value.filter(f => f.has_summary).length
  return { total: files.value.length, cached }
})

let searchTimer: ReturnType<typeof setTimeout> | null = null

async function loadFiles() {
  loading.value = true
  try {
    const resp = await communityStore.listPreSummaryFiles(props.taskId, activeBatch.value, currentPage.value, pageSize)
    if (resp) {
      files.value = resp.files || []
      totalFiles.value = resp.total || 0
    }
  } catch { /* ignore */ }
  finally { loading.value = false }
}

function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    currentPage.value = 1
    loadFiles()
  }, 300)
}

function prevPage() {
  if (currentPage.value > 1) { currentPage.value--; loadFiles() }
}
function nextPage() {
  if (currentPage.value < totalPages.value) { currentPage.value++; loadFiles() }
}
function switchBatch(batch: Batch) {
  activeBatch.value = batch
  currentPage.value = 1
  loadFiles()
}

function openDetail(filePath: string) {
  detailFilePath.value = filePath
  showDetail.value = true
}

function onDetailDeleted() {
  showDetail.value = false
  loadFiles()
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + 'MB'
  if (bytes >= 1024) return (bytes / 1024).toFixed(0) + 'KB'
  return bytes + 'B'
}

const filteredFiles = computed(() => {
  if (!searchQuery.value.trim()) return files.value
  const q = searchQuery.value.trim().toLowerCase()
  return files.value.filter(f => f.file_path.toLowerCase().includes(q))
})

onMounted(loadFiles)
watch(() => props.taskId, loadFiles)
</script>

<template>
  <div class="presummary-file-list">
    <span
      v-if="false"
      class="cmp-id"
    >RP-003</span>

    <!-- 项目/任务标识 -->
    <div class="ps-context-bar">
      <span class="ps-context-project">{{ projectName }}</span>
      <span class="ps-context-sep">/</span>
      <span class="ps-context-task">{{ taskName }}</span>
      <span class="ps-context-id">({{ props.taskId.slice(0, 8) }}…)</span>
    </div>

    <!-- Toolbar -->
    <div class="ps-toolbar">
      <div class="ps-batch-tabs">
        <button
          v-for="b in BATCHES"
          :key="b"
          class="ps-batch-tab"
          :class="{ 'ps-batch-active': activeBatch === b }"
          @click="switchBatch(b)"
        >{{ t(`report.preSummaryBatch${b}`) }}</button>
      </div>
      <div class="ps-spacer" />
      <div class="ps-search">
        <input
          v-model="searchQuery"
          class="ps-search-input"
          :placeholder="t('report.preSummarySearch')"
          @input="onSearchInput"
        />
      </div>
    </div>

    <!-- Stats bar -->
    <div class="ps-stats-bar">
      <span class="ps-stat">{{ t('report.preSummaryTotal') }}: {{ totalFiles }}</span>
      <span class="ps-stat-sep">|</span>
      <span class="ps-stat">{{ t('report.preSummaryCached') }}: {{ cacheStats.cached }}/{{ cacheStats.total }}</span>
      <span class="ps-stat-sep">|</span>
      <span class="ps-stat">{{ t('report.preSummaryPage', { current: currentPage, total: totalPages }) }}</span>
    </div>

    <!-- File table -->
    <div class="ps-table-wrap">
      <table
        v-if="filteredFiles.length > 0"
        class="ps-table"
      >
        <thead>
          <tr>
            <th class="ps-col-path">{{ t('file.filePath') || '文件路径' }}</th>
            <th class="ps-col-num">{{ t('report.preSummaryScore') }}</th>
            <th class="ps-col-num">{{ t('report.preSummarySize') }}</th>
            <th class="ps-col-status">{{ t('report.preSummaryCachedLabel') }}</th>
            <th class="ps-col-action">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="f in filteredFiles"
            :key="f.file_path"
            class="ps-row"
            @click="openDetail(f.file_path)"
          >
            <td class="ps-cell-path">
              <span class="ps-path-text">{{ f.file_path }}</span>
            </td>
            <td class="ps-cell-num">{{ f.score?.toFixed(1) ?? '-' }}</td>
            <td class="ps-cell-num">{{ formatSize(f.size) }}</td>
            <td class="ps-cell-status">
              <span
                v-if="f.has_summary"
                class="ps-cached-badge"
              >{{ t('report.preSummaryCachedLabel') }}</span>
              <span
                v-else
                class="ps-uncached-badge"
              >{{ t('report.preSummaryNotCached') }}</span>
            </td>
            <td class="ps-cell-action">
              <button
                class="ps-delete-btn"
                :title="t('report.preSummaryDelete')"
                @click.stop="openDetail(f.file_path)"
              >{{ t('report.preSummaryViewDetails') || '详情' }}</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div
        v-else-if="!loading"
        class="ps-empty"
      >{{ t('report.preSummaryNoFiles') }}</div>
      <div
        v-else
        class="ps-empty ps-loading"
      >{{ t('common.loading') }}</div>
    </div>

    <!-- Pagination -->
    <div class="ps-pagination">
      <button
        class="ps-page-btn"
        :disabled="currentPage <= 1"
        @click="prevPage"
      >◀</button>
      <span class="ps-page-info">{{ t('report.preSummaryPage', { current: currentPage, total: totalPages }) }}</span>
      <button
        class="ps-page-btn"
        :disabled="currentPage >= totalPages"
        @click="nextPage"
      >▶</button>
    </div>

    <!-- Detail dialog -->
    <PreSummaryDetailDialog
      v-if="showDetail"
      :task-id="props.taskId"
      :file-path="detailFilePath"
      @close="showDetail = false"
      @deleted="onDetailDeleted"
    />
  </div>
</template>

<style scoped>
.presummary-file-list {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 16px 20px;
  overflow: hidden;
}

.ps-context-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 10px;
  padding: 6px 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 11px;
  flex-shrink: 0;
}
.ps-context-project {
  font-weight: 600;
  color: var(--text-primary);
}
.ps-context-sep {
  color: var(--text-muted);
  margin: 0 2px;
}
.ps-context-task {
  color: var(--text-secondary);
}
.ps-context-id {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 9px;
}

.ps-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-shrink: 0;
}

.ps-batch-tabs {
  display: flex;
  gap: 4px;
}

.ps-batch-tab {
  padding: 3px 12px;
  font-size: 11px;
  font-weight: 500;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-secondary);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}

.ps-batch-tab:hover {
  border-color: var(--accent);
  color: var(--text-primary);
}

.ps-batch-active {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

.ps-spacer {
  flex: 1;
}

.ps-search-input {
  width: 220px;
  padding: 4px 8px;
  font-size: 11px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-primary);
  color: var(--text-primary);
  outline: none;
}

.ps-search-input:focus {
  border-color: var(--accent);
}

.ps-stats-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  color: var(--text-muted);
  margin-bottom: 8px;
  flex-shrink: 0;
}

.ps-stat-sep {
  opacity: 0.4;
}

.ps-table-wrap {
  flex: 1;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 6px;
}

.ps-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}

.ps-table th {
  position: sticky;
  top: 0;
  background: var(--bg-tertiary);
  color: var(--text-muted);
  font-weight: 500;
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

.ps-table td {
  padding: 5px 8px;
  border-bottom: 1px solid var(--border);
  color: var(--text-primary);
}

.ps-row {
  cursor: pointer;
  transition: background 0.1s;
}

.ps-row:hover {
  background: var(--bg-hover);
}

.ps-col-path {
  min-width: 200px;
}

.ps-col-num {
  width: 50px;
  text-align: right;
}

.ps-col-status {
  width: 70px;
  text-align: center;
}

.ps-col-action {
  width: 56px;
  text-align: center;
}

.ps-cell-path {
  font-family: var(--font-mono);
  font-size: 10px;
  max-width: 400px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ps-path-text {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ps-cell-num {
  text-align: right;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-secondary);
}

.ps-cached-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 9px;
  background: color-mix(in srgb, var(--success) 15%, transparent);
  color: var(--success);
  border: 1px solid color-mix(in srgb, var(--success) 30%, transparent);
}

.ps-uncached-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 9px;
  background: var(--bg-tertiary);
  color: var(--text-muted);
  border: 1px solid var(--border);
}

.ps-delete-btn {
  padding: 1px 6px;
  font-size: 9px;
  border: 1px solid var(--border);
  border-radius: 3px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}

.ps-delete-btn:hover {
  border-color: var(--error);
  color: var(--error);
}

.ps-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  font-size: 12px;
  color: var(--text-muted);
}

.ps-loading {
  opacity: 0.6;
}

.ps-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 0;
  flex-shrink: 0;
}

.ps-page-btn {
  padding: 2px 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  cursor: pointer;
  font-size: 11px;
  transition: all 0.15s;
}

.ps-page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.ps-page-btn:hover:not(:disabled) {
  border-color: var(--accent);
}

.ps-page-info {
  font-size: 10px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}
</style>
