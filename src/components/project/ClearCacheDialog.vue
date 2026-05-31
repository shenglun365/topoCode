<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ipc } from '@/services/ipc'

const { t } = useI18n()

const props = defineProps<{ projectId: string }>()
const emit = defineEmits<{ close: [] }>()

interface CacheItem {
  key: string
  label: string
  count: number
  checked: boolean
  status: 'pending' | 'running' | 'completed' | 'error'
  deleted?: number
}

const TABLE_LABELS: Record<string, string> = {
  ast_data: t('project.cacheItemAst'),
  dependencies: t('project.cacheItemDeps'),
  call_chains: t('project.cacheItemCallChains'),
  community_hierarchy: t('project.cacheItemCommunityHier'),
  community_llm_results: t('project.cacheItemLlmResults'),
  graph_node: t('project.cacheItemGraphNodes'),
  graph_doc: t('project.cacheItemGraphDocs'),
  base_node: t('project.cacheItemBaseNodes'),
  components: t('project.cacheItemComponents'),
  ai_qa: t('project.cacheItemAiQa'),
  tasks: t('project.cacheItemTasks'),
}

const loading = ref(true)
const items = ref<CacheItem[]>([])
const isDeleting = ref(false)
const autoCloseTimer = ref<ReturnType<typeof setTimeout> | null>(null)

const allChecked = computed({
  get: () => items.value.length > 0 && items.value.every(i => i.checked),
  set: (val: boolean) => { items.value.forEach(i => { i.checked = val }) },
})

const totalCount = computed(() => items.value.reduce((s, i) => s + i.count, 0))
const selectedCount = computed(() => items.value.filter(i => i.checked).length)
const displayedItems = computed(() => items.value.filter(i => i.checked))

