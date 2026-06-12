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
  nodeCount?: number
  fileCount?: number
  edgeCount?: number
  parentId?: string
  qualityScore?: number | null
  status?: string
}

const props = defineProps<{
  items: ExternalItem[]
  allCommunities?: CommNode[]
  edgeType?: string
}>()

const { t } = useI18n()
const { showId, componentId } = useComponentId('EH-001')

const topN = ref(20)
const drillCommId = ref<string | null>(null)
const drillChildrenPage = ref(1)
const drillChildrenPageSize = 40

function childrenOf(commId: string): CommNode[] {
  if (!props.allCommunities) return []
  return props.allCommunities.filter(c => c.parentId === commId)
}

const drillChildren = computed(() => childrenOf(drillCommId.value || ''))

const drillChildrenPaged = computed(() => {
  const start = (drillChildrenPage.value - 1) * drillChildrenPageSize
  return drillChildren.value.slice(start, start + drillChildrenPageSize)
})

const drillChildrenTotalPages = computed(() => Math.max(1, Math.ceil(drillChildren.value.length / drillChildrenPageSize)))

const drillLabel = computed(() => {
  if (!drillCommId.value) return ''
  return communityIdLabel(drillCommId.value)
})

const packages = computed(() => {
  const items = [...props.items].sort((a, b) => (b.fileCount || b.count || 0) - (a.fileCount || a.count || 0))
  return items.slice(0, topN.value).map(i => i.package || i.name || '')
})

const communities = computed(() => {
  const commMap = new Map<string, { id: string; name?: string; count: number }>()
  for (const item of props.items) {
    for (const c of (item.communities || [])) {
      const key = c.communityId
      if (!commMap.has(key)) {
        commMap.set(key, { id: c.communityId, name: c.name, count: 0 })
      }
      commMap.get(key)!.count += (item.fileCount || item.count || 0)
    }
  }
  return Array.from(commMap.values()).sort((a, b) => b.count - a.count).slice(0, topN.value)
})

