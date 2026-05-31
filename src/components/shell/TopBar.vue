<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ArrowRightStartOnRectangleIcon,
  ArrowLeftEndOnRectangleIcon,
  ArrowRightEndOnRectangleIcon,
  ArrowLeftStartOnRectangleIcon,
  MoonIcon,
  SunIcon,
  MinusIcon,
  Square2StackIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'
import { usePanelStore } from '@/stores/panel'
import { useThemeStore } from '@/stores/theme'
import { useProjectStore } from '@/stores/project'
import { useOnboardingStore } from '@/stores/onboarding'
import { useStatusStore } from '@/stores/status'
import { useNavigationStore } from '@/stores/navigation'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('SH-005')
const { t } = useI18n()
const router = useRouter()
const panelStore = usePanelStore()
const themeStore = useThemeStore()
const projectStore = useProjectStore()
const onboardingStore = useOnboardingStore()
const statusStore = useStatusStore()
const navigation = useNavigationStore()

// ── 配置 ──
const DOCS_URL = 'https://opencode.ai'

// ── 无边框窗口控制 ──
const isMaximized = ref(false)

onMounted(async () => {
  try {
    isMaximized.value = await window.api?.window.isMaximized() || false
  } catch {}
})

async function onMinimize() {
  await window.api?.window.minimize()
}

async function onMaximize() {
  await window.api?.window.maximize()
  try {
    isMaximized.value = await window.api?.window.isMaximized() || false
  } catch {}
}

async function onClose() {
  await window.api?.window.close()
}

// ── 菜单 ──
const showMenu = ref<string | null>(null)
let menuTimer: ReturnType<typeof setTimeout> | null = null

function clearMenuTimer() {
  if (menuTimer) { clearTimeout(menuTimer); menuTimer = null }
}

function toggleMenu(key: string) {
  clearMenuTimer()
  showMenu.value = showMenu.value === key ? null : key
}

function closeMenu() {
  showMenu.value = null
}

function onMenuMouseEnter(key: string) {
  clearMenuTimer()
}

function onMenuMouseLeave(key: string) {
  clearMenuTimer()
  menuTimer = setTimeout(() => { closeMenu() }, 500)
}

function onDropdownMouseEnter() {
  clearMenuTimer()
}

function onDropdownMouseLeave() {
  clearMenuTimer()
  menuTimer = setTimeout(() => { closeMenu() }, 500)
}

// ── 弹窗 ──
const showAbout = ref(false)
const showExitConfirm = ref(false)

const menus: Record<string, { label: string; shortcut?: string; action?: string }[]> = {
  file: [
    { label: t('shell.topBar.importProject'), shortcut: 'Ctrl+O', action: 'import' },
    { label: t('shell.topBar.goHome'), shortcut: '' },
    { divider: true } as any,
    { label: t('shell.topBar.exit'), shortcut: 'Ctrl+Q', action: 'exit' },
  ],
  view: [
    { label: t('shell.topBar.toggleLeftPanel'), shortcut: 'Ctrl+B', action: 'toggleLeft' },
    { label: t('shell.topBar.toggleRightPanel'), shortcut: 'Ctrl+J', action: 'toggleRight' },
    { divider: true } as any,
    { label: t('shell.topBar.zoomIn'), shortcut: 'Ctrl++', action: 'zoomIn' },
    { label: t('shell.topBar.zoomOut'), shortcut: 'Ctrl+-', action: 'zoomOut' },
    { label: t('shell.topBar.resetZoom'), shortcut: 'Ctrl+0', action: 'resetZoom' },
  ],
  help: [
    { label: t('shell.topBar.documentation'), shortcut: '', action: 'docs' },
    { divider: true } as any,
    { label: t('shell.topBar.about'), shortcut: '', action: 'about' },
  ],
}

