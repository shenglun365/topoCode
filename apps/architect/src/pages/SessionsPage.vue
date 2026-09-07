<script setup lang="ts">
/**
 * 会话中心(P1) —— 会话是唯一主体，流程不复存在。
 * 组织维度: 时间/模块/自定义分组(元数据)；流程视图=过滤器。
 * 详情: 摘要/备案文档/关联执行；对话本体在全局会话栏(ConversationDock)。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  ChatBubbleOvalLeftEllipsisIcon, MagnifyingGlassIcon, PlusIcon, ArrowPathIcon,
  DocumentArrowDownIcon, TagIcon, TrashIcon, PencilSquareIcon, SparklesIcon,
  FolderIcon, ClockIcon, XMarkIcon,
} from '@heroicons/vue/24/outline'
import TaskDetailView from '@/components/coding/TaskDetailView.vue'
import { useConversationStore } from '@/stores/conversation-store'
import { useArchTaskStore } from '@/stores/task-store'
import { sessionService, type ConversationMeta, type SessionDoc } from '@/services/session-service'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const conv = useConversationStore()
const task = useArchTaskStore()

const list = ref<ConversationMeta[]>([])
const groupsInfo = ref<{ groups: string[]; modules: string[] }>({ groups: [], modules: [] })
const docs = ref<SessionDoc[]>([])
const selected = ref<ConversationMeta | null>(null)
const loading = ref(false)
const busyTip = ref('')

// ── 过滤器 ──
const q = ref('')
const kindFilter = ref('all')
const timeFilter = ref<'all' | 'today' | 'week' | 'earlier'>('all')
const groupFilter = ref('')          // '' = 全部; group:<name> / module:<name>
const kindOptions = ['all', 'requirement', 'design', 'asset', 'execution', 'generic']

async function load() {
  loading.value = true
  try {
    const [l, g] = await Promise.all([sessionService.list({ limit: 400 }), sessionService.groups()])
    list.value = l
    groupsInfo.value = g
    void task.load()
  } finally {
    loading.value = false
  }
}
onMounted(async () => {
  await load()
  // 深链 ?select=<convId|reqId>（兼容旧需求深链）
  const sel = typeof route.query.select === 'string' ? route.query.select : ''
  if (sel) {
    const meta = list.value.find((c) => c.id === sel || (sel.startsWith('RQ-') && c.reqId === sel))
    if (meta) select(meta)
  }
})

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
  if (kindFilter.value !== 'all') out = out.filter((c) => c.kind === kindFilter.value)
  if (timeFilter.value !== 'all') out = out.filter((c) => timeBucket(c) === timeFilter.value)
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

// ── 选择与详情 ──
async function select(c: ConversationMeta) {
  selected.value = c
  docs.value = []
  try {
    docs.value = await sessionService.docs(c.id)
  } catch { /* 无文档 */ }
  if (route.query.select !== c.id) {
    router.replace({ query: { ...route.query, select: c.id } })
  }
}
watch(() => route.query.select, (sel) => {
  if (!sel && selected.value) selected.value = null
})

const linkedExecs = computed(() =>
  selected.value ? task.executionTasks.filter((e) => e.conversationId === selected.value?.id) : [])
const openExecId = ref('')

function openInDock(c: ConversationMeta) {
  void conv.openConversation(c)
}
function newConversation() {
  conv.newConversation('requirement')
}

// ── 行操作 ──
async function rename(c: ConversationMeta) {
  const title = window.prompt(t('session.actions.renamePrompt'), c.title)
  if (!title || title === c.title) return
  await sessionService.update(c.id, { title })
  c.title = title
}
async function summarize(c: ConversationMeta) {
  busyTip.value = c.id
  try {
    const updated = await sessionService.summarize(c.id)
    Object.assign(c, updated)
    if (selected.value?.id === c.id) Object.assign(selected.value, updated)
  } finally {
    busyTip.value = ''
  }
}
async function editTags(c: ConversationMeta) {
  const groups = window.prompt(t('session.actions.groupsPrompt'), c.tags.groups.join(', '))
  if (groups === null) return
  const modules = window.prompt(t('session.actions.modulesPrompt'), c.tags.modules.join(', '))
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
  if (!window.confirm(t('session.actions.deleteConfirm', { title: c.title }))) return
  await sessionService.remove(c.id)
  list.value = list.value.filter((x) => x.id !== c.id)
  if (selected.value?.id === c.id) selected.value = null
}
async function newGroup() {
  const name = window.prompt(t('session.actions.newGroupPrompt'))
  if (!name || !name.trim()) return
  const names = [...new Set([...groupsInfo.value.groups, name.trim()])]
  await sessionService.saveGroups(names)
  groupsInfo.value = { ...groupsInfo.value, groups: names }
}

