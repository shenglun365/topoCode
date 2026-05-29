<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  SunIcon,
  MoonIcon,
  ComputerDesktopIcon,
  ArrowPathIcon,
  LinkIcon,
  GlobeAltIcon,
} from '@heroicons/vue/24/outline'
import { useSettingsStore } from '@/stores/settings'
import { useStatusStore } from '@/stores/status'
import type { SupportedLocale } from '@/i18n'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('ST-004')
const { t } = useI18n()
const settingsStore = useSettingsStore()
const statusStore = useStatusStore()

const memoryLimitStatusClass = computed(() => {
  if (statusStore.backend.status !== 'running') return 'status-dot-error'
  if (settingsStore.memoryLimitPending) return 'status-dot-warning'
  return 'status-dot-ok'
})

const memoryLimitStatusText = computed(() => {
  if (statusStore.backend.status !== 'running') return t('common.disconnected')
  if (settingsStore.memoryLimitPending) return t('settings.memoryLimitPending')
  return t('settings.memoryLimitActive')
})

onMounted(() => {
  settingsStore.loadPythonMemoryLimit()
})

const languages = [
  { value: 'zh-CN' as SupportedLocale, key: 'settings.simplifiedChinese' },
  { value: 'en-US' as SupportedLocale, key: 'settings.english' },
]
</script>

