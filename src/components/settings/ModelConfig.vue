<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import {
  CpuChipIcon,
  GlobeAltIcon,
  ComputerDesktopIcon,
  PlusIcon,
  WrenchScrewdriverIcon,
  PencilIcon,
  TrashIcon,
  ArrowPathIcon,
  CheckCircleIcon,
  XCircleIcon,
} from '@heroicons/vue/24/outline'
import { useSettingsStore } from '@/stores/settings'
import { taskTypeLabels } from '@/utils/mock'

const { t } = useI18n()
const settingsStore = useSettingsStore()

function getProviderIcon(provider: string): any {
  switch (provider) {
    case 'ollama': return ComputerDesktopIcon
    case 'openai': return GlobeAltIcon
    case 'lmstudio': return ComputerDesktopIcon
    default: return CpuChipIcon
  }
}

function getStatusBadge(status: string): string {
  switch (status) {
    case 'connected': return 'badge-green'
    case 'offline': return 'badge-red'
    case 'error': return 'badge-yellow'
    default: return 'badge-gray'
  }
}

function getStatusText(status: string): string {
  switch (status) {
    case 'connected': return t('settings.connected')
    case 'offline': return t('settings.offline')
    case 'error': return t('common.error')
    default: return ''
  }
}
</script>

<template>
  <div class="model-config">
    <h2 style="font-size:16px; font-weight:600; margin-bottom:4px;">{{ t('settings.aiModelConfig') }}</h2>
    <p class="text-muted" style="font-size:12px; margin-bottom:20px;">{{ t('settings.aiModelDesc') }}</p>

    <!-- 当前使用 -->
    <div class="card" style="margin-bottom:16px; border-left:3px solid var(--accent);">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <div>
          <div style="font-size:11px; color:var(--text-muted); margin-bottom:2px;">{{ t('settings.currentlyUsing') }}</div>
          <div style="font-size:14px; font-weight:600;">
            {{ settingsStore.defaultModel?.name || t('settings.notConfigured') }}
          </div>
          <div class="text-muted" style="font-size:11px;">
            {{ settingsStore.defaultModel?.url }}
          </div>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          <span class="badge badge-green">● {{ t('settings.connected') }}</span>
          <span v-if="settingsStore.defaultModel?.latency" style="font-size:10px; color:var(--text-muted);">
            {{ t('settings.latency') }} {{ settingsStore.defaultModel.latency }}ms
          </span>
        </div>
      </div>
    </div>

    <!-- 配置列表 -->
    <div style="margin-bottom:16px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
        <h3 style="font-size:13px; font-weight:600;">{{ t('settings.savedConfigs') }}</h3>
        <button class="btn btn-primary btn-sm">
          <PlusIcon class="w-4 h-4" />
          <span>{{ t('settings.addConfig') }}</span>
        </button>
      </div>

      <!-- 配置项 -->
      <div
        v-for="config in settingsStore.modelConfigs"
        :key="config.id"
        class="card"
        style="padding:12px; margin-bottom:8px;"
        :style="{ border: config.isDefault ? '1px solid var(--accent)' : '1px solid var(--border)' }"
      >
        <div style="display:flex; gap:12px; align-items:flex-start;">
          <!-- 图标 -->
          <component
            :is="getProviderIcon(config.provider)"
            class="w-6 h-6 text-accent"
          />

          <!-- 信息 -->
          <div style="flex:1;">
            <div style="display:flex; align-items:center; gap:6px; margin-bottom:2px;">
              <span style="font-size:12px; font-weight:500;">{{ config.name }}</span>
              <span v-if="config.isDefault" class="badge badge-blue" style="font-size:8px;">{{ t('common.default') }}</span>
            </div>
            <div style="font-size:11px; color:var(--text-muted); font-family:var(--font-mono);">
              {{ config.url }}
            </div>
            <div style="display:flex; gap:6px; margin-top:6px; flex-wrap:wrap;">
              <span :class="`badge ${config.type === 'local' ? 'badge-green' : 'badge-yellow'}`" style="font-size:9px;">
                {{ config.type === 'local' ? t('settings.local') : t('settings.cloud') }}
              </span>
              <span :class="`badge ${getStatusBadge(config.status)}`" style="font-size:9px;">
                ● {{ getStatusText(config.status) }}
              </span>
              <span v-if="config.temperature" class="badge badge-gray" style="font-size:9px;">
                Temperature: {{ config.temperature }}
              </span>
              <span v-if="config.maxTokens" class="badge badge-gray" style="font-size:9px;">
                Max: {{ config.maxTokens }}
              </span>
            </div>
          </div>
        </div>

        <!-- 操作按钮 -->
        <div style="display:flex; gap:4px; margin-top:10px; padding-top:10px; border-top:1px solid var(--border);">
          <button class="btn btn-ghost btn-sm">
            <ArrowPathIcon class="w-3 h-3" />
            <span>{{ t('settings.testConnection') }}</span>
          </button>
          <button v-if="!config.isDefault" class="btn btn-ghost btn-sm" @click="settingsStore.setDefaultModel(config.id)">
            {{ t('settings.setDefault') }}
          </button>
          <button class="btn btn-ghost btn-sm">
            <PencilIcon class="w-3 h-3" />
            <span>{{ t('common.edit') }}</span>
          </button>
          <div style="flex:1;"></div>
          <button class="btn btn-ghost btn-sm" style="color:var(--error);">
            <TrashIcon class="w-3 h-3" />
            <span>{{ t('common.delete') }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 任务级模型绑定 -->
    <div class="divider"></div>
    <div style="margin-top:16px;">
      <h3 style="font-size:13px; font-weight:600; margin-bottom:12px;">{{ t('settings.taskModelBinding') }}</h3>
      <p class="text-muted" style="font-size:11px; margin-bottom:12px;">{{ t('settings.taskModelDesc') }}</p>
      <div style="display:flex; flex-direction:column; gap:8px;">
        <div
          v-for="(modelId, taskType) in settingsStore.taskBindings"
          :key="taskType"
          class="card"
          style="padding:10px;"
        >
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div>
              <div style="font-size:12px; font-weight:500;">
                {{ taskTypeLabels[taskType]?.name || taskType }}
              </div>
              <div class="text-muted" style="font-size:10px;">
                {{ taskTypeLabels[taskType]?.desc }}
              </div>
            </div>
            <select
              class="select"
              style="width:180px; padding:4px 8px; font-size:11px;"
              :value="modelId"
              @change="settingsStore.setTaskBinding(taskType, ($event.target as HTMLSelectElement).value)"
            >
              <option
                v-for="model in settingsStore.modelConfigs"
                :key="model.id"
                :value="model.id"
              >
                {{ model.name }}
              </option>
            </select>
          </div>
        </div>
      </div>
    </div>

    <!-- 隐私设置 -->
    <div class="divider"></div>
    <div style="margin-top:16px;">
      <h3 style="font-size:13px; font-weight:600; margin-bottom:12px;">{{ t('settings.privacySettings') }}</h3>
      <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 0;">
        <div>
          <div style="font-size:12px;">{{ t('settings.localOnly') }}</div>
          <div class="text-muted" style="font-size:10px;">{{ t('settings.localOnlyDesc') }}</div>
        </div>
        <label class="toggle">
          <input type="checkbox" v-model="settingsStore.localOnly">
          <span class="toggle-slider"></span>
        </label>
      </div>
      <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 0;">
        <div>
          <div style="font-size:12px;">{{ t('settings.anonymousData') }}</div>
          <div class="text-muted" style="font-size:10px;">{{ t('settings.anonymousDataDesc') }}</div>
        </div>
        <label class="toggle">
          <input type="checkbox" v-model="settingsStore.anonymousData">
          <span class="toggle-slider"></span>
        </label>
      </div>
    </div>
  </div>
</template>

<style scoped>
.model-config {
  max-width: 600px;
}
</style>
