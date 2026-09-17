<script setup lang="ts">
/**
 * 会话中心左栏 · 需求跟踪(标签页内容区)。
 *
 * 条目 = 工作记录六维度: 谁创建 / 内容 / 待谁操作 / 操作类型 / 结果 / 当前状态。
 *  - 数据: 跨会话全量(scope=all), 条目带 主/子会话双 ID(精确跟踪需求执行链);
 *  - 自动挂账: 任务/回执/需求/决策/异常在后端事件点写入; 此处支持手动补挂与流转
 *    (标记完成/取消、有效性作废/恢复);
 *  - 联动: 点击条目 → 打开其主会话(左列表高亮 + 右栏对话载入)。
 * 筛选控件在页面顶栏(与顶栏整合), 经 props 透传; 加载时机: 挂载/筛选变化/刷新 nonce。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckIcon, ChevronDownIcon, PlusIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import { trackingService, type TrackingItem, type TrackingVocab } from '@/services/tracking-service'
import type { ConversationMeta } from '@/services/session-service'
import { useConversationStore } from '@/stores/conversation-store'

const props = defineProps<{
  /** 会话中心已加载的会话列表: 主会话标题映射与打开联动。 */
  sessions?: ConversationMeta[]
  /** 筛选状态(顶栏持有): 分类/状态/待办角色/关键字。 */
  category?: string
  state?: string
  assignee?: string
  q?: string
  /** 顶栏刷新按钮 nonce: 变化即重载。 */
  refreshNonce?: number
  /** 字典(顶栏一次拉取, 传引用): 分类/操作类型/角色/状态。 */
  vocab?: TrackingVocab | null
}>()

const emit = defineEmits<{
  (e: 'count', n: number): void
  (e: 'loading', v: boolean): void
}>()

const { t } = useI18n()
const conv = useConversationStore()

const loading = ref(false)
const loadError = ref(false)
const items = ref<TrackingItem[]>([])

const STATE_CLS: Record<string, string> = {
  running: 'bg-ctp-blue/15 text-ctp-blue',
  waiting: 'bg-ctp-yellow/15 text-ctp-yellow',
  done: 'bg-ctp-green/15 text-ctp-green',
  failed: 'bg-ctp-red/15 text-ctp-red',
  cancelled: 'bg-ctp-surface0 text-ctp-overlay0',
}
const ROLE_CLS: Record<string, string> = {
  user: 'bg-ctp-peach/15 text-ctp-peach',
  architect: 'bg-ctp-sky/15 text-ctp-sky',
  coding: 'bg-ctp-mauve/15 text-ctp-mauve',
}

function stateLabel(s: string): string {
  const key = `session.tracking.state.${s}`
  const label = t(key)
  return label === key ? s : label
}
function roleLabel(r: string): string {
  const key = `session.tracking.role.${r}`
  const label = t(key)
  return label === key ? r : label
}

const filtered = computed(() => {
  // 服务端已按筛选查询; 此处仅作 valid 过滤兜底(作废条目默认隐藏)
  return items.value
})

async function load() {
  loading.value = true
  emit('loading', true)
  loadError.value = false
  try {
    const r = await trackingService.list({
      category: props.category || undefined,
      state: props.state || undefined,
      assignee: props.assignee || undefined,
      q: (props.q || '').trim() || undefined,
      scope: 'all',
      limit: 300,
    })
    items.value = r?.items || []
    emit('count', items.value.length)
  } catch { loadError.value = true } finally {
    loading.value = false
    emit('loading', false)
  }
}

// ── 联动: 打开主会话(子会话不在会话列表时回退主会话) ──
function convTitle(id?: string): string {
  if (!id) return ''
  return (props.sessions ?? []).find((c) => c.id === id)?.title || id
}
function openSource(item: TrackingItem) {
  const target = item.mainConversationId || item.conversationId || ''
  const meta = (props.sessions ?? []).find((c) => c.id === target)
  if (meta) void conv.openConversation(meta)
}

// ── 流转/有效性(人工处理面) ──
const busyId = ref('')
async function markState(item: TrackingItem, state: string, resultState?: string) {
  if (busyId.value) return
  busyId.value = item.id
  try {
    const updated = await trackingService.update(item.id, { state, resultState })
    replace(updated)
  } catch { /* 静默 */ } finally { busyId.value = '' }
}
async function toggleValid(item: TrackingItem) {
  if (busyId.value) return
  busyId.value = item.id
  try {
    const updated = await trackingService.update(item.id, { valid: !item.valid })
    replace(updated)
  } catch { /* 静默 */ } finally { busyId.value = '' }
}
function replace(updated: TrackingItem) {
  const i = items.value.findIndex((x) => x.id === updated.id)
  if (i >= 0) items.value[i] = updated
}

