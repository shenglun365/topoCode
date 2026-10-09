<script setup lang="ts">
/**
 * 执行器会话列表(2026-10 会话中心并入)——双形态复用:
 * - mode=page  : 独立页(ExecSessionsPage)——点行=打开时间线, ↗跳会话中心
 * - mode=panel : 会话中心左栏标签(SessionsPage)——点行=右侧打开关联会话
 *   (dock 对话流), ↗=浏览器新 tab 打开独立页(?job= 定位)
 * 数据面: GET /arch/exec-sessions(architect 自持留痕)。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { ArrowPathIcon, CommandLineIcon, ArrowTopRightOnSquareIcon } from '@heroicons/vue/24/outline'
import { apiGet } from '@/services/api-client'

const props = withDefaults(defineProps<{
  /** page=独立页(点行选时间线); panel=会话中心(点行右侧打开对话) */
  mode?: 'page' | 'panel'
  /** 面板态: 期望展示的项目过滤(会话中心按当前项目)。空=全部 */
  projectId?: string
}>(), { mode: 'page', projectId: '' })

const emit = defineEmits<{
  (e: 'chat', conversationId: string, jobId: string): void
  (e: 'job', jobId: string, row?: SessionRow): void
}>()

const { t } = useI18n()
const router = useRouter()

interface SessionRow {
  jobId: string; eventCount: number; firstTs: number; lastTs: number
  lastStatus: string; taskId: string; title: string; executorType: string
  conversationId: string; sessionRef: string; taskStatus: string
}

const sessions = ref<SessionRow[]>([])
const selected = ref('')
const loading = ref(false)
let timer: number | undefined

const isActive = (s: SessionRow) => !s.lastStatus && s.taskStatus !== 'done'

const execStats = computed(() => {
  const m: Record<string, number> = {}
  for (const s of sessions.value) m[s.executorType || '?'] = (m[s.executorType || '?'] || 0) + 1
  return Object.entries(m).sort((a, b) => b[1] - a[1])
})

const fmt = (ts: number) => ts ? new Date(ts < 1e12 ? ts * 1000 : ts).toLocaleTimeString() : ''

async function loadSessions() {
  loading.value = true
  try {
    sessions.value = await apiGet<SessionRow[]>('/arch/exec-sessions?limit=100')
  } finally { loading.value = false }
}

function rowClick(s: SessionRow) {
  if (props.mode === 'panel') {
    if (s.conversationId) emit('chat', s.conversationId, s.jobId)
    else emit('job', s.jobId, s)                  // 无关联会话 → 父级决定(新 tab)
    return
  }
  selected.value = s.jobId
  emit('job', s.jobId, s)
}

function openNewTab(s: SessionRow) {
  // hash 路由: router.resolve 生成 #/…?job= 深链(new URL path 风格会 404)
  window.open(router.resolve({ path: '/workbench/exec-sessions', query: { job: s.jobId } }).href, '_blank')
}

onMounted(() => {
  loadSessions()
  // 面板态 10s 轻刷新(会话中心常驻); 独立页无自动刷(原页行为)
  if (props.mode === 'panel') timer = window.setInterval(loadSessions, 10000)
})
onBeforeUnmount(() => { if (timer) window.clearInterval(timer) })

defineExpose({ loadSessions })
</script>

<template>
  <div class="flex flex-col min-h-0">
    <!-- 执行器分布 -->
    <div v-if="execStats.length" class="flex items-center gap-1.5 flex-wrap px-1 pb-2">
      <span
        v-for="[ex, n] in execStats" :key="ex"
        class="chip bg-ctp-surface0 text-ctp-subtext0 !text-[9px]"
      >{{ ex }} × {{ n }}</span>
    </div>

    <div class="overflow-auto flex-1 divide-y divide-ctp-surface0">
      <div
        v-for="s in sessions" :key="s.jobId"
        class="w-full text-left px-3 py-2 text-xs cursor-pointer"
        :class="s.jobId === selected && mode === 'page' ? 'bg-ctp-surface1' : 'hover:bg-ctp-surface0/50'"
        @click="rowClick(s)"
      >
        <div class="flex items-center gap-1.5">
          <span class="chip shrink-0 bg-ctp-surface0 text-ctp-subtext0">{{ s.executorType || '?' }}</span>
          <span class="flex-1 truncate font-medium" :title="s.title || s.jobId">{{ s.title || s.jobId }}</span>
          <span v-if="isActive(s)" class="w-1.5 h-1.5 rounded-full bg-ctp-green shrink-0 animate-pulse" />
          <button
            class="shrink-0 text-[10px] text-ctp-sky hover:underline"
            :title="mode === 'panel' ? t('execSessions.newTab') : t('execSessions.openConv')"
            @click.stop="openNewTab(s)"
          ><ArrowTopRightOnSquareIcon class="w-3 h-3 inline" /></button>
        </div>
        <div class="text-[10px] text-ctp-overlay0 mt-0.5 flex gap-2">
          <span>{{ s.eventCount }} ev</span>
          <span>{{ fmt(s.lastTs) }}</span>
          <span v-if="s.lastStatus">{{ s.lastStatus }}</span>
          <span v-if="mode === 'panel' && !s.conversationId" class="text-ctp-overlay0">
            {{ t('execSessions.noConvHint') }}
          </span>
        </div>
      </div>
      <div v-if="!sessions.length && !loading" class="px-3 py-8 text-center text-xs text-ctp-overlay0">
        {{ t('execSessions.empty') }}
      </div>
    </div>

    <div class="flex items-center gap-1.5 px-1 pt-2 text-[10px] text-ctp-overlay0">
      <button class="btn btn-xs !py-0.5" :disabled="loading" @click="loadSessions">
        <ArrowPathIcon class="w-3 h-3" />{{ t('common.refresh') }}
      </button>
      <span class="ml-auto">{{ t('execSessions.centerHint') }}</span>
    </div>
  </div>
</template>
