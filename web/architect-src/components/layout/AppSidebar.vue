<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ClipboardDocumentListIcon, QueueListIcon,
  ServerStackIcon,
  GlobeAltIcon, ShieldCheckIcon, ShieldExclamationIcon, MapIcon, Cog6ToothIcon,
  ChevronDownIcon, ChevronRightIcon,
} from '@heroicons/vue/24/outline'
import { useArchArchitectureStore } from '@/stores/architecture-store'
import { useArchTaskStore } from '@/stores/task-store'
import { useArchAgentStore } from '@/stores/agent-store'
import { useArchSpecStore } from '@/stores/spec-store'
import { useArchMcpStore } from '@/stores/mcp-store'
import { useArchMergeBaselineStore } from '@/stores/merge-baseline-store'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const architecture = useArchArchitectureStore()
const task = useArchTaskStore()
const agent = useArchAgentStore()
const spec = useArchSpecStore()
const mcp = useArchMcpStore()
const mergeBaseline = useArchMergeBaselineStore()
mcp.load()
spec.load()
mergeBaseline.load()

const collapsed = ref<Record<string, boolean>>({})

const baselineSyncChip = computed(() => {
  if (mergeBaseline.sync.status === 'done') return '✓'
  if (mergeBaseline.sync.status === 'syncing') return '…'
  const n = mergeBaseline.uncommitted.length
  return n > 0 ? `±${n}` : '—'
})

function nav(path: string, query?: Record<string, string>) {
  router.push(query ? { path, query } : { path })
}

function toggle(section: string) {
  collapsed.value[section] = !collapsed.value[section]
}

function isOpen(section: string) {
  return !collapsed.value[section]
}

function isActive(path: string) {
  return route.path.startsWith(path)
}
</script>

