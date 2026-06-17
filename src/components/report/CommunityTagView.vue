<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCommunityStore, type CommunityItem } from '@/stores/community-store'
import { useComponentSelectionStore } from '@/stores/component-selection-store'
import { useComponentId } from '@/composables/useComponentId'
import { communityLabel } from '@/utils/communityLabel'

const { t } = useI18n()
const communityStore = useCommunityStore()
const selectionStore = useComponentSelectionStore()

const props = defineProps<{
  taskId: string
  edgeType: 'INCLUDE' | 'CALL' | 'EXTERNAL_INCLUDE' | 'EXTERNAL_CALL'
  externalStats: any
  availableLevels: string[]
  search: string
}>()

const emit = defineEmits<{
  'open-community': [item: CommunityItem]
}>()

const { showId, componentId } = useComponentId('CT-001')

const isExternalTab = computed(() =>
  props.edgeType === 'EXTERNAL_INCLUDE' || props.edgeType === 'EXTERNAL_CALL'
)

const selectedLevel = ref('L0')

watch(() => props.availableLevels, (levels) => {
  if (levels.length > 0 && !levels.includes(selectedLevel.value)) {
    selectedLevel.value = levels[0]
  }
}, { immediate: true })

const levelCommunities = computed(() => {
  if (isExternalTab.value) return []
  const coms = communityStore.tasks[props.taskId]?.communities || []
  return coms.filter(c =>
    c.edgeType === props.edgeType &&
    c.level === selectedLevel.value
  )
})

const filteredCommunities = computed(() => {
  const q = props.search.trim().toLowerCase()
  if (!q) return levelCommunities.value
  return levelCommunities.value.filter(c => {
    const name = (c.name || '').toLowerCase()
    const id = c.communityId.toLowerCase()
    return name.includes(q) || id.includes(q)
  })
})

const page = ref(1)
const pageSize = ref(72)
const containerRef = ref<HTMLElement | null>(null)

function calcPageSize() {
  if (!containerRef.value) return
  const h = containerRef.value.clientHeight
  if (h > 0) {
    const size = Math.max(50, Math.min(200, Math.floor(h / 28)))
    pageSize.value = size
  }
}

let resizeObs: ResizeObserver | null = null
onMounted(async () => {
  await nextTick()
  calcPageSize()
  if (containerRef.value) {
    resizeObs = new ResizeObserver(() => calcPageSize())
    resizeObs.observe(containerRef.value)
  }
})
onUnmounted(() => {
  resizeObs?.disconnect()
})

watch(() => props.search, () => { page.value = 1 })

const totalPages = computed(() => Math.max(1, Math.ceil(filteredCommunities.value.length / pageSize.value)))
const pagedCommunities = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredCommunities.value.slice(start, start + pageSize.value)
})

function commName(item: CommunityItem): string {
  return communityLabel(item)
}

function levelLabel(lv: string): string {
  if (lv === 'L0') return t('report.l0Community', 'L0 社区')
  const num = lv.slice(1)
  return t('report.lxCommunity', { level: num })
}

function handleTagClick(item: CommunityItem) {
  if (selectionStore.selecting) {
    selectionStore.toggle({
      id: item.communityId,
      type: 'community',
      name: communityLabel(item),
      taskId: props.taskId,
      metadata: {
        nodeCount: item.nodeCount,
        fileCount: item.fileCount,
        qualityScore: item.qualityScore ?? undefined,
      },
    })
    return
  }
  emit('open-community', item)
}

function handleExternalTagClick(name: string, count: number) {
  if (!selectionStore.selecting) return
  selectionStore.toggle({
    id: name,
    type: 'external_package',
    name,
    taskId: props.taskId,
    metadata: { fileCount: count },
  })
}
</script>

