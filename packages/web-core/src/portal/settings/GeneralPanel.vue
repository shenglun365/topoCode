<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ipc } from '../../services/ipc'
import { LocaleToggle } from '../../shell'
import { authHeaders } from '../../services/api'
import type { ImportConfig } from '../../types/ipc'

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
    appsError.value = `进程信息不可用：${e?.message || e}（需 supervisor 控制面）`
  }
}

async function restartApp(label: string) {
  restarting.value = label
  try {
    await fetch(`/api/system/apps/${label}/restart`, { method: 'POST', headers: authHeaders() })
  } catch (e: any) {
    window.alert(`重启失败：${e?.message || e}`)
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
    <h3>通用设置</h3>

    <div class="section">
      <h4>界面语言</h4>
      <div class="row">
        <LocaleToggle @update:locale="onLocale" />
        <span class="muted">全局统一存储（topoone-locale），chat/docs 正文翻译分批接入。</span>
      </div>
    </div>

    <div class="section">
      <h4>导入设置</h4>
      <div class="row">
        <label>忽略模式
          <select v-model="importConfig.ignoreMode">
            <option value="strict">strict</option>
            <option value="loose">loose</option>
          </select>
        </label>
        <button class="btn btn-primary btn-sm" @click="saveImportConfig">保存导入配置</button>
      </div>
    </div>

    <div class="section">
      <h4>子系统进程与端口（只读）</h4>
      <p v-if="appsError" class="error">{{ appsError }}</p>
      <table v-else class="settings-table">
        <thead><tr><th>进程</th><th>状态</th><th>PID</th><th>重启次数</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="a in apps" :key="a.label">
            <td>{{ a.label }}</td>
            <td>{{ a.status }}</td>
            <td>{{ a.pid ?? '-' }}</td>
            <td>{{ a.restart_count }}</td>
            <td>
              <button class="btn btn-ghost btn-xs" :disabled="restarting === a.label" @click="restartApp(a.label)">
                {{ restarting === a.label ? '重启中…' : '重启' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
