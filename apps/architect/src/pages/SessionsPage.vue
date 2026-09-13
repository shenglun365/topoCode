<script setup lang="ts">
/**
 * 会话中心(P1) —— 会话是唯一主体，流程不复存在。
 * 组织维度: 时间/模块/自定义分组(元数据)；流程视图=过滤器。
 * 详情: 摘要/备案文档/关联执行；对话本体在全局会话栏(ConversationDock)。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  ChatBubbleOvalLeftEllipsisIcon, MagnifyingGlassIcon, PlusIcon, ArrowPathIcon,
  DocumentArrowDownIcon, TagIcon, TrashIcon, PencilSquareIcon, SparklesIcon, CheckIcon,
  ArrowUpTrayIcon, ArrowDownTrayIcon, BoltIcon,
  FolderIcon, ClockIcon, XMarkIcon, ClipboardDocumentIcon, StopIcon,
} from '@heroicons/vue/24/outline'
import { useConversationStore } from '@/stores/conversation-store'
import { useAppDialog } from '@/composables/useAppDialog'
import { sessionService, type ContextUnit, type ConversationMeta, type SessionDoc } from '@/services/session-service'
import { apiGet, apiPost } from '@/services/api-client'
import { projectService } from '@/services/project-service'
import { copyText } from '@/utils/clipboard'
import { useSplitPane } from '@/composables/useSplitPane'
import ConversationDock from '@/components/chat/ConversationDock.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const conv = useConversationStore()

// ── 布局: 左栏信息(列表+详情) / 右栏对话(inline 停靠)——与资产地图页同构 ──
const { splitPct, dragging, boxRef: splitBoxRef, onDown: onSplitPointerDown } = useSplitPane({ initial: 62, min: 40, max: 78 })

const list = ref<ConversationMeta[]>([])
const groupsInfo = ref<{ groups: string[]; modules: string[] }>({ groups: [], modules: [] })

// ── 引用复制: 一键拷贝 JSON(项目ID/项目名称/会话名称/会话ID) ──
const copied = ref('')
const projNameMap = ref<Record<string, string>>({})

function projectNameOf(c: ConversationMeta): string {
  return (c.projectId && projNameMap.value[c.projectId]) || c.projectId || ''
}

const stopExecBusy = ref('')
async function stopExec(c: ConversationMeta) {
  if (stopExecBusy.value) return
  stopExecBusy.value = c.id
  try {
    await apiPost(`/sessions/${c.id}/stop-exec`, {})
    await load()
  } catch { /* 刷新兜底 */ } finally {
    stopExecBusy.value = ''
  }
}

async function copyRef(c: ConversationMeta) {
  const payload = {
    projectId: c.projectId || '',
    projectName: projectNameOf(c),
    sessionName: c.title || '',
    sessionId: c.id,
  }
  const ok = await copyText(JSON.stringify(payload, null, 2))
  if (ok) {
    copied.value = c.id
    setTimeout(() => { copied.value = '' }, 1500)
  }
}
const dialog = useAppDialog()
const loading = ref(false)
const busyTip = ref('')

// ── 过滤器 ──
const q = ref('')
const timeFilter = ref<'all' | 'today' | 'week' | 'earlier'>('all')
const groupFilter = ref('')          // '' = 全部; group:<name> / module:<name>
const statusFilter = ref('all')      // 生命周期重构: all | active | running(workState) | archived

// PR3 角色徽标: 会话列表显示 executor 角色名
async function loadRoles() { /* 角色目录已退役(执行器直绑); 保留空挂点防引用 */ }

