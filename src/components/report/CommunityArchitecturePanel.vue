<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  RectangleGroupIcon,
  FolderIcon,
  ChartBarIcon,
} from '@heroicons/vue/24/outline'
import { useCommunityStore, type CommunityItem } from '@/stores/community-store'
import { useFuncGroupStore } from '@/stores/funcGroup'
import CommunityTagView from './CommunityTagView.vue'
import { useComponentId } from '@/composables/useComponentId'

const { t } = useI18n()
const communityStore = useCommunityStore()
const funcGroup = useFuncGroupStore()

const props = defineProps<{
  taskId: string
  tabId: string
  projectId: string
  taskUpdatedAt: string
  hasAnyCommunity: boolean
  totalScopeFiles: number
  coveragePercent: number
  coveredFileCount: number
  depCommunityCount: number
  callCommunityCount: number
  externalStats: any
}>()

const emit = defineEmits<{
  'open-md': [params: { taskId: string; content: string; title: string; parentLevel?: string; parentCommId?: string; parentEdgeType?: string }]
}>()

const { showId, componentId } = useComponentId('CV-001')
const commEdgeType = ref<'INCLUDE' | 'CALL' | 'EXTERNAL_INCLUDE' | 'EXTERNAL_CALL'>('INCLUDE')
const communitySearch = ref('')

// 恢复 tab UI 状态
onMounted(() => {
  const saved = funcGroup.getTabExtraState('analysis', props.tabId)
  if (saved) {
    if (saved.edgeType) commEdgeType.value = saved.edgeType
  }
})

watch(commEdgeType, (v) => {
  funcGroup.saveTabExtraState('analysis', props.tabId, { edgeType: v })
  if (v === 'EXTERNAL_INCLUDE' || v === 'EXTERNAL_CALL') {
    communityStore.loadExternalStats(props.taskId, true)
  }
})

const isExternalTab = computed(() =>
  commEdgeType.value === 'EXTERNAL_INCLUDE' || commEdgeType.value === 'EXTERNAL_CALL'
)

const hasAnyCommunity = computed(() => props.hasAnyCommunity)

const runtimeCommunities = computed(() => {
  if (isExternalTab.value) return []
  const coms = communityStore.tasks[props.taskId]?.communities || []
  return coms.filter(c => c.level === 'L0' && c.edgeType === commEdgeType.value)
})

const availableLevels = computed(() => {
  if (isExternalTab.value) return []
  const coms = communityStore.tasks[props.taskId]?.communities || []
  const typeComs = coms.filter(c => c.edgeType === commEdgeType.value)
  const levels = new Set(typeComs.map(c => c.level))
  return Array.from(levels).sort()
})

function commName(item: CommunityItem): string {
  const name = item.name && item.name !== item.communityId ? item.name : ''
  if (name) return name.length > 12 ? name.slice(0, 12) + '\u2026' : name
  return communityIdLabel(item)
}

function communityIdLabel(item: { communityId: string; level?: string }): string {
  const parts = item.communityId.split('-')
  const num = parts[parts.length - 1]
  const level = item.level || 'L0'
  return `${level}-${num}`
}

function openCommunityDoc(item: CommunityItem) {
  if (item.summary) {
    emit('open-md', {
      taskId: props.taskId,
      content: `## ${commName(item)}\n\n${item.summary || ''}`,
      title: commName(item),
      parentCommId: item.communityId,
      parentLevel: item.level || 'L0',
      parentEdgeType: item.edgeType,
    })
  }
}

</script>