async function handleMenuItemClick(item: any) {
  closeMenu()
  if (item.action === 'import') {
    await handleFileImport()
  } else if (item.action === 'goHome') {
    router.push('/home')
    navigation.navigateTo('home')
  } else if (item.action === 'exit') {
    handleExit()
  } else if (item.action === 'toggleLeft') {
    panelStore.toggleLeft()
  } else if (item.action === 'toggleRight') {
    panelStore.toggleRight()
  } else if (item.action === 'zoomIn') {
    const pct = await window.api?.window.zoomIn()
    if (pct) statusStore.setZoom(pct)
  } else if (item.action === 'zoomOut') {
    const pct = await window.api?.window.zoomOut()
    if (pct) statusStore.setZoom(pct)
  } else if (item.action === 'resetZoom') {
    const pct = await window.api?.window.resetZoom()
    if (pct) statusStore.setZoom(pct)
  } else if (item.action === 'docs') {
    window.open(DOCS_URL, '_blank')
  } else if (item.action === 'about') {
    showAbout.value = true
  }
}

async function handleFileImport() {
  closeMenu()
  if (window.api && window.api.dialog) {
    const paths = await window.api.dialog.openDirectory()
    if (paths) {
      await projectStore.importProject(paths)
    }
  }
}

async function handleExit() {
  showExitConfirm.value = true
}

async function confirmExit() {
  showExitConfirm.value = false
  await window.api?.app.quit()
}

onMounted(() => {
  // 窗口 zoom 限制在 preload 中处理
})
</script>

<template>
  <div class="app-top">
    <span v-if="showId" class="cmp-id">{{ componentId }}</span>
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
          @mouseenter="onMenuMouseEnter(key)"
          @mouseleave="onMenuMouseLeave(key)"
        >
          <span>{{ key === 'file' ? t('shell.topBar.file') : key === 'view' ? t('shell.topBar.view') : t('shell.topBar.help') }}</span>

          <!-- 下拉菜单 -->
          <div
            v-if="showMenu === key"
            class="menu-dropdown show"
            @click.stop
            @mouseenter="onDropdownMouseEnter"
            @mouseleave="onDropdownMouseLeave"
          >
            <template v-for="(menuItem, idx) in menuItems" :key="idx">
              <div
                v-if="!menuItem.divider"
                class="menu-dropdown-item"
                @click="handleMenuItemClick(menuItem)"
              >
                <span>{{ menuItem.label }}</span>
                <span v-if="menuItem.shortcut" class="shortcut">{{ menuItem.shortcut }}</span>
              </div>
              <div v-else class="menu-dropdown-divider" />
            </template>
          </div>
        </div>
      </div>

      <!-- 占位 -->
      <div style="flex:1;" />

      <!-- 右侧工具 -->
      <div class="tab-bar-actions">
        <div
          class="icon-btn"
          :class="{ active: !panelStore.leftCollapsed }"
          :title="t('shell.topBar.toggleLeftPanel')"
          @click="panelStore.toggleLeft()"
        >
          <ArrowLeftEndOnRectangleIcon v-if="!panelStore.leftCollapsed" class="w-4 h-4" />
          <ArrowRightStartOnRectangleIcon v-else class="w-4 h-4" />
        </div>
        <div
          class="icon-btn"
          :class="{ active: !panelStore.rightCollapsed }"
          :title="t('shell.topBar.toggleRightPanel')"
          @click="panelStore.toggleRight()"
        >
          <ArrowRightEndOnRectangleIcon v-if="!panelStore.rightCollapsed" class="w-4 h-4" />
          <ArrowLeftStartOnRectangleIcon v-else class="w-4 h-4" />
        </div>
        <div
          class="icon-btn"
          :title="`${t('shell.topBar.toggleTheme')} (${themeStore.theme === 'dark' ? t('settings.darkMode') : t('settings.lightMode')})`"
          @click="themeStore.toggleTheme()"
        >
          <MoonIcon v-if="themeStore.theme === 'dark'" class="w-4 h-4" />
          <SunIcon v-else class="w-4 h-4" />
        </div>
        <!-- 新手引导入口（暂时隐藏）
        <div
          class="icon-btn"
          :title="t('shell.topBar.guide')"
          @click="onboardingStore.start()"
        >
          <QuestionMarkCircleIcon class="w-4 h-4" />
        </div>
        -->
      </div>

      <!-- 窗口控制（无边框窗口） -->
      <div class="window-controls">
        <div class="win-btn" @click="onMinimize" :title="t('common.minimize')">
          <MinusIcon class="w-3.5 h-3.5" />
        </div>
        <div class="win-btn" @click="onMaximize" :title="t(isMaximized ? 'common.restore' : 'common.maximize')">
          <Square2StackIcon class="w-3.5 h-3.5" />
        </div>
        <div class="win-btn win-btn-close" @click="onClose" :title="t('common.close')">
          <XMarkIcon class="w-3.5 h-3.5" />
        </div>
      </div>
    </div>

    <!-- 关于弹窗 -->
    <Teleport to="body">
      <div v-if="showAbout" class="modal-overlay" @click.self="showAbout = false">
        <div class="modal about-modal">
          <div class="modal-header">
            <span class="modal-title">{{ t('shell.topBar.about') }}</span>
            <button class="btn btn-ghost btn-xs" @click="showAbout = false">
              <XMarkIcon class="w-4 h-4" />
            </button>
          </div>
          <div class="modal-body about-body">
            <div class="about-icon">◆</div>
            <div class="about-name">TopoCode</div>
            <div class="about-version">v1.0.0</div>
