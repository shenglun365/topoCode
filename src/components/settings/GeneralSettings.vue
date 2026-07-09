<script setup lang="ts">
import { computed, onMounted, watch, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowPathIcon,
  GlobeAltIcon,
} from '@heroicons/vue/24/outline'
import { useSettingsStore } from '@/stores/settings-store'
import { useStatusStore } from '@/stores/status'
import type { SupportedLocale } from '@/i18n'
import { useComponentId } from '@/composables/useComponentId'
import { ipc } from '@/services/ipc'

const { showId, componentId } = useComponentId('ST-004')
const { t } = useI18n({ useScope: 'global' })
const settingsStore = useSettingsStore()
const statusStore = useStatusStore()

const autoMigrate = ref(false)

async function browseResourceDir() {
  const dir = await (window.api as any)?.dialog?.openDirectory()
  if (dir) {
    settingsStore.setResourceProjectsDir(dir, autoMigrate.value)
  }
}

function openInFileManager(dir: string) {
  ;(window.api as any)?.shell?.openPath(dir)
}

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

// 字体大小实时生效
watch(() => settingsStore.fontSize, (val) => {
  document.documentElement.style.fontSize = val + 'px'
})
onMounted(() => {
  document.documentElement.style.fontSize = settingsStore.fontSize + 'px'
})

const languages = [
  { value: 'zh-CN' as SupportedLocale, key: 'settings.simplifiedChinese' },
  { value: 'en-US' as SupportedLocale, key: 'settings.english' },
]

const aiLanguage = ref('zh-CN')

async function loadAiLanguage() {
  try {
    const r = await (window.api as any)?.promptTemplate?.getDefaultLocale()
    if (r && r.locale) aiLanguage.value = r.locale
  } catch {}
}

async function setAiLanguage(locale: string) {
  aiLanguage.value = locale
  try {
    await (window.api as any)?.promptTemplate?.setDefaultLocale({ locale })
  } catch {}
}

onMounted(() => { loadAiLanguage() })

// HTTP 服务 IP 设置
const localIps = ref<string[]>([])
const showRestartHint = ref(false)

const restartLabel = computed(() => {
  if (settingsStore.restartState === 'restarting') return t('common.restarting')
  if (settingsStore.restartState === 'success') return t('common.restartSuccess')
  if (settingsStore.restartState === 'error') return t('common.restartFailed')
  return t('common.restart')
})

const restartBtnClass = computed(() => {
  if (settingsStore.restartState === 'restarting') return 'btn-ghost'
  if (settingsStore.restartState === 'success') return 'btn-primary restart-ok'
  if (settingsStore.restartState === 'error') return 'btn-primary restart-fail'
  return 'btn-primary'
})

const restartBtnTitle = computed(() => {
  if (settingsStore.hasRunningTasks) return t('common.restartBlockedTasksShort')
  if (settingsStore.restartState === 'error') return settingsStore.restartErrorMsg
  return ''
})

async function detectLocalIps() {
  try {
    const pc = new RTCPeerConnection({ iceServers: [] })
    pc.createDataChannel('')
    pc.onicecandidate = (e) => {
      if (e.candidate) {
        const ip = e.candidate.candidate.split(' ')[4]
        if (ip && !localIps.value.includes(ip) && ip !== '127.0.0.1') {
          localIps.value.push(ip)
        }
      }
    }
    setTimeout(() => pc.close(), 2000)
  } catch {}
}

onMounted(() => { detectLocalIps() })



function onBindIpChange(val: string) {
  statusStore.httpHost = val
  showRestartHint.value = true
  saveHttpConfig()
}

function onPortChange(val: number) {
  if (val > 0 && val <= 65535) {
    statusStore.httpPort = val
    showRestartHint.value = true
    saveHttpConfig()
  }
}

async function saveHttpConfig() {
  try {
    await ipc.backend.saveHttpConfig({ host: statusStore.httpHost, port: statusStore.httpPort })
  } catch (e) {
    console.warn('[GeneralSettings] saveHttpConfig failed:', e)
  }
}

async function applyHttpConfigAndRestart() {
  await saveHttpConfig()
  await settingsStore.restartBackend()
  showRestartHint.value = false
}

