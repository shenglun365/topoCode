<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useComponentId } from '@/composables/useComponentId'
import { communityIdLabel } from '@/utils/communityLabel'

interface ExternalItem {
  package?: string
  name?: string
  fileCount?: number
  count?: number
  files: string[]
  communities?: Array<{ communityId: string; name?: string }>
}

interface CommNode {
  communityId: string
  name?: string
  parentId?: string
}

const props = defineProps<{
  items: ExternalItem[]
  allCommunities?: CommNode[]
  showGuideButton?: boolean
}>()

const emit = defineEmits<{
  'drill': [communityId: string]
  'guide-click': []
}>()

const { t } = useI18n()
const { showId, componentId } = useComponentId('EH-001')

const topN = ref(20)
const scale = ref(1)
const scrollRef = ref<HTMLElement | null>(null)

const tooltip = ref('')
const tooltipX = ref(0)
const tooltipY = ref(0)

watch(topN, (v) => {
  console.log('[Heatmap] topN change →', v, 'items:', props.items.length)
})

watch(scale, (newVal) => {
  console.log('[Heatmap] scale →', newVal.toFixed(1),
    'baseW×baseH:', baseW.value, '×', baseH.value,
    'computedW×H:', Math.round(baseW.value * newVal), '×', Math.round(baseH.value * newVal))
})

const CELL_W = 30
const CELL_H = 24
const CORNER_W = 90
const LABEL_W = 100

const packages = computed(() => {
  const sorted = [...props.items].sort((a, b) => (b.fileCount || b.count || 0) - (a.fileCount || a.count || 0))
  return sorted.slice(0, topN.value).map(i => i.package || i.name || '')
})

const communities = computed(() => {
  const commMap = new Map<string, { id: string; name?: string; count: number; hasChildren: boolean }>()
  for (const item of props.items) {
    for (const c of (item.communities || [])) {
      const key = c.communityId
      if (!commMap.has(key)) {
        const hasChildren = (props.allCommunities || []).some(cm => cm.parentId === c.communityId)
        commMap.set(key, { id: c.communityId, name: c.name, count: 0, hasChildren })
      }
      commMap.get(key)!.count += (item.fileCount || item.count || 0)
    }
  }
  return Array.from(commMap.values()).sort((a, b) => b.count - a.count).slice(0, topN.value)
})

const baseW = computed(() => CORNER_W + packages.value.length * CELL_W + LABEL_W)
const baseH = computed(() => Math.max(1, communities.value.length) * CELL_H)

const matrix = computed(() => {
  return communities.value.map(comm => {
    const row: number[] = []
    for (const pkgLabel of packages.value) {
      let count = 0
      for (const item of props.items) {
        const key = item.package || item.name || ''
        if (key !== pkgLabel) continue
        const commIds = (item.communities || []).map(c => c.communityId)
        if (commIds.includes(comm.id)) {
          count += (item.fileCount || item.count || 0)
        }
      }
      row.push(count)
    }
    return { comm, row }
  })
})

const maxCount = computed(() => {
  let m = 1
  for (const r of matrix.value) {
    for (const c of r.row) {
      if (c > m) m = c
    }
  }
  return m
})

function opacity(count: number): number {
  if (count === 0) return 0
  return 0.1 + (count / maxCount.value) * 0.7
}

function cellColor(count: number): string {
  if (count === 0) return 'transparent'
  const ratio = count / maxCount.value
  const r = Math.round(60 + ratio * 180)
  const g = Math.round(60 + (1 - ratio) * 80)
  const b = Math.round(220 - ratio * 100)
  return `rgb(${r}, ${g}, ${b})`
}

function showTooltip(event: MouseEvent, commName: string, pkgName: string, count: number) {
  tooltip.value = `${commName} × ${pkgName}: ${count} refs`
  tooltipX.value = event.clientX + 10
  tooltipY.value = event.clientY - 20
}

function hideTooltip() { tooltip.value = '' }

function commLabel(c: { id: string; name?: string }): string {
  if (c.name && c.name !== c.id) return c.name.slice(0, 12)
  return communityIdLabel(c.id).slice(0, 20)
}

function onWheel(e: WheelEvent) {
  if (!e.ctrlKey && !e.metaKey) return
  e.preventDefault()
  const delta = -e.deltaY * 0.002
  scale.value = Math.max(0.4, Math.min(3.0, Number((scale.value + delta).toFixed(1))))
}
</script>

