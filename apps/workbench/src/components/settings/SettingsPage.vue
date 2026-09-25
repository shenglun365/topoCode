<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { AppToolbar, readFontSize } from '@topo/web-core/shell'
import ModelsPanel from './ModelsPanel.vue'
import GeneralPanel from './GeneralPanel.vue'
import ThemesPanel from './ThemesPanel.vue'
import AgentsPanel from './AgentsPanel.vue'
import AboutPanel from './AboutPanel.vue'

const { t } = useI18n()

type SectionKey = 'models' | 'general' | 'theme' | 'agents' | 'about'

const fontSize = ref(readFontSize())

const sections: Array<{ key: SectionKey; labelKey: string }> = [
  { key: 'models', labelKey: 'settings.tabs.models' },
  { key: 'general', labelKey: 'settings.tabs.general' },
  { key: 'theme', labelKey: 'settings.tabs.theme' },
  { key: 'agents', labelKey: 'settings.tabs.agents' },
  { key: 'about', labelKey: 'settings.tabs.about' },
]

const active = ref<SectionKey>('models')

function goHome() {
  // history 路由切换（原 location.hash='#/'）
  window.location.href = '/app/'
}
</script>

<template>
  <div class="settings-page">
    <AppToolbar
      app-key="portal"
      :title="t('common.settings')"
      :font-targets="['--content-font-size']"
      :font-size="fontSize"
      @update:font-size="fontSize = $event"
    >
      <template #tools>
        <a href="#/" class="toolbar-btn">← {{ t('nav.backHome') }}</a>
        <a href="#/user" class="toolbar-btn">{{ t('nav.userCenter') }}</a>
      </template>
    </AppToolbar>

    <div class="settings-body">
      <aside class="settings-nav">
        <button
          v-for="s in sections"
          :key="s.key"
          class="nav-item"
          :class="{ active: active === s.key }"
          @click="active = s.key"
        >
          {{ t(s.labelKey) }}
        </button>
      </aside>
      <main class="settings-main">
        <ModelsPanel v-if="active === 'models'" />
        <GeneralPanel v-else-if="active === 'general'" />
        <ThemesPanel v-else-if="active === 'theme'" />
        <AgentsPanel v-else-if="active === 'agents'" />
        <AboutPanel v-else />
      </main>
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: var(--font-sans);
}
.settings-body {
  flex: 1;
  display: flex;
  align-items: stretch;
  min-height: 0;
}
.settings-nav {
  width: calc(180px * var(--ui-scale));
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  padding: calc(12px * var(--ui-scale)) 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: var(--bg-secondary);
}
.nav-item {
  padding: 8px calc(12px * var(--ui-scale));
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  text-align: left;
  font-size: calc(13px * var(--ui-scale));
}
.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.nav-item.active {
  background: var(--bg-tertiary);
  color: var(--accent);
  font-weight: 600;
}
.settings-main {
  flex: 1;
  overflow: auto;
  padding: calc(20px * var(--ui-scale)) calc(24px * var(--ui-scale));
}
</style>

<style>
/* 设置面板共享样式 */
.panel h3 {
  margin: 0 0 8px;
  font-size: calc(16px * var(--ui-scale));
}
.panel-hint {
  color: var(--text-muted);
  font-size: calc(12px * var(--ui-scale));
  margin: 0 0 calc(12px * var(--ui-scale));
}
.section {
  margin-bottom: calc(24px * var(--ui-scale));
}
.section h4 {
  margin: 0 0 8px;
  font-size: calc(14px * var(--ui-scale));
  color: var(--text-secondary);
}
.row {
  display: flex;
  align-items: center;
  gap: calc(10px * var(--ui-scale));
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.settings-table {
  width: 100%;
  border-collapse: collapse;
  font-size: calc(13px * var(--ui-scale));
}
.settings-table th,
.settings-table td {
  padding: 6px calc(10px * var(--ui-scale));
  border-bottom: 1px solid var(--border);
  text-align: left;
  vertical-align: middle;
}
.settings-table th {
  color: var(--text-muted);
  font-weight: 500;
  font-size: calc(12px * var(--ui-scale));
}
.row-actions {
  display: flex;
  gap: 6px;
  white-space: nowrap;
}
.mono {
  font-family: var(--font-mono);
  font-size: calc(12px * var(--ui-scale));
}
.muted {
  color: var(--text-muted);
  font-size: calc(12px * var(--ui-scale));
}
.error {
  color: var(--error);
  font-size: calc(12px * var(--ui-scale));
}
.empty {
  color: var(--text-muted);
  font-size: calc(13px * var(--ui-scale));
  padding: calc(12px * var(--ui-scale)) 0;
}
.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px calc(12px * var(--ui-scale));
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-card);
  color: var(--text-primary);
  cursor: pointer;
  font-size: calc(13px * var(--ui-scale));
  text-decoration: none;
}
.btn:hover {
  border-color: var(--accent);
}
.btn-primary {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}
.btn-ghost {
  background: transparent;
  color: var(--text-secondary);
}
.btn-danger {
  color: var(--error);
}
.btn-sm {
  padding: 3px 8px;
  font-size: calc(12px * var(--ui-scale));
}
.btn-xs {
  padding: 2px 6px;
  font-size: calc(11px * var(--ui-scale));
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.danger {
  color: var(--error);
}
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}
.modal-box {
  width: calc(520px * var(--ui-scale));
  max-width: 92vw;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: calc(20px * var(--ui-scale));
  box-shadow: var(--shadow-md);
}
.modal-box h3 {
  margin: 0 0 calc(14px * var(--ui-scale));
  font-size: calc(15px * var(--ui-scale));
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: calc(12px * var(--ui-scale));
  margin-bottom: calc(12px * var(--ui-scale));
}
.form-grid label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: calc(12px * var(--ui-scale));
  color: var(--text-secondary);
}
.form-grid input,
.form-grid select {
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-card);
  color: var(--text-primary);
  outline: none;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
.check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: calc(13px * var(--ui-scale));
}
.theme-apps {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.theme-app-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: calc(420px * var(--ui-scale));
  font-size: calc(13px * var(--ui-scale));
}
.about-body {
  text-align: center;
  padding: calc(24px * var(--ui-scale)) 0;
}
.about-logo {
  font-size: calc(40px * var(--ui-scale));
  color: var(--accent);
  font-weight: 700;
}
.about-body h4 {
  margin: 8px 0 4px;
  font-size: calc(18px * var(--ui-scale));
}
</style>
