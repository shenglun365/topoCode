<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ipc } from '../../services/ipc'
import { LocaleToggle } from '../../shell'
import { authHeaders } from '../../services/api'
import type { ImportConfig } from '../../types/ipc'

const { t } = useI18n()

/** 系统进程（经网关 /api/system/apps 代理 supervisor） */
interface SystemApp {
  label: string
  status: string
  pid: number | null
  restart_count: number
  alive: boolean
}

const locale = ref<'zh-CN' | 'en-US'>('zh-CN')
const importConfig = ref<ImportConfig>({ ignoreMode: 'strict', customPatterns: [], extraIgnoreFiles: [] })
const apps = ref<SystemApp[]>([])
const appsError = ref('')
const restarting = ref<string | null>(null)

async function loadImportConfig() {
  try {
    importConfig.value = await ipc.settings.getImportConfig()
  } catch { /* ignore */ }
}

async function saveImportConfig() {
  await ipc.settings.setImportConfig(importConfig.value)
}

async function loadApps() {
  try {
    const res = await fetch('/api/system/apps', { headers: authHeaders() })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    apps.value = await res.json()
    appsError.value = ''
  } catch (e: any) {
    apps.value = []
    appsError.value = t('settings.general.appsError', { message: e?.message || e })
  }
}

async function restartApp(label: string) {
  restarting.value = label
  try {
    await fetch(`/api/system/apps/${label}/restart`, { method: 'POST', headers: authHeaders() })
  } catch (e: any) {
    window.alert(t('settings.general.restartFailed', { message: e?.message || e }))
  } finally {
    restarting.value = null
    await loadApps()
  }
}

function onLocale(l: string) {
  locale.value = l as 'zh-CN' | 'en-US'
}

onMounted(() => {
  loadImportConfig()
  loadApps()
})
</script>

<template>
  <div class="panel">
    <h3>{{ t('settings.tabs.general') }}</h3>

    <div class="section">
      <h4>{{ t('settings.general.language') }}</h4>
      <div class="row">
        <LocaleToggle @update:locale="onLocale" />
        <span class="muted">{{ t('settings.general.localeHint') }}</span>
      </div>
    </div>

    <div class="section">
      <h4>{{ t('settings.general.importSection') }}</h4>
      <div class="row">
        <label>{{ t('settings.general.ignoreMode') }}
          <select v-model="importConfig.ignoreMode">
            <option value="strict">strict</option>
            <option value="loose">loose</option>
          </select>
        </label>
        <button class="btn btn-primary btn-sm" @click="saveImportConfig">{{ t('settings.general.saveImport') }}</button>
      </div>
      <div class="row mirror-row">
        <label class="mirror-label">{{ t('settings.general.mirrorRoot') }}</label>
        <input
          v-model="importConfig.sourceMirrorRoot"
          class="input mirror-input font-mono"
          :placeholder="t('settings.general.mirrorRootPlaceholder')"
        >
      </div>
      <p class="muted">{{ t('settings.general.mirrorRootHint') }}</p>
    </div>

    <div class="section">
      <h4>{{ t('settings.general.appsSection') }}</h4>
      <p v-if="appsError" class="error">{{ appsError }}</p>
      <table v-else class="settings-table">
        <thead><tr><th>{{ t('settings.general.process') }}</th><th>{{ t('common.status') }}</th><th>PID</th><th>{{ t('settings.general.restartCount') }}</th><th>{{ t('common.actions') }}</th></tr></thead>
        <tbody>
          <tr v-for="a in apps" :key="a.label">
            <td>{{ a.label }}</td>
            <td>{{ a.status }}</td>
            <td>{{ a.pid ?? '-' }}</td>
            <td>{{ a.restart_count }}</td>
            <td>
              <button class="btn btn-ghost btn-xs" :disabled="restarting === a.label" @click="restartApp(a.label)">
                {{ restarting === a.label ? t('common.restarting') : t('common.restart') }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.mirror-row {
  margin-top: calc(10px * var(--ui-scale, 1));
}
.mirror-label {
  margin-right: calc(8px * var(--ui-scale, 1));
  white-space: nowrap;
}
.mirror-input {
  flex: 1;
  min-width: 0;
  font-size: calc(12px * var(--ui-scale, 1));
}
</style>
