<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import {
  PlusIcon, XMarkIcon, MagnifyingGlassIcon,
} from '@heroicons/vue/24/outline'
import TaskCreateView from '@/components/coding/TaskCreateView.vue'
import TaskDetailView from '@/components/coding/TaskDetailView.vue'
import { useArchRequirementStore } from '@/stores/requirement-store'
import { useArchTaskStore } from '@/stores/task-store'
import type { ExecutionTask } from '@/types'

const { t } = useI18n()
const route = useRoute()
const requirement = useArchRequirementStore()
const task = useArchTaskStore()
requirement.load()
task.load()

interface Tab { key: string; label: string }
const tabs = ref<Tab[]>([{ key: 'list', label: t('execute.listTitle') }])
const activeKey = ref('list')
const createPreselect = ref<string[]>([])

const execTabKey = (id: string) => `exec:${id}`
const isExecTab = (key: string) => key.startsWith('exec:')
const execIdOf = (key: string) => key.slice(5)

const executions = computed(() => task.executionTasks)
const activeExec = computed(() => (isExecTab(activeKey.value) ? task.findExecution(execIdOf(activeKey.value)) : undefined))

const execStatusColor: Record<string, string> = {
  created: 'bg-ctp-surface0 text-ctp-subtext0',
  running: 'bg-ctp-blue/15 text-ctp-blue',
  accepting: 'bg-ctp-yellow/15 text-ctp-yellow',
  done: 'bg-ctp-green/15 text-ctp-green',
  failed: 'bg-ctp-red/15 text-ctp-red',
  blocked: 'bg-ctp-red/15 text-ctp-red',
  stopped: 'bg-ctp-red/15 text-ctp-red',
}
const connColor: Record<string, string> = {
  unknown: 'bg-ctp-surface0 text-ctp-overlay1',
  ok: 'bg-ctp-green/15 text-ctp-green',
  fail: 'bg-ctp-red/15 text-ctp-red',
}

function planTitleOf(exec: ExecutionTask) {
  return requirement.planById(exec.planId)?.title ?? exec.planId
}

function labelOf(key: string): string {
  if (key === 'list') return t('execute.listTitle')
  if (key === 'create') return t('execute.createTask')
  const e = task.findExecution(execIdOf(key))
  return e ? `执行: ${planTitleOf(e)}` : key
}

function openList() { activeKey.value = 'list' }
function openCreate(preselect: string[] = []) {
  createPreselect.value = preselect
  if (!tabs.value.some((x) => x.key === 'create')) {
    tabs.value.push({ key: 'create', label: t('execute.createTask') })
  }
  activeKey.value = 'create'
}
function openExec(id: string) {
  if (!tabs.value.some((x) => x.key === execTabKey(id))) {
    tabs.value.push({ key: execTabKey(id), label: labelOf(execTabKey(id)) })
  }
  activeKey.value = execTabKey(id)
  const i = tabs.value.findIndex((x) => x.key === 'create')
  if (i >= 0) tabs.value.splice(i, 1)
  if (!tabs.value.some((x) => x.key === 'list')) tabs.value.unshift({ key: 'list', label: t('execute.listTitle') })
}
function closeTab(key: string) {
  const i = tabs.value.findIndex((x) => x.key === key)
  if (i < 0) return
  tabs.value.splice(i, 1)
  if (activeKey.value === key) activeKey.value = tabs.value[tabs.value.length - 1]?.key ?? 'list'
}
function onCreated(exec: ExecutionTask) {
  openExec(exec.id)
}
function onReplaced() {
  if (isExecTab(activeKey.value)) closeTab(activeKey.value)
}

onMounted(() => {
  const sel = route.query.select
  if (typeof sel === 'string' && sel.trim()) {
    openCreate(sel.split(',').filter(Boolean))
  }
})

// ---- 列表：搜索 / 排序 / 状态过滤 ----
const query = ref('')
const statusFilter = ref<'all' | ExecutionTask['status']>('all')
const sortKey = ref<'createdAt' | 'status' | 'title'>('createdAt')
const sortDir = ref<'asc' | 'desc'>('desc')
const statusOptions: Array<{ key: 'all' | ExecutionTask['status']; label: string }> = [
  { key: 'all', label: t('execute.filterAll') },
  { key: 'created', label: t('execute.execStatus.created') },
  { key: 'running', label: t('execute.execStatus.running') },
  { key: 'accepting', label: t('execute.execStatus.accepting') },
  { key: 'done', label: t('execute.execStatus.done') },
  { key: 'failed', label: t('execute.execStatus.failed') },
  { key: 'stopped', label: t('execute.execStatus.stopped') },
  { key: 'blocked', label: t('execute.execStatus.blocked') },
]
const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  const list = executions.value.filter((e) => {
    if (statusFilter.value !== 'all' && e.status !== statusFilter.value) return false
    if (!q) return true
    return e.id.toLowerCase().includes(q) || planTitleOf(e).toLowerCase().includes(q)
  })
  const dir = sortDir.value === 'asc' ? 1 : -1
  return [...list].sort((a, b) => {
    if (sortKey.value === 'title') return planTitleOf(a).localeCompare(planTitleOf(b)) * dir
    if (sortKey.value === 'status') return a.status.localeCompare(b.status) * dir
    return (a.createdAt - b.createdAt) * dir
  })
})
function toggleSort(key: 'createdAt' | 'status' | 'title') {
  if (sortKey.value === key) sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  else {
    sortKey.value = key
    sortDir.value = 'asc'
  }
}
const sortArrow = (key: string) => (sortKey.value === key ? (sortDir.value === 'asc' ? '↑' : '↓') : '')
</script>

