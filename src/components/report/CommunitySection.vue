<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { HashtagIcon } from '@heroicons/vue/24/outline'
import { formatCommunityId } from '@/utils/community'

const { t } = useI18n()

export interface CommunityItem {
  id: string
  communityId: string
  level?: string
  edgeType: string
  name?: string
  summary?: string
  mermaid?: string
  plantuml?: string
  nodeCount?: number
  edgeCount?: number
  qualityScore?: number | null
  status?: string
}

const props = defineProps<{
  communities: CommunityItem[]
  edgeType: 'INCLUDE' | 'CALL'
}>()

const emit = defineEmits<{
  'update:edgeType': [type: 'INCLUDE' | 'CALL']
  'select-community': [item: CommunityItem]
}>()

const communitySearch = ref('')
const communityPage = ref(1)
const communityPageSize = 100

const communityItems = computed(() => {
  const q = communitySearch.value.trim().toLowerCase()
  if (!q) return props.communities
  return props.communities.filter(c => {
    const id = c.communityId.toLowerCase()
    const name = (c.name || '').toLowerCase()
    return id.includes(q) || name.includes(q)
  })
})

const commStats = computed(() => {
  const items = communityItems.value
  const nodes = items.map(c => c.nodeCount || 0)
  const quals = items.map(c => c.qualityScore).filter((q): q is number => q != null)
  return {
    count: items.length,
    maxNodes: nodes.length ? Math.max(...nodes) : 0,
    minNodes: nodes.length ? Math.min(...nodes) : 0,
    avgQuality: quals.length ? (quals.reduce((a, b) => a + b, 0) / quals.length) : 0,
  }
})

const communityTotalPages = computed(() => Math.max(1, Math.ceil(communityItems.value.length / communityPageSize)))
const pagedCommunityItems = computed(() => {
  const start = (communityPage.value - 1) * communityPageSize
  return communityItems.value.slice(start, start + communityPageSize)
})

watch(communitySearch, () => { communityPage.value = 1 })

function commName(item: CommunityItem): string {
  const name = item.name && item.name !== item.communityId ? item.name : ''
  if (name) return name.length > 10 ? name.slice(0, 10) + '\u2026' : name
  return communityIdLabel(item)
}

function communityIdLabel(item: { communityId: string; level?: string }): string {
  const parts = item.communityId.split('-')
  const num = parts[parts.length - 1]
  const level = item.level || parts[parts.length - 2] || 'L0'
  return `${level}-${num}`
}
</script>

