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

// 视图切换：摘要 / 源码
const viewMode = ref<'summary' | 'source'>('summary')
const sourceContent = ref('')
const sourceLoading = ref(false)
const sourceFound = ref(false)
const sourceTruncated = ref(false)
let sourceLoaded = false

async function loadSource() {
  if (sourceLoaded || sourceLoading.value) return
  sourceLoading.value = true
  try {
    const resp = await communityStore.getPreSummaryFileSource(props.taskId, props.filePath)
    sourceFound.value = !!resp?.found
    sourceContent.value = resp?.content || ''
    sourceTruncated.value = !!resp?.truncated
    sourceLoaded = true
  } catch {
    sourceFound.value = false
  }
  finally { sourceLoading.value = false }
}

function switchMode(mode: 'summary' | 'source') {
  viewMode.value = mode
  if (mode === 'source') loadSource()
}

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
        <div class="psd-view-toggle">
          <button
            class="psd-mode-btn"
            :class="{ 'psd-mode-active': viewMode === 'summary' }"
            @click="switchMode('summary')"
          >
            {{ t('report.preSummaryViewSummary') }}
          </button>
          <button
            class="psd-mode-btn"
            :class="{ 'psd-mode-active': viewMode === 'source' }"
            @click="switchMode('source')"
          >
            {{ t('report.preSummaryViewSource') }}
          </button>
        </div>
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
          <template v-if="viewMode === 'summary'">
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
          </template>
          <template v-else>
            <template v-if="sourceLoading">
              <div class="psd-loading">
                {{ t('common.loading') }}
              </div>
            </template>
            <template v-else-if="!sourceFound">
              <div class="psd-not-found">
                {{ t('report.preSummarySourceNotFound') }}
              </div>
            </template>
            <template v-else>
              <div
                v-if="sourceTruncated"
                class="psd-truncated-tip"
              >
                {{ t('report.preSummarySourceTruncated') }}
              </div>
              <pre class="psd-source-text">{{ sourceContent }}</pre>
            </template>
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
  border-radius: calc(10px * var(--ui-scale, 1));
  width: calc(600px * var(--ui-scale, 1));
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
  gap: calc(8px * var(--ui-scale, 1));
  padding: calc(12px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1));
  border-bottom: 1px solid var(--border);
}

.psd-title {
  font-size: calc(13px * var(--ui-scale, 1));
  font-weight: 600;
  color: var(--text-primary);
}

.psd-spacer {
  flex: 1;
}

.psd-close-btn {
  width: calc(24px * var(--ui-scale, 1));
  height: calc(24px * var(--ui-scale, 1));
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: calc(4px * var(--ui-scale, 1));
}

.psd-close-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.psd-body {
  flex: 1;
  overflow-y: auto;
  padding: calc(16px * var(--ui-scale, 1));
}

.psd-meta {
  display: flex;
  flex-direction: column;
  gap: calc(6px * var(--ui-scale, 1));
}

.psd-meta-row {
  display: flex;
  align-items: flex-start;
  gap: calc(8px * var(--ui-scale, 1));
}

.psd-meta-label {
  flex-shrink: 0;
  width: calc(70px * var(--ui-scale, 1));
  font-size: calc(10px * var(--ui-scale, 1));
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.3px;
  padding-top: 1px;
}

.psd-meta-value {
  font-size: calc(12px * var(--ui-scale, 1));
  color: var(--text-primary);
}

.psd-path {
  font-family: var(--font-mono);
  font-size: calc(10px * var(--ui-scale, 1));
  word-break: break-all;
}

.psd-divider {
  height: 1px;
  background: var(--border);
  margin: calc(12px * var(--ui-scale, 1)) 0;
}

.psd-content {
  min-height: calc(80px * var(--ui-scale, 1));
}

.psd-view-toggle {
  display: flex;
  gap: calc(4px * var(--ui-scale, 1));
  margin-left: calc(10px * var(--ui-scale, 1));
}
.psd-mode-btn {
  padding: calc(2px * var(--ui-scale, 1)) calc(8px * var(--ui-scale, 1));
  border: 1px solid var(--border);
  border-radius: calc(4px * var(--ui-scale, 1));
  background: transparent;
  color: var(--text-muted);
  font-size: calc(10px * var(--ui-scale, 1));
  cursor: pointer;
}
.psd-mode-btn:hover {
  color: var(--text-primary);
}
.psd-mode-active {
  background: color-mix(in srgb, var(--accent) 15%, transparent);
  border-color: color-mix(in srgb, var(--accent) 40%, transparent);
  color: var(--accent);
}
.psd-source-text {
  margin: 0;
  max-height: 100%;
  overflow: auto;
  font-family: var(--font-mono);
  font-size: calc(11px * var(--ui-scale, 1));
  line-height: 1.5;
  white-space: pre;
  color: var(--text-primary);
}
.psd-truncated-tip {
  padding: calc(4px * var(--ui-scale, 1)) 0;
  color: var(--text-muted);
  font-size: calc(10px * var(--ui-scale, 1));
}
.psd-summary-text {
  font-size: calc(12px * var(--ui-scale, 1));
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
  height: calc(80px * var(--ui-scale, 1));
  font-size: calc(12px * var(--ui-scale, 1));
  color: var(--text-muted);
}

.psd-footer {
  display: flex;
  align-items: center;
  gap: calc(8px * var(--ui-scale, 1));
  padding: calc(10px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1));
  border-top: 1px solid var(--border);
}

.psd-btn {
  padding: calc(5px * var(--ui-scale, 1)) calc(14px * var(--ui-scale, 1));
  font-size: calc(11px * var(--ui-scale, 1));
  border: 1px solid var(--border);
  border-radius: calc(4px * var(--ui-scale, 1));
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
  border-radius: calc(10px * var(--ui-scale, 1));
  padding: calc(20px * var(--ui-scale, 1)) calc(24px * var(--ui-scale, 1));
  min-width: calc(280px * var(--ui-scale, 1));
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

.psd-confirm-box p {
  margin: 0 0 calc(16px * var(--ui-scale, 1));
  font-size: calc(14px * var(--ui-scale, 1));
  color: var(--text-primary);
}

.psd-confirm-actions {
  display: flex;
  gap: calc(8px * var(--ui-scale, 1));
  justify-content: flex-end;
}
</style>
