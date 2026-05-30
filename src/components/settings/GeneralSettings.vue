<script setup lang="ts">
import { computed, onMounted, watch, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowPathIcon,
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

// HTTP 服务 IP 设置
const localIps = ref<string[]>([])
const showRestartHint = ref(false)

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
}

async function applyHttpConfigAndRestart() {
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
            <option value="127.0.0.1">localhost (127.0.0.1)</option>
            <option value="0.0.0.0">0.0.0.0</option>
            <option
              v-for="ip in localIps"
              :key="ip"
              :value="ip"
            >{{ ip }}</option>
          </select>
          <span style="font-size:11px; color:var(--text-muted);">{{ t('settings.port') }}:</span>
          <input
            type="number"
            class="input"
            style="width:80px; padding:4px 8px; font-size:11px;"
            :value="statusStore.httpPort"
            @change="statusStore.httpPort = Number(($event.target as HTMLInputElement).value) || statusStore.httpPort; showRestartHint = true"
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
          <button
            v-if="showRestartHint"
            class="btn btn-primary btn-sm"
            @click="applyHttpConfigAndRestart"
          >
            <ArrowPathIcon class="w-3 h-3" />
            <span>{{ t('common.restart') }}</span>
          </button>
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
