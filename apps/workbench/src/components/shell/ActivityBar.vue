<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  HomeIcon,
  FolderIcon,
  LightBulbIcon,
  BookOpenIcon,
} from '@heroicons/vue/24/outline'
import { useNavigationStore } from '@/stores/navigation'
import { usePanelStore } from '@/stores/panel'
import type { PageType } from '@/types'
import { useComponentId } from '@topo/web-core/composables/useComponentId'

const { showId, componentId } = useComponentId('SH-002')
const { t } = useI18n()
const router = useRouter()
const navigation = useNavigationStore()
const panelStore = usePanelStore()

const iconMap = {
  home: HomeIcon,
  code: FolderIcon,
  analysis: LightBulbIcon,
  knowledge: BookOpenIcon,
}

const activities = [
  { page: 'home' as PageType, key: 'nav.home' },
  { page: 'code' as PageType, key: 'nav.code' },
  { page: 'analysis' as PageType, key: 'nav.analysis' },
  // { page: 'knowledge' as PageType, key: 'nav.knowledge' },
]

const currentPage = computed(() => navigation.currentPage)

function navigateTo(page: PageType) {
  navigation.navigateTo(page)
  if (page === 'analysis' && panelStore.leftCollapsed) {
    panelStore.setLeftCollapsed(false)
  }
  router.push(`/${page}`)
}
</script>

<template>
  <nav class="activity-bar">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div
      v-for="activity in activities"
      :key="activity.page"
      class="activity-item"
      :class="{ active: currentPage === activity.page }"
      :title="t(activity.key)"
      @click="navigateTo(activity.page)"
    >
      <component
        :is="iconMap[activity.page]"
      />
    </div>
  </nav>
</template>

<style scoped>
.activity-bar {
  width: var(--activity-bar-width);
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: calc(4px * var(--ui-scale, 1));
  padding-bottom: calc(4px * var(--ui-scale, 1));
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
}

.activity-item {
  width: calc(36px * var(--ui-scale, 1));
  height: calc(36px * var(--ui-scale, 1));
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  cursor: pointer;
  color: var(--text-muted);
  font-size: calc(18px * var(--ui-scale, 1));
  transition: all 0.15s ease;
  position: relative;
  margin-bottom: calc(2px * var(--ui-scale, 1));
}

.activity-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.activity-item.active {
  color: var(--accent);
  background: var(--bg-tertiary);
}

.activity-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: calc(3px * var(--ui-scale, 1));
  height: calc(20px * var(--ui-scale, 1));
  background: var(--accent);
  border-radius: 0 calc(2px * var(--ui-scale, 1)) calc(2px * var(--ui-scale, 1)) 0;
}

/* 图标固定 24×24，不随字号变化 */
.activity-item svg {
  width: calc(24px * var(--ui-scale, 1));
  height: calc(24px * var(--ui-scale, 1));
  flex-shrink: 0;
}
</style>