const matrix = computed(() => {
  return communities.value.map(comm => {
    const row: number[] = []
    for (const pkg of packages.value) {
      let count = 0
      for (const item of props.items) {
        const key = item.package || item.name || ''
        if (key !== pkg) continue
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

const tooltip = ref('')
const tooltipX = ref(0)
const tooltipY = ref(0)

function showTooltip(event: MouseEvent, commName: string, pkgName: string, count: number) {
  tooltip.value = `${commName} × ${pkgName}: ${count} refs`
  tooltipX.value = event.clientX + 10
  tooltipY.value = event.clientY - 20
}

function hideTooltip() {
  tooltip.value = ''
}

function commLabel(c: { id: string; name?: string }): string {
  if (c.name && c.name !== c.id) return c.name.slice(0, 12)
  return communityIdLabel(c.id).slice(0, 20)
}

function handleDrill(commId: string) {
  const children = childrenOf(commId)
  if (children.length > 0) {
    drillCommId.value = commId
    drillChildrenPage.value = 1
  }
}

function handleRollUp() {
  drillCommId.value = null
  drillChildrenPage.value = 1
}
</script>

<template>
  <span v-if="showId" class="cmp-id">{{ componentId }}</span>
  <div class="ehm-container">
    <div class="ehm-toolbar">
      <button
        v-if="drillCommId"
        class="ehm-rollup-btn"
        :title="t('report.rollUp', '返回上层')"
        @click="handleRollUp"
      >\u2190</button>
      <span v-if="drillCommId" class="ehm-drill-label">{{ drillLabel }}</span>
      <span class="ehm-label">{{ t('report.matrixSize', '矩阵尺寸') }}:</span>
      <select v-model.number="topN" class="ehm-select">
        <option :value="10">10×10</option>
        <option :value="20">20×20</option>
        <option :value="30">30×30</option>
        <option :value="50">50×50</option>
      </select>
    </div>
    <div class="ehm-scroll" v-if="!drillCommId && matrix.length > 0 && packages.length > 0">
      <table class="ehm-table">
        <thead>
          <tr>
            <th class="ehm-corner"></th>
            <th v-for="pkg in packages" :key="pkg" class="ehm-col" :title="pkg">
              {{ pkg.length > 10 ? pkg.slice(0, 10) + '\u2026' : pkg }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="mr in matrix" :key="mr.comm.id">
            <td class="ehm-row-label" :title="commLabel(mr.comm)">
              {{ commLabel(mr.comm) }}
            </td>
            <td
              v-for="(count, ci) in mr.row"
              :key="ci"
              class="ehm-cell"
              :class="{ 'has-count': count > 0 }"
              :style="{ background: cellColor(count), opacity: opacity(count) }"
              @mouseenter="showTooltip($event, commLabel(mr.comm), packages[ci], count)"
              @mouseleave="hideTooltip"
              @dblclick="handleDrill(mr.comm.id)"
            >
              <span v-if="count > 0" class="cell-text">{{ count }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else-if="drillCommId && drillChildren.length > 0" class="ehm-scroll ehm-children-list">
      <table class="ehm-table">
        <thead>
          <tr>
            <th class="ehm-col-h">{{ t('report.communityArchitecture', '组件') }}</th>
            <th class="ehm-col-h">{{ t('report.nodes', '节点') }}</th>
            <th class="ehm-col-h">{{ t('report.files', '文件') }}</th>
            <th class="ehm-col-h">{{ t('report.edges', '边') }}</th>
            <th class="ehm-col-h">{{ t('report.qualityScore', '质量') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in drillChildrenPaged" :key="c.communityId" class="ehm-child-row">
            <td class="ehm-child-name" :title="c.communityId">{{ c.name ? c.name : communityIdLabel(c.communityId) }}</td>
            <td class="ehm-child-num">{{ c.nodeCount ?? '-' }}</td>
            <td class="ehm-child-num">{{ c.fileCount ?? '-' }}</td>
            <td class="ehm-child-num">{{ c.edgeCount ?? '-' }}</td>
            <td class="ehm-child-num">
              <span v-if="c.qualityScore != null">{{ (c.qualityScore * 100).toFixed(0) }}%</span>
              <span v-else>-</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else-if="drillCommId" class="ehm-empty">{{ t('report.noCommunities', '该社区无子组件') }}</div>
    <div v-if="drillCommId && drillChildrenTotalPages > 1" class="ehm-pagination">
      <button class="btn btn-ghost btn-xs" :disabled="drillChildrenPage <= 1" @click="drillChildrenPage--">{{ t('common.prev', '上一页') }}</button>
      <span class="ehm-page">{{ drillChildrenPage }} / {{ drillChildrenTotalPages }}</span>
      <button class="btn btn-ghost btn-xs" :disabled="drillChildrenPage >= drillChildrenTotalPages" @click="drillChildrenPage++">{{ t('common.next', '下一页') }}</button>
    </div>
    <div v-else class="ehm-empty">{{ t('report.noCommunities', '无关联数据') }}</div>
    <div
      v-if="tooltip"
      class="ehm-tooltip"
      :style="{ left: tooltipX + 'px', top: tooltipY + 'px' }"
    >{{ tooltip }}</div>
  </div>
</template>

<style scoped>
.ehm-container { display: flex; flex-direction: column; flex: 1; overflow: hidden; position: relative; align-items: center; justify-content: center; }
.ehm-toolbar { display: flex; align-items: center; gap: 0.5rem; padding: 0.35rem 0; flex-shrink: 0; align-self: stretch; }
.ehm-rollup-btn {
  display: flex; align-items: center; justify-content: center;
  width: 24px; height: 24px; padding: 0; font-size: 0.7rem;
  background: transparent; border: 1px solid transparent;
  border-radius: 0.25rem; color: var(--text-muted); cursor: pointer;
}
.ehm-rollup-btn:hover { background: var(--bg-tertiary); color: var(--text-primary); border-color: var(--border); }
.ehm-drill-label { font-size: 0.7rem; color: var(--accent, #7c3aed); font-weight: 500; }
.ehm-label { font-size: 0.75rem; color: var(--text-muted); }
.ehm-select {
  padding: 0.15rem 0.3rem; font-size: 0.75rem;
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: 0.25rem; color: var(--text-primary); outline: none;
}
.ehm-scroll { flex: 1; overflow: auto; display: flex; align-items: center; justify-content: center; }
.ehm-table { border-collapse: collapse; }
.ehm-corner { min-width: 100px; position: sticky; left: 0; z-index: 2; background: var(--bg-primary); }
.ehm-col {
  writing-mode: vertical-rl; text-orientation: mixed;
  padding: 0.2rem 0.3rem; font-size: 0.6rem; font-weight: 600;
  color: var(--text-muted); white-space: nowrap; height: 100px; vertical-align: bottom;
}
.ehm-row-label {
  position: sticky; left: 0; z-index: 1; background: var(--bg-primary);
  padding: 0.15rem 0.4rem; font-size: 0.65rem; font-weight: 500;
  color: var(--text-primary); white-space: nowrap; text-align: right; max-width: 120px;
  overflow: hidden; text-overflow: ellipsis;
}
.ehm-cell {
  width: 28px; height: 22px; text-align: center; border: 1px solid var(--border);
  transition: transform 0.1s; cursor: pointer;
}
.ehm-cell:hover { transform: scale(1.2); z-index: 1; }
.cell-text { font-size: 0.55rem; color: var(--text-primary); font-weight: 600; }
.ehm-empty { padding: 1rem; text-align: center; color: var(--text-muted); font-style: italic; font-size: 0.75rem; }
.ehm-tooltip {
  position: fixed; z-index: 300; pointer-events: none;
  padding: 0.2rem 0.5rem; font-size: 0.7rem; color: var(--text-primary);
  background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 0.25rem;
  white-space: nowrap;
}
.ehm-children-list { padding: 0.3rem 0; }
.ehm-col-h {
  padding: 0.3rem 0.5rem; font-size: 0.68rem; font-weight: 600; color: var(--text-muted);
  text-align: left; white-space: nowrap; border-bottom: 2px solid var(--border);
}
.ehm-child-row:hover { background: var(--bg-secondary); }
.ehm-child-name { font-size: 0.7rem; color: var(--text-primary); padding: 0.2rem 0.5rem; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ehm-child-num { font-size: 0.68rem; color: var(--text-muted); font-family: var(--font-mono); padding: 0.2rem 0.5rem; text-align: right; }
.ehm-pagination { display: flex; align-items: center; justify-content: center; gap: 0.5rem; padding: 0.35rem 0; flex-shrink: 0; }
.ehm-page { font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono); }
</style>
