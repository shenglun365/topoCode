<script setup lang="ts">
// cv-284 需求浮层大窗(共享组件, 多入口挂载): 全文渲染(spec-view 组装单源)+
// 版本切换器(specVersions 链任意版浏览, 旧版快照只读)+编辑入口(EditSpecModal
// 复用, 仅最新版)+关联任务清单(specVer 建卡固化标注)。
// 入口: 消息流需求卡放大钮(ChatFeedPanel)/会话列表需求跟踪条(ConversationDock)。
import { computed, ref, watch } from 'vue'
import { apiGet } from '@/services/api-client'
import { assembleSpecView } from '@/services/spec-view'
import ChatMessageBlocks from '@/components/ChatMessageBlocks.vue'
import EditSpecModal from '@/components/requirements/EditSpecModal.vue'

const props = defineProps<{
  requirementId: string
  convId?: string
  showGenerate?: boolean   // 任务生成钮(需会话发送通道的宿主才开启)
}>()

const emit = defineEmits<{
  close: []
  'generate-tasks': []
}>()

interface SpecVersionRow {
  ver: number
  state: string
  snapshot: Record<string, unknown>
  source?: Record<string, unknown>
  reason?: string
  createdAt?: number
}

const row = ref<{ title?: string; status?: string; activeVer?: number;
                  specVersions?: SpecVersionRow[] } | null>(null)
const selVer = ref(0)
const tasks = ref<Array<Record<string, any>>>([])
const editing = ref(false)
const execBusy = ref(false)
const execMsg = ref('')

async function load() {
  try {
    row.value = await apiGet(`/requirements/${encodeURIComponent(props.requirementId)}`)
    selVer.value = Number(row.value?.activeVer || 0)
      || (row.value?.specVersions || []).length
  } catch { row.value = null }
  if (props.convId) {
    try {
      const r = await apiGet<{ tasks?: Array<Record<string, any>> }>(
        `/tasks?convId=${encodeURIComponent(props.convId)}`)
      tasks.value = (r.tasks || []).filter(
        (t) => String(t.reqId || '') === props.requirementId)
    } catch { tasks.value = [] }
  }
}
watch(() => props.requirementId, () => { void load() }, { immediate: true })

const versions = computed(() => row.value?.specVersions || [])
const selected = computed(() =>
  versions.value.find((v) => v.ver === selVer.value)
  || versions.value[versions.value.length - 1] || null)
const isLatest = computed(() =>
  !versions.value.length || selVer.value
    === Math.max(...versions.value.map((v) => v.ver)))
const view = computed(() =>
  assembleSpecView((selected.value?.snapshot || {}) as Record<string, unknown>,
    String(row.value?.title || '')))

const statusView: Record<string, { label: string; cls: string }> = {
  running: { label: '执行中', cls: 'bg-ctp-green/15 text-ctp-green' },
  waiting_input: { label: '待输入', cls: 'bg-ctp-yellow/15 text-ctp-yellow' },
  failed: { label: '失败', cls: 'bg-ctp-red/15 text-ctp-red' },
  done: { label: '已完成', cls: 'bg-ctp-overlay0/15 text-ctp-overlay1' },
  saved: { label: '待执行', cls: 'bg-ctp-blue/15 text-ctp-blue' },
  cancelled: { label: '已取消', cls: 'bg-ctp-overlay0/15 text-ctp-overlay0' },
  ignored: { label: '已忽略', cls: 'bg-ctp-overlay0/10 text-ctp-overlay0' },
}
const verStateView: Record<string, { label: string; cls: string }> = {
  confirmed: { label: '生效', cls: 'bg-ctp-mauve/15 text-ctp-mauve' },
  draft: { label: '草稿', cls: 'bg-ctp-blue/15 text-ctp-blue' },
  superseded: { label: '历史', cls: 'bg-ctp-surface0 text-ctp-overlay0' },
}