async function load() {
  loading.value = true
  try {
    // scope=all: 跨全库(主库+各项目库)汇总 — 会话中心统一视图(会话管理+资产管理)
    const [l, g] = await Promise.all([sessionService.list({ limit: 400, scope: 'all' }), sessionService.groups('all')])
    void loadRoles()
    list.value = l
    groupsInfo.value = g
  } finally {
    loading.value = false
  }
}
onMounted(async () => {
  // 会话集合变更(右栏对话新建/更新会话) → 左侧列表同步刷新(免手动刷新页面)
  window.addEventListener('arch:sessions-changed', onSessionsChanged)
  await load()
  // 项目名称映射(引用复制用): arch_projects 全量, 失败静默(降级显示 projectId)
  try {
    const ps = await projectService.listProjects()
    projNameMap.value = Object.fromEntries(ps.map((p) => [p.id, p.name || '']))
  } catch { /* noop */ }
  // 深链 ?select=<convId|reqId>（兼容旧需求深链）→ 直接在对话栏打开
  const sel = typeof route.query.select === 'string' ? route.query.select : ''
  if (sel) {
    const meta = list.value.find((c) => c.id === sel || (sel.startsWith('RQ-') && c.reqId === sel))
    if (meta) openInDock(meta)
  }
})

// 同页深链变化(信息流卡片「前往任务管理」等) → 重新定位会话
watch(() => route.query.select, (sel) => {
  if (typeof sel === 'string' && sel) {
    const meta = list.value.find((c) => c.id === sel || (sel.startsWith('RQ-') && c.reqId === sel))
    if (meta) openInDock(meta)
  }
})

function onSessionsChanged() { void load() }
onUnmounted(() => window.removeEventListener('arch:sessions-changed', onSessionsChanged))

// ── 时间分桶 ──
const DAY = 86400000
function timeBucket(c: ConversationMeta): 'today' | 'week' | 'earlier' {
  const ts = c.updatedAt || c.createdAt || 0
  const now = Date.now()
  if (now - ts < DAY) return 'today'
  if (now - ts < 7 * DAY) return 'week'
  return 'earlier'
}

const filtered = computed(() => {
  let out = list.value
  if (timeFilter.value !== 'all') out = out.filter((c) => timeBucket(c) === timeFilter.value)
  if (statusFilter.value === 'running') out = out.filter((c) => (c as any).workState === 'running')
  else if (statusFilter.value !== 'all') out = out.filter((c) => (c.status || 'active') === statusFilter.value)
  if (groupFilter.value.startsWith('group:')) {
    const g = groupFilter.value.slice(6)
    out = out.filter((c) => c.tags.groups.includes(g))
  } else if (groupFilter.value.startsWith('module:')) {
    const m = groupFilter.value.slice(7)
    out = out.filter((c) => c.tags.modules.includes(m))
  }
  const kw = q.value.trim().toLowerCase()
  if (kw) {
    out = out.filter((c) =>
      c.title.toLowerCase().includes(kw)
      || (c.summary || '').toLowerCase().includes(kw)
      || (c.preview || '').toLowerCase().includes(kw))
  }
  return out
})

// 分组渲染: 时间桶为默认维度; 选定 group/module 维度时按其分桶
const grouped = computed<{ key: string; items: ConversationMeta[] }[]>(() => {
  const items = filtered.value
  if (groupFilter.value) return [{ key: '', items }]
  const buckets: Record<string, ConversationMeta[]> = { today: [], week: [], earlier: [] }
  for (const c of items) buckets[timeBucket(c)].push(c)
  return (['today', 'week', 'earlier'] as const)
    .filter((k) => buckets[k].length)
    .map((k) => ({ key: k, items: buckets[k] }))
})

function openInDock(c: ConversationMeta) {
  void conv.openConversation(c)
}
function newConversation() {
  conv.newConversation()
}

