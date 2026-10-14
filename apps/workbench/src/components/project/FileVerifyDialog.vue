<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, PlusCircleIcon, PencilSquareIcon, TrashIcon } from '@heroicons/vue/24/outline'

const { t } = useI18n()

const props = defineProps<{ projectId: string }>()
const emit = defineEmits<{ close: [] }>()

interface VerifyDetail {
  filePath: string
  status: 'added' | 'modified' | 'deleted'
}

interface VerifyResult {
  mode: 'git'
  baseline: string
  head: string
  branch: string
  dirty: number
  added: string[]
  modified: string[]
  deleted: string[]
  total: number
  note: string
  details: VerifyDetail[]
}

const loading = ref(true)
const verifying = ref(false)
const progress = ref(0)
const message = ref('')
const result = ref<VerifyResult | null>(null)
const error = ref('')
const verifyId = ref('')
const filterStatus = ref('all')
let pollTimer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  startVerify()
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

async function startVerify() {
  verifying.value = true
  loading.value = false
  error.value = ''
  try {
    const res = await (window.api as any).system.verifyFiles(props.projectId)
    verifyId.value = res.verifyId
    startPolling()
  } catch (e: any) {
    error.value = e.message || t('project.verify.verifyFailed')
    verifying.value = false
  }
}

function startPolling() {
  pollTimer = setInterval(async () => {
    try {
      const status = await (window.api as any).system.verifyStatus(verifyId.value)
      if (!status) return
      progress.value = status.progress || 0
      message.value = status.message || ''
      if (status.status === 'done') {
        if (pollTimer) clearInterval(pollTimer)
        verifying.value = false
        result.value = status.result
      } else if (status.status === 'error') {
        if (pollTimer) clearInterval(pollTimer)
        error.value = status.message || t('project.verify.verifyFailed')
        verifying.value = false
      }
    } catch {
      // ignore
    }
  }, 1000)
}

function close() {
  if (pollTimer) clearInterval(pollTimer)
  emit('close')
}

const filteredDetails = () => {
  if (!result.value) return []
  if (filterStatus.value === 'all') return result.value.details
  return result.value.details.filter(d => d.status === filterStatus.value)
}

function shortHash(h: string): string {
  return h ? h.slice(0, 8) : '-'
}

function statusIcon(status: string) {
  if (status === 'added') return PlusCircleIcon
  if (status === 'modified') return PencilSquareIcon
  return TrashIcon
}

function statusColor(status: string) {
  if (status === 'added') return 'var(--success)'
  if (status === 'modified') return 'var(--warning)'
  return 'var(--error)'
}
</script>