async function executeNow() {
  if (execBusy.value || !props.convId) return
  execBusy.value = true
  execMsg.value = ''
  try {
    const { apiPost } = await import('@/services/api-client')
    await apiPost(`/requirements/${encodeURIComponent(props.requirementId)}/execute-now`,
      { convId: props.convId })
    execMsg.value = '已启动——进展见会话任务卡'
    void load()
  } catch (e) {
    execMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    execBusy.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-6"
      @click.self="emit('close')"
    >
      <div class="flex w-[85vw] max-w-5xl max-h-[85vh] flex-col rounded-lg border border-ctp-surface1 bg-ctp-base shadow-2xl">
        <div class="flex shrink-0 flex-wrap items-center gap-2 border-b border-ctp-surface1 px-4 py-2.5">
          <span class="text-xs font-semibold text-ctp-blue">需求卡</span>
          <span class="font-mono text-[10px] text-ctp-overlay1">{{ requirementId }}</span>
          <span
            v-if="row?.title"
            class="max-w-48 truncate text-xs font-medium text-ctp-text"
          >{{ row.title }}</span>
          <span class="flex-1" />
          <!-- 版本切换器: 旧版快照只读浏览 -->
          <button
            v-for="v in versions"
            :key="v.ver"
            class="chip !px-1.5 !text-[9px] font-mono cursor-pointer"
            :class="v.ver === selVer
              ? 'bg-ctp-blue/20 text-ctp-blue' : 'bg-ctp-surface0 text-ctp-overlay0 hover:text-ctp-subtext1'"
            :title="`${verStateView[v.state]?.label || v.state}${v.reason ? ' · ' + v.reason : ''}`"
            @click="selVer = v.ver"
          >v{{ v.ver }}<span
            v-if="verStateView[v.state]"
            class="ml-0.5 opacity-70"
          >{{ verStateView[v.state].label }}</span></button>
          <button
            v-if="isLatest"
            class="btn btn-xs btn-ghost"
            title="编辑需求内容 — 保存后生成新版(v+1)，旧版保留"
            @click="editing = true"
          >✎ 编辑</button>
          <button class="btn btn-xs btn-ghost" @click="emit('close')">✕ 关闭</button>
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto px-5 py-3">
          <div
            v-if="!isLatest"
            class="mb-2 rounded-md border border-ctp-overlay0/20 bg-ctp-surface0/40 px-2.5 py-1.5 text-[10px] text-ctp-overlay0"
          >历史版本快照 v{{ selVer }}（只读）——执行始终取台账最新规约</div>
          <ChatMessageBlocks :content="view.body" />
          <div
            v-if="convId && tasks.length"
            class="mt-4 border-t border-ctp-surface1 pt-2"
          >
            <div class="mb-1.5 text-[11px] font-medium text-ctp-subtext1">
              关联任务（{{ tasks.length }}）——建卡时固化规约版本
            </div>
            <div class="space-y-1">
              <div
                v-for="t in tasks"
                :key="t.id"
                class="flex items-center gap-2 rounded-md border border-ctp-surface1 bg-ctp-mantle/60 px-2.5 py-1.5 text-[11px]"
              >
                <span class="truncate">{{ t.title }}</span>
                <span
                  v-if="t.specVer"
                  class="chip !px-1.5 !text-[9px] bg-ctp-mauve/15 text-ctp-mauve font-mono shrink-0"
                  title="本任务绑定需求规约(建卡时固化)"
                >规约 v{{ t.specVer }}</span>
                <span
                  class="chip !text-[9px] shrink-0"
                  :class="statusView[t.status]?.cls || 'bg-ctp-surface1 text-ctp-subtext0'"
                >{{ statusView[t.status]?.label || t.status }}</span>
              </div>
            </div>
          </div>
        </div>
        <div
          v-if="isLatest"
          class="flex shrink-0 flex-wrap items-center gap-2 border-t border-ctp-surface1 px-4 py-2"
        >
          <button
            v-if="showGenerate"
            class="btn btn-xs btn-primary"
            title="按规约生成任务计划——任务卡确认后执行"
            @click="emit('generate-tasks')"
          >任务生成</button>
          <button
            class="btn btn-xs btn-blue"
            :disabled="execBusy || !convId"
            :title="convId ? '免任务计划——以需求最新版直接创建单任务并立即执行' : '需要会话上下文'"
            @click="executeNow"
          >{{ execBusy ? '启动中…' : '立即执行' }}</button>
          <span
            v-if="execMsg"
            class="text-[10px] text-ctp-overlay0"
          >{{ execMsg }}</span>
          <span
            v-if="!showGenerate"
            class="text-[10px] text-ctp-overlay0"
          >任务生成请在会话内操作（按规约生成任务计划）</span>
        </div>
      </div>
    </div>
    <EditSpecModal
      v-if="editing"
      :requirement-id="requirementId"
      :title="String(selected?.snapshot?.title || row?.title || '')"
      :desc="String(selected?.snapshot?.desc || '')"
      :conv-id="convId"
      @close="editing = false"
    />
  </Teleport>
</template>
