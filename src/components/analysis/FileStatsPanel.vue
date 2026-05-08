<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { DocumentTextIcon, FolderIcon } from '@heroicons/vue/24/outline'
import { useAnalysisStore } from '@/stores/analysis'
import type { FileStatsResult } from '@/types/ipc'

const props = defineProps<{
  projectId: string
  scope: string
  patternType: 'all' | 'glob' | 'regex'
  pattern: string
  excludeDirs: string[]
}>()

const emit = defineEmits<{
  'update:scope': [val: string]
  'update:patternType': [val: 'all' | 'glob' | 'regex']
  'update:pattern': [val: string]
  'suggestExtensions': [exts: string[]]
}>()

const { t } = useI18n()
const analysisStore = useAnalysisStore()

const stats = ref<FileStatsResult | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const customScope = ref('')

// 计算最大文件数用于条形图比例
const maxCount = computed(() => {
  if (!stats.value || !stats.value.extensions) return 1
  return Math.max(...Object.values(stats.value.extensions), 1)
})

// 加载统计数据
async function loadStats() {
  if (!props.projectId) {
    console.warn('[FileStatsPanel] loadStats: projectId is empty')
    return
  }

  loading.value = true
  error.value = null

  try {
    const scope = props.scope === '__custom__' ? customScope.value : (props.scope || undefined)
    console.log('[FileStatsPanel] loadStats calling scanFileStats:', {
      projectId: props.projectId,
      scope,
      patternType: props.patternType,
      pattern: props.pattern,
      excludeDirs: props.excludeDirs,
    })
    const result = await analysisStore.scanFileStats(props.projectId, {
      scope: scope || undefined,
      patternType: props.patternType,
      pattern: props.pattern || undefined,
      excludeDirs: props.excludeDirs.length > 0 ? props.excludeDirs : undefined,
    })
    console.log('[FileStatsPanel] loadStats result:', result)
    stats.value = result

    // 推荐 top 5 扩展名
    const exts = Object.keys(result.extensions).slice(0, 5)
    if (exts.length > 0) {
      emit('suggestExtensions', exts)
    }
  } catch (err: any) {
    console.error('[FileStatsPanel] loadStats error:', err)
    error.value = err?.message || t('common.loadFailed')
  } finally {
    loading.value = false
  }
}

// 防抖加载
let debounceTimer: ReturnType<typeof setTimeout> | null = null
function debouncedLoadStats() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(loadStats, 300)
}

// 监听 props 变化
watch([() => props.scope, () => props.patternType, () => props.pattern, () => props.excludeDirs], () => {
  debouncedLoadStats()
}, { immediate: false })

// 初始加载
loadStats()

function onScopeChange(val: string) {
  emit('update:scope', val)
  if (val !== '__custom__') {
    loadStats()
  }
}

function onCustomScopeInput() {
  if (props.scope === '__custom__') {
    debouncedLoadStats()
  }
}
</script>

<template>
  <div class="file-stats-panel">
    <!-- 目录范围选择 -->
    <div class="stats-section">
      <label class="stats-label">{{ t('analysis.directoryScope') }}</label>
      <select
        class="stats-select"
        :value="scope"
        @change="onScopeChange(($event.target as HTMLSelectElement).value)"
      >
        <option value="">{{ t('analysis.allDirectories') }}</option>
        <option v-for="dir in stats?.directories" :key="dir" :value="dir">
          {{ dir }}
        </option>
        <option value="__custom__">{{ t('analysis.customPath') }}</option>
      </select>
    </div>

    <!-- 自定义路径输入 -->
    <div v-if="scope === '__custom__'" class="stats-section">
      <input
        class="stats-input"
        :value="customScope"
        @input="onCustomScopeInput"
        :placeholder="t('analysis.patternPlaceholder')"
      />
    </div>

    <!-- 匹配模式 -->
    <div class="stats-section">
      <label class="stats-label">{{ t('analysis.matchMode') }}</label>
      <div class="radio-group">
        <label class="radio-item">
          <input
            type="radio"
            value="all"
            :value="patternType"
            @change="emit('update:patternType', 'all')"
          />
          <span>{{ t('analysis.allFiles') }}</span>
        </label>
        <label class="radio-item">
          <input
            type="radio"
            value="glob"
            :value="patternType"
            @change="emit('update:patternType', 'glob')"
          />
          <span>{{ t('analysis.stringMatch') }}</span>
        </label>
        <label class="radio-item">
          <input
            type="radio"
            value="regex"
            :value="patternType"
            @change="emit('update:patternType', 'regex')"
          />
          <span>{{ t('analysis.regexMatch') }}</span>
        </label>
      </div>
    </div>

    <!-- 匹配模式输入 -->
    <div v-if="patternType !== 'all'" class="stats-section">
      <input
        class="stats-input"
        :value="pattern"
        @input="emit('update:pattern', ($event.target as HTMLInputElement).value)"
        :placeholder="t('analysis.patternPlaceholder')"
      />
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="stats-loading">
      <div class="loading-spinner"></div>
      <span>{{ t('file.loading') }}</span>
    </div>

    <!-- 错误状态 -->
    <div v-else-if="error" class="stats-error">
      <span>{{ error }}</span>
    </div>

    <!-- 文件统计 -->
    <div v-else-if="stats && stats.extensions && Object.keys(stats.extensions).length > 0" class="stats-results">
      <div class="stats-header">
        <DocumentTextIcon class="w-4 h-4" />
        <span>{{ t('analysis.fileDistribution') }}</span>
      </div>

      <div class="stats-bars">
        <div
          v-for="(count, lang) in stats.extensions"
          :key="lang"
          class="stat-bar-row"
        >
          <span class="stat-lang">{{ lang }}</span>
          <span class="stat-count">{{ count }}</span>
          <div class="stat-bar">
            <div
              class="stat-bar-fill"
              :style="{ width: `${(count / maxCount) * 100}%` }"
            />
          </div>
        </div>
      </div>

      <div class="stats-summary">
        <FolderIcon class="w-3.5 h-3.5" />
        <span>{{ t('analysis.totalFiles', { total: stats.totalFiles, dirs: stats.totalDirs }) }}</span>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-else-if="stats && stats.totalFiles === 0" class="stats-empty">
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
}

.stats-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stats-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.stats-select,
.stats-input {
  padding: 6px 8px;
  font-size: 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-primary);
  outline: none;
}

.stats-select:focus,
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

.stats-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.stats-bars {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.stat-bar-row {
  display: grid;
  grid-template-columns: 60px 40px 1fr;
  align-items: center;
  gap: 8px;
  font-size: 11px;
}

.stat-lang {
  color: var(--text-secondary);
  font-family: monospace;
}

.stat-count {
  color: var(--text-muted);
  text-align: right;
}

.stat-bar {
  height: 12px;
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

.stats-summary {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  font-size: 11px;
  color: var(--text-muted);
}
</style>