<template>
  <Teleport to="body">
    <div
      class="dialog-overlay"
      @click.self="close"
    >
      <div class="dialog-card">
        <div class="dialog-header">
          <span class="dialog-title">{{ t('project.verifyFiles') }}</span>
          <button
            class="dialog-close"
            @click="close"
          >
            &times;
          </button>
        </div>

        <div
          v-if="loading"
          class="dialog-loading"
        >
          <div class="spinner" /><span>{{ t('common.loading') }}...</span>
        </div>

        <div
          v-show="verifying"
          class="progress-section"
        >
          <div class="progress-bar-track">
            <div
              class="progress-bar-fill"
              :style="{ width: progress + '%' }"
            />
          </div>
          <div class="progress-info">
            {{ message || t('common.processing') }}
          </div>
        </div>

        <div
          v-show="error"
          class="error-section"
        >
          <div class="error-msg">
            {{ error }}
          </div>
        </div>

        <template v-if="result">
          <div
            v-if="result.note === 'not-git'"
            class="notice-section"
          >
            {{ t('project.verify.notGit') }}
          </div>
          <div
            v-else-if="result.note === 'no-baseline'"
            class="notice-section"
          >
            {{ t('project.verify.noBaseline') }}
          </div>

          <div class="result-summary">
            <div class="baseline-info">
              <span
                v-if="result.branch"
                class="chip"
              >{{ result.branch }}</span>
              <span class="hash-pair">
                git diff <code>{{ shortHash(result.baseline) }}</code>
                <span class="arrow">→</span> <code>{{ shortHash(result.head) }}</code>
              </span>
              <span
                v-if="result.dirty > 0"
                class="chip dirty"
              >{{ t('project.verify.dirty', { n: result.dirty }) }}</span>
            </div>
            <div class="stats">
              <div class="stat-row">
                <PlusCircleIcon class="stat-icon added" /><span>{{ t('project.verifyAdded') }}: {{ result.added.length }}</span>
              </div>
              <div class="stat-row">
                <PencilSquareIcon class="stat-icon modified" /><span>{{ t('project.verifyModified') }}: {{ result.modified.length }}</span>
              </div>
              <div class="stat-row">
                <TrashIcon class="stat-icon deleted" /><span>{{ t('project.verifyDeleted') }}: {{ result.deleted.length }}</span>
              </div>
            </div>
          </div>

          <div class="filter-bar">
            <select
              v-model="filterStatus"
              class="filter-select"
            >
              <option value="all">
                {{ t('common.all') }} ({{ result.total }})
              </option>
              <option value="added">
                {{ t('project.verifyAdded') }} ({{ result.added.length }})
              </option>
              <option value="modified">
                {{ t('project.verifyModified') }} ({{ result.modified.length }})
              </option>
              <option value="deleted">
                {{ t('project.verifyDeleted') }} ({{ result.deleted.length }})
              </option>
            </select>
          </div>

          <div class="detail-list">
            <div
              v-for="d in filteredDetails()"
              :key="d.filePath"
              class="detail-row"
              :class="d.status"
            >
              <component
                :is="statusIcon(d.status)"
                class="detail-icon"
                :style="{ color: statusColor(d.status) }"
              />
              <span class="detail-path">{{ d.filePath }}</span>
            </div>
            <div
              v-if="filteredDetails().length === 0"
              class="empty-detail"
            >
              {{ t('common.noData') }}
            </div>
          </div>
        </template>

        <div class="dialog-footer">
          <button
            class="btn btn-ghost btn-sm"
            @click="close"
          >
            {{ t('common.close') }}
          </button>
          <button
            v-if="result"
            class="btn btn-primary btn-sm"
            :disabled="verifying"
            @click="startVerify"
          >
            <ArrowPathIcon class="icon-sm" /> {{ t('common.refresh') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 10000; }
.dialog-card { background: var(--bg-primary); border: 1px solid var(--border); border-radius: calc(10px * var(--ui-scale, 1)); min-width: calc(480px * var(--ui-scale, 1)); max-width: calc(640px * var(--ui-scale, 1)); max-height: 80vh; display: flex; flex-direction: column; box-shadow: 0 8px 32px rgba(0,0,0,0.25); }
.dialog-header { display: flex; align-items: center; justify-content: space-between; padding: calc(12px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); border-bottom: 1px solid var(--border); }
.dialog-title { font-size: calc(13px * var(--ui-scale, 1)); font-weight: 600; color: var(--text-primary); }
.dialog-close { font-size: calc(18px * var(--ui-scale, 1)); color: var(--text-muted); background: none; border: none; cursor: pointer; padding: 0 calc(4px * var(--ui-scale, 1)); }
.dialog-close:hover { color: var(--text-primary); }
.dialog-loading { padding: calc(24px * var(--ui-scale, 1)); text-align: center; color: var(--text-muted); display: flex; align-items: center; justify-content: center; gap: calc(8px * var(--ui-scale, 1)); }
.spinner { width: calc(20px * var(--ui-scale, 1)); height: calc(20px * var(--ui-scale, 1)); border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.6s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.progress-section { padding: calc(20px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); display: flex; flex-direction: column; gap: calc(12px * var(--ui-scale, 1)); }
.progress-bar-track { height: calc(6px * var(--ui-scale, 1)); background: var(--bg-tertiary); border-radius: calc(3px * var(--ui-scale, 1)); overflow: hidden; }
.progress-bar-fill { height: 100%; background: var(--accent); border-radius: calc(3px * var(--ui-scale, 1)); transition: width 0.3s; }
.progress-info { font-size: calc(11px * var(--ui-scale, 1)); color: var(--text-muted); text-align: center; }
.error-section { padding: calc(20px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); }
.error-msg { font-size: calc(12px * var(--ui-scale, 1)); color: var(--error); text-align: center; }
.notice-section { margin: calc(12px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)) 0; padding: calc(8px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1)); border: 1px solid var(--warning); border-radius: calc(6px * var(--ui-scale, 1)); color: var(--warning); font-size: calc(11px * var(--ui-scale, 1)); }
.result-summary { padding: calc(12px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); display: flex; flex-direction: column; gap: calc(10px * var(--ui-scale, 1)); border-bottom: 1px solid var(--border); }
.baseline-info { display: flex; align-items: center; gap: calc(8px * var(--ui-scale, 1)); flex-wrap: wrap; font-size: calc(11px * var(--ui-scale, 1)); color: var(--text-muted); }
.hash-pair code { font-family: var(--font-mono); background: var(--bg-tertiary); padding: 1px calc(5px * var(--ui-scale, 1)); border-radius: calc(4px * var(--ui-scale, 1)); color: var(--text-primary); }
.hash-pair .arrow { margin: 0 calc(2px * var(--ui-scale, 1)); }
.chip { background: var(--bg-tertiary); border-radius: calc(4px * var(--ui-scale, 1)); padding: 1px calc(8px * var(--ui-scale, 1)); font-size: calc(10px * var(--ui-scale, 1)); }
.chip.dirty { color: var(--warning); }
.stats { display: flex; gap: calc(16px * var(--ui-scale, 1)); }
.stat-row { display: flex; align-items: center; gap: calc(6px * var(--ui-scale, 1)); font-size: calc(11px * var(--ui-scale, 1)); color: var(--text-primary); }
.stat-icon { width: calc(14px * var(--ui-scale, 1)); height: calc(14px * var(--ui-scale, 1)); }
.stat-icon.added { color: var(--success); }
.stat-icon.modified { color: var(--warning); }
.stat-icon.deleted { color: var(--error); }
.filter-bar { padding: calc(6px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); border-bottom: 1px solid var(--border); }
.filter-select { font-size: calc(11px * var(--ui-scale, 1)); padding: calc(3px * var(--ui-scale, 1)) calc(6px * var(--ui-scale, 1)); background: var(--bg-secondary); border: 1px solid var(--border); border-radius: calc(4px * var(--ui-scale, 1)); color: var(--text-primary); }
.detail-list { flex: 1; overflow-y: auto; padding: calc(4px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); max-height: calc(300px * var(--ui-scale, 1)); }
.detail-row { display: flex; align-items: center; gap: calc(6px * var(--ui-scale, 1)); padding: calc(4px * var(--ui-scale, 1)) calc(4px * var(--ui-scale, 1)); font-size: calc(10px * var(--ui-scale, 1)); }
.detail-row:hover { background: var(--bg-tertiary); border-radius: calc(4px * var(--ui-scale, 1)); }
.detail-icon { width: calc(12px * var(--ui-scale, 1)); height: calc(12px * var(--ui-scale, 1)); flex-shrink: 0; }
.detail-path { color: var(--text-primary); word-break: break-all; font-family: var(--font-mono); font-size: calc(10px * var(--ui-scale, 1)); }
.empty-detail { padding: calc(16px * var(--ui-scale, 1)); text-align: center; color: var(--text-muted); font-size: calc(11px * var(--ui-scale, 1)); }
.dialog-footer { display: flex; align-items: center; justify-content: flex-end; gap: calc(6px * var(--ui-scale, 1)); padding: calc(10px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); border-top: 1px solid var(--border); }
.icon-sm { width: calc(14px * var(--ui-scale, 1)); height: calc(14px * var(--ui-scale, 1)); }
</style>
