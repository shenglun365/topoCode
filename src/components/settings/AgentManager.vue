<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import {
  CpuChipIcon,
  PlusIcon,
  Cog6ToothIcon,
  ArrowPathIcon,
  PencilIcon,
  TrashIcon,
} from '@heroicons/vue/24/outline'
import { useSettingsStore } from '@/stores/settings'

const { t } = useI18n()
const settingsStore = useSettingsStore()

function getStatusBadge(status: string): string {
  switch (status) {
    case 'online': return 'badge-green'
    case 'offline': return 'badge-red'
    case 'not-detected': return 'badge-gray'
    case 'not-configured': return 'badge-red'
    default: return 'badge-gray'
  }
}

function getStatusText(status: string): string {
  switch (status) {
    case 'online': return `● ${t('settings.online')}`
    case 'offline': return `● ${t('settings.offline')}`
    case 'not-detected': return `○ ${t('settings.notDetected')}`
    case 'not-configured': return `○ ${t('settings.notConfigured')}`
    default: return ''
  }
}

async function detectAgent(id: string) {
  await settingsStore.detectAgent(id)
}

async function setDefaultAgent(id: string) {
  await settingsStore.updateAgent({ id })
}

async function removeAgent(id: string) {
  if (confirm(t('settings.confirmDeleteAgent'))) {
    await settingsStore.removeAgent(id)
  }
}
</script>

<template>
  <div class="agent-manager">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
      <div>
        <h2 style="font-size:16px; font-weight:600; margin-bottom:2px;">{{ t('settings.agentManagement') }}</h2>
        <p class="text-muted" style="font-size:12px;">{{ t('settings.agentDesc') }}</p>
      </div>
      <button class="btn btn-primary btn-sm">
        <PlusIcon class="w-4 h-4" />
        <span>{{ t('settings.addAgent') }}</span>
      </button>
    </div>

    <!-- Agent 列表 -->
    <div
      v-for="agent in settingsStore.agents"
      :key="agent.id"
      class="card"
      style="padding:14px; margin-bottom:10px;"
      :style="{ border: agent.isDefault ? '1px solid var(--accent)' : '1px solid var(--border)' }"
    >
      <!-- 默认徽章 -->
      <div v-if="agent.isDefault" style="position:absolute; top:10px; right:10px; display:flex; gap:4px;">
        <span class="badge badge-blue">{{ t('common.default') }}</span>
        <button class="btn btn-ghost btn-sm" style="padding:2px 6px;">
          <Cog6ToothIcon class="w-3 h-3" />
        </button>
      </div>

      <div style="display:flex; gap:12px; align-items:flex-start;">
        <!-- 图标 -->
        <CpuChipIcon class="w-6 h-6 text-accent" />

        <!-- 信息 -->
        <div style="flex:1;">
          <div style="font-size:13px; font-weight:500; margin-bottom:2px;">{{ agent.name }}</div>
          <div style="font-size:11px; color:var(--text-muted); font-family:var(--font-mono); margin-bottom:6px;">
            {{ agent.path || t('settings.toBeConfigured') }}
          </div>
          <div v-if="agent.args" style="font-size:11px; color:var(--text-muted); margin-bottom:6px;">
            {{ t('settings.args') }}: <code style="background:var(--bg-tertiary); padding:1px 4px; border-radius:3px; font-size:10px;">{{ agent.args }}</code>
          </div>
          <div style="display:flex; gap:6px; align-items:center;">
            <span :class="`badge ${getStatusBadge(agent.status)}`" style="font-size:9px;">
              {{ getStatusText(agent.status) }}
            </span>
            <span v-if="agent.version" style="font-size:10px; color:var(--text-muted);">{{ agent.version }}</span>
          </div>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div style="display:flex; gap:4px; margin-top:10px; padding-top:10px; border-top:1px solid var(--border);">
        <button
          v-if="agent.status !== 'not-configured'"
          class="btn btn-ghost btn-sm"
          @click="detectAgent(agent.id)"
        >
          <ArrowPathIcon class="w-3 h-3" />
          <span>{{ t('settings.testConnection') }}</span>
        </button>
        <button v-if="!agent.isDefault" class="btn btn-ghost btn-sm" @click="setDefaultAgent(agent.id)">
          {{ t('settings.setDefault') }}
        </button>
        <button class="btn btn-ghost btn-sm">
          <PencilIcon class="w-3 h-3" />
          <span>{{ t('common.edit') }}</span>
        </button>
        <div style="flex:1;"></div>
        <button
          class="btn btn-ghost btn-sm"
          style="color:var(--error);"
          @click="removeAgent(agent.id)"
        >
          <TrashIcon class="w-3 h-3" />
          <span>{{ t('common.delete') }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-manager {
  max-width: 600px;
}
</style>