// ── 备案文档 ──
const extracting = ref(false)
const viewingDoc = ref<SessionDoc | null>(null)
async function extractDoc() {
  if (!selected.value || extracting.value) return
  extracting.value = true
  try {
    const doc = await sessionService.docFromConversation(selected.value.id, selected.value.title)
    docs.value.unshift(doc)
  } catch (err) {
    window.alert(err instanceof Error ? err.message : t('session.docs.extractFailed'))
  } finally {
    extracting.value = false
  }
}
async function removeDoc(doc: SessionDoc) {
  if (!window.confirm(t('session.docs.deleteConfirm'))) return
  await sessionService.removeDoc(doc.id)
  docs.value = docs.value.filter((d) => d.id !== doc.id)
  if (viewingDoc.value?.id === doc.id) viewingDoc.value = null
}

function fmt(ts?: number) {
  return ts ? new Date(ts).toLocaleString() : '—'
}
function kindClass(kind: string) {
  if (kind === 'asset') return 'bg-ctp-mauve/15 text-ctp-mauve'
  if (kind === 'design') return 'bg-ctp-peach/15 text-ctp-peach'
  if (kind === 'execution') return 'bg-ctp-green/15 text-ctp-green'
  return 'bg-ctp-sky/15 text-ctp-sky'
}
function statusClass(s: string) {
  if (s === 'running') return 'bg-ctp-green/15 text-ctp-green'
  if (s === 'waiting') return 'bg-ctp-yellow/15 text-ctp-yellow'
  if (s === 'archived') return 'bg-ctp-surface0 text-ctp-overlay0'
  if (s === 'done') return 'bg-ctp-blue/15 text-ctp-blue'
  return 'bg-ctp-surface0 text-ctp-subtext0'
}
</script>