<div class="about-desc">{{ t('settings.aboutTagline') }}</div>
<div class="about-section">
              <span class="about-label">作者</span>
              <span>TopoCode Team</span>
            </div>
            <div class="about-section">
              <span class="about-label">联系方式</span>
              <a href="mailto:support@opencode.ai">support@opencode.ai</a>
            </div>
            <button class="btn btn-ghost btn-sm" @click="window.open(DOCS_URL, '_blank'); showAbout = false">
              检查版本升级
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 退出确认弹窗 -->
    <Teleport to="body">
      <div v-if="showExitConfirm" class="modal-overlay" @click.self="showExitConfirm = false">
        <div class="modal" style="width:400px;">
          <div class="modal-header">
            <span class="modal-title">{{ t('common.confirm') }}</span>
            <button class="btn btn-ghost btn-xs" @click="showExitConfirm = false">
              <XMarkIcon class="w-4 h-4" />
            </button>
          </div>
          <div class="modal-body">
            <p style="font-size:13px;color:var(--text-primary);">{{ t('shell.topBar.exitConfirm') }}</p>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost btn-sm" @click="showExitConfirm = false">{{ t('common.cancel') }}</button>
            <button class="btn btn-primary btn-sm" style="background:var(--error);border-color:var(--error);" @click="confirmExit">{{ t('common.confirm') }}</button>
          </div>
        </div>
      </div>
    </Teleport>
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
  -webkit-app-region: drag;
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

.tab-bar-actions .icon-btn.active {
  color: var(--accent);
  background: var(--bg-tertiary);
}

/* 关于弹窗 */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.modal {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg, 8px);
  max-width: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4);
}

.about-modal {
  width: 380px;
}

.modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.modal-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.modal-body {
  padding: 20px;
  overflow-y: auto;
}

.about-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  text-align: center;
}

.about-icon {
  font-size: 36px;
  color: var(--accent);
}

.about-name {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}

.about-version {
  font-size: 12px;
  color: var(--text-muted);
}

.about-desc {
  font-size: 12px;
  color: var(--text-secondary);
  max-width: 280px;
  line-height: 1.5;
}

.about-section {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: var(--text-secondary);
}

.about-label {
  font-weight: 600;
  color: var(--text-primary);
}
</style>

<!-- 无边框窗口拖拽（unscoped） -->
<style>
.app-row1 { -webkit-app-region: drag; }
.app-row1 button,
.app-row1 .icon-btn,
.app-row1 .menu-item,
.app-row1 .window-controls,
.app-row1 .win-btn { -webkit-app-region: no-drag; }

.window-controls {
  display: flex;
  align-items: center;
  height: 100%;
  margin-right: -8px;
}
.win-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 46px;
  height: 100%;
  color: var(--text-secondary);
  cursor: pointer;
  transition: background 0.15s;
}
.win-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.win-btn-close:hover {
  background: #e81123;
  color: #fff;
}
</style>
