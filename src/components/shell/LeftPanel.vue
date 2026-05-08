<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowPathIcon,
  ChevronRightIcon,
} from '@heroicons/vue/24/outline'
import { usePanelStore } from '@/stores/panel'
import { useNavigationStore } from '@/stores/navigation'

const { t } = useI18n()
const panelStore = usePanelStore()
const navigation = useNavigationStore()

const panelTitleKeys: Record<string, string> = {
  home: 'nav.projects',
  analysis: 'nav.tasks',
  knowledge: 'nav.knowledge',
  coder: 'nav.chat',
  user: 'nav.settings',
}

const title = computed(() => t(panelTitleKeys[navigation.currentPage] || 'common.panel'))

const panelContent = ref('')

// 根据当前页面加载对应的左侧面板内容
function loadPanelContent() {
  switch (navigation.currentPage) {
    case 'home':
      panelContent.value = 'home'
      break
    case 'analysis':
      panelContent.value = 'analysis'
      break
    case 'knowledge':
      panelContent.value = 'knowledge'
      break
    case 'coder':
      panelContent.value = 'coder'
      break
    default:
      panelContent.value = ''
  }
}

loadPanelContent()
</script>

<template>
  <aside
    class="panel-left"
    :class="{ collapsed: panelStore.leftCollapsed }"
    :style="{ width: panelStore.leftCollapsed ? 0 : `${panelStore.leftWidth}px` }"
  >
    <div class="panel-header">
      <span>{{ title }}</span>
      <div class="panel-header-actions">
        <div class="icon-btn" :title="t('common.refresh')">
          <ArrowPathIcon class="w-3.5 h-3.5" />
        </div>
        <div class="icon-btn" @click="panelStore.toggleLeft()" :title="t('common.collapse')">
          <ChevronRightIcon class="w-3.5 h-3.5" />
        </div>
      </div>
    </div>
    <div class="panel-body">
      <!-- 动态内容插槽 -->
      <slot :page="panelContent">
        <!-- 默认空状态 -->
        <div class="empty-state">
          <div class="icon">📋</div>
          <div class="title">{{ title }}</div>
          <div class="desc">{{ t('shell.leftPanel.dynamicContent') }}</div>
        </div>
      </slot>
    </div>
  </aside>
</template>

<style scoped>
.panel-left {
  flex-shrink: 0;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.2s ease;
}

.panel-left.collapsed {
  width: 0 !important;
  border-right: none;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border);
  min-height: 32px;
}

.panel-header-actions {
  display: flex;
  gap: 4px;
}

.panel-header-actions .icon-btn {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  cursor: pointer;
  color: var(--text-muted);
  font-size: 12px;
}

.panel-header-actions .icon-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.panel-body {
  flex: 1;
  overflow: auto;
  padding: 4px 0;
}
</style>
