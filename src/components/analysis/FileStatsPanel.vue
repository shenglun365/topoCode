<script setup lang="ts">
import { ref, watch, computed, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DocumentTextIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'
import { useAnalysisStore } from '@/stores/analysis'
import type { FileStatsResult, DirTreeNode } from '@/types/ipc'
import DirTreeNodeComponent from './DirTreeNodeComponent.vue'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('AN-005')
const props = defineProps<{
  projectId: string
  scope: string
  patternType: 'all' | 'glob' | 'regex'
  pattern: string
  excludeDirs: string[]
  selectedScopes?: string[]
  selectedExtensions?: string[]
}>()

const emit = defineEmits<{
  'update:scope': [val: string]
  'update:patternType': [val: 'all' | 'glob' | 'regex']
  'update:pattern': [val: string]
  'suggestExtensions': [exts: string[]]
  'update:selectedScopes': [val: string[]]
  'update:selectedExtensions': [val: string[]]
}>()

const { t } = useI18n()
const analysisStore = useAnalysisStore()

const stats = ref<FileStatsResult | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

// Directory multi-select (tree structure)
const selectedScopes = ref<string[]>(props.selectedScopes ? [...props.selectedScopes] : [])
const expandedDirs = ref<Set<string>>(new Set())
const dirTreeRef = ref<HTMLElement | null>(null)

// File type multi-select
const selectedExtensions = ref<string[]>(props.selectedExtensions ? [...props.selectedExtensions] : [])

// Compute max count for bar chart
const maxCount = computed(() => {
  if (!stats.value || !stats.value.extensions) return 1
  return Math.max(...Object.values(stats.value.extensions), 1)
})

/**
 * 获取所有子目录的路径
 */
function getAllChildPaths(node: DirTreeNode): string[] {
  const paths: string[] = []
  if (node.children) {
    for (const child of node.children) {
      paths.push(child.path)
      paths.push(...getAllChildPaths(child))
    }
  }
  return paths
}

/**
 * 切换目录选择（使用 glob 模式，不枚举子目录）
 */
function handleDirToggle(node: DirTreeNode) {
  const action = (node as any).__action
  let paths = (node as any).__paths
  
  if (action === 'select') {
    const existing = new Set(selectedScopes.value)
    for (const p of paths) {
      // 清除该路径下已存在的精确子路径，避免冗余
      for (const ep of [...existing]) {
        if (ep.startsWith(p.replace('/*', '') + '/')) existing.delete(ep)
      }
      existing.add(p)
    }
    selectedScopes.value = Array.from(existing)
  } else if (action === 'deselect') {
    // 移除路径及其所有子路径和 glob 模式
    const removeSet = new Set(paths)
    selectedScopes.value = selectedScopes.value.filter(p => {
      for (const r of removeSet) {
        const prefix = r.replace('/*', '')
        if (p === prefix || p.startsWith(prefix + '/') || p === r) return false
      }
      return true
    })
  } else {
    // Legacy: single node toggle
    const idx = selectedScopes.value.indexOf(node.path)
    if (idx >= 0) {
      selectedScopes.value.splice(idx, 1)
    } else {
      selectedScopes.value.push(node.path)
    }
  }
  
  emitSelectedScopes()
}

/**
 * 切换目录展开/折叠
 */
function handleDirExpand(dir: string) {
  if (expandedDirs.value.has(dir)) {
    expandedDirs.value.delete(dir)
  } else {
    expandedDirs.value.add(dir)
  }
}

// 通配符作用域输入
const globScopeInput = ref('')

function addGlobScope() {
  const val = globScopeInput.value.trim()
  if (!val) return
  if (!selectedScopes.value.includes(val)) {
    selectedScopes.value.push(val)
    emitSelectedScopes()
  }
  globScopeInput.value = ''
}

function removeScopeByPath(path: string) {
  const idx = selectedScopes.value.indexOf(path)
  if (idx >= 0) {
    selectedScopes.value.splice(idx, 1)
    emitSelectedScopes()
  }
}

// 从目录树中收集所有顶层路径（使用 glob 模式，不递归子目录避免字符串爆炸）
function collectAllDirPaths(): string[] {
  if (!stats.value?.directories) return []
  const paths: string[] = []
  function collect(nodes: DirTreeNode[], isRoot: boolean) {
    for (const node of nodes) {
      if (isRoot) {
        // 顶层目录使用 glob 模式
        paths.push(node.path + '/*')
      }
      if (node.children) collect(node.children, false)
    }
  }
  collect(stats.value.directories, true)
  return paths
}

// Select all directories
function selectAllDirs() {
  if (!stats.value?.directories) return
  selectedScopes.value = collectAllDirPaths()
  emitSelectedScopes()
}

// Invert directory selection — 选中的取消，没选中的选中
function invertDirs() {
  if (!stats.value?.directories) return
  const allPaths = collectAllDirPaths()
  const selected = new Set(selectedScopes.value)
  // 清除所有已选目录（包括精确路径和子路径）
  const toggled = []
  for (const p of allPaths) {
    const prefix = p.replace('/*', '')
    const anySelected = [...selected].some(s => s === prefix || s === p || s.startsWith(prefix + '/'))
    if (!anySelected) toggled.push(p)
  }
  selectedScopes.value = toggled
  emitSelectedScopes()
}

// Toggle file type selection
function toggleExtension(ext: string) {
  const idx = selectedExtensions.value.indexOf(ext)
  if (idx >= 0) {
    selectedExtensions.value.splice(idx, 1)
  } else {
    selectedExtensions.value.push(ext)
  }
  emitSelectedExtensions()
}

// Select all extensions
function selectAllExtensions() {
  if (stats.value?.extensions) {
    selectedExtensions.value = [...Object.keys(stats.value.extensions)]
  }
  emitSelectedExtensions()
}

// Invert extension selection
function invertExtensions() {
  if (!stats.value?.extensions) return
  const all = Object.keys(stats.value.extensions)
  selectedExtensions.value = all.filter(e => !selectedExtensions.value.includes(e))
  emitSelectedExtensions()
}

// Remove a selected extension
function removeExtension(ext: string) {
  const idx = selectedExtensions.value.indexOf(ext)
  if (idx >= 0) {
    selectedExtensions.value.splice(idx, 1)
  }
  emitSelectedExtensions()
}

/**
 * 格式化扩展名显示：空字符串显示为"无后缀名"
 */
function formatExtension(ext: string): string {
  if (!ext || ext.trim() === '') {
    return t('analysis.noExtension')
  }
  return ext
}

function emitSelectedScopes() {
  emit('update:selectedScopes', [...selectedScopes.value])
}

function emitSelectedExtensions() {
  emit('update:selectedExtensions', [...selectedExtensions.value])
}

// Load stats
async function loadStats() {
  if (!props.projectId) return

  // Save scroll position before reload
  const savedScrollTop = dirTreeRef.value?.scrollTop ?? 0

  loading.value = true
  error.value = null

  try {
    const scopes = selectedScopes.value.length > 0 ? [...selectedScopes.value] : undefined
    const scanOptions = {
      scopes,
      scope: scopes ? undefined : (props.scope || undefined),
      patternType: props.patternType,
      pattern: props.pattern || undefined,
      excludeDirs: props.excludeDirs.length > 0 ? [...props.excludeDirs] : undefined,
      selectedExtensions: selectedExtensions.value.length > 0 ? [...selectedExtensions.value] : undefined,
    }
    const result = await analysisStore.scanFileStats(props.projectId, scanOptions)
    stats.value = result

    // Recommend top 5 extensions
    const exts = Object.keys(result.extensions).slice(0, 5)
    if (exts.length > 0) {
      emit('suggestExtensions', exts)
    }

    // Restore scroll position after DOM update
    await nextTick()
    if (dirTreeRef.value) {
      dirTreeRef.value.scrollTop = savedScrollTop
    }
  } catch (err: any) {
    error.value = err?.message || t('common.loadFailed')
  } finally {
    loading.value = false
  }
}

// Debounced reload for pattern input (typing)
let debounceTimer: ReturnType<typeof setTimeout> | null = null
function debouncedLoadStats() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(loadStats, 300)
}

