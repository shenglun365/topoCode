<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCommunityStore } from '@/stores/community-store'

const { t } = useI18n()
const communityStore = useCommunityStore()

const props = defineProps<{
  taskId: string
  filePath: string
}>()

const emit = defineEmits<{
  close: []
  deleted: []
}>()

const loading = ref(true)
const summary = ref('')
const summaryLen = ref(0)
const createdAt = ref('')
const source = ref('')
const found = ref(false)
const deleting = ref(false)

async function loadSummary() {
  loading.value = true
  try {
    const resp = await communityStore.getFileSummary(props.taskId, props.filePath)
    if (resp?.found) {
      found.value = true
      summary.value = resp.summary || ''
      summaryLen.value = resp.summary_len || 0
      createdAt.value = resp.created_at || ''
      source.value = resp.source || ''
    } else {
      found.value = false
      summary.value = ''
    }
  } catch {
    found.value = false
  }
  finally { loading.value = false }
}

const showDeleteConfirm = ref(false)

async function handleDelete() {
  if (deleting.value) return
  showDeleteConfirm.value = true
}

async function doDelete() {
  showDeleteConfirm.value = false
  deleting.value = true
  try {
    await communityStore.deleteFileSummary(props.taskId, props.filePath)
    emit('deleted')
  } catch { /* ignore */ }
  finally { deleting.value = false }
}

onMounted(loadSummary)
</script>

<template>
  <div
    class="psd-overlay"
    @click.self="emit('close')"
  >
    <div class="psd-dialog">
      <div class="psd-header">
        <span class="psd-title">{{ t('report.filePreSummary') }}</span>
        <div class="psd-spacer" />
        <button
          class="psd-close-btn"
          @click="emit('close')"
        >
          ✕
        </button>
      </div>
      <div class="psd-body">
        <div class="psd-meta">
          <div class="psd-meta-row">
            <span class="psd-meta-label">{{ t('file.filePath') }}</span>
            <span class="psd-meta-value psd-path">{{ filePath }}</span>
          </div>
          <div class="psd-meta-row">
            <span class="psd-meta-label">{{ t('report.preSummaryCacheTime') }}</span>
            <span class="psd-meta-value">{{ createdAt || '-' }}</span>
          </div>
          <div class="psd-meta-row">
            <span class="psd-meta-label">{{ t('report.preSummaryScore') }}</span>
            <span class="psd-meta-value">{{ summaryLen }} {{ t('report.preSummaryChars') }}</span>
          </div>
        </div>
        <div class="psd-divider" />
        <div class="psd-content">
          <template v-if="loading">
            <div class="psd-loading">
              {{ t('common.loading') }}
            </div>
          </template>
          <template v-else-if="!found">
            <div class="psd-not-found">
              {{ t('report.preSummaryNotCached') }}
            </div>
          </template>
          <template v-else>
            <pre class="psd-summary-text">{{ summary }}</pre>
          </template>
        </div>
      </div>
      <div class="psd-footer">
        <button
          class="psd-btn psd-btn-danger"
          :disabled="!found || deleting"
          @click="handleDelete"
        >
          {{ deleting ? '...' : t('report.preSummaryDelete') }}
        </button>
        <div class="psd-spacer" />
        <button
          class="psd-btn"
          @click="emit('close')"
        >
          {{ t('report.preSummaryClose') }}
        </button>
      </div>

      <!-- 确认删除弹窗 -->
      <div
        v-if="showDeleteConfirm"
        class="psd-overlay"
        @click.self="showDeleteConfirm = false"
      >
        <div class="psd-confirm-box">
          <p>{{ t('report.preSummaryDeleteConfirm') }}</p>
          <div class="psd-confirm-actions">
            <button
              class="psd-btn psd-btn-danger"
              @click="doDelete"
            >
              {{ t('common.confirm') }}
            </button>
            <button
              class="psd-btn"
              @click="showDeleteConfirm = false"
            >
              {{ t('common.cancel') }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.psd-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.psd-dialog {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 10px;
  width: 600px;
  max-width: 90vw;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  overflow: hidden;
}

.psd-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}

.psd-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.psd-spacer {
  flex: 1;
}

.psd-close-btn {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: 4px;
}

.psd-close-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.psd-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.psd-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.psd-meta-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.psd-meta-label {
  flex-shrink: 0;
  width: 70px;
  font-size: 10px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.3px;
  padding-top: 1px;
}

.psd-meta-value {
  font-size: 12px;
  color: var(--text-primary);
}

.psd-path {
  font-family: var(--font-mono);
  font-size: 10px;
  word-break: break-all;
}

.psd-divider {
  height: 1px;
  background: var(--border);
  margin: 12px 0;
}

.psd-content {
  min-height: 80px;
}

.psd-summary-text {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  margin: 0;
}

.psd-loading,
.psd-not-found {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 80px;
  font-size: 12px;
  color: var(--text-muted);
}

.psd-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-top: 1px solid var(--border);
}

.psd-btn {
  padding: 5px 14px;
  font-size: 11px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.15s;
}

.psd-btn:hover {
  border-color: var(--accent);
}

.psd-btn-danger {
  color: var(--error);
  border-color: color-mix(in srgb, var(--error) 40%, transparent);
}

.psd-btn-danger:hover {
  background: color-mix(in srgb, var(--error) 10%, transparent);
  border-color: var(--error);
}

.psd-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.psd-confirm-box {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 20px 24px;
  min-width: 280px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

.psd-confirm-box p {
  margin: 0 0 16px;
  font-size: 14px;
  color: var(--text-primary);
}

.psd-confirm-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
</style>