<template>
  <aside class="w-64 shrink-0 flex flex-col bg-ctp-mantle border-r border-ctp-surface0">
    <div class="px-4 py-2.5 text-[11px] uppercase tracking-wider text-ctp-overlay1 border-b border-ctp-surface0">
      {{ t('nav.resource') }}
    </div>
    <div class="flex-1 overflow-auto py-2 space-y-1 text-sm">
      <button
        class="tree-section w-full text-left flex items-center justify-between cursor-pointer"
        @click="toggle('req')"
      >
        <span>{{ t('nav.tree.requirements') }}</span>
        <component
          :is="isOpen('req') ? ChevronDownIcon : ChevronRightIcon"
          class="w-3 h-3 text-ctp-overlay0"
        />
      </button>

      <template v-if="isOpen('req')">
        <button
          class="tree-item"
          :class="{ '!text-ctp-blue': isActive('/workbench/requirements') }"
          @click="nav('/workbench/requirements')"
        >
          <ClipboardDocumentListIcon class="w-4 h-4 text-ctp-sky" />
          <span class="flex-1 text-left">{{ t('nav.tree.requirements') }}</span>
        </button>

        <button
          class="tree-item"
          :class="{ '!text-ctp-blue': isActive('/workbench/execute') }"
          @click="nav('/workbench/execute')"
        >
          <QueueListIcon class="w-4 h-4 text-ctp-green" />
          <span class="flex-1 text-left">{{ t('nav.tree.tasks') }}</span>
          <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ task.doneCount }}/{{ task.totalCount }}</span>
        </button>
      </template>

      <button
        class="tree-section w-full text-left flex items-center justify-between cursor-pointer"
        @click="toggle('assets')"
      >
        <span>{{ t('nav.tree.dataAssets') }}</span>
        <component
          :is="isOpen('assets') ? ChevronDownIcon : ChevronRightIcon"
          class="w-3 h-3 text-ctp-overlay0"
        />
      </button>

      <template v-if="isOpen('assets')">
        <button
          class="tree-item"
          :class="{ '!text-ctp-blue': isActive('/workbench/assets') && (!route.query.tab || route.query.tab === 'modules') && !route.query.sub }"
          @click="nav('/workbench/assets', { tab: 'modules' })"
        >
          <ServerStackIcon class="w-4 h-4 text-ctp-blue" />
          <span class="flex-1 text-left">{{ t('nav.tree.components') }}</span>
          <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ architecture.components.length }}</span>
        </button>

        <button
          class="tree-item"
          :class="{ '!text-ctp-blue': isActive('/workbench/assets') && route.query.tab === 'spec' }"
          @click="nav('/workbench/assets', { tab: 'spec' })"
        >
          <ShieldCheckIcon class="w-4 h-4 text-ctp-peach" />
          <span class="flex-1 text-left">{{ t('nav.tree.spec') }}</span>
          <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ spec.ruleCount }}</span>
        </button>

        <button
          class="tree-item"
          :class="{ '!text-ctp-blue': isActive('/workbench/archmap') && route.query.view === 'impact' }"
          @click="nav('/workbench/archmap', { view: 'impact' })"
        >
          <MapIcon class="w-4 h-4 text-ctp-mauve" />
          <span class="flex-1 text-left">{{ t('nav.tree.impact') }}</span>
          <span class="chip bg-ctp-surface0 text-ctp-subtext0">v0→v1</span>
        </button>
        <button
          class="tree-item"
          :class="{ '!text-ctp-blue': isActive('/workbench/archmap') && route.query.view === 'merge' }"
          @click="nav('/workbench/archmap', { view: 'merge' })"
        >
          <ShieldExclamationIcon class="w-4 h-4 text-ctp-sapphire" />
          <span class="flex-1 text-left">{{ t('nav.tree.mergeBaseline') }}</span>
          <span
            class="chip"
            :class="mergeBaseline.sync.status === 'done' ? 'bg-ctp-green/15 text-ctp-green' : 'bg-ctp-surface0 text-ctp-subtext0'"
          >{{ baselineSyncChip }}</span>
        </button>
      </template>

      <button
        class="tree-section w-full text-left flex items-center justify-between cursor-pointer"
        @click="toggle('ext')"
      >
        <span>{{ t('nav.tree.external') }}</span>
        <component
          :is="isOpen('ext') ? ChevronDownIcon : ChevronRightIcon"
          class="w-3 h-3 text-ctp-overlay0"
        />
      </button>

      <template v-if="isOpen('ext')">
        <button
          class="tree-item"
          @click="nav('/workbench/mcp')"
        >
          <GlobeAltIcon class="w-4 h-4 text-ctp-sky" />
          <span class="flex-1 text-left">{{ t('nav.tree.mcp') }}</span>
          <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ mcp.calls.length || '—' }}</span>
        </button>
      </template>

      <button
        class="tree-section w-full text-left flex items-center justify-between cursor-pointer"
        @click="toggle('cfg')"
      >
        <span>{{ t('nav.tree.config') }}</span>
        <component
          :is="isOpen('cfg') ? ChevronDownIcon : ChevronRightIcon"
          class="w-3 h-3 text-ctp-overlay0"
        />
      </button>

      <template v-if="isOpen('cfg')">
        <button
          class="tree-item"
          @click="nav('/workbench/config')"
        >
          <Cog6ToothIcon class="w-4 h-4 text-ctp-lavender" />
          <span class="flex-1 text-left">{{ t('nav.tree.config') }}</span>
          <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ agent.adapters.length }}</span>
        </button>
      </template>
    </div>
  </aside>
</template>

<style scoped>
.tree-item {
  @apply w-full flex items-center gap-2 px-3 py-1.5 text-ctp-subtext0 hover:bg-ctp-surface0 hover:text-ctp-text transition-colors cursor-pointer;
}
.tree-sub-item {
  @apply w-full flex items-center gap-1.5 py-1 text-xs text-ctp-overlay1 hover:text-ctp-text transition-colors cursor-pointer;
}
.tree-section {
  @apply px-3 pt-3 pb-1 text-[10px] uppercase tracking-wider text-ctp-overlay1 hover:text-ctp-text transition-colors;
}
</style>
