<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
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
}>()

const emit = defineEmits<{
  'drill': [communityId: string]
}>()

const { t } = useI18n()
const { showId, componentId } = useComponentId('EH-001')

const topN = ref(20)
const scale = ref(1)
const tooltip = ref('')
const tooltipX = ref(0)
const tooltipY = ref(0)
const scrollRef = ref<HTMLElement | null>(null)

/* ---- auto-size topN to fill container ---- */
const CELL_W = 30
const CELL_H = 24
const CORNER_W = 90
const LABEL_W = 100
const TOOLBAR_H = 38

const baseW = computed(() => CORNER_W + packages.value.length * CELL_W + LABEL_W)
const baseH = computed(() => Math.max(1, communities.value.length) * CELL_H)

const zoomStyle = computed(() => ({
  transform: `scale(${scale.value})`,
  transformOrigin: '0 0',
  width: `${baseW.value * scale.value}px`,
  height: `${baseH.value * scale.value}px`,
}))

function autoSize() {
  const el = scrollRef.value?.parentElement
  if (!el) return
  const cw = el.clientWidth - CORNER_W - LABEL_W - 16
  const ch = el.clientHeight - TOOLBAR_H - 8
  const cols = Math.max(5, Math.floor(cw / CELL_W))
  const rows = Math.max(5, Math.floor(ch / CELL_H))
  const maxContent = Math.max(
    new Set(props.items.map(i => i.package || i.name || '')).size,
    ...props.items.map(i => (i.communities || []).length)
  )
  topN.value = Math.min(cols, rows, Math.max(10, maxContent), 60)
}

let resizeObs: ResizeObserver | null = null
onMounted(() => {
  nextTick(autoSize)
  if (scrollRef.value?.parentElement) {
    resizeObs = new ResizeObserver(() => autoSize())
    resizeObs.observe(scrollRef.value.parentElement)
  }
})
onUnmounted(() => resizeObs?.disconnect())

watch(() => props.items, () => {
  scale.value = 1
  nextTick(autoSize)
})

/* ---- scroll-wheel zoom ---- */
function onWheel(e: WheelEvent) {
  if (e.ctrlKey || e.metaKey) {
    e.preventDefault()
    const delta = -e.deltaY * 0.002
    scale.value = Math.max(0.4, Math.min(3.0, scale.value + delta))
  }
}

const packages = computed(() => {
  const items = [...props.items].sort((a, b) => (b.fileCount || b.count || 0) - (a.fileCount || a.count || 0))
  return items.slice(0, topN.value).map(i => i.name || i.package || '')
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

const matrix = computed(() => {
  return communities.value.map(comm => {
    const row: number[] = []
    for (const pkgLabel of packages.value) {
      let count = 0
      for (const item of props.items) {
        const key = item.name || item.package || ''
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
</script>

<template>
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
  <div class="ehm-container">
    <div class="ehm-toolbar">
      <span class="ehm-label">{{ t('report.matrixSize', '矩阵') }}: {{ communities.length }}×{{ packages.length }}</span>
      <button
        class="ehm-zoom-btn"
        :disabled="scale <= 0.4"
        title="Zoom out"
        @click="scale = Math.max(0.4, scale - 0.2)"
      >
        −
      </button>
      <span class="ehm-zoom-label">{{ Math.round(scale * 100) }}%</span>
      <button
        class="ehm-zoom-btn"
        :disabled="scale >= 3.0"
        title="Zoom in"
        @click="scale = Math.min(3.0, scale + 0.2)"
      >
        +
      </button>
      <button
        class="ehm-zoom-btn"
        :disabled="scale === 1"
        title="Reset zoom"
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
        :style="zoomStyle"
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
  </div>
</template>

<style scoped>
.ehm-container { display: flex; flex-direction: column; flex: 1; overflow: hidden; position: relative; align-items: center; justify-content: center; }
.ehm-toolbar { display: flex; align-items: center; gap: 0.4rem; padding: 0.3rem 0; flex-shrink: 0; align-self: stretch; }
.ehm-label { font-size: 0.7rem; color: var(--text-muted); }
.ehm-zoom-btn {
  display: flex; align-items: center; justify-content: center;
  min-width: 22px; height: 20px; padding: 0 0.25rem; font-size: 0.65rem;
  background: transparent; border: 1px solid var(--border);
  border-radius: 0.2rem; color: var(--text-muted); cursor: pointer;
}
.ehm-zoom-btn:hover:not(:disabled) { color: var(--text-primary); border-color: var(--accent); }
.ehm-zoom-btn:disabled { opacity: 0.3; cursor: default; }
.ehm-zoom-label { font-size: 0.65rem; color: var(--text-muted); font-family: var(--font-mono); min-width: 32px; text-align: center; }
.ehm-scroll { flex: 1; overflow: auto; display: flex; align-items: flex-start; justify-content: center; padding: 8px 4px; }
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
</style>