// ── 手动挂账(内联表单; 字典由顶栏 vocab prop 提供) ──
const addOpen = ref(false)
const addBusy = ref(false)
const addForm = ref({ category: '', title: '', content: '', actionType: '', assigneeRole: '' })
function openAdd() {
  addOpen.value = !addOpen.value
}
async function submitAdd() {
  const title = addForm.value.title.trim()
  if (!title || addBusy.value) return
  addBusy.value = true
  try {
    const row = await trackingService.create({
      category: addForm.value.category,
      title, content: addForm.value.content,
      actionType: addForm.value.actionType,
      assigneeRole: addForm.value.assigneeRole,
      state: addForm.value.assigneeRole ? 'waiting' : 'done',
      waitingFor: addForm.value.assigneeRole,
      conversationId: conv.activeId || '',
    })
    items.value = [row, ...items.value]
    emit('count', items.value.length)
    addOpen.value = false
    addForm.value = { category: '', title: '', content: '', actionType: '', assigneeRole: '' }
  } catch { /* 静默 */ } finally { addBusy.value = false }
}

// 会话集合变更(新会话/沉淀) → 同步刷新; 会话删除(后端级联清台账) → 重载
function onSessionsChanged() { void load() }
function onConversationRemoved() { void load() }
onMounted(() => {
  window.addEventListener('arch:sessions-changed', onSessionsChanged)
  window.addEventListener('arch:conversation-removed', onConversationRemoved)
  void load()
})
onUnmounted(() => {
  window.removeEventListener('arch:sessions-changed', onSessionsChanged)
  window.removeEventListener('arch:conversation-removed', onConversationRemoved)
})

watch(() => [props.category, props.state, props.assignee], () => { void load() })
watch(() => props.refreshNonce, () => { void load() })

function fmtTime(ts: unknown): string {
  const n = Number(ts)
  return n ? new Date(n).toLocaleString() : ''
}
</script>

