<script setup lang="ts">
/**
 * ArchitectureExplorer — 社区架构树 + drill-down。
 *
 * 从 community-store 加载社区数据，展示层次化的社区结构。
 * 支持展开/收起、点击节点查看详情。
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronRightIcon, ChevronDownIcon, CubeIcon, CircleStackIcon } from '@heroicons/vue/24/outline'
import { useCommunityStore, type CommunityItem } from '@/stores/community-store'

const props = defineProps<{
  taskId: string
  projectId?: string
}>()

const { t } = useI18n()
const communityStore = useCommunityStore()
const expanded = ref<Set<string>>(new Set())
const loading = ref(false)

const callCommunities = computed(() =>
  communityStore.tasks[props.taskId]?.communities.filter(c => c.edgeType === 'CALL' && c.level === 'L0') || []
)
const depCommunities = computed(() =>
  communityStore.tasks[props.taskId]?.communities.filter(c => c.edgeType === 'INCLUDE' && c.level === 'L0') || []
)

const childrenOf = (parentId: string): CommunityItem[] => {
  const all = communityStore.tasks[props.taskId]?.communities || []
  return all.filter(c => c.parentId === parentId)
}

function toggleExpand(id: string) {
  if (expanded.value.has(id)) {
    expanded.value.delete(id)
  } else {
    expanded.value.add(id)
  }
}

function getHubLabel(item: CommunityItem): string {
  if (item.nodeCount > 20) return 'hub'
  if (item.nodeCount < 4) return 'small'
  return ''
}

onMounted(async () => {
  if (props.taskId && props.projectId) {
    loading.value = true
    try {
      await communityStore.loadCommunities(props.taskId, props.projectId)
    } finally {
      loading.value = false
    }
  }
})

watch(() => props.taskId, async (newId) => {
  if (newId && props.projectId) {
    loading.value = true
    try {
      await communityStore.loadCommunities(newId, props.projectId || '')
    } finally {
      loading.value = false
    }
  }
})
</script>

<template>
  <div class="arch-explorer">
    <div class="explorer-header">
      <CubeIcon class="hdr-icon" />
      <span>{{ t('arch.explorer', '架构') }}</span>
      <span
        v-if="loading"
        class="loading"
      >...</span>
    </div>
    <div class="explorer-body">
      <div
        v-if="!props.taskId"
        class="empty"
      >
        <p>{{ t('arch.noTask', '请先运行项目分析') }}</p>
      </div>
      <template v-else>
        <!-- INCLUDE communities -->
        <div
          v-if="depCommunities.length"
          class="section"
        >
          <div class="section-title">
            <CircleStackIcon class="sec-icon" />
            {{ t('arch.depCommunities', '依赖社区') }} ({{ depCommunities.length }})
          </div>
          <div
            v-for="item in depCommunities"
            :key="item.id"
            class="comm-item"
          >
            <div
              class="comm-row"
              @click="toggleExpand(item.id)"
            >
              <ChevronRightIcon
                v-if="!expanded.has(item.id)"
                class="expand-icon"
              />
              <ChevronDownIcon
                v-else
                class="expand-icon"
              />
              <span class="comm-name">{{ item.name || item.communityId }}</span>
              <span class="comm-meta">{{ item.nodeCount }} nodes</span>
              <span
                v-if="getHubLabel(item)"
                class="hub-badge"
              >{{ getHubLabel(item) }}</span>
            </div>
            <div
              v-if="expanded.has(item.id)"
              class="comm-children"
            >
              <div
                v-for="child in childrenOf(item.communityId)"
                :key="child.id"
                class="child-item"
              >
                {{ child.name || child.communityId }}
                <span class="child-meta">{{ child.nodeCount }}n</span>
              </div>
            </div>
          </div>
        </div>
        <!-- CALL communities -->
        <div
          v-if="callCommunities.length"
          class="section"
        >
          <div class="section-title">
            <CubeIcon class="sec-icon" />
            {{ t('arch.callCommunities', '调用社区') }} ({{ callCommunities.length }})
          </div>
          <div
            v-for="item in callCommunities"
            :key="item.id"
            class="comm-item"
          >
            <div
              class="comm-row"
              @click="toggleExpand(item.id)"
            >
              <ChevronRightIcon
                v-if="!expanded.has(item.id)"
                class="expand-icon"
              />
              <ChevronDownIcon
                v-else
                class="expand-icon"
              />
              <span class="comm-name">{{ item.name || item.communityId }}</span>
              <span class="comm-meta">{{ item.nodeCount }} nodes</span>
              <span
                v-if="getHubLabel(item)"
                class="hub-badge"
              >{{ getHubLabel(item) }}</span>
            </div>
            <div
              v-if="expanded.has(item.id)"
              class="comm-children"
            >
              <div
                v-for="child in childrenOf(item.communityId)"
                :key="child.id"
                class="child-item"
              >
                {{ child.name || child.communityId }}
                <span class="child-meta">{{ child.nodeCount }}n</span>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.arch-explorer { height: 100%; display: flex; flex-direction: column; background: var(--bg-primary, #1a1a2e); }
.explorer-header { display: flex; align-items: center; gap: 0.5rem; padding: 0.75rem 1rem; border-bottom: 1px solid var(--border, #374151); font-size: 0.85rem; font-weight: 600; color: var(--text-primary, #e5e7eb); }
.hdr-icon { width: 1rem; height: 1rem; }
.loading { color: var(--accent); animation: pulse 0.8s infinite; }
.explorer-body { flex: 1; overflow-y: auto; padding: 0.25rem 0; }
.empty { padding: 2rem 1rem; text-align: center; color: var(--text-secondary, #9ca3af); font-size: 0.85rem; }
.section { margin-bottom: 0.5rem; }
.section-title { display: flex; align-items: center; gap: 0.35rem; padding: 0.4rem 1rem; font-size: 0.75rem; font-weight: 600; color: var(--text-muted, #6b7280); text-transform: uppercase; letter-spacing: 0.05em; }
.sec-icon { width: 0.75rem; height: 0.75rem; }
.comm-item { cursor: pointer; }
.comm-row { display: flex; align-items: center; gap: 0.35rem; padding: 0.35rem 1rem; font-size: 0.8rem; color: var(--text-primary, #e5e7eb); }
.comm-row:hover { background: var(--bg-secondary, #2d2d44); }
.expand-icon { width: 0.75rem; height: 0.75rem; flex-shrink: 0; color: var(--text-muted, #6b7280); }
.comm-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.comm-meta { font-size: 0.7rem; color: var(--text-muted, #6b7280); flex-shrink: 0; }
.hub-badge { font-size: 0.6rem; background: var(--accent, #7c3aed); color: #fff; border-radius: 0.25rem; padding: 0.1rem 0.3rem; }
.comm-children { padding-left: 1.2rem; }
.child-item { padding: 0.2rem 1rem; font-size: 0.75rem; color: var(--text-secondary, #9ca3af); display: flex; justify-content: space-between; }
.child-meta { font-size: 0.65rem; color: var(--text-muted, #6b7280); }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
</style>