<template>
  <div class="h-full flex flex-col min-h-0">
    <!-- 标签栏 -->
    <div class="shrink-0 px-5 pt-4 flex items-center gap-1.5 overflow-x-auto">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="group flex items-center gap-1.5 rounded-t-lg border border-ctp-surface1 px-3 py-1.5 text-xs transition-colors"
        :class="activeKey === tab.key ? 'bg-ctp-crust text-ctp-text border-b-transparent' : 'bg-ctp-mantle text-ctp-subtext0 hover:text-ctp-text'"
        @click="activeKey = tab.key"
      >
        <span class="whitespace-nowrap">{{ tab.label }}</span>
        <button
          v-if="tab.key !== 'list'"
          class="text-ctp-overlay1 hover:text-ctp-red"
          @click.stop="closeTab(tab.key)"
        >
          <XMarkIcon class="w-3 h-3" />
        </button>
      </button>
      <button
        v-if="!tabs.some((x) => x.key === 'create')"
        class="ml-auto btn btn-sm btn-green shrink-0"
        @click="openCreate()"
      >
        <PlusIcon class="w-3.5 h-3.5" />{{ t('execute.newTask') }}
      </button>
    </div>

    <div class="flex-1 min-h-0 p-5 pt-3">
      <!-- 任务列表 -->
      <div
        v-if="activeKey === 'list'"
        class="h-full flex flex-col min-h-0"
      >
        <!-- 搜索/过滤 -->
        <div class="shrink-0 flex items-center gap-2 mb-3">
          <div class="relative flex-1 max-w-xs">
            <MagnifyingGlassIcon class="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-ctp-overlay0" />
            <input
              v-model="query"
              class="input pl-8 !py-1.5 text-xs"
              :placeholder="t('execute.searchPlaceholder')"
            >
          </div>
          <div class="flex flex-wrap gap-1.5">
            <button
              v-for="s in statusOptions"
              :key="s.key"
              class="chip cursor-pointer"
              :class="statusFilter === s.key ? 'bg-ctp-blue/15 text-ctp-blue' : 'bg-ctp-surface0 text-ctp-subtext1'"
              @click="statusFilter = s.key"
            >
              {{ s.label }}
            </button>
          </div>
        </div>

        <!-- 任务表 -->
        <div class="flex-1 min-h-0 overflow-auto panel">
          <table class="w-full text-left text-xs">
            <thead class="sticky top-0 bg-ctp-mantle text-ctp-overlay1">
              <tr>
                <th
                  class="px-3 py-2 font-medium cursor-pointer hover:text-ctp-text"
                  @click="toggleSort('title')"
                >
                  {{ t('execute.colTitle') }} {{ sortArrow('title') }}
                </th>
                <th
                  class="px-3 py-2 font-medium cursor-pointer hover:text-ctp-text"
                  @click="toggleSort('status')"
                >
                  {{ t('execute.colStatus') }} {{ sortArrow('status') }}
                </th>
                <th class="px-3 py-2 font-medium">
                  {{ t('execute.colAgent') }}
                </th>
                <th class="px-3 py-2 font-medium">
                  {{ t('execute.colReqs') }}
                </th>
                <th class="px-3 py-2 font-medium">
                  {{ t('execute.colConn') }}
                </th>
                <th
                  class="px-3 py-2 font-medium cursor-pointer hover:text-ctp-text"
                  @click="toggleSort('createdAt')"
                >
                  {{ t('execute.colCreated') }} {{ sortArrow('createdAt') }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="e in filtered"
                :key="e.id"
                class="border-t border-ctp-surface0 cursor-pointer transition-colors hover:bg-ctp-surface0/50"
                @click="openExec(e.id)"
              >
                <td class="px-3 py-2">
                  <div class="flex items-center gap-2">
                    <span class="font-mono text-[10px] text-ctp-overlay1 shrink-0">{{ e.id }}</span>
                    <span class="truncate">{{ planTitleOf(e) }}</span>
                    <span
                      v-if="e.amendments.length"
                      class="chip bg-ctp-peach/15 text-ctp-peach shrink-0"
                    >+{{ e.amendments.length }}</span>
                  </div>
                </td>
                <td class="px-3 py-2">
                  <span
                    class="chip"
                    :class="execStatusColor[e.status]"
                  >{{ t(`execute.execStatus.${e.status}`) }}</span>
                </td>
                <td class="px-3 py-2">
                  <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ e.adapter }}{{ e.model ? ` · ${e.model}` : '' }}</span>
                </td>
                <td class="px-3 py-2 text-ctp-overlay1">
                  {{ e.reqIds.length }}
                </td>
                <td class="px-3 py-2">
                  <span
                    class="chip"
                    :class="connColor[e.connectivity]"
                  >{{ t(`execute.conn${e.connectivity === 'ok' ? 'Ok' : e.connectivity === 'fail' ? 'Fail' : 'Unknown'}`) }}</span>
                </td>
                <td class="px-3 py-2 text-ctp-overlay1">
                  {{ new Date(e.createdAt).toLocaleString() }}
                </td>
              </tr>
              <tr v-if="!filtered.length">
                <td
                  colspan="6"
                  class="px-3 py-10 text-center text-ctp-overlay0"
                >
                  {{ t('common.empty') }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 新建任务 -->
      <TaskCreateView
        v-else-if="activeKey === 'create'"
        :preselect="createPreselect"
        @created="onCreated"
        @back="openList"
      />

      <!-- 任务详情 -->
      <TaskDetailView
        v-else-if="activeExec"
        :exec-id="activeExec.id"
        @close="closeTab(activeKey)"
        @replaced="onReplaced"
      />
    </div>
  </div>
</template>