<template>
  <section class="home-section">
    <div class="section-header">
      <svg
        class="w-4 h-4"
        viewBox="0 0 20 20"
        fill="currentColor"
      >
        <path d="M2 3a1 1 0 011-1h5a1 1 0 011 1v3a1 1 0 01-1 1H3a1 1 0 01-1-1V3zm0 8a1 1 0 011-1h5a1 1 0 011 1v3a1 1 0 01-1 1H3a1 1 0 01-1-1v-3zm8-8a1 1 0 011-1h5a1 1 0 011 1v3a1 1 0 01-1 1h-5a1 1 0 01-1-1V3zm0 8a1 1 0 011-1h5a1 1 0 011 1v3a1 1 0 01-1 1h-5a1 1 0 01-1-1v-3z" />
      </svg>
      <span>{{ t('report.communitySummary') }}</span>
    </div>

    <div class="comm-et-tabs">
      <button
        :class="['comm-et-tab', { active: edgeType === 'INCLUDE' }]"
        @click="emit('update:edgeType', 'INCLUDE')"
      >
        {{ t('report.pipeline.edgeInclude') }}
      </button>
      <button
        :class="['comm-et-tab', { active: edgeType === 'CALL' }]"
        @click="emit('update:edgeType', 'CALL')"
      >
        {{ t('report.pipeline.edgeCall') }}
      </button>
    </div>

    <div class="comm-stats">
      <span class="comm-stat">
        <HashtagIcon class="w-3 h-3" /> {{ commStats.count }}
      </span>
      <span class="comm-stat">{{ t('report.communityMaxNodes') }}: {{ commStats.maxNodes }}</span>
      <span class="comm-stat">{{ t('report.communityMinNodes') }}: {{ commStats.minNodes }}</span>
      <span
        class="comm-stat quality-stat"
        :title="'质量分反映社区内聚度，分值越高组件间区分度越好。平均约 ' + (commStats.avgQuality ? commStats.avgQuality.toFixed(3) : '-')"
      >
        {{ t('report.communityAvgQuality') }}: {{ commStats.avgQuality ? commStats.avgQuality.toFixed(3) : '-' }}
        <span class="quality-hint">ⓘ</span>
      </span>
    </div>

    <div class="comm-search">
      <input
        v-model="communitySearch"
        type="text"
        placeholder="搜索组件名称/ID..."
        class="comm-search-input"
      >
    </div>

    <div class="community-items">
      <template v-if="pagedCommunityItems.length > 0">
        <div
          v-for="item in pagedCommunityItems"
          :key="item.id"
          class="community-chip"
          :class="{ 'has-result': item.status === 'completed' && !!(item.name) && item.name !== item.communityId }"
          :title="`${item.communityId} (${item.nodeCount} 节点, 质量: ${item.qualityScore ?? '-'})`"
          @click="emit('select-community', item)"
        >
          <span class="chip-name">{{ commName(item) }}</span>
          <span class="chip-count">{{ item.nodeCount }}</span>
        </div>
      </template>
      <div
        v-else
        class="comm-empty"
      >
        {{ t('report.pipeline.noCommunities') }}
      </div>
    </div>

    <div
      v-if="communityTotalPages > 1"
      class="comm-pagination"
    >
      <button
        class="btn btn-ghost btn-xs"
        :disabled="communityPage <= 1"
        @click="communityPage--"
      >
        上一页
      </button>
      <span class="comm-page-info">{{ communityPage }} / {{ communityTotalPages }}</span>
      <button
        class="btn btn-ghost btn-xs"
        :disabled="communityPage >= communityTotalPages"
        @click="communityPage++"
      >
        下一页
      </button>
    </div>
  </section>
</template>

<style scoped>
.home-section { margin-bottom: 20px; }
.section-header { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }
.comm-et-tabs { display: flex; gap: 0; margin-bottom: 8px; border-bottom: 1px solid var(--border); }
.comm-et-tab { flex: 1; padding: 4px 8px; text-align: center; font-size: 10px; font-weight: 500; color: var(--text-muted); background: transparent; border: none; cursor: pointer; border-bottom: 2px solid transparent; transition: all 0.15s; }
.comm-et-tab:hover { color: var(--text-primary); background: var(--bg-tertiary); }
.comm-et-tab.active { color: var(--accent); border-bottom-color: var(--accent); }
.comm-stats { display: flex; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
.comm-stat { display: flex; align-items: center; gap: 3px; font-size: 10px; color: var(--text-muted); font-family: var(--font-mono); }
.community-items { display: flex; flex-wrap: wrap; gap: 4px; }
.community-chip { display: flex; align-items: center; gap: 4px; padding: 2px 8px; background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 10px; font-size: 10px; cursor: pointer; transition: border-color 0.15s, background 0.15s; }
.community-chip:hover { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, transparent); }
.community-chip.has-result { border-color: var(--accent); }
.community-chip.has-result .chip-name { color: var(--success); }
.chip-name { color: var(--text-primary); max-width: 100px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chip-count { color: var(--text-muted); font-family: var(--font-mono); font-size: 9px; }
.comm-empty { font-size: 10px; color: var(--text-muted); padding: 4px 0; }
.comm-search { margin-bottom: 8px; }
.comm-search-input { width: 100%; padding: 4px 8px; font-size: 11px; border: 1px solid var(--border); border-radius: 4px; background: var(--bg-primary); color: var(--text-primary); outline: none; box-sizing: border-box; }
.comm-search-input:focus { border-color: var(--accent); }
.comm-pagination { display: flex; align-items: center; justify-content: center; gap: 8px; margin-top: 8px; }
.comm-page-info { font-size: 10px; color: var(--text-muted); font-family: var(--font-mono); }
.quality-stat { cursor: help; position: relative; }
.quality-hint { font-size: 9px; color: var(--text-muted); margin-left: 2px; }
</style>