<template>
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
  <div class="ehm-container">
    <div class="ehm-zoom-overlay">
      <span class="ehm-label">{{ t('report.matrixSize', '矩阵尺寸') }}:</span>
      <select
        v-model.number="topN"
        class="ehm-size-select"
      >
        <option :value="10">
          10×10
        </option>
        <option :value="20">
          20×20
        </option>
        <option :value="30">
          30×30
        </option>
        <option :value="50">
          50×50
        </option>
      </select>
      <span class="ehm-overlay-sep" />
      <button
        class="ehm-zoom-btn"
        :disabled="scale <= 0.4"
        title="缩小"
        @click="scale = Math.max(0.4, Number((scale - 0.2).toFixed(1)))"
      >
        −
      </button>
      <span class="ehm-zoom-label">{{ Math.round(scale * 100) }}%</span>
      <button
        class="ehm-zoom-btn"
        :disabled="scale >= 3.0"
        title="放大"
        @click="scale = Math.min(3.0, Number((scale + 0.2).toFixed(1)))"
      >
        +
      </button>
      <button
        class="ehm-zoom-btn"
        title="重置"
        @click="scale = 1"
      >
        {{ t('report.resetView', '重置') }}
      </button>
    </div>

    <div
      v-if="matrix.length > 0 && packages.length > 0"
      ref="scrollRef"
      class="ehm-scroll"
      @wheel="onWheel"
    >
      <div
        class="ehm-table-wrap"
        :style="{ width: baseW + 'px', height: baseH + 'px', zoom: scale }"
      >
        <table class="ehm-table">
          <thead>
            <tr>
              <th class="ehm-corner" />
              <th
                v-for="pkg in packages"
                :key="pkg"
                class="ehm-col"
                :title="pkg"
              >
                {{ pkg.length > 8 ? pkg.slice(0, 8) + '\u2026' : pkg }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="mr in matrix"
              :key="mr.comm.id"
            >
              <td
                class="ehm-row-label"
                :class="{ 'ehm-row-drillable': mr.comm.hasChildren }"
                :title="commLabel(mr.comm) + (mr.comm.hasChildren ? ' — ' + t('report.dblclickToDrill', '双击下钻') : '')"
              >
                {{ commLabel(mr.comm) }}
              </td>
              <td
                v-for="(count, ci) in mr.row"
                :key="ci"
                class="ehm-cell"
                :style="{ background: cellColor(count), opacity: opacity(count) }"
                @mouseenter="showTooltip($event, commLabel(mr.comm), packages[ci], count)"
                @mouseleave="hideTooltip"
                @dblclick="mr.comm.hasChildren && emit('drill', mr.comm.id)"
              >
                <span
                  v-if="count > 0"
                  class="cell-text"
                >{{ count }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div
      v-else
      class="ehm-empty"
    >
      {{ t('report.noCommunities', '无关联数据') }}
    </div>

    <div
      v-if="tooltip"
      class="ehm-tooltip"
      :style="{ left: tooltipX + 'px', top: tooltipY + 'px' }"
    >
      {{ tooltip }}
    </div>

    <button
      v-if="showGuideButton !== false"
      class="ehm-guide-btn"
      @click="emit('guide-click')"
    >
      <svg
        class="w-4 h-4"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      ><path d="M2.25 12.76c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 0 1 1.037-.443 48.282 48.282 0 0 0 5.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z" /></svg>
    </button>
  </div>
</template>

<style scoped>
.ehm-container { display: flex; flex-direction: column; flex: 1; overflow: hidden; position: relative; align-items: center; }

.ehm-zoom-overlay {
  position: absolute; top: 12px; left: 12px; z-index: 211;
  display: flex; align-items: center; gap: 0.3rem;
  padding: 0.15rem 0.35rem;
  background: var(--bg-primary); border: 1px solid var(--border);
  border-radius: 0.25rem;
}
.ehm-label { font-size: 0.7rem; color: var(--text-muted); }
.ehm-size-select {
  padding: 0.05rem 0.15rem; font-size: 0.65rem;
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: 0.2rem; color: var(--text-primary); outline: none; cursor: pointer;
}
.ehm-overlay-sep { width: 1px; height: 14px; background: var(--border); }
.ehm-zoom-btn {
  display: flex; align-items: center; justify-content: center;
  min-width: 22px; height: 20px; padding: 0 0.25rem; font-size: 0.65rem;
  background: transparent; border: 1px solid var(--border);
  border-radius: 0.2rem; color: var(--text-muted); cursor: pointer;
}
.ehm-zoom-btn:hover:not(:disabled) { color: var(--text-primary); border-color: var(--accent); }
.ehm-zoom-btn:disabled { opacity: 0.3; cursor: default; }
.ehm-zoom-label { font-size: 0.65rem; color: var(--text-muted); font-family: var(--font-mono); min-width: 32px; text-align: center; }

.ehm-scroll { flex: 1; overflow: auto; display: flex; align-items: center; justify-content: safe center; }
.ehm-table-wrap { display: inline-block; }
.ehm-table { border-collapse: collapse; }
.ehm-corner { min-width: 90px; position: sticky; left: 0; z-index: 2; background: var(--bg-primary); }
.ehm-col {
  writing-mode: vertical-rl; text-orientation: mixed;
  padding: 0.2rem 0.3rem; font-size: 0.6rem; font-weight: 600;
  color: var(--text-muted); white-space: nowrap; height: 80px; vertical-align: bottom;
}
.ehm-row-label {
  position: sticky; left: 0; z-index: 1; background: var(--bg-primary);
  padding: 0.15rem 0.4rem; font-size: 0.62rem; font-weight: 500;
  color: var(--text-primary); white-space: nowrap; text-align: right; max-width: 100px;
  overflow: hidden; text-overflow: ellipsis;
}
.ehm-row-drillable { cursor: pointer; }
.ehm-row-drillable:hover { color: var(--accent, #7c3aed); }
.ehm-cell {
  width: 30px; height: 24px; text-align: center; border: 1px solid var(--border);
  transition: transform 0.1s; cursor: pointer;
}
.ehm-cell:hover { transform: scale(1.25); z-index: 1; }
.cell-text { font-size: 0.55rem; color: var(--text-primary); font-weight: 600; }
.ehm-empty { padding: 1rem; text-align: center; color: var(--text-muted); font-style: italic; font-size: 0.75rem; }
.ehm-tooltip {
  position: fixed; z-index: 300; pointer-events: none;
  padding: 0.2rem 0.5rem; font-size: 0.7rem; color: var(--text-primary);
  background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 0.25rem;
  white-space: nowrap;
}
.ehm-guide-btn {
  position: absolute; bottom: 12px; right: 12px; z-index: 211;
  width: 32px; height: 32px; padding: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 1rem;
  background: var(--bg-primary); color: var(--accent);
  border: 1px solid var(--accent); border-radius: 50%;
  cursor: pointer; transition: all 0.15s;
}
.ehm-guide-btn:hover {
  background: var(--accent); color: #fff;
  box-shadow: 0 0 8px rgba(124, 58, 237, 0.4);
}
</style>