// Sync local refs with props (编辑模式下父组件异步加载数据后回显)
watch(() => props.selectedScopes, (val) => {
  if (val && val.length > 0) {
    selectedScopes.value = [...val]
  }
})
watch(() => props.selectedExtensions, (val) => {
  if (val && val.length > 0) {
    selectedExtensions.value = [...val]
  }
})

// Track initial load to prevent duplicate requests
let initialLoadDone = false

// Watch pattern input changes — debounced (typing)
watch([() => props.patternType, () => props.pattern, () => props.excludeDirs], () => {
  if (initialLoadDone) debouncedLoadStats()
}, { immediate: false })

// Watch scope/extension selection — immediate refresh (no debounce)
watch([selectedScopes, selectedExtensions], () => {
  if (initialLoadDone) loadStats()
}, { deep: true })

// Initial load
loadStats().then(() => { initialLoadDone = true })
</script>

<template>
  <div class="file-stats-panel">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- Directory tree with checkboxes -->
    <div class="stats-section">
      <div class="section-header">
        <span class="stats-label">{{ t('analysis.directoryScope') }}</span>
        <div class="section-actions">
          <button
            class="text-btn"
            @click="selectAllDirs"
          >
            {{ t('analysis.selectAll') }}
          </button>
          <span class="divider">/</span>
          <button
            class="text-btn"
            @click="invertDirs"
          >
            {{ t('analysis.invertSelection') }}
          </button>
        </div>
      </div>

      <div
        ref="dirTreeRef"
        class="dir-tree"
      >
        <div
          v-if="!stats?.directories || stats.directories.length === 0"
          class="empty-hint"
        >
          {{ t('analysis.noDirectories') }}
        </div>
        <template v-else>
          <DirTreeNodeComponent
            v-for="dir in stats.directories"
            :key="dir.path"
            :node="dir"
            :selected-scopes="selectedScopes"
            :expanded-dirs="expandedDirs"
            @toggle="handleDirToggle"
            @expand="handleDirExpand"
          />
        </template>
      </div>

      <div class="selection-count">
        {{ t('analysis.selectedCount', { count: selectedScopes.length, total: stats?.totalDirs || 0 }) }}
      </div>

      <!-- 通配符作用域输入 -->
      <div class="glob-scope-row">
        <input
          v-model="globScopeInput"
          class="stats-input glob-scope-input"
          :placeholder="t('analysis.globScopePlaceholder')"
          @keydown.enter="addGlobScope"
        >
        <button
          class="text-btn"
          :disabled="!globScopeInput.trim()"
          @click="addGlobScope"
        >
          +
        </button>
      </div>
      <div
        v-if="selectedScopes.some(s => s.includes('*') || s.includes('?'))"
        class="glob-scope-tags"
      >
        <span
          v-for="(s, i) in selectedScopes.filter(s => s.includes('*') || s.includes('?'))"
          :key="s"
          class="glob-tag"
        >
          <code>{{ s }}</code>
          <button
            class="tag-remove"
            @click="removeScopeByPath(s)"
          >
            <XMarkIcon class="w-3 h-3" />
          </button>
        </span>
      </div>
    </div>

    <!-- Match mode -->
    <div class="stats-section">
      <label class="stats-label">{{ t('analysis.matchMode') }}</label>
      <div class="radio-group">
        <label class="radio-item">
          <input
            type="radio"
            value="all"
            :checked="patternType === 'all'"
            @change="emit('update:patternType', 'all')"
          >
          <span>{{ t('analysis.allFiles') }}</span>
        </label>
        <label class="radio-item">
          <input
            type="radio"
            value="glob"
            :checked="patternType === 'glob'"
            @change="emit('update:patternType', 'glob')"
          >
          <span>{{ t('analysis.stringMatch') }}</span>
        </label>
        <label class="radio-item">
          <input
            type="radio"
            value="regex"
            :checked="patternType === 'regex'"
            @change="emit('update:patternType', 'regex')"
          >
          <span>{{ t('analysis.regexMatch') }}</span>
        </label>
      </div>
    </div>

    <!-- Pattern input -->
    <div
      v-if="patternType !== 'all'"
      class="stats-section"
    >
      <input
        class="stats-input"
        :value="pattern"
        :placeholder="t('analysis.patternPlaceholder')"
        @input="emit('update:pattern', ($event.target as HTMLInputElement).value)"
      >
    </div>

    <!-- Loading state -->
    <div
      v-if="loading"
      class="stats-loading"
    >
      <div class="loading-spinner" />
      <span>{{ t('file.loading') }}</span>
    </div>

    <!-- Error state -->
    <div
      v-else-if="error"
      class="stats-error"
    >
      <span>{{ error }}</span>
    </div>

    <!-- File distribution (clickable bars) -->
    <div
      v-else-if="stats && stats.extensions && Object.keys(stats.extensions).length > 0"
      class="stats-results"
    >
      <div class="section-header">
        <DocumentTextIcon class="w-4 h-4" />
        <span>{{ t('analysis.fileDistribution') }}</span>
        <div class="section-actions">
          <button
            class="text-btn"
            @click="selectAllExtensions"
          >
            {{ t('analysis.selectAll') }}
          </button>
          <span class="divider">/</span>
          <button
            class="text-btn"
            @click="invertExtensions"
          >
            {{ t('analysis.invertSelection') }}
          </button>
        </div>
      </div>

      <div class="stats-bars">
        <div
          v-for="(count, ext) in stats.extensions"
          :key="ext || '__no_ext__'"
          class="stat-bar-row"
          :class="{ 'selected': selectedExtensions.includes(ext) }"
          @click="toggleExtension(ext)"
        >
          <span class="stat-ext">{{ formatExtension(ext) }}</span>
          <span class="stat-count">{{ count }}</span>
          <div class="stat-bar">
            <div
              class="stat-bar-fill"
              :style="{ width: `${(count / maxCount) * 100}%` }"
            />
          </div>
          <button
            v-if="selectedExtensions.includes(ext)"
            class="remove-btn"
            @click.stop="removeExtension(ext)"
          >
            <XMarkIcon class="w-3 h-3" />
          </button>
        </div>
      </div>

      <!-- Selected extensions as tags -->
      <div
        v-if="selectedExtensions.length > 0"
        class="selected-tags"
      >
        <span class="tags-label">{{ t('analysis.selectedExtensions') }}:</span>
        <div class="tag-list">
          <span
            v-for="ext in selectedExtensions"
            :key="ext || '__no_ext__'"
            class="tag-chip"
          >
            {{ formatExtension(ext) }}
            <button
              class="tag-remove"
              @click="removeExtension(ext)"
            >
              <XMarkIcon class="w-3 h-3" />
            </button>
          </span>
        </div>
      </div>

      <div class="stats-summary">
        <span>{{ t('analysis.totalFiles', { total: stats.totalFiles, dirs: stats.totalDirs }) }}</span>
      </div>
    </div>

    <!-- Empty state -->
    <div
      v-else-if="stats && stats.totalFiles === 0"
      class="stats-empty"
    >
      <span>{{ t('file.noFiles') }}</span>
    </div>
  </div>