// ── 行操作 ──
// ── 标题行内编辑(悬停标题 → 手动修改/自动摘要) ──
const editingId = ref('')
const titleDraft = ref('')
function startEdit(c: ConversationMeta) {
  editingId.value = c.id
  titleDraft.value = c.title
}
async function saveEdit(c: ConversationMeta) {
  if (editingId.value !== c.id) return
  editingId.value = ''
  const title = titleDraft.value.trim()
  if (!title || title === c.title) return
  await sessionService.update(c.id, { title })
  c.title = title
}
async function summarize(c: ConversationMeta, force = false) {
  busyTip.value = c.id
  try {
    const updated = await sessionService.summarize(c.id, force)
    Object.assign(c, updated)
  } finally {
    busyTip.value = ''
  }
}
async function editTags(c: ConversationMeta) {
  const groups = await dialog.prompt(t('session.actions.groupsPrompt'), c.tags.groups.join(', '))
  if (groups === null) return
  const modules = await dialog.prompt(t('session.actions.modulesPrompt'), c.tags.modules.join(', '))
  if (modules === null) return
  const tags = {
    groups: groups.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
    modules: modules.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
  }
  await sessionService.update(c.id, { tags })
  c.tags = tags
  void sessionService.groups().then((g) => { groupsInfo.value = g })
}
async function removeSession(c: ConversationMeta) {
  if (!(await dialog.confirm(t('session.actions.deleteConfirm', { title: c.title }), { danger: true }))) return
  await sessionService.remove(c.id)
  list.value = list.value.filter((x) => x.id !== c.id)
  // 左右联动: 通知对话栏清除该会话(若正打开)——右侧不残留已删会话
  window.dispatchEvent(new CustomEvent('arch:conversation-removed', { detail: c.id }))
}
async function newGroup() {
  const name = await dialog.prompt(t('session.actions.newGroupPrompt'))
  if (!name || !name.trim()) return
  const names = [...new Set([...groupsInfo.value.groups, name.trim()])]
  await sessionService.saveGroups(names)
  groupsInfo.value = { ...groupsInfo.value, groups: names }
}


