<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import {
  ArrowsPointingOutIcon,
  ArrowUturnLeftIcon,
  TableCellsIcon,
  ChartBarIcon,
  Squares2X2Icon,
  ArrowPathIcon,
  FunnelIcon,
  DocumentArrowDownIcon,
} from '@heroicons/vue/24/outline'

const props = defineProps<{
  canRollUp: boolean
  externalMode?: boolean
  externalViewMode?: 'force' | 'table' | 'heatmap'
  internalViewMode?: 'force' | 'dagre' | 'table' | 'heatmap'
  filterActive?: boolean
}>()

const emit = defineEmits<{
  'roll-up': []
  'fullscreen': []
  'update:externalViewMode': [mode: 'force' | 'table' | 'heatmap']
  'update:internalViewMode': [mode: 'force' | 'dagre' | 'table' | 'heatmap']
  'reset-view': []
  'toggle-filter': [event?: MouseEvent]
  'export-arch': []
}>()

const { t } = useI18n()
</script>

<template>
  <div class="gt-container">
    <button
      v-if="props.canRollUp"
      class="gt-btn"
      :title="t('report.rollUp', '返回上层')"
      @click="emit('roll-up')"
    >
      <ArrowUturnLeftIcon class="w-3 h-3" />
    </button>

    <template v-if="externalMode">
      <button
        class="gt-btn gt-view-btn"
        :class="{ active: (externalViewMode || 'force') === 'force' }"
        :title="t('report.viewForce', '力导向图')"
        @click="emit('update:externalViewMode', 'force')"
      >
        <ChartBarIcon class="w-3 h-3" />
      </button>
      <button
        class="gt-btn gt-view-btn"
        :class="{ active: externalViewMode === 'table' }"
        :title="t('report.viewTable', '表格')"
        @click="emit('update:externalViewMode', 'table')"
      >
        <TableCellsIcon class="w-3 h-3" />
      </button>
      <button
        class="gt-btn gt-view-btn"
        :class="{ active: externalViewMode === 'heatmap' }"
        :title="t('report.viewHeatmap', '热力图')"
        @click="emit('update:externalViewMode', 'heatmap')"
      >
        <Squares2X2Icon class="w-3 h-3" />
      </button>
    </template>
    <template v-else>
      <button
        class="gt-btn gt-view-btn"
        :class="{ active: (internalViewMode || 'force') === 'force' }"
        :title="t('report.viewForce', '力导向图')"
        @click="emit('update:internalViewMode', 'force')"
      >
        <ChartBarIcon class="w-3 h-3" />
      </button>
      <button
        class="gt-btn gt-view-btn"
        :class="{ active: internalViewMode === 'dagre' }"
        :title="t('report.viewDagre', 'Dagre图')"
        @click="emit('update:internalViewMode', 'dagre')"
      >
        <ArrowUturnLeftIcon
          class="w-3 h-3"
          style="transform: rotate(90deg)"
        />
      </button>
      <button
        class="gt-btn gt-view-btn"
        :class="{ active: internalViewMode === 'table' }"
        :title="t('report.viewTable', '表格')"
        @click="emit('update:internalViewMode', 'table')"
      >
        <TableCellsIcon class="w-3 h-3" />
      </button>
      <button
        class="gt-btn gt-view-btn"
        :class="{ active: internalViewMode === 'heatmap' }"
        :title="t('report.viewHeatmap', '热力图')"
        @click="emit('update:internalViewMode', 'heatmap')"
      >
        <Squares2X2Icon class="w-3 h-3" />
      </button>
    </template>

    <button
      class="gt-btn"
      :title="t('report.resetView', '重置视图')"
      @click="emit('reset-view')"
    >
      <ArrowPathIcon class="w-3 h-3" />
    </button>
    <button
      class="gt-btn"
      :class="{ active: props.filterActive }"
      :title="t('report.nodeFilter', '节点筛选')"
      @click="(e: MouseEvent) => emit('toggle-filter', e)"
    >
      <FunnelIcon class="w-3 h-3" />
    </button>
    <button
      class="gt-btn"
      :title="t('report.exportArch', '导出架构文档')"
      @click="emit('export-arch')"
    >
      <DocumentArrowDownIcon class="w-3 h-3" />
    </button>
    <button
      class="gt-btn"
      :title="t('report.fullscreen', '全屏')"
      @click="emit('fullscreen')"
    >
      <ArrowsPointingOutIcon class="w-3 h-3" />
    </button>
  </div>
</template>

<style scoped>
.gt-container { display: flex; align-items: center; gap: 0.25rem; flex-shrink: 0; }
.gt-btn {
  display: flex; align-items: center; justify-content: center;
  width: 24px; height: 24px; padding: 0;
  background: transparent; border: 1px solid transparent;
  border-radius: 0.25rem; color: var(--text-muted); cursor: pointer;
  transition: all 0.15s;
}
.gt-btn:hover { background: var(--bg-tertiary); color: var(--text-primary); border-color: var(--border); }
.gt-btn.active { background: var(--bg-accent-subtle, #2d1f5e); color: var(--accent, #7c3aed); border-color: var(--accent, #7c3aed); }
.gt-style-btn { width: auto; padding: 0 0.35rem; }
.gt-view-btn { width: auto; padding: 0 0.3rem; }
.gt-style-label { font-size: 0.65rem; font-weight: 600; font-family: var(--font-mono); }
</style>