<template>
  <div class="flex h-full min-h-0">
    <!-- 左: 会话列表 -->
    <section class="flex min-h-0 min-w-0 flex-1 flex-col p-4">
      <div class="mb-3 flex shrink-0 flex-wrap items-center gap-2">
        <div class="relative w-56">
          <MagnifyingGlassIcon class="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ctp-overlay0" />
          <input v-model="q" class="input pl-8 text-xs" :placeholder="t('session.searchPlaceholder')">
        </div>
        <div class="flex items-center gap-1">
          <button
            v-for="k in kindOptions"
            :key="k"
            class="chip cursor-pointer"
            :class="kindFilter === k ? 'bg-ctp-blue/20 text-ctp-blue' : 'bg-ctp-surface0 text-ctp-subtext0'"
            @click="kindFilter = k"
          >
            {{ k === 'all' ? t('session.filter.all') : t(`session.kind.${k}`) }}
          </button>
        </div>
        <select v-model="timeFilter" class="input !w-auto !py-1 text-xs">
          <option value="all">{{ t('session.time.all') }}</option>
          <option value="today">{{ t('session.time.today') }}</option>
          <option value="week">{{ t('session.time.week') }}</option>
          <option value="earlier">{{ t('session.time.earlier') }}</option>
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
            :class="selected?.id === c.id ? 'bg-ctp-surface0/70' : ''"
            @click="select(c)"
          >
            <span class="chip shrink-0" :class="kindClass(c.kind)">{{ t(`session.kind.${c.kind}`) }}</span>
            <span class="chip shrink-0" :class="statusClass(c.status)">{{ t(`session.status.${c.status}`) }}</span>
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-1.5">
                <span class="truncate text-xs font-medium text-ctp-text">{{ c.title }}</span>
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
              <button class="rounded p-1 text-ctp-subtext0 hover:bg-ctp-surface1 hover:text-ctp-blue" :title="t('session.openInDock')" @click.stop="openInDock(c)">
                <ChatBubbleOvalLeftEllipsisIcon class="h-3.5 w-3.5" />
              </button>
              <button class="rounded p-1 text-ctp-subtext0 hover:bg-ctp-surface1 hover:text-ctp-blue" :title="t('session.actions.summarize')" @click.stop="summarize(c)">
                <SparklesIcon class="h-3.5 w-3.5" :class="busyTip === c.id ? 'animate-pulse' : ''" />
              </button>
              <button class="rounded p-1 text-ctp-subtext0 hover:bg-ctp-surface1 hover:text-ctp-blue" :title="t('session.actions.rename')" @click.stop="rename(c)">
                <PencilSquareIcon class="h-3.5 w-3.5" />
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

    <!-- 右: 会话详情 -->
    <section
      v-if="selected"
      class="hidden w-[24rem] shrink-0 flex-col overflow-auto border-l border-ctp-surface0 bg-ctp-mantle/40 lg:flex"
    >
      <div class="sticky top-0 z-10 flex items-start gap-2 border-b border-ctp-surface0 bg-ctp-mantle/95 px-3 py-2 backdrop-blur">
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-medium text-ctp-text">{{ selected.title }}</p>
          <p class="text-[10px] text-ctp-overlay0">
            {{ t(`session.kind.${selected.kind}`) }} · {{ selected.msgCount }} {{ t('session.msgUnit') }} · {{ fmt(selected.updatedAt) }}
          </p>
        </div>
        <button class="rounded p-1 text-ctp-subtext0 hover:text-ctp-text" @click="selected = null">
          <XMarkIcon class="h-4 w-4" />
        </button>
      </div>

      <div class="space-y-3 p-3">
        <div class="flex items-center gap-1.5">
          <button class="btn btn-sm btn-blue flex-1" @click="openInDock(selected)">
            <ChatBubbleOvalLeftEllipsisIcon class="h-3.5 w-3.5" />{{ t('session.openInDock') }}
          </button>
          <button class="btn btn-sm btn-ghost" :disabled="busyTip === selected.id" @click="summarize(selected)">
            <SparklesIcon class="h-3.5 w-3.5" :class="busyTip === selected.id ? 'animate-pulse' : ''" />{{ t('session.actions.summarize') }}
          </button>
        </div>

        <div v-if="selected.summary" class="rounded-lg border border-ctp-surface0 bg-ctp-base/60 p-2.5">
          <p class="mb-1 text-[10px] uppercase tracking-wider text-ctp-overlay1">{{ t('session.summary') }}</p>
          <p class="whitespace-pre-wrap text-[11px] leading-relaxed text-ctp-subtext1">{{ selected.summary }}</p>
        </div>

        <!-- 备案文档 -->
        <div class="rounded-lg border border-ctp-surface0 bg-ctp-base/60 p-2.5">
          <div class="mb-1.5 flex items-center gap-1.5">
            <p class="flex-1 text-[10px] uppercase tracking-wider text-ctp-overlay1">{{ t('session.docs.title') }}</p>
            <button class="btn btn-sm btn-ghost !px-1.5 !py-0.5" :disabled="extracting" @click="extractDoc">
              <DocumentArrowDownIcon class="h-3 w-3" :class="extracting ? 'animate-pulse' : ''" />
            </button>
          </div>
          <button
            v-for="d in docs"
            :key="d.id"
            class="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-[11px] text-ctp-subtext1 hover:bg-ctp-surface0"
            @click="viewingDoc = d"
          >
            <DocumentArrowDownIcon class="h-3 w-3 shrink-0 text-ctp-overlay0" />
            <span class="min-w-0 flex-1 truncate">{{ d.title }}</span>
            <span class="shrink-0 text-[10px] text-ctp-overlay0">{{ fmt(d.updatedAt) }}</span>
            <span class="shrink-0 text-ctp-overlay0 hover:text-ctp-red" @click.stop="removeDoc(d)">
              <TrashIcon class="h-3 w-3" />
            </span>
          </button>
          <p v-if="!docs.length" class="py-1 text-[10px] text-ctp-overlay0">{{ t('session.docs.empty') }}</p>
        </div>

        <!-- 关联执行 -->
        <div class="rounded-lg border border-ctp-surface0 bg-ctp-base/60 p-2.5">
          <p class="mb-1.5 text-[10px] uppercase tracking-wider text-ctp-overlay1">{{ t('session.execs.title') }}</p>
          <button
            v-for="e in linkedExecs"
            :key="e.id"
            class="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-[11px] hover:bg-ctp-surface0"
            @click="openExecId = openExecId === e.id ? '' : e.id"
          >
            <span class="chip bg-ctp-green/15 text-ctp-green">{{ e.id }}</span>
            <span class="chip bg-ctp-surface1 text-ctp-subtext0">{{ t(`execute.status.${e.status}`) || e.status }}</span>
            <span class="ml-auto text-[10px] text-ctp-overlay0">{{ fmt(e.updatedAt) }}</span>
          </button>
          <p v-if="!linkedExecs.length" class="py-1 text-[10px] text-ctp-overlay0">{{ t('session.execs.empty') }}</p>
        </div>
      </div>

      <!-- 执行详情内嵌 -->
      <div v-if="openExecId" class="min-h-0 flex-1 border-t border-ctp-surface0">
        <TaskDetailView :key="openExecId" :exec-id="openExecId" />
      </div>
    </section>

    <!-- 文档查看浮层 -->
    <div v-if="viewingDoc" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-6" @click.self="viewingDoc = null">
      <div class="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-ctp-surface1 bg-ctp-base shadow-2xl">
        <div class="flex shrink-0 items-center gap-2 border-b border-ctp-surface0 px-4 py-2.5">
          <p class="flex-1 truncate text-sm font-medium text-ctp-text">{{ viewingDoc.title }}</p>
          <button class="rounded p-1 text-ctp-subtext0 hover:text-ctp-text" @click="viewingDoc = null">
            <XMarkIcon class="h-4 w-4" />
          </button>
        </div>
        <pre class="flex-1 overflow-auto whitespace-pre-wrap px-4 py-3 text-xs leading-relaxed text-ctp-subtext1">{{ viewingDoc.contentMd }}</pre>
      </div>
    </div>
  </div>
</template>
