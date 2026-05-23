<template>
  <div class="plugin-manager">
  <span v-if="showId" class="cmp-id">{{ componentId }}</span>
    <div class="plugin-header">
      <h2 class="plugin-title">{{ t('settings.plugins') }}</h2>
      <p class="plugin-desc">{{ t('settings.pluginsDesc') }}</p>
    </div>

    <div class="plugin-list">
      <div
        v-for="plugin in plugins"
        :key="plugin.id"
        class="plugin-card"
        :class="`status-${plugin.status}`"
      >
        <div class="plugin-icon">
          <span class="icon-emoji">{{ plugin.icon }}</span>
        </div>

        <div class="plugin-info">
          <h3 class="plugin-name">{{ plugin.name }}</h3>
          <div class="plugin-meta">
            <span class="plugin-version">v{{ plugin.version }}</span>
            <span class="plugin-engine">{{ plugin.engine }}</span>
          </div>
        </div>

        <div class="plugin-status">
          <StatusDot :status="plugin.status" />
          <span class="status-text">{{ statusText(plugin.status) }}</span>
        </div>

        <div v-if="plugin.status === 'loading'" class="plugin-progress">
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: `${plugin.progress || 0}%` }"></div>
          </div>
          <span class="progress-text">{{ plugin.progress || 0 }}%</span>
        </div>

        <div class="plugin-actions">
          <div v-if="plugin.status === 'loaded'" class="toggle-switch">
            <input
              type="checkbox"
              :checked="plugin.enabled"
              @change="togglePlugin(plugin.id, ($event.target as HTMLInputElement).checked)"
            />
          </div>

          <button
            v-if="plugin.status === 'not-installed'"
            class="action-btn install-btn"
            @click="installPlugin(plugin.id)"
          >
            {{ t('settings.install') }}
          </button>

          <button
            v-if="plugin.status === 'error'"
            class="action-btn retry-btn"
            @click="retryPlugin(plugin.id)"
          >
            {{ t('settings.retry') }}
          </button>

          <button
            v-if="plugin.status === 'loaded'"
            class="action-btn uninstall-btn"
            @click="uninstallPlugin(plugin.id)"
          >
            {{ t('settings.uninstall') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import StatusDot from '../shell/StatusDot.vue'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('ST-007')
const { t } = useI18n()

export interface ParserPlugin {
  id: string
  name: string
  icon: string
  version: string
  engine: string
  status: 'loaded' | 'loading' | 'not-installed' | 'error'
  progress?: number
  enabled: boolean
}

const props = defineProps<{
  plugins: ParserPlugin[]
}>()

const emit = defineEmits<{
  install: [id: string]
  uninstall: [id: string]
  toggle: [id: string, enabled: boolean]
  retry: [id: string]
}>()

function statusText(status: string): string {
  return {
    'loaded': t('settings.loaded'),
    'loading': t('settings.loading'),
    'not-installed': t('settings.notInstalled'),
    'error': t('settings.error'),
  }[status] || status
}

function installPlugin(id: string) {
  emit('install', id)
}

function uninstallPlugin(id: string) {
  emit('uninstall', id)
}

function togglePlugin(id: string, enabled: boolean) {
  emit('toggle', id, enabled)
}

function retryPlugin(id: string) {
  emit('retry', id)
}
</script>

<style scoped lang="scss">
.plugin-manager {
  @apply flex flex-col gap-4;
}

.plugin-header {
  @apply flex flex-col gap-1;
}

.plugin-title {
  @apply text-sm font-semibold text-[--text-primary];
}

.plugin-desc {
  @apply text-xs text-[--text-muted];
}

.plugin-list {
  @apply flex flex-col gap-2;
}

.plugin-card {
  @apply flex items-center gap-3 p-3 rounded-lg bg-[--bg-secondary] border border-[--border] transition-colors;

  &.status-loaded {
    @apply border-green-500/30;
  }

  &.status-loading {
    @apply border-yellow-500/30;
  }

  &.status-error {
    @apply border-red-500/30;
  }
}

.plugin-icon {
  @apply flex items-center justify-center w-10 h-10 rounded-lg bg-[--bg-tertiary];
}

.icon-emoji {
  @apply text-xl;
}

.plugin-info {
  @apply flex-1 min-w-0;
}

.plugin-name {
  @apply text-sm font-medium text-[--text-primary] mb-0.5;
}

.plugin-meta {
  @apply flex gap-2;
}

.plugin-version {
  @apply text-xs text-[--text-muted];
}

.plugin-engine {
  @apply text-xs text-[--text-muted];
}

.plugin-status {
  @apply flex items-center gap-2;
}

.status-text {
  @apply text-xs text-[--text-secondary];
}

.plugin-progress {
  @apply flex items-center gap-2 flex-1 min-w-[100px];
}

.progress-bar {
  @apply flex-1 h-1 rounded-full bg-[--bg-tertiary] overflow-hidden;
}

.progress-fill {
  @apply h-full bg-yellow-400 transition-all duration-300;
}

.progress-text {
  @apply text-xs text-[--text-muted];
}

.plugin-actions {
  @apply flex items-center gap-2;
}

.toggle-switch {
  @apply relative;
}

.toggle-switch input {
  @apply appearance-none w-10 h-5 rounded-full bg-[--bg-tertiary] outline-none cursor-pointer transition-colors;

  &:checked {
    @apply bg-[--accent];
  }

  &::before {
    content: '';
    @apply absolute left-0.5 top-0.5 w-4 h-4 rounded-full bg-white transition-transform;

    checked: {
      @apply translate-x-5;
    }
  }
}

.action-btn {
  @apply px-3 py-1.5 text-xs rounded transition-colors;

  &.install-btn {
    @apply bg-[--accent]/20 text-[--accent] hover:bg-[--accent]/30;
  }

  &.retry-btn {
    @apply bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30;
  }

  &.uninstall-btn {
    @apply bg-red-500/20 text-red-400 hover:bg-red-500/30;
  }
}
</style>
