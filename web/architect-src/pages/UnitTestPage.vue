<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { MagnifyingGlassIcon, PlusIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import UnitTestCreateView from '@/components/unit-test/UnitTestCreateView.vue'
import UnitTestWorkspace from '@/components/unit-test/UnitTestWorkspace.vue'
import { useArchUnitTestStore } from '@/stores/unit-test-store'

const { t } = useI18n()
const route = useRoute()
const store = useArchUnitTestStore()
store.load()

interface Tab { key: string; label: string }
const tabs = ref<Tab[]>([{ key: 'list', label: t('unitTest.listTitle') }])
const activeKey = ref('list')

const utTabKey = (id: string) => `ut:${id}`
const isUtTab = (key: string) => key.startsWith('ut:')
const utIdOf = (key: string) => key.slice(3)
const activeSessionId = computed(() => (isUtTab(activeKey.value) ? utIdOf(activeKey.value) : undefined))

const sessions = computed(() => store.sessions)

const statusClass: Record<string, string> = {
  created: 'bg-ctp-surface0 text-ctp-subtext0',
  running: 'bg-ctp-blue/15 text-ctp-blue',
  done: 'bg-ctp-green/15 text-ctp-green',
  failed: 'bg-ctp-red/15 text-ctp-red',
  stopped: 'bg-ctp-red/15 text-ctp-red',
}
const channelClass: Record<string, string> = {
  agent: 'bg-ctp-sky/15 text-ctp-sky',
  cli: 'bg-ctp-mauve/15 text-ctp-mauve',
}

function labelOf(key: string): string {
  if (key === 'list') return t('unitTest.listTitle')
  if (key === 'create') return t('unitTest.newSession')
  const s = store.sessions.find((x) => x.id === utIdOf(key))
  return s ? s.title : key
}

function openList() { activeKey.value = 'list' }
function openCreate() {
  if (!tabs.value.some((x) => x.key === 'create')) tabs.value.push({ key: 'create', label: t('unitTest.newSession') })
  activeKey.value = 'create'
}
function openSession(id: string) {
  if (!tabs.value.some((x) => x.key === utTabKey(id))) tabs.value.push({ key: utTabKey(id), label: labelOf(utTabKey(id)) })
  activeKey.value = utTabKey(id)
  const i = tabs.value.findIndex((x) => x.key === 'create')
  if (i >= 0) tabs.value.splice(i, 1)
  if (!tabs.value.some((x) => x.key === 'list')) tabs.value.unshift({ key: 'list', label: t('unitTest.listTitle') })
}
function closeTab(key: string) {
  const i = tabs.value.findIndex((x) => x.key === key)
  if (i < 0) return
  tabs.value.splice(i, 1)
  if (activeKey.value === key) activeKey.value = tabs.value[tabs.value.length - 1]?.key ?? 'list'
}
function onCreated() {
  const s = store.activeSession
  if (s) openSession(s.id)
}
function onBackFromCreate() { openList() }

const query = ref('')
const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return sessions.value
  return sessions.value.filter((s) => s.title.toLowerCase().includes(q) || s.id.toLowerCase().includes(q))
})
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
        @click="openCreate"
      >
        <PlusIcon class="w-3.5 h-3.5" />{{ t('unitTest.newSession') }}
      </button>
    </div>

    <div class="flex-1 min-h-0 p-5 pt-3">
      <!-- 会话列表 -->
      <div
        v-if="activeKey === 'list'"
        class="h-full flex flex-col min-h-0"
      >
        <div class="shrink-0 flex items-center gap-2 mb-3">
          <div class="relative flex-1 max-w-xs">
            <MagnifyingGlassIcon class="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-ctp-overlay0" />
            <input
              v-model="query"
              class="input pl-8 !py-1.5 text-xs"
              :placeholder="t('unitTest.searchPlaceholder')"
            >
          </div>
          <span class="text-[11px] text-ctp-overlay1">{{ t('unitTest.sessionListHint') }}</span>
        </div>

        <div class="flex-1 min-h-0 overflow-auto panel">
          <table class="w-full text-left text-xs">
            <thead class="sticky top-0 bg-ctp-mantle text-ctp-overlay1">
              <tr>
                <th class="px-3 py-2 font-medium">{{ t('unitTest.colSession') }}</th>
                <th class="px-3 py-2 font-medium">{{ t('unitTest.colChannel') }}</th>
                <th class="px-3 py-2 font-medium">{{ t('unitTest.colStatus') }}</th>
                <th class="px-3 py-2 font-medium">{{ t('unitTest.colTests') }}</th>
                <th class="px-3 py-2 font-medium">{{ t('execute.colCreated') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="s in filtered"
                :key="s.id"
                class="border-t border-ctp-surface0 cursor-pointer transition-colors hover:bg-ctp-surface0/50"
                @click="openSession(s.id)"
              >
                <td class="px-3 py-2">
                  <div class="flex items-center gap-2">
                    <span class="font-mono text-[10px] text-ctp-overlay1 shrink-0">{{ s.id }}</span>
                    <span class="truncate">{{ s.title }}</span>
                  </div>
                </td>
                <td class="px-3 py-2">
                  <span class="chip" :class="channelClass[s.channel]">{{ t(`unitTest.channel.${s.channel}`) }}</span>
                </td>
                <td class="px-3 py-2">
                  <span class="chip" :class="statusClass[s.status]">{{ t(`unitTest.sessionStatus.${s.status}`) }}</span>
                </td>
                <td class="px-3 py-2 text-ctp-overlay1">{{ s.testIds.length }}</td>
                <td class="px-3 py-2 text-ctp-overlay1">{{ new Date(s.createdAt).toLocaleString() }}</td>
              </tr>
              <tr v-if="!filtered.length">
                <td colspan="5" class="px-3 py-10 text-center text-ctp-overlay0">{{ t('common.empty') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 新建会话 -->
      <UnitTestCreateView
        v-else-if="activeKey === 'create'"
        @created="onCreated"
        @back="onBackFromCreate"
      />

      <!-- 工作区 -->
      <UnitTestWorkspace
        v-else-if="activeSessionId"
        :session-id="activeSessionId"
        @close="closeTab(activeKey)"
      />
    </div>
  </div>
</template>