<template>
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
  <div
    ref="containerRef"
    class="ctv-container"
  >
    <div
      v-if="!isExternalTab"
      class="ctv-level-filter"
    >
      <span class="level-filter-label">{{ t('report.level', '层级') }}:</span>
      <button
        v-for="lv in props.availableLevels"
        :key="lv"
        class="level-filter-btn"
        :class="{ active: selectedLevel === lv }"
        @click="selectedLevel = lv; page = 1"
      >
        {{ levelLabel(lv) }}
      </button>
    </div>

    <div
      v-if="!isExternalTab"
      class="arch-tags"
    >
      <div
        v-for="item in pagedCommunities"
        :key="item.id"
        class="arch-tag"
        :class="{
          'has-name': item.status === 'completed' && item.name && item.name !== item.communityId,
          'selected': selectionStore.isSelected(item.communityId),
          'selecting': selectionStore.selecting,
        }"
        :title="`${item.communityId} (${item.nodeCount} 节点${item.qualityScore ? ', 质量: ' + (item.qualityScore * 100).toFixed(0) + '%' : ''})`"
        @click="handleTagClick(item)"
      >
        <span class="tag-name">{{ commName(item) }}</span>
        <span class="tag-count">{{ item.nodeCount }}</span>
      </div>
      <div
        v-if="filteredCommunities.length === 0"
        class="arch-empty"
      >
        {{ props.search ? t('report.noSearchResults', '无匹配社区') : t('report.noCommunities', '该视角下无社区数据') }}
      </div>
    </div>

    <div
      v-if="isExternalTab && props.externalStats"
      class="arch-tags"
    >
      <template v-if="props.edgeType === 'EXTERNAL_INCLUDE'">
        <div
          v-for="dep in props.externalStats.externalDeps.slice(0, 50)"
          :key="dep.package"
          class="arch-tag"
          :class="{ 'selected': selectionStore.isSelected(dep.package), 'selecting': selectionStore.selecting }"
          :title="dep.files.slice(0, 10).join('\n') + (dep.files.length > 10 ? '\n...' + (dep.files.length - 10) + ' more' : '')"
          @click="handleExternalTagClick(dep.package, dep.fileCount)"
        >
          <span class="tag-name">{{ dep.package }}</span>
          <span class="tag-count">{{ dep.fileCount }}</span>
        </div>
      </template>
      <template v-if="props.edgeType === 'EXTERNAL_CALL'">
        <div
          v-for="call in props.externalStats.externalCalls.slice(0, 50)"
          :key="call.name"
          class="arch-tag"
          :class="{ 'selected': selectionStore.isSelected(call.name), 'selecting': selectionStore.selecting }"
          :title="call.files.slice(0, 10).join('\n') + (call.files.length > 10 ? '\n...' + (call.files.length - 10) + ' more' : '')"
          @click="handleExternalTagClick(call.name, call.count)"
        >
          <span class="tag-name">{{ call.name }}</span>
          <span class="tag-count">{{ call.count }}</span>
        </div>
      </template>
      <div
        v-if="props.edgeType === 'EXTERNAL_INCLUDE' && (!props.externalStats.externalDeps || props.externalStats.externalDeps.length === 0)"
        class="arch-empty"
      >
        {{ t('report.noCommunities', '无外部依赖数据') }}
      </div>
      <div
        v-if="props.edgeType === 'EXTERNAL_CALL' && (!props.externalStats.externalCalls || props.externalStats.externalCalls.length === 0)"
        class="arch-empty"
      >
        {{ t('report.noCommunities', '无外部调用数据') }}
      </div>
    </div>

    <div
      v-if="isExternalTab && !props.externalStats"
      class="arch-empty"
    >
      {{ t('report.noCommunities', '该视角下无数据') }}
    </div>

    <div
      v-if="!isExternalTab && totalPages > 1"
      class="ctv-pagination"
    >
      <button
        class="btn btn-ghost btn-xs"
        :disabled="page <= 1"
        @click="page--"
      >
        {{ t('common.prev', '上一页') }}
      </button>
      <span class="ctv-page-info">{{ page }} / {{ totalPages }} ({{ filteredCommunities.length }})</span>
      <button
        class="btn btn-ghost btn-xs"
        :disabled="page >= totalPages"
        @click="page++"
      >
        {{ t('common.next', '下一页') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.ctv-container { display: flex; flex-direction: column; }
.ctv-level-filter { display: flex; align-items: center; gap: 0.35rem; margin-bottom: 0.5rem; font-size: 0.75rem; flex-wrap: wrap; }
.level-filter-label { color: var(--text-muted); flex-shrink: 0; }
.level-filter-btn {
  padding: 0.1rem 0.45rem; font-size: 0.7rem;
  color: var(--text-muted); background: var(--bg-secondary);
  border: 1px solid var(--border); border-radius: 0.25rem;
  cursor: pointer; transition: all 0.15s;
}
.level-filter-btn:hover { border-color: var(--accent, #7c3aed); color: var(--text-primary); }
.level-filter-btn.active {
  color: var(--accent, #7c3aed); border-color: var(--accent, #7c3aed);
  background: var(--bg-accent-subtle, #2d1f5e);
}

.arch-tags { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-bottom: 0.5rem; }
.arch-tag {
  display: flex; align-items: center; gap: 0.3rem;
  padding: 0.2rem 0.5rem; border-radius: 0.375rem;
  background: var(--bg-secondary); border: 1px solid var(--border);
  font-size: 0.75rem; cursor: pointer; transition: all 0.15s;
}
.arch-tag:hover { border-color: var(--accent, #7c3aed); }
.arch-tag.has-name { background: var(--bg-accent-subtle, #2d1f5e); border-color: var(--accent, #7c3aed); }
.arch-tag.selecting { cursor: copy; }
.arch-tag.selected { border-color: #22c55e; background: color-mix(in srgb, #22c55e 10%, var(--bg-secondary)); outline: 1px solid #22c55e; }
.tag-name { font-weight: 500; color: var(--text-primary); max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tag-count { font-size: 0.65rem; color: var(--text-muted); background: var(--bg-tertiary); border-radius: 0.25rem; padding: 0.05rem 0.3rem; }
.arch-empty { font-size: 0.75rem; color: var(--text-muted); padding: 0.5rem; font-style: italic; }

.ctv-pagination { display: flex; align-items: center; justify-content: center; gap: 0.5rem; margin-top: 0.5rem; }
.ctv-page-info { font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono); }
</style>