function fmt(ts?: number) {
  return ts ? new Date(ts).toLocaleString() : '—'
}
function statusClass(s: string) {
  if (s === 'running') return 'bg-ctp-blue/15 text-ctp-blue'
  if (s === 'archived') return 'bg-ctp-surface0 text-ctp-overlay0'
  return 'bg-ctp-green/15 text-ctp-green'          // active 活跃(可运行)
}
/** 查看状态徽标(第二维度): 未读=蓝 / 待回复=黄 / 报错=红 / 已读=不显示。 */
function reviewClass(rs?: string) {
  if (rs === 'unread') return 'bg-ctp-blue/20 text-ctp-blue'
  if (rs === 'awaiting_reply') return 'bg-ctp-yellow/20 text-ctp-yellow'
  if (rs === 'error') return 'bg-ctp-red/20 text-ctp-red'
  return ''
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <!-- 顶栏: 搜索/过滤/操作(与资产地图页同构: 页头 + 分栏内容区) -->
    <div class="flex shrink-0 flex-wrap items-center gap-2 px-5 pt-5">
      <div class="relative w-56">
        <MagnifyingGlassIcon class="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ctp-overlay0" />
        <input v-model="q" class="input pl-8 text-xs" :placeholder="t('session.searchPlaceholder')">
      </div>
      <select v-model="timeFilter" class="input !w-auto !py-1 text-xs">
        <option value="all">{{ t('session.time.all') }}</option>
        <option value="today">{{ t('session.time.today') }}</option>
        <option value="week">{{ t('session.time.week') }}</option>
        <option value="earlier">{{ t('session.time.earlier') }}</option>
      </select>
      <select v-model="statusFilter" class="input !w-auto !py-1 text-xs">
        <option value="all">{{ t('session.statusFilter.all') }}</option>
        <option value="active">{{ t('session.status.active') }}</option>
        <option value="running">{{ t('session.status.running') }}</option>
        <option value="archived">{{ t('session.status.archived') }}</option>
      </select>
      <select v-model="groupFilter" class="input !w-auto !py-1 text-xs">
        <option value="">{{ t('session.group.all') }}</option>
        <optgroup v-if="groupsInfo.groups.length" :label="t('session.group.custom')">
          <option v-for="g in groupsInfo.groups" :key="g" :value="`group:${g}`">{{ g }}</option>
        </optgroup>
        <optgroup v-if="groupsInfo.modules.length" :label="t('session.group.byModule')">
          <option v-for="m in groupsInfo.modules" :key="m" :value="`module:${m}`">{{ m }}</option>
        </optgroup>
      </select>
      <button class="btn btn-sm btn-ghost" :title="t('session.group.new')" @click="newGroup">
        <FolderIcon class="h-3.5 w-3.5" />
      </button>
      <div class="ml-auto flex items-center gap-1.5">
        <button class="btn btn-sm btn-ghost" :disabled="loading" @click="load">
          <ArrowPathIcon class="h-3.5 w-3.5" :class="loading ? 'animate-spin' : ''" />
        </button>
        <button class="btn btn-sm btn-blue" @click="newConversation">
          <PlusIcon class="h-3.5 w-3.5" />{{ t('session.newConversation') }}
        </button>
      </div>
    </div>

    <!-- 分栏内容区: 左=信息(会话列表+详情) / 右=对话(inline 停靠) -->
    <div
      ref="splitBoxRef"
      class="min-h-0 min-w-0 flex-1 px-5 pb-5 pt-4"
      :class="dragging ? 'cursor-col-resize select-none' : ''"
    >
      <div class="flex h-full min-h-0">
        <!-- 左: 信息区 -->
        <div class="flex h-full min-h-0 min-w-0" :style="{ width: splitPct + '%' }">
          <!-- 左: 会话列表 -->
          <section class="flex min-h-0 min-w-0 flex-1 flex-col">
            <div class="min-h-0 flex-1 overflow-auto panel">
        <template v-for="g in grouped" :key="g.key || 'flat'">
          <div v-if="g.key" class="sticky top-0 z-10 flex items-center gap-1.5 bg-ctp-mantle/95 px-3 py-1.5 text-[10px] uppercase tracking-wider text-ctp-overlay1 backdrop-blur">
            <ClockIcon class="h-3 w-3" />{{ t(`session.time.${g.key}`) }}
            <span class="text-ctp-overlay0">({{ g.items.length }})</span>
          </div>
          <div
            v-for="c in g.items"
            :key="c.id"
            class="group flex cursor-pointer items-center gap-2 border-b border-ctp-surface0/60 px-3 py-2 hover:bg-ctp-surface0/40"
            :class="conv.activeId === c.id ? 'bg-ctp-surface0/70' : ''"
            @click="openInDock(c)"
          >
            <span class="chip shrink-0" :class="statusClass(c.status)">{{ t(`session.status.${c.status}`) }}</span>
            <span
              v-if="(c as any).workState === 'running'"
              class="chip shrink-0 animate-pulse bg-ctp-peach/15 text-ctp-peach"
              :title="t('session.workState.runningHint')"
            >▶ {{ t('session.workState.running') }}</span>
            <span
              v-if="(c as any).executorId"
              class="chip shrink-0 bg-ctp-mauve/15 text-ctp-mauve"
              :title="t('session.role.roleTitle')"
            >⌨ {{ (c as any).executorId }}</span>
            <span v-if="reviewClass(c.reviewState)" class="chip shrink-0" :class="reviewClass(c.reviewState)">{{ t(`session.review.${c.reviewState}`) }}</span>
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-1.5">
                <input
                  v-if="editingId === c.id"
                  v-model="titleDraft"
                  class="input w-full min-w-0 !px-1.5 !py-0.5 text-xs"
                  @click.stop
                  @keydown.enter.prevent="saveEdit(c)"
                  @keydown.esc="editingId = ''"
                  @blur="saveEdit(c)"
                >
                <span
                  v-else
                  class="group/t flex min-w-0 items-center gap-1"
                >
                  <span class="truncate text-xs font-medium text-ctp-text">{{ c.title || t('session.dock.untitled') }}</span>
                  <span class="hidden shrink-0 items-center gap-0.5 group-hover/t:flex">
                    <button class="rounded p-0.5 text-ctp-overlay0 hover:bg-ctp-surface1 hover:text-ctp-blue" :title="t('session.actions.rename')" @click.stop="startEdit(c)">
                      <PencilSquareIcon class="h-3 w-3" />
                    </button>
                    <button class="rounded p-0.5 text-ctp-overlay0 hover:bg-ctp-surface1 hover:text-ctp-blue" :title="t('session.actions.summarize')" @click.stop="summarize(c, true)">
                      <SparklesIcon class="h-3 w-3" :class="busyTip === c.id ? 'animate-pulse' : ''" />
                    </button>
                  </span>
                </span>
                <span
                  v-for="tag in [...c.tags.groups, ...c.tags.modules].slice(0, 3)"
                  :key="tag"
                  class="chip hidden shrink-0 bg-ctp-surface1 text-ctp-overlay1 lg:inline-block"
                >{{ tag }}</span>
              </div>
              <p class="truncate text-[10px] text-ctp-overlay0">
                {{ c.summary || c.preview || t('session.noSummary') }}
              </p>
            </div>
            <div class="hidden shrink-0 flex-col items-end text-[10px] text-ctp-overlay0 xl:flex">
              <span>{{ c.msgCount }} {{ t('session.msgUnit') }}</span>
              <span>{{ fmt(c.updatedAt) }}</span>
            </div>
            <div class="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
              <!-- running 会话: 停止作业(UI 确定操作) -->
              <button
                v-if="(c as any).workState === 'running'"
                class="rounded p-1 text-ctp-subtext0 hover:bg-ctp-surface1 hover:text-ctp-red"
                :title="t('session.job.stop')"
                @click.stop="stopExec(c)"
              >
                <StopIcon class="h-3.5 w-3.5" />
              </button>
              <!-- 一键复制引用 JSON(项目ID/项目名称/会话名称/会话ID) -->
              <button
                class="rounded p-1 text-ctp-subtext0 hover:bg-ctp-surface1 hover:text-ctp-green"
                :title="t('session.copy.menu')"
                @click.stop="copyRef(c)"
              >
                <CheckIcon v-if="copied === c.id" class="h-3.5 w-3.5 text-ctp-green" />
                <ClipboardDocumentIcon v-else class="h-3.5 w-3.5" />
              </button>
              <button class="rounded p-1 text-ctp-subtext0 hover:bg-ctp-surface1 hover:text-ctp-blue" :title="t('session.openInDock')" @click.stop="openInDock(c)">
                <ChatBubbleOvalLeftEllipsisIcon class="h-3.5 w-3.5" />
              </button>
              <button class="rounded p-1 text-ctp-subtext0 hover:bg-ctp-surface1 hover:text-ctp-peach" :title="t('session.actions.editTags')" @click.stop="editTags(c)">
                <TagIcon class="h-3.5 w-3.5" />
              </button>
              <button class="rounded p-1 text-ctp-subtext0 hover:bg-ctp-surface1 hover:text-ctp-red" :title="t('common.delete')" @click.stop="removeSession(c)">
                <TrashIcon class="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </template>
        <p v-if="!filtered.length" class="px-3 py-12 text-center text-xs text-ctp-overlay0">
          {{ t('common.empty') }}
        </p>
      </div>
    </section>


        </div>

        <!-- 分割线(与资产地图页同款拖拽分割线) -->
        <div
          class="w-4 shrink-0 -mx-0.5 flex items-center justify-center cursor-col-resize select-none touch-none group"
          :class="dragging ? 'cursor-col-resize' : ''"
          @pointerdown="onSplitPointerDown"
        >
          <div
            class="h-12 w-0.5 rounded-full bg-ctp-overlay1/40 transition-colors group-hover:bg-ctp-blue/60"
            :class="dragging ? '!bg-ctp-blue/70' : ''"
          />
        </div>

        <!-- 右: 对话栏·inline 停靠(P1 决策2: 唯一对话栏——与资产地图页同构: 左信息/右对话) -->
        <div class="flex min-h-0 min-w-0 flex-1 flex-col">
          <ConversationDock inline scope="sessions" default-kind="generic" :skill-scenarios="['plan', 'coding', 'capability']" />
        </div>
      </div>
    </div>

  </div>
</template>
