<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Bars3Icon,
  ArrowRightOnRectangleIcon,
  MoonIcon,
  SunIcon,
  PlusIcon,
  Squares2X2Icon,
  QuestionMarkCircleIcon,
} from '@heroicons/vue/24/outline'
import { usePanelStore } from '@/stores/panel'
import { useThemeStore } from '@/stores/theme'
import { useWindowStore } from '@/stores/window'
import { useProjectStore } from '@/stores/project'
import { useOnboardingStore } from '@/stores/onboarding'
import { useStatusStore } from '@/stores/status'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('SH-005')
const { t } = useI18n()
const panelStore = usePanelStore()
const themeStore = useThemeStore()
const windowStore = useWindowStore()
const projectStore = useProjectStore()
const onboardingStore = useOnboardingStore()
const statusStore = useStatusStore()

async function handleFileImport() {
  closeMenu()
  if (window.api && window.api.dialog) {
    const paths = await window.api.dialog.openDirectory()
    if (paths) {
      await projectStore.importProject(paths)
    }
  }
}

onMounted(() => {
  windowStore.init()
})

const showMenu = ref<string | null>(null)

const menus = {
  file: [
    { label: t('shell.topBar.importProject'), shortcut: 'Ctrl+O', action: 'import' },
    { label: t('shell.topBar.closeProject'), shortcut: '' },
    { divider: true },
    { label: t('shell.topBar.exit'), shortcut: 'Ctrl+Q' },
  ],
  edit: [
    { label: t('shell.topBar.undo'), shortcut: 'Ctrl+Z' },
    { label: t('shell.topBar.redo'), shortcut: 'Ctrl+Shift+Z' },
    { divider: true },
    { label: t('shell.topBar.find'), shortcut: 'Ctrl+F' },
    { label: t('shell.topBar.replace'), shortcut: 'Ctrl+H' },
  ],
  view: [
    { label: t('shell.topBar.toggleLeftPanel'), shortcut: 'Ctrl+B' },
    { label: t('shell.topBar.toggleRightPanel'), shortcut: 'Ctrl+J' },
    { divider: true },
    { label: t('shell.topBar.zoomIn'), shortcut: 'Ctrl++', action: 'zoomIn' },
    { label: t('shell.topBar.zoomOut'), shortcut: 'Ctrl+-', action: 'zoomOut' },
    { label: t('shell.topBar.resetZoom'), shortcut: 'Ctrl+0', action: 'resetZoom' },
  ],
  tools: [
    { label: t('shell.topBar.restartBackend'), shortcut: '' },
    { label: t('shell.topBar.clearCache'), shortcut: '' },
  ],
  help: [
    { label: t('shell.topBar.guide'), shortcut: '', action: 'guide' },
    { divider: true },
    { label: t('shell.topBar.documentation'), shortcut: '' },
    { label: t('shell.topBar.about'), shortcut: '' },
  ],
}

function toggleMenu(menu: string) {
  showMenu.value = showMenu.value === menu ? null : menu
}

function closeMenu() {
  showMenu.value = null
}

async function handleMenuItemClick(item: any) {
  closeMenu()
  if (item.action === 'import') {
    await handleFileImport()
  } else if (item.action === 'guide') {
    onboardingStore.start()
  } else if (item.action === 'zoomIn') {
    const pct = await window.api?.window.zoomIn()
    if (pct) statusStore.setZoom(pct)
  } else if (item.action === 'zoomOut') {
    const pct = await window.api?.window.zoomOut()
    if (pct) statusStore.setZoom(pct)
  } else if (item.action === 'resetZoom') {
    const pct = await window.api?.window.resetZoom()
    if (pct) statusStore.setZoom(pct)
  }
}
</script>