</template>

<style scoped>
.file-stats-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: 6px;
  border: 1px solid var(--border);
  max-height: 600px;
  overflow-y: auto;
}

.stats-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 6px;
}

.section-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 4px;
}

.divider {
  color: var(--text-muted);
  font-size: 11px;
}

.stats-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.text-btn {
  background: none;
  border: none;
  color: var(--accent);
  font-size: 11px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 3px;
}

.text-btn:hover {
  background: var(--bg-hover);
}

/* Directory tree */
.dir-tree {
  max-height: 200px;
  overflow-y: auto;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 6px;
}

.selection-count {
  font-size: 11px;
  color: var(--text-muted);
}

.empty-hint {
  font-size: 12px;
  color: var(--text-muted);
  padding: 8px;
  text-align: center;
}

.glob-scope-row {
  display: flex;
  gap: 4px;
  align-items: center;
}

.glob-scope-input {
  flex: 1;
}

.glob-scope-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.glob-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: var(--bg-tertiary);
  border: 1px solid var(--accent);
  border-radius: 12px;
  font-size: 11px;
  color: var(--accent);
}

.glob-tag code {
  font-family: monospace;
  font-size: 11px;
}

.stats-input {
  padding: 6px 8px;
  font-size: 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-primary);
  outline: none;
}

