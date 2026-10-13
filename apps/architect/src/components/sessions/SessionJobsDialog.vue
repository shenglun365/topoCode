<script setup lang="ts">
/**
 * 作业历史弹窗(2610 统一列表): 取代原「执行器会话」标签的档案浏览职责。
 *
 * 数据面: GET /arch/exec-sessions(全量) 按 conversationId 前端过滤
 * (主行=直通/任务链作业; 子行=该子会话作业); ↗ 打开 /exec-session-view
 * 时间线深链; 删除=留痕档案+终态任务行(活跃拒绝, 与删除守卫同口径)。
 */
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  ArrowPathIcon, ArrowTopRightOnSquareIcon, TrashIcon, XMarkIcon,
} from '@heroicons/vue/24/outline'
import { useAppDialog } from '@/composables/useAppDialog'
import { apiDelete, apiGet } from '@/services/api-client'

interface JobRow {
  jobId: string
  title: string
  eventCount: number
  lastTs: number
  lastStatus: string
  taskId: string
  taskStatus: string
  executorType: string
  conversationId: string
}

const props = defineProps<{
  /** 目标会话(主/子): 列出其直发作业(conversationId 精确匹配) */
  session: { id: string; title: string } | null
}>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'changed'): void
}>()

const { t } = useI18n()
const router = useRouter()
const dialog = useAppDialog()
const rows = ref<JobRow[]>([])
const loading = ref(false)
const error = ref('')
const deleting = ref('')

async function load() {
  if (!props.session) return
  loading.value = true
  error.value = ''
  try {
    const all = await apiGet<JobRow[]>('/arch/exec-sessions?limit=200')
    rows.value = (all || []).filter((r) => r.conversationId === props.session!.id)
  } catch (e: any) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}
// immediate: v-if 挂载时 prop 已就位, watcher 需立即首拉(否则恒显空态)
watch(() => props.session, () => { void load() }, { immediate: true })

/** 活跃判定(与后端 delete_job_archive 口径一致): 无终态事件且任务未终态。
 *  2610 F3: input_required=保活等待输入(非终态, 禁删); stopped=用户中止(终态)。 */
const JOB_TERMINAL = ['done', 'failed', 'cancelled', 'stopped']
function isActive(r: JobRow): boolean {
  if (!r.lastStatus || r.lastStatus === 'input_required') return true
  return !!r.taskStatus && !JOB_TERMINAL.includes(r.taskStatus)
}
/** 状态 chip 文案(i18n; 未知原样回显) */
function statusLabel(r: JobRow): string {
  const map: Record<string, string> = {
    done: t('session.jobs.stDone'),
    failed: t('session.jobs.stFailed'),
    finished: t('session.jobs.stDone'),
    input_required: t('session.jobs.stWaiting'),
    stopped: t('session.jobs.stStopped'),
  }
  return map[r.lastStatus] || r.lastStatus || t('session.jobs.done')
}
function titleLine(r: JobRow): string {
  return r.title || r.jobId
}
const fmt = (ts: number) => ts ? new Date(ts < 1e12 ? ts * 1000 : ts).toLocaleString() : ''

function openTimeline(r: JobRow) {
  window.open(router.resolve({ path: '/exec-session-view', query: { job: r.jobId } }).href, '_blank')
}

async function onDelete(r: JobRow) {
  if (isActive(r) || deleting.value) return
  const ok = await dialog.confirm(
    t('session.jobs.deleteConfirm', { job: titleLine(r) }), { danger: true })
  if (!ok) return
  deleting.value = r.jobId
  try {
    await apiDelete(`/arch/exec-sessions/${encodeURIComponent(r.jobId)}`)
    await load()
    emit('changed')
  } catch (e: any) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    deleting.value = ''
  }
}
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 p-4 backdrop-blur-sm"
    @click.self="emit('close')"
  >
    <div class="panel flex max-h-[75vh] w-full max-w-md flex-col">
      <div class="panel-header shrink-0">
        <span class="truncate">{{ t('session.jobs.title') }} · {{ session?.title || '' }}</span>
        <button class="btn btn-xs btn-ghost" @click="emit('close')">
          <XMarkIcon class="w-3.5 h-3.5" />
        </button>
      </div>

      <div class="min-h-0 flex-1 overflow-auto p-3 text-xs">
        <p v-if="loading" class="py-6 text-center text-ctp-overlay0">{{ t('common.loading') }}</p>
        <p v-else-if="error" class="rounded-lg bg-ctp-red/10 p-2 text-ctp-red break-all">{{ error }}</p>

        <template v-else>
          <ul v-if="rows.length" class="space-y-1.5">
            <li
              v-for="r in rows" :key="r.jobId"
              class="rounded-lg border border-ctp-surface1 px-2.5 py-1.5"
            >
              <div class="flex items-center gap-1.5">
                <span
                  class="chip shrink-0"
                  :class="isActive(r) ? 'animate-pulse bg-ctp-peach/20 text-ctp-peach' : 'bg-ctp-green/15 text-ctp-green'"
                >{{ isActive(r) ? t('session.jobs.active') : statusLabel(r) }}</span>
                <span v-if="r.executorType" class="chip shrink-0 bg-ctp-surface0 text-ctp-subtext0">{{ r.executorType }}</span>
                <span class="min-w-0 flex-1 truncate font-medium" :title="titleLine(r)">{{ titleLine(r) }}</span>
              </div>
              <div class="mt-1 flex items-center gap-2 text-[10px] text-ctp-overlay0">
                <span class="min-w-0 flex-1 truncate font-mono" :title="r.jobId">{{ r.jobId }}</span>
                <span class="shrink-0 tabular-nums">{{ r.eventCount }} ev</span>
                <span class="shrink-0 tabular-nums">{{ fmt(r.lastTs) }}</span>
                <button
                  class="shrink-0 text-ctp-sky hover:underline"
                  :title="t('session.jobs.openTimeline')"
                  @click="openTimeline(r)"
                ><ArrowTopRightOnSquareIcon class="h-3 w-3 inline" /></button>
                <button
                  class="shrink-0 rounded p-0.5"
                  :class="isActive(r)
                    ? 'pointer-events-none text-ctp-overlay0 opacity-40'
                    : 'text-ctp-overlay0 hover:bg-ctp-surface1 hover:text-ctp-red'"
                  :title="isActive(r)
                    ? t('session.subs.cannotDeleteRunning') : t('session.jobs.delete')"
                  @click="onDelete(r)"
                >
                  <TrashIcon class="h-3 w-3" :class="deleting === r.jobId ? 'animate-pulse' : ''" />
                </button>
              </div>
            </li>
          </ul>
          <p v-else class="py-6 text-center text-ctp-overlay0">{{ t('session.jobs.empty') }}</p>
          <p class="mt-2 text-[10px] text-ctp-overlay0">{{ t('session.jobs.hint') }}</p>
        </template>
      </div>
    </div>
  </div>
</template>