<template>
  <div class="app-top">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div class="app-row1">
      <!-- 产品 Logo -->
      <div class="menu-bar-logo">
        <span class="logo-icon">◆</span>
        <span class="logo-text">TopoCode</span>
      </div>

      <!-- 通用菜单 -->
      <div class="menu-bar">
        <div
          v-for="(menuItems, key) in menus"
          :key="key"
          class="menu-item"
          :class="{ active: showMenu === key }"
          @click="toggleMenu(key)"
        >
          <span>{{ key === 'file' ? t('shell.topBar.file') : key === 'edit' ? t('shell.topBar.edit') : key === 'view' ? t('shell.topBar.view') : key === 'tools' ? t('shell.topBar.tools') : t('shell.topBar.help') }}</span>

          <!-- 下拉菜单 -->
          <div
            v-if="showMenu === key"
            class="menu-dropdown show"
            @click.stop
          >
            <template
              v-for="(menuItem, idx) in menuItems"
              :key="idx"
            >
              <div
                v-if="!menuItem.divider"
                class="menu-dropdown-item"
                @click="handleMenuItemClick(menuItem)"
              >
                <span>{{ menuItem.label }}</span>
                <span
                  v-if="menuItem.shortcut"
                  class="shortcut"
                >{{ menuItem.shortcut }}</span>
              </div>
              <div
                v-else
                class="menu-dropdown-divider"
              />
            </template>
          </div>
        </div>
      </div>

      <!-- 占位 -->
      <div style="flex:1;" />

      <!-- 右侧工具 -->
      <div class="tab-bar-actions">
        <!-- 窗口管理 -->
        <div class="window-manager">
          <button
            class="icon-btn"
            :class="{ disabled: !windowStore.canCreateMore }"
            :title="t('window.newWindow')"
            @click="windowStore.createNewWindow()"
          >
            <PlusIcon class="w-4 h-4" />
          </button>
          <button
            class="icon-btn"
            :title="t('window.windowCount')"
            @click="windowStore.refresh()"
          >
            <Squares2X2Icon class="w-4 h-4" />
            <span class="window-count-badge">{{ windowStore.windowCount }}</span>
          </button>
        </div>
        <div
          class="icon-btn"
          :title="t('shell.topBar.toggleLeftPanel')"
          @click="panelStore.toggleLeft()"
        >
          <Bars3Icon class="w-4 h-4" />
        </div>
        <div
          class="icon-btn"
          :title="t('shell.topBar.toggleRightPanel')"
          @click="panelStore.toggleRight()"
        >
          <ArrowRightOnRectangleIcon class="w-4 h-4" />
        </div>
        <div
          class="icon-btn"
          :title="`${t('shell.topBar.toggleTheme')} (${themeStore.theme === 'dark' ? t('settings.darkMode') : t('settings.lightMode')})`"
          @click="themeStore.toggleTheme()"
        >
          <MoonIcon
            v-if="themeStore.theme === 'dark'"
            class="w-4 h-4"
          />
          <SunIcon
            v-else
            class="w-4 h-4"
          />
        </div>
        <div
          class="icon-btn"
          :title="t('shell.topBar.guide')"
          @click="onboardingStore.start()"
        >
          <QuestionMarkCircleIcon class="w-4 h-4" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.app-top {
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.app-row1 {
  display: flex;
  height: var(--tab-bar-height);
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  align-items: center;
  padding: 0 8px;
  gap: 8px;
}

.menu-bar-logo {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  padding: 0 8px;
}

.logo-icon {
  font-size: 16px;
  color: var(--accent);
  font-weight: bold;
}

.logo-text {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.5px;
}

.menu-bar {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.menu-item {
  position: relative;
  padding: 4px 10px;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: all 0.15s;
  user-select: none;
}

.menu-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.menu-item.active {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.menu-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  min-width: 180px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  padding: 4px;
  z-index: 1000;
}

.menu-dropdown-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: all 0.1s;
}

.menu-dropdown-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.menu-dropdown-item .shortcut {
  font-size: 10px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.menu-dropdown-divider {
  height: 1px;
  background: var(--border);
  margin: 4px 0;
}

.tab-bar-actions {
  display: flex;
  align-items: center;
  padding: 0 8px;
  gap: 4px;
}

.tab-bar-actions .icon-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--text-muted);
  transition: all 0.15s;
}

.tab-bar-actions .icon-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.window-manager {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-right: 4px;
  padding-right: 8px;
  border-right: 1px solid var(--border);
}

.window-count-badge {
  position: absolute;
  top: 2px;
  right: 2px;
  min-width: 14px;
  height: 14px;
  font-size: 9px;
  font-weight: 600;
  color: var(--accent);
  background: var(--bg-tertiary);
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 4px;
}

.icon-btn.disabled {
  opacity: 0.4;
  pointer-events: none;
}

.icon-btn.active {
  color: var(--accent);
  background: var(--bg-tertiary);
}
</style>