.stats-input:focus {
  border-color: var(--accent);
}

.radio-group {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.radio-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
}

.radio-item input[type="radio"] {
  accent-color: var(--accent);
}

.stats-loading,
.stats-error,
.stats-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  font-size: 12px;
  color: var(--text-muted);
  gap: 8px;
}

.stats-error {
  color: var(--error);
}

.stats-results {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.stats-bars {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-bar-row {
  display: grid;
  grid-template-columns: 70px 35px 1fr 24px;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  padding: 4px 6px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s;
}

.stat-bar-row:hover {
  background: var(--bg-hover);
}

.stat-bar-row.selected {
  background: var(--bg-active);
  border: 1px solid var(--accent);
}

.stat-bar-row:not(.selected) {
  border: 1px solid transparent;
}

.stat-ext {
  color: var(--text-secondary);
  font-family: monospace;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stat-count {
  color: var(--text-muted);
  text-align: right;
}

.stat-bar {
  height: 10px;
  background: var(--bg-tertiary);
  border-radius: 3px;
  overflow: hidden;
}

.stat-bar-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.3s;
  border-radius: 3px;
}

.stat-bar-row.selected .stat-bar-fill {
  background: var(--accent-hover);
}

.remove-btn {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 2px;
}

.remove-btn:hover {
  color: var(--error);
  background: var(--bg-hover);
}

/* Selected tags */
.selected-tags {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tags-label {
  font-size: 11px;
  color: var(--text-muted);
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.tag-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: var(--bg-tertiary);
  border: 1px solid var(--accent);
  border-radius: 12px;
  font-size: 11px;
  color: var(--accent);
  font-family: monospace;
}

.tag-remove {
  background: none;
  border: none;
  color: var(--accent);
  cursor: pointer;
  padding: 0;
  display: flex;
  align-items: center;
  opacity: 0.7;
}

.tag-remove:hover {
  opacity: 1;
  color: var(--error);
}

.stats-summary {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  font-size: 11px;
  color: var(--text-muted);
}

.loading-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