<template>
  <section class="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden panel">
    <!-- 头行: 挂账入口 -->
    <div class="flex shrink-0 items-center gap-1.5 border-b border-ctp-surface0 px-2 py-1.5">
      <span class="text-[10px] font-medium text-ctp-subtext1">{{ t('session.tracking.title') }}</span>
      <span class="flex-1" />
      <button
        class="btn btn-xs"
        :class="addOpen ? 'btn-blue' : 'btn-ghost'"
        :title="t('session.tracking.add')"
        @click="openAdd"
      >
        <PlusIcon class="w-3 h-3" />{{ t('session.tracking.add') }}
      </button>
    </div>

    <!-- 手动挂账表单 -->
    <div v-if="addOpen" class="shrink-0 space-y-1 border-b border-ctp-surface0 px-2 py-2">
      <input
        v-model="addForm.title"
        class="input !py-1 !text-[11px] w-full"
        :placeholder="t('session.tracking.titlePh')"
        @keydown.enter="submitAdd"
      >
      <textarea
        v-model="addForm.content"
        rows="2"
        class="input !py-1 !text-[11px] w-full resize-y"
        :placeholder="t('session.tracking.contentPh')"
      />
      <div class="flex flex-wrap items-center gap-1">
        <select v-model="addForm.category" class="input !w-auto !py-0.5 !px-1.5 !text-[10px]">
          <option value="">{{ t('session.tracking.allCategories') }}</option>
          <option v-for="c in (vocab?.categories ?? [])" :key="c" :value="c">{{ c }}</option>
        </select>
        <select v-model="addForm.actionType" class="input !w-auto !py-0.5 !px-1.5 !text-[10px]">
          <option value="">{{ t('session.tracking.allActionTypes') }}</option>
          <option v-for="a in (vocab?.actionTypes ?? [])" :key="a" :value="a">{{ a }}</option>
        </select>
        <select v-model="addForm.assigneeRole" class="input !w-auto !py-0.5 !px-1.5 !text-[10px]">
          <option value="">{{ t('session.tracking.noAssignee') }}</option>
          <option v-for="r in (vocab?.roles ?? [])" :key="r" :value="r">{{ roleLabel(r) }}</option>
        </select>
        <span class="flex-1" />
        <button class="btn btn-xs btn-ghost" @click="addOpen = false">
          <XMarkIcon class="w-3 h-3" />
        </button>
        <button class="btn btn-xs btn-blue" :disabled="addBusy || !addForm.title.trim()" @click="submitAdd">
          <CheckIcon class="w-3 h-3" />
        </button>
      </div>
    </div>

    <!-- 条目列表 -->
    <div class="min-h-0 flex-1 overflow-y-auto p-2">
      <p
        v-if="!filtered.length && !loading"
        class="py-6 text-center text-[10px] text-ctp-overlay0"
      >{{ loadError ? t('session.tracking.loadFailed') : t('session.tracking.empty') }}</p>
      <div
        v-for="item in filtered"
        :key="item.id"
        class="group mb-1 rounded border px-2 py-1.5 transition-colors"
        :class="[
          item.valid ? 'border-ctp-surface1 bg-ctp-mantle/60' : 'border-ctp-surface0 bg-ctp-surface0/30 opacity-60',
          item.id === busyId ? 'animate-pulse' : '',
        ]"
      >
        <div class="flex items-center gap-1.5">
          <span
            v-if="item.category"
            class="chip shrink-0 bg-ctp-surface1 font-mono !text-[9px] text-ctp-overlay1"
          >{{ item.category }}</span>
          <span
            v-if="item.actionType"
            class="chip shrink-0 bg-ctp-teal/15 font-mono !text-[9px] text-ctp-teal"
          >{{ item.actionType }}</span>
          <span
            class="min-w-0 flex-1 cursor-pointer truncate text-[11px] text-ctp-text"
            :title="item.title"
            @click="openSource(item)"
          >{{ item.title || t('session.tracking.untitled') }}</span>
          <span class="chip shrink-0 font-mono !text-[9px]" :class="STATE_CLS[item.state] || 'bg-ctp-surface0 text-ctp-overlay0'">
            {{ stateLabel(item.state) }}<template v-if="item.state === 'waiting' && item.waitingFor">·{{ roleLabel(item.waitingFor) }}</template>
          </span>
          <!-- 行内流转 -->
          <span class="hidden shrink-0 items-center gap-0.5 group-hover:flex">
            <button
              v-if="item.state !== 'done'"
              class="rounded p-0.5 text-ctp-overlay0 hover:text-ctp-green"
              :title="t('session.tracking.markDone')"
              @click="markState(item, 'done', 'ok')"
            ><CheckIcon class="h-3 w-3" /></button>
            <button
              class="rounded p-0.5 text-ctp-overlay0 hover:text-ctp-peach"
              :title="item.valid ? t('session.tracking.invalid') : t('session.tracking.restore')"
              @click="toggleValid(item)"
            >{{ item.valid ? '🚫' : '↺' }}</button>
          </span>
        </div>
        <p
          v-if="item.content"
          class="mt-0.5 truncate text-[9px] text-ctp-overlay0"
          :title="item.content"
        >{{ item.content }}</p>
        <div class="mt-0.5 flex flex-wrap items-center gap-1 text-[9px] text-ctp-overlay0">
          <span v-if="item.creatorRole" class="chip shrink-0 !text-[8px]" :class="ROLE_CLS[item.creatorRole] || 'bg-ctp-surface0 text-ctp-overlay0'">
            {{ t('session.tracking.creator') }}: {{ roleLabel(item.creatorRole) }}<template v-if="item.creatorId">·{{ item.creatorId }}</template>
          </span>
          <span v-if="item.assigneeRole" class="chip shrink-0 bg-ctp-surface0 !text-[8px] text-ctp-subtext0">
            {{ t('session.tracking.assignee') }}: {{ roleLabel(item.assigneeRole) }}<template v-if="item.assigneeId">·{{ item.assigneeId }}</template>
          </span>
          <span
            v-if="item.mainConversationId"
            class="shrink-0 cursor-pointer hover:text-ctp-sky"
            :title="t('session.tracking.mainConv')"
            @click="openSource(item)"
          >{{ t('session.tracking.mainConv') }}: {{ convTitle(item.mainConversationId) }}</span>
          <span
            v-if="item.conversationId && item.conversationId !== item.mainConversationId"
            class="shrink-0 truncate"
            :title="t('session.tracking.subConv')"
          >{{ t('session.tracking.subConv') }}: {{ convTitle(item.conversationId) }}</span>
          <span
            v-if="item.result"
            class="min-w-0 flex-1 truncate"
            :class="item.resultState === 'failed' ? 'text-ctp-red' : 'text-ctp-subtext0'"
            :title="item.result"
          >{{ t('session.tracking.result') }}: {{ item.result }}</span>
          <span class="ml-auto shrink-0">{{ fmtTime(item.createdAt) }}</span>
        </div>
      </div>
    </div>
  </section>
</template>