function openHttpPage() {
  const ip = statusStore.httpHost === '0.0.0.0' ? '127.0.0.1' : statusStore.httpHost
  window.open(`http://${ip}:${statusStore.httpPort}`, '_blank')
}
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

    <!-- 界面语言 -->
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
      <span class="form-hint">{{ t('settings.uiLanguageHint', '界面显示语言') }}</span>
    </div>

    <!-- AI 解析输出语言 -->
    <div class="form-group">
      <label class="form-label">{{ t('settings.aiAnalysisLanguage', 'AI 解析语言') }}</label>
      <select
        class="select"
        style="width:200px;"
        :value="aiLanguage"
        @change="setAiLanguage(($event.target as HTMLSelectElement).value)"
      >
        <option value="zh-CN">简体中文</option>
        <option value="en-US">English</option>
      </select>
      <span class="form-hint">{{ t('settings.aiAnalysisLanguageHint', 'LLM 分析输出内容的语言（与界面语言独立）') }}</span>
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
        <div style="font-size:12px; font-weight:500; margin-bottom:10px;">
          {{ t('settings.kbDocAccess') }}
        </div>
        <div style="display:flex; gap:8px; align-items:center; margin-bottom:8px;">
          <span style="font-size:11px; color:var(--text-muted);">{{ t('settings.bindIp') }}:</span>
          <select
            class="input"
            style="width:150px; padding:4px 8px; font-size:11px;"
            :value="statusStore.httpHost"
            @change="onBindIpChange(($event.target as HTMLSelectElement).value)"
          >
            <option value="127.0.0.1">
              localhost (127.0.0.1)
            </option>
            <option value="0.0.0.0">
              0.0.0.0
            </option>
            <option
              v-for="ip in localIps"
              :key="ip"
              :value="ip"
            >
              {{ ip }}
            </option>
          </select>
          <span style="font-size:11px; color:var(--text-muted);">{{ t('settings.port') }}:</span>
          <input
            type="number"
            class="input"
            style="width:80px; padding:4px 8px; font-size:11px;"
            :value="statusStore.httpPort"
            @change="onPortChange(Number(($event.target as HTMLInputElement).value))"
          >
        </div>
        <div style="display:flex; gap:4px; align-items:center;">
          <button
            class="btn btn-ghost btn-sm"
            @click="openHttpPage"
          >
            <GlobeAltIcon class="w-3 h-3" />
            <span>{{ t('settings.openInBrowser') }}</span>
          </button>
          <div style="flex:1;" />
          <template v-if="showRestartHint || settingsStore.restartState !== 'idle'">
            <button
              class="btn btn-sm"
              :class="restartBtnClass"
              :disabled="settingsStore.restartState === 'restarting' || settingsStore.hasRunningTasks"
              :title="restartBtnTitle"
              @click="applyHttpConfigAndRestart"
            >
              <span
                v-if="settingsStore.restartState === 'restarting'"
                class="spinner"
              />
              <ArrowPathIcon
                v-else
                class="w-3 h-3"
              />
              <span>{{ restartLabel }}</span>
            </button>
          </template>
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

    <!-- 资源项目存储位置 -->
    <div style="margin-top:16px;">
      <h3 style="font-size:13px; font-weight:600; margin-bottom:12px;">
        资源项目
      </h3>
      <div class="card" style="padding:14px;">
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label">资源项目存储位置</label>
          <div style="display:flex; gap:6px; align-items:center;">
            <input
              class="input"
              style="flex:1; padding:6px 10px; font-size:12px;"
              :value="settingsStore.resourceProjectsDir"
              readonly
              placeholder="默认: ~/.topocode/resource-projects/"
            >
            <button class="btn btn-ghost btn-sm" @click="browseResourceDir">
              浏览
            </button>
          </div>
          <div style="margin-top:4px;">
            <label style="display:flex; align-items:center; gap:6px; font-size:11px; cursor:pointer;">
              <input type="checkbox" v-model="autoMigrate" style="accent-color:var(--accent);">
              自动迁移已有数据到新目录
            </label>
          </div>
          <div style="font-size:10px; color:var(--text-muted); margin-top:4px;">
            资源下载后的备份文件同样存储在该目录下
          </div>
        </div>

        <!-- 历史记录 -->
        <div v-if="settingsStore.resourceDirHistory.length > 1" style="margin-top:8px; padding-top:8px; border-top:1px solid var(--border);">
          <div style="font-size:11px; color:var(--text-muted); margin-bottom:4px;">最近使用的目录：</div>
          <div v-for="(dir, i) in settingsStore.resourceDirHistory" :key="i" style="display:flex; align-items:center; gap:4px; padding:2px 0;">
            <span style="font-size:10px; color:var(--text-muted); font-family:var(--font-mono); flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{{ dir }}</span>
            <button class="btn btn-ghost btn-icon btn-xs" title="在文件夹中打开" @click="openInFileManager(dir)">
              <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
            </button>
            <button class="btn btn-ghost btn-xs" style="font-size:10px;" @click="settingsStore.restoreResourceDir(i)" :disabled="dir === settingsStore.resourceProjectsDir">
              恢复
            </button>
          </div>
          <div style="font-size:10px; color:var(--text-muted); margin-top:2px;">
            如不迁移，需手动将旧目录内容复制到新目录，否则已有项目将无法访问。
          </div>
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
        <div
          class="form-group"
          style="margin-bottom:12px;"
        >
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
          <div style="display:flex; align-items:center; gap:6px;">
            <button
              class="btn btn-sm"
              :class="restartBtnClass"
              :disabled="settingsStore.restartState === 'restarting' || settingsStore.hasRunningTasks"
              :title="restartBtnTitle"
              @click="settingsStore.restartBackend()"
            >
              <span
                v-if="settingsStore.restartState === 'restarting'"
                class="spinner"
              />
              <ArrowPathIcon
                v-else
                class="w-3 h-3"
              />
              <span>{{ restartLabel }}</span>
            </button>
          </div>
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

.restart-ok { background: var(--success); color: #fff; }
.restart-ok:hover { background: color-mix(in srgb, var(--success) 85%, #000); }
.restart-fail { background: var(--error); color: #fff; }
.restart-fail:hover { background: color-mix(in srgb, var(--error) 85%, #000); }

.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid transparent;
  border-top-color: currentColor;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