<template>
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
  <section
    v-if="hasAnyCommunity || isExternalTab"
    class="ca-section"
  >
    <div class="section-header">
      <RectangleGroupIcon class="w-4 h-4" />
      <span>{{ t('report.communityArchitecture', '组件架构') }}</span>
      <span class="arch-stats">
        <template v-if="!isExternalTab">
          <span class="arch-stats-count">{{ runtimeCommunities.length }}</span>
          {{ t('report.l0Communities', '个L0社区') }}
          <span class="arch-stats-divider">|</span>
          <span class="arch-stats-coverage">{{ t('report.coverage', '覆盖率') }} <strong>{{ props.coveragePercent }}%</strong> {{ props.coveredFileCount }}/{{ props.totalScopeFiles }}</span>
        </template>
        <template v-else-if="commEdgeType === 'EXTERNAL_INCLUDE' && props.externalStats">
          <span class="arch-stats-count">{{ props.externalStats.totalExternalDeps || 0 }}</span>{{ t('report.externalPackages') }}
          <span class="arch-stats-divider">|</span>
          <span class="arch-stats-coverage">{{ props.externalStats.uniqueExternalDepFiles }}{{ t('report.fileCount') }}</span>
          <span class="arch-stats-divider">|</span>
          <span class="arch-stats-coverage">{{ t('report.totalFiles') }} {{ props.totalScopeFiles }}</span>
          <span class="arch-stats-divider">|</span>
          <span class="arch-stats-coverage">{{ props.externalStats.totalExternalDeps }}{{ t('report.externalImports') }}</span>
        </template>
        <template v-else-if="commEdgeType === 'EXTERNAL_CALL' && props.externalStats">
          <span class="arch-stats-count">{{ props.externalStats.totalExternalCalls || 0 }}</span>{{ t('report.externalApis') }}
          <span class="arch-stats-divider">|</span>
          <span class="arch-stats-coverage">{{ props.externalStats.uniqueExternalCallFiles }}{{ t('report.fileCount') }}</span>
          <span class="arch-stats-divider">|</span>
          <span class="arch-stats-coverage">{{ t('report.totalFiles') }} {{ props.totalScopeFiles }}</span>
          <span class="arch-stats-divider">|</span>
          <span class="arch-stats-coverage">{{ props.externalStats.totalExternalCalls }}{{ t('report.externalCalls') }}</span>
        </template>
      </span>
      <div class="header-spacer" />
      <div class="arch-actions">
        <div class="arch-search">
          <input
            v-model="communitySearch"
            type="text"
            :placeholder="t('report.searchCommunity', '搜索组件...')"
            class="arch-search-input"
          >
        </div>
      </div>
    </div>

    <div class="arch-tabs">
      <button
        class="arch-tab"
        :class="{ active: commEdgeType === 'INCLUDE' }"
        @click="commEdgeType = 'INCLUDE'"
      >
        <FolderIcon class="w-3.5 h-3.5" />
        {{ t('report.internalDependency', '内部依赖分析') }} ({{ props.depCommunityCount }})
      </button>
      <button
        class="arch-tab"
        :class="{ active: commEdgeType === 'CALL' }"
        @click="commEdgeType = 'CALL'"
      >
        <ChartBarIcon class="w-3.5 h-3.5" />
        {{ t('report.internalCall', '内部调用分析') }} ({{ props.callCommunityCount }})
      </button>
      <button
        class="arch-tab"
        :class="{ active: commEdgeType === 'EXTERNAL_INCLUDE' }"
        @click="commEdgeType = 'EXTERNAL_INCLUDE'"
      >
        <FolderIcon class="w-3.5 h-3.5" />
        {{ t('report.externalDependency', '外部依赖视图') }}
      </button>
      <button
        class="arch-tab"
        :class="{ active: commEdgeType === 'EXTERNAL_CALL' }"
        @click="commEdgeType = 'EXTERNAL_CALL'"
      >
        <ChartBarIcon class="w-3.5 h-3.5" />
        {{ t('report.externalCall', '外部调用视图') }}
      </button>
    </div>

    <CommunityTagView
      :task-id="props.taskId"
      :tab-id="props.tabId"
      :edge-type="commEdgeType"
      :external-stats="props.externalStats"
      :available-levels="availableLevels"
      :search="communitySearch"
      @open-community="openCommunityDoc"
    />
  </section>
</template>

<style scoped>
.ca-section { margin-bottom: 0; display: flex; flex-direction: column; flex: 1; min-height: 0; position: relative; }
.section-header {
  display: flex; align-items: center; gap: 6px;
  font-size: 13px; font-weight: 600; color: var(--text-primary);
  margin-bottom: 10px; padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.arch-stats { font-size: 0.75rem; color: var(--text-muted); font-weight: 400; white-space: nowrap; display: flex; align-items: center; gap: 6px; }
.arch-stats-divider { color: var(--border); }
.arch-stats-coverage { color: var(--text-muted); }
.arch-stats-coverage strong { color: var(--text-primary); }
.arch-stats-count { color: var(--accent, #7c3aed); font-weight: 600; }
.header-spacer { flex: 1; }

.arch-actions { display: flex; align-items: center; gap: 0.5rem; }
.arch-search { display: flex; }
.arch-search-input {
  width: 160px; padding: 0.2rem 0.5rem; font-size: 0.75rem;
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: 0.375rem; color: var(--text-primary);
}
.arch-search-input:focus { outline: none; border-color: var(--accent); }

.arch-tabs { display: flex; gap: 0; margin-bottom: 0.75rem; border-bottom: 2px solid var(--border); }
.arch-tab {
  display: flex; align-items: center; gap: 0.35rem;
  padding: 0.4rem 0.9rem; font-size: 0.8rem; color: var(--text-muted);
  border: none; background: none; cursor: pointer;
  border-bottom: 2px solid transparent; margin-bottom: -2px; transition: all 0.15s;
}
.arch-tab:hover { color: var(--text-primary); }
.arch-tab.active { color: var(--accent, #7c3aed); border-bottom-color: var(--accent, #7c3aed); }
</style>
