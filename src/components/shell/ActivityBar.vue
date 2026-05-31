<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  HomeIcon,
  FolderIcon,
  LightBulbIcon,
  BookOpenIcon,
  Cog6ToothIcon,
} from '@heroicons/vue/24/outline'
import { useNavigationStore } from '@/stores/navigation'
import type { PageType } from '@/types'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('SH-002')
const { t } = useI18n()
const router = useRouter()
const navigation = useNavigationStore()

const iconMap = {
  home: HomeIcon,
  code: FolderIcon,
  analysis: LightBulbIcon,
  knowledge: BookOpenIcon,
  user: Cog6ToothIcon,
}

const activities = [
  { page: 'home' as PageType, key: 'nav.home' },
  { page: 'code' as PageType, key: 'nav.code' },
  { page: 'analysis' as PageType, key: 'nav.analysis' },
  // { page: 'knowledge' as PageType, key: 'nav.knowledge' },
]

const bottomActivities = [
  { page: 'user' as PageType, key: 'nav.settings' },
]

const currentPage = computed(() => navigation.currentPage)

function navigateTo(page: PageType) {
  navigation.navigateTo(page)
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
        class="w-5 h-5"
      />
    </div>

    <div class="activity-spacer" />

    <div
      v-for="activity in bottomActivities"
      :key="activity.page"
      class="activity-item"
      :class="{ active: currentPage === activity.page }"
      :title="t(activity.key)"
      @click="navigateTo(activity.page)"
    >
      <component
        :is="iconMap[activity.page]"
        class="w-5 h-5"
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
  padding-top: 4px;
  padding-bottom: 4px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
}

.activity-item {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  cursor: pointer;
  color: var(--text-muted);
  font-size: 18px;
  transition: all 0.15s ease;
  position: relative;
  margin-bottom: 2px;
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
  width: 3px;
  height: 20px;
  background: var(--accent);
  border-radius: 0 2px 2px 0;
}

.activity-spacer {
  flex: 1;
}
</style>