<template>
  <div class="general-settings">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <h2 style="font-size:16px; font-weight:600; margin-bottom:16px;">
      {{ t('settings.generalSettings') }}
    </h2>

    <!-- 主题 -->
    <div class="form-group">
      <label class="form-label">{{ t('settings.themeMode') }}</label>
      <div style="display:flex; gap:8px;">
        <button class="btn btn-ghost btn-sm">
          <SunIcon class="w-4 h-4" />
          <span>{{ t('settings.lightMode') }}</span>
        </button>
        <button class="btn btn-primary btn-sm">
          <MoonIcon class="w-4 h-4" />
          <span>{{ t('settings.darkMode') }}</span>
        </button>
        <button class="btn btn-ghost btn-sm">
          <ComputerDesktopIcon class="w-4 h-4" />
          <span>{{ t('settings.systemMode') }}</span>
        </button>
      </div>
    </div>

    <!-- 语言 -->
    <div class="form-group">
      <label class="form-label">{{ t('settings.language') }}</label>
      <select
        class="select"
        style="width:200px;"
        :value="settingsStore.locale"
        @change="settingsStore.setLocale(($event.target as HTMLSelectElement).value as SupportedLocale)"
      >
        <option
          v-for="lang in languages"
          :key="lang.value"
          :value="lang.value"
        >
          {{ t(lang.key) }}
        </option>
      </select>
    </div>

    <!-- 代码字体大小 -->
    <div class="form-group">
      <label class="form-label">{{ t('settings.fontSize') }}</label>
      <div style="display:flex; align-items:center; gap:8px;">
        <input
          type="range"
          class="slider"
          min="10"
          max="20"
          :value="settingsStore.fontSize"
          style="width:200px;"
          @input="settingsStore.fontSize = Number(($event.target as HTMLInputElement).value)"
        >
        <span style="font-size:12px; font-family:var(--font-mono); min-width:30px;">
          {{ settingsStore.fontSize }}px
        </span>
      </div>
    </div>

    <!-- 自动保存间隔 -->
    <div class="form-group">
      <label class="form-label">{{ t('settings.autoSaveInterval') }}</label>
      <select
        class="select"
        style="width:120px;"
        :value="settingsStore.autoSaveInterval"
        @change="settingsStore.autoSaveInterval = Number(($event.target as HTMLSelectElement).value)"
      >
        <option :value="30">
          {{ t('common.seconds', { value: 30 }) }}
        </option>
        <option :value="60">
          {{ t('common.seconds', { value: 60 }) }}
        </option>
        <option :value="300">
          {{ t('common.minutes', { value: 5 }) }}
        </option>
        <option :value="0">
          {{ t('common.off') }}
        </option>
      </select>
    </div>

    <div class="divider" />

    <!-- 本地 HTTP 服务 -->
    <div style="margin-top:16px;">
      <h3 style="font-size:13px; font-weight:600; margin-bottom:12px;">
        {{ t('settings.localHttpServer') }}
      </h3>
      <div
        class="card"
        style="padding:14px;"
      >
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
          <div>
            <div style="font-size:12px; font-weight:500;">
              {{ t('settings.kbDocAccess') }}
            </div>
            <div
              class="text-muted"
              style="font-size:10px;"
            >
              {{ t('settings.kbDocAccessHint') }}
            </div>
          </div>
          <label class="toggle">
            <input
              v-model="settingsStore.kbHttpServer"
              type="checkbox"
            >
            <span class="toggle-slider" />
          </label>
        </div>
        <div style="display:flex; gap:8px; align-items:center; margin-bottom:8px;">
          <span style="font-size:11px; color:var(--text-muted);">{{ t('settings.port') }}:</span>
          <input
            type="number"
            class="input"
            :value="settingsStore.kbHttpPort"
            style="width:80px; padding:4px 8px; font-size:11px;"
            @input="settingsStore.kbHttpPort = Number(($event.target as HTMLInputElement).value)"
          >
          <span style="font-size:11px; color:var(--text-muted);">{{ t('settings.address') }}:</span>
          <span style="font-size:11px; font-family:var(--font-mono); color:var(--accent);">
            http://localhost:{{ settingsStore.kbHttpPort }}
          </span>
        </div>
        <div style="display:flex; gap:4px;">
          <button class="btn btn-ghost btn-sm">
            <LinkIcon class="w-3 h-3" />
            <span>{{ t('settings.testConnection') }}</span>
          </button>
          <button class="btn btn-ghost btn-sm">
            <GlobeAltIcon class="w-3 h-3" />
            <span>{{ t('settings.openInBrowser') }}</span>
          </button>
        </div>
        <div style="margin-top:8px; padding:8px; background:var(--bg-primary); border-radius:var(--radius-sm); font-size:10px; color:var(--text-muted);">
          <strong>{{ t('settings.availableUriPaths') }}:</strong><br>
          /kb/docs/&lt;{{ t('settings.docId') }}&gt; — {{ t('settings.openDocBrowse') }}<br>
          /kb/docs/&lt;{{ t('settings.docId') }}&gt;/edit — {{ t('settings.openDocEdit') }}
        </div>
      </div>
    </div>

    <div class="divider" />

    <!-- 后端端口设置 -->
    <div style="margin-top:16px;">
      <h3 style="font-size:13px; font-weight:600; margin-bottom:12px;">
        {{ t('settings.backendPorts') }}
      </h3>
      <div
        class="card"
        style="padding:14px;"
      >
        <div
          class="form-group"
          style="margin-bottom:12px;"
        >
          <label class="form-label">{{ t('settings.dealerPort') }}</label>
          <div style="display:flex; gap:8px; align-items:center;">
            <input
              type="number"
              class="input"
              :value="settingsStore.zmqDealerPort"
              style="width:100px; padding:4px 8px; font-size:11px;"
              min="1024"
              max="65535"
              @input="settingsStore.zmqDealerPort = Number(($event.target as HTMLInputElement).value)"
            >
            <button
              class="btn btn-ghost btn-sm"
              @click="settingsStore.testPort('dealer')"
            >
              <LinkIcon class="w-3 h-3" />
              <span>{{ t('settings.testPort') }}</span>
            </button>
            <span
              v-if="settingsStore.dealerPortStatus"
              class="status-dot"
              :style="{ backgroundColor: settingsStore.dealerPortStatus === 'available' ? 'var(--success)' : 'var(--error)' }"
            />
          </div>
        </div>
        <div
          class="form-group"
          style="margin-bottom:12px;"
        >
          <label class="form-label">{{ t('settings.pubPort') }}</label>
          <div style="display:flex; gap:8px; align-items:center;">
            <input
              type="number"
              class="input"
              :value="settingsStore.zmqPubPort"
              style="width:100px; padding:4px 8px; font-size:11px;"
              min="1024"
              max="65535"
              @input="settingsStore.zmqPubPort = Number(($event.target as HTMLInputElement).value)"
            >
            <button
              class="btn btn-ghost btn-sm"
              @click="settingsStore.testPort('pub')"
            >
              <LinkIcon class="w-3 h-3" />
              <span>{{ t('settings.testPort') }}</span>
            </button>
            <span
              v-if="settingsStore.pubPortStatus"
              class="status-dot"
              :style="{ backgroundColor: settingsStore.pubPortStatus === 'available' ? 'var(--success)' : 'var(--error)' }"
            />
          </div>
        </div>
        <div style="font-size:10px; color:var(--text-muted); margin-top:8px;">
          {{ t('settings.portChangeHint') }}
        </div>
      </div>
    </div>

    <!-- 后端内存限制 -->
    <div style="margin-top:16px;">
      <h3 style="font-size:13px; font-weight:600; margin-bottom:12px;">
        {{ t('settings.pythonBackend') }}
      </h3>
      <div
        class="card"
        style="padding:14px;"
      >
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label">{{ t('settings.memoryLimit') }}</label>
          <div style="display:flex; gap:10px; align-items:center;">
            <input
              type="range"
              min="4096"
              max="8192"
              step="1024"
              :value="settingsStore.pythonMemoryLimit"
              style="flex:1;"
              @input="settingsStore.setPythonMemoryLimit(Number(($event.target as HTMLInputElement).value))"
            >
            <span style="font-size:12px; font-family:var(--font-mono); min-width:70px; text-align:right;">
              {{ settingsStore.pythonMemoryLimit }} MB
            </span>
          </div>
          <div style="font-size:10px; color:var(--text-muted); margin-top:4px;">
            {{ t('settings.memoryLimitHint') }}
          </div>
        </div>

        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div style="display:flex; align-items:center; gap:8px;">
            <span
              class="status-dot"
              :class="memoryLimitStatusClass"
            />
            <span style="font-size:12px;">
              {{ memoryLimitStatusText }}
            </span>
          </div>
          <button
            class="btn btn-ghost btn-sm"
            @click="settingsStore.restartBackend()"
          >
            <ArrowPathIcon class="w-3 h-3" />
            <span>{{ t('common.restart') }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.general-settings {
  max-width: 600px;
}

.form-group {
  margin-bottom: 16px;
}

.form-label {
  display: block;
  font-size: 12px;
  font-weight: 500;
  margin-bottom: 6px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.status-dot-ok {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  background: var(--success);
  box-shadow: 0 0 4px var(--success);
}
.status-dot-warning {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  background: var(--warning);
}
.status-dot-error {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  background: var(--error);
}
</style>
