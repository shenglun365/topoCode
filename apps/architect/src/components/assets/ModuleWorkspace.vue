<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ServerStackIcon, MagnifyingGlassIcon, ClockIcon } from '@heroicons/vue/24/outline'
import BaselineSummaryBar from './BaselineSummaryBar.vue'
import KbQueryView from './KbQueryView.vue'
import KbQueryHistory from './KbQueryHistory.vue'
import ComponentListView from './ComponentListView.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

// ---- 工作区视图切换: 复合查询 / 组件浏览 / 历史信息流 ----
type WorkspaceView = 'query' | 'browse' | 'history'
const view = ref<WorkspaceView>(route.query.view === 'browse' || route.query.view === 'history' ? route.query.view : 'query')
watch(
  () => route.query.view,
  (q) => {
    if (q === 'browse' || q === 'history' || q === 'query') view.value = q
  },
)
function setView(v: WorkspaceView) {
  view.value = v
  router.replace({ query: { ...route.query, tab: 'modules', view: v } })
}

// ---- 组件浏览: 列表选择 ----
const selectedComp = ref('')

/** 查看详情：选中组件(供后续引用/跳转)。 */
function openComponentDoc(id: string) {
  selectedComp.value = id
}
</script>

<template>
  <div class="space-y-4">
    <BaselineSummaryBar />

    <!-- 工作区视图切换 -->
    <div class="flex items-center gap-1 bg-ctp-crust/60 rounded-lg p-1 w-fit">
      <button
        class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors"
        :class="view === 'query' ? 'bg-ctp-surface1 text-ctp-text' : 'text-ctp-subtext0 hover:text-ctp-text'"
        @click="setView('query')"
      >
        <MagnifyingGlassIcon class="w-4 h-4" />{{ t('kbQuery.tab.query') }}
      </button>
      <button
        class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors"
        :class="view === 'browse' ? 'bg-ctp-surface1 text-ctp-text' : 'text-ctp-subtext0 hover:text-ctp-text'"
        @click="setView('browse')"
      >
        <ServerStackIcon class="w-4 h-4" />{{ t('kbQuery.tab.browse') }}
      </button>
      <button
        class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors"
        :class="view === 'history' ? 'bg-ctp-surface1 text-ctp-text' : 'text-ctp-subtext0 hover:text-ctp-text'"
        @click="setView('history')"
      >
        <ClockIcon class="w-4 h-4" />{{ t('kbQuery.tab.history') }}
      </button>
    </div>

    <!-- 复合查询视图 -->
    <KbQueryView v-if="view === 'query'" />

    <!-- 历史信息流 -->
    <KbQueryHistory v-else-if="view === 'history'" />

    <!-- 组件浏览视图(列表 + 翻页 + 关键字查找) -->
    <div
      v-else
      class="grid grid-cols-1 xl:grid-cols-6 gap-4"
    >
      <div class="xl:col-span-6">
        <ComponentListView
          @select="selectedComp = $event"
          @open-detail="openComponentDoc"
        />
      </div>
    </div>
  </div>
</template>
