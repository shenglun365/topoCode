<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  GlobeAltIcon, ChatBubbleLeftRightIcon, ShieldCheckIcon, MapIcon,
  ShieldExclamationIcon, Squares2X2Icon, Cog6ToothIcon,
  ChevronDoubleLeftIcon, ChevronDoubleRightIcon,
} from '@heroicons/vue/24/outline'
import { useArchSpecStore } from '@/stores/spec-store'
import { useArchMcpStore } from '@/stores/mcp-store'
import { useArchMergeBaselineStore } from '@/stores/merge-baseline-store'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const spec = useArchSpecStore()
const mcp = useArchMcpStore()
const mergeBaseline = useArchMergeBaselineStore()
mcp.load()
spec.load()
mergeBaseline.load()

/** 缩略 rail 模式(仅图标)：持久化，腾出工作区可视空间。 */
const RAIL_KEY = 'arch.sidebar.rail'
const rail = ref(localStorage.getItem(RAIL_KEY) === '1')
function toggleRail() {
  rail.value = !rail.value
  localStorage.setItem(RAIL_KEY, rail.value ? '1' : '0')
}

const baselineSyncChip = computed(() => {
  if (mergeBaseline.sync.status === 'done') return '✓'
  if (mergeBaseline.sync.status === 'syncing') return '…'
  const n = mergeBaseline.uncommitted.length
  return n > 0 ? `±${n}` : '—'
})

function nav(path: string, query?: Record<string, string>) {
  router.push(query ? { path, query } : { path })
}

function isActive(path: string) {
  return route.path.startsWith(path)
}

/** 工作区首页(/workbench)是否激活：精确匹配不带子路径。 */
function isOverviewActive() {
  return route.path === '/workbench' || route.path === '/workbench/'
}

/** P1 会话中心：扁平导航(单层) —— 项目概览/会话管理/项目规约/资产地图/基线管理/MCP/系统管理 */
const items = computed(() => ([
  { key: 'overview', path: '/workbench/', icon: GlobeAltIcon, color: 'text-ctp-mauve', exact: true, chip: '' },
  { key: 'sessions', path: '/workbench/sessions', icon: ChatBubbleLeftRightIcon, color: 'text-ctp-sky', chip: '' },
  { key: 'spec', path: '/workbench/assets', query: { tab: 'spec' }, icon: ShieldCheckIcon, color: 'text-ctp-peach', chip: String(spec.ruleCount || '') },
  { key: 'assetMap', path: '/workbench/asset-mgmt', icon: MapIcon, color: 'text-ctp-mauve', chip: '' },
  { key: 'baseline', path: '/workbench/archmap', query: { view: 'merge' }, icon: ShieldExclamationIcon, color: 'text-ctp-sapphire', chip: baselineSyncChip.value },
  { key: 'mcp', path: '/workbench/mcp', icon: Squares2X2Icon, color: 'text-ctp-sky', chip: String(mcp.calls.length || '') },
  { key: 'config', path: '/workbench/config', icon: Cog6ToothIcon, color: 'text-ctp-lavender', chip: '' },
]))
</script>

<template>
  <aside
    class="shrink-0 flex flex-col bg-ctp-mantle border-r border-ctp-surface0 transition-[width] duration-150"
    :class="rail ? 'w-12' : 'w-56'"
  >
    <div class="flex-1 overflow-auto py-2 space-y-1 text-sm">
      <button
        v-for="item in items"
        :key="item.key"
        class="tree-item"
        :class="{ 'is-active': item.exact ? isOverviewActive() : isActive(item.path) }"
        :title="t(`nav.flat.${item.key}`)"
        @click="nav(item.path, item.query)"
      >
        <component :is="item.icon" class="w-4 h-4" :class="item.color" />
        <span v-if="!rail" class="flex-1 text-left">{{ t(`nav.flat.${item.key}`) }}</span>
        <span
          v-if="!rail && item.chip && item.chip !== '—'"
          class="chip bg-ctp-surface0 text-ctp-subtext0"
          :class="item.key === 'baseline' && mergeBaseline.sync.status === 'done' ? 'bg-ctp-green/15 !text-ctp-green' : ''"
        >{{ item.chip }}</span>
      </button>
    </div>

    <div class="shrink-0 border-t border-ctp-surface0 py-1">
      <button
        class="tree-item"
        :class="rail ? 'justify-center' : ''"
        :title="rail ? t('nav.expand') : t('nav.rail')"
        @click="toggleRail"
      >
        <component
          :is="rail ? ChevronDoubleRightIcon : ChevronDoubleLeftIcon"
          class="w-4 h-4 text-ctp-overlay1"
        />
        <span v-if="!rail" class="flex-1 text-left text-xs">{{ t('nav.rail') }}</span>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.tree-item {
  @apply w-full flex items-center gap-2 px-3 py-1.5 text-ctp-subtext0 hover:bg-ctp-surface0 hover:text-ctp-text transition-colors cursor-pointer;
}
.tree-item.is-active {
  @apply bg-ctp-surface0 text-ctp-blue;
}
.tree-item.is-active > svg {
  @apply text-ctp-blue;
}
</style>
