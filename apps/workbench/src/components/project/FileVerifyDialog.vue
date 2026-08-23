<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, CheckCircleIcon, XCircleIcon, QuestionMarkCircleIcon } from '@heroicons/vue/24/outline'

const { t } = useI18n()

const props = defineProps<{ projectId: string }>()
const emit = defineEmits<{ close: [] }>()

interface VerifyDetail {
  filePath: string
  status: 'matched' | 'mismatch' | 'missing'
  expectedHash: string
  actualHash: string
}

interface VerifyResult {
  total: number
  matched: number
  mismatch: number
  missing: number
  matchRate: number
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
  }, 10000)
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

function statusIcon(status: string) {
  if (status === 'matched') return CheckCircleIcon
  if (status === 'mismatch') return XCircleIcon
  return QuestionMarkCircleIcon
}

function statusColor(status: string) {
  if (status === 'matched') return 'var(--success)'
  if (status === 'mismatch') return 'var(--error)'
  return 'var(--text-muted)'
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
          <span class="dialog-title">{{ t('project.verifyFiles', '文件比对') }}</span>
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
            {{ message || t('common.processing', '处理中...') }}
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
          <div class="result-summary">
            <div
              class="match-ring"
              :class="{ 'high': result.matchRate >= 80, 'mid': result.matchRate >= 50 && result.matchRate < 80, 'low': result.matchRate < 50 }"
            >
              <svg
                viewBox="0 0 120 120"
                class="ring-svg"
              >
                <circle
                  cx="60"
                  cy="60"
                  r="52"
                  fill="none"
                  stroke="var(--bg-tertiary)"
                  stroke-width="8"
                />
                <circle
                  cx="60"
                  cy="60"
                  r="52"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="8"
                  :stroke-dasharray="`${result.matchRate / 100 * 327} 327`"
                  transform="rotate(-90, 60, 60)"
                  stroke-linecap="round"
                />
              </svg>
              <div class="match-rate-text">
                {{ result.matchRate }}%
              </div>
            </div>
            <div class="stats">
              <div class="stat-row">
                <CheckCircleIcon class="stat-icon matched" /><span>{{ t('project.verifyMatched', '匹配') }}: {{ result.matched }}</span>
              </div>
              <div class="stat-row">
                <XCircleIcon class="stat-icon mismatched" /><span>{{ t('project.verifyMismatch', '不匹配') }}: {{ result.mismatch }}</span>
              </div>
              <div class="stat-row">
                <QuestionMarkCircleIcon class="stat-icon missing" /><span>{{ t('project.verifyMissing', '缺失') }}: {{ result.missing }}</span>
              </div>
            </div>
          </div>

          <div class="filter-bar">
            <select
              v-model="filterStatus"
              class="filter-select"
            >
              <option value="all">
                {{ t('common.all', '全部') }} ({{ result.total }})
              </option>
              <option value="matched">
                {{ t('project.verifyMatched', '匹配') }} ({{ result.matched }})
              </option>
              <option value="mismatch">
                {{ t('project.verifyMismatch', '不匹配') }} ({{ result.mismatch }})
              </option>
              <option value="missing">
                {{ t('project.verifyMissing', '缺失') }} ({{ result.missing }})
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
              {{ t('common.noData', '无数据') }}
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
.dialog-card { background: var(--bg-primary); border: 1px solid var(--border); border-radius: calc(10px * var(--ui-scale, 1)); min-width: calc(480px * var(--ui-scale, 1)); max-width: calc(560px * var(--ui-scale, 1)); max-height: 80vh; display: flex; flex-direction: column; box-shadow: 0 8px 32px rgba(0,0,0,0.25); }
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
.result-summary { padding: calc(16px * var(--ui-scale, 1)); display: flex; align-items: center; gap: calc(20px * var(--ui-scale, 1)); border-bottom: 1px solid var(--border); }
.match-ring { position: relative; width: calc(80px * var(--ui-scale, 1)); height: calc(80px * var(--ui-scale, 1)); flex-shrink: 0; }
.ring-svg { width: 100%; height: 100%; }
.match-ring.high { color: var(--success); }
.match-ring.mid { color: #f59e0b; }
.match-ring.low { color: var(--error); }
.match-rate-text { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-size: calc(16px * var(--ui-scale, 1)); font-weight: 700; font-family: var(--font-mono); }
.stats { display: flex; flex-direction: column; gap: calc(4px * var(--ui-scale, 1)); }
.stat-row { display: flex; align-items: center; gap: calc(6px * var(--ui-scale, 1)); font-size: calc(11px * var(--ui-scale, 1)); color: var(--text-primary); }
.stat-icon { width: calc(14px * var(--ui-scale, 1)); height: calc(14px * var(--ui-scale, 1)); }
.stat-icon.matched { color: var(--success); }
.stat-icon.mismatched { color: var(--error); }
.stat-icon.missing { color: var(--text-muted); }
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