onMounted(async () => {
  try {
    const result = await ipc.analysis.getClearCacheCounts(props.projectId)
    items.value = Object.entries(result.counts).map(([key, count]) => ({
      key,
      label: TABLE_LABELS[key] || key,
      count,
      checked: true,
      status: 'pending' as const,
    }))
  } catch (e) {
    console.error('[ClearCacheDialog] Failed to load counts:', e)
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  if (autoCloseTimer.value) clearTimeout(autoCloseTimer.value)
})

async function confirmClear() {
  isDeleting.value = true
  const selected = items.value.filter(i => i.checked)
  for (const item of selected) {
    item.status = 'running'
    try {
      const result = await ipc.analysis.clearProjectCacheTable(props.projectId, item.key)
      item.deleted = result.deleted
      item.status = 'completed'
    } catch (e) {
      item.status = 'error'
    }
  }
  autoCloseTimer.value = setTimeout(() => emit('close'), 2000)
}

function cancel() {
  if (isDeleting.value) return
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <div class="ccd-overlay" @click.self="cancel">
      <div class="ccd-card">
        <div class="ccd-header">
          <span class="ccd-title">{{ t('project.clearCache') }}</span>
          <button v-if="!isDeleting" class="ccd-close" @click="cancel">&times;</button>
        </div>

        <div v-if="loading" class="ccd-loading">
          <div class="ccd-spinner" />
          <span>{{ t('common.loading') }}...</span>
        </div>

        <template v-else-if="!isDeleting">
          <div class="ccd-hint">{{ t('project.clearCacheSelectHint') }}</div>
          <div class="ccd-select-all">
            <label class="ccd-cb-row">
              <input type="checkbox" v-model="allChecked" class="ccd-cb">
              <span class="ccd-cb-label">{{ t('common.selectAll') }} ({{ items.length }})</span>
              <span class="ccd-total">{{ totalCount }} {{ t('project.cacheRecords') }}</span>
            </label>
          </div>
          <div class="ccd-list">
            <label v-for="item in items" :key="item.key" class="ccd-cb-row ccd-item">
              <input type="checkbox" v-model="item.checked" class="ccd-cb">
              <span class="ccd-cb-label">{{ item.label }}</span>
              <span class="ccd-count">{{ item.count }} {{ t('project.cacheRecords') }}</span>
            </label>
          </div>
          <div class="ccd-footer">
            <span class="ccd-selected">{{ t('project.cacheSelected', { n: selectedCount }) }}</span>
            <div class="ccd-actions">
              <button class="btn btn-ghost btn-sm" @click="cancel">{{ t('common.cancel') }}</button>
              <button class="btn btn-warning btn-sm" :disabled="selectedCount === 0" @click="confirmClear">
                {{ t('project.clearCache') }}
              </button>
            </div>
          </div>
        </template>

        <template v-else>
          <div class="ccd-progress">
            <div v-for="item in displayedItems" :key="item.key" :class="['ccd-progress-item', `ccd-${item.status}`]">
              <span class="ccd-pi-label">{{ item.label }}</span>
              <span v-if="item.status === 'pending'" class="ccd-pi-status ccd-pending">{{ t('project.cacheWaiting') }}</span>
              <span v-else-if="item.status === 'running'" class="ccd-pi-status ccd-running">{{ t('common.deleting') }}</span>
              <span v-else-if="item.status === 'completed'" class="ccd-pi-status ccd-completed">{{ t('project.cacheDeleted', { n: item.deleted }) }}</span>
              <span v-else-if="item.status === 'error'" class="ccd-pi-status ccd-error">{{ t('common.error') }}</span>
            </div>
          </div>
        </template>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.ccd-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex;
  align-items: center; justify-content: center; z-index: 10000;
}
.ccd-card {
  background: var(--bg-primary); border: 1px solid var(--border); border-radius: 10px;
  min-width: 420px; max-width: 480px; max-height: 80vh; display: flex;
  flex-direction: column; box-shadow: 0 8px 32px rgba(0,0,0,0.25);
}
.ccd-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--border);
}
.ccd-title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.ccd-close { font-size: 18px; color: var(--text-muted); background: none; border: none; cursor: pointer; padding: 0 4px; }
.ccd-close:hover { color: var(--text-primary); }
.ccd-loading { padding: 24px; text-align: center; color: var(--text-muted); display: flex; align-items: center; justify-content: center; gap: 8px; }
.ccd-spinner { width: 20px; height: 20px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: ccd-spin 0.6s linear infinite; }
@keyframes ccd-spin { to { transform: rotate(360deg); } }
.ccd-hint { padding: 8px 16px; font-size: 10px; color: var(--text-muted); }
.ccd-select-all { padding: 4px 16px; border-bottom: 1px solid var(--border); }
.ccd-list { flex: 1; overflow-y: auto; padding: 4px 16px; max-height: 320px; }
.ccd-cb-row { display: flex; align-items: center; gap: 6px; padding: 5px 4px; cursor: pointer; font-size: 11px; }
.ccd-cb-row:hover { background: var(--bg-tertiary); border-radius: 4px; }
.ccd-cb { accent-color: var(--accent); width: 14px; height: 14px; }
.ccd-cb-label { flex: 1; color: var(--text-primary); }
.ccd-total, .ccd-count { color: var(--text-muted); font-family: var(--font-mono); font-size: 9px; white-space: nowrap; }
.ccd-footer {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 16px; border-top: 1px solid var(--border);
}
.ccd-selected { font-size: 10px; color: var(--text-muted); }
.ccd-actions { display: flex; gap: 6px; }

.ccd-progress { padding: 12px 16px; display: flex; flex-direction: column; gap: 6px; }
.ccd-progress-item { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 11px; }
.ccd-pi-label { flex: 1; color: var(--text-primary); }
.ccd-pi-status { font-size: 9px; font-family: var(--font-mono); white-space: nowrap; }
.ccd-pending { color: var(--text-muted); }
.ccd-running { color: var(--accent); }
.ccd-running::before { content: ''; display: inline-block; width: 8px; height: 8px; border: 1.5px solid var(--accent); border-top-color: transparent; border-radius: 50%; animation: ccd-spin 0.6s linear infinite; margin-right: 4px; vertical-align: middle; }
.ccd-completed { color: var(--success); }
.ccd-error { color: var(--error); }
</style>
