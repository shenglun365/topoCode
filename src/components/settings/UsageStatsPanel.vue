<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { TrashIcon, ArrowPathIcon } from '@heroicons/vue/24/outline'
import { useModelConfigStore } from '@/stores/model-config-store'
import { useAgentUsageStore } from '@/stores/agent-usage-store'
import { useComponentId } from '@/composables/useComponentId'

const { t } = useI18n()
const modelConfigStore = useModelConfigStore()
const agentUsageStore = useAgentUsageStore()

function todayStr(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const usageDateRange = ref({ start: '', end: '' })
const selectedIds = ref<number[]>([])

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

async function initUsageStats() {
  const end = todayStr()
  const startDate = new Date()
  startDate.setDate(startDate.getDate() - 30)
  const start = `${startDate.getFullYear()}-${String(startDate.getMonth() + 1).padStart(2, '0')}-${String(startDate.getDate()).padStart(2, '0')}`
  usageDateRange.value = { start, end }
  await agentUsageStore.loadUsageStats(undefined, start, end)
}

function toggleSelectAll() {
  if (selectedIds.value.length === agentUsageStore.usageStats.length) {
    selectedIds.value = []
  } else {
    selectedIds.value = agentUsageStore.usageStats.map(s => s.id)
  }
}

async function handleDeleteUsageStat(id: number) {
  await agentUsageStore.deleteUsageStat(id)
}

async function handleDeleteUsageStatsBatch() {
  if (selectedIds.value.length === 0) return
  await agentUsageStore.deleteUsageStatsBatch(selectedIds.value)
  selectedIds.value = []
}

const showClearDialog = ref(false)
const clearModelId = ref('')
const clearStartDate = ref('')
const clearEndDate = ref('')
const { showId, componentId } = useComponentId('US-001')

function openClearDialog() {
  clearModelId.value = ''
  const now = new Date()
  const end = todayStr()
  const weekAgo = new Date(now)
  weekAgo.setDate(weekAgo.getDate() - 7)
  const start = `${weekAgo.getFullYear()}-${String(weekAgo.getMonth() + 1).padStart(2, '0')}-${String(weekAgo.getDate()).padStart(2, '0')}`
  clearStartDate.value = start
  clearEndDate.value = end
  showClearDialog.value = true
}

function setClearQuickRange(days: number | null) {
  const end = todayStr()
  clearEndDate.value = end
  if (days === null) {
    clearStartDate.value = ''
  } else {
    const d = new Date()
    d.setDate(d.getDate() - days)
    clearStartDate.value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  }
}

async function handleClearByCondition() {
  await agentUsageStore.deleteUsageStatsByCondition({
    modelId: clearModelId.value || undefined,
    startDate: clearStartDate.value || undefined,
    endDate: clearEndDate.value || undefined,
  })
  showClearDialog.value = false
}

async function refreshUsageStats() {
  await agentUsageStore.loadUsageStats(undefined, usageDateRange.value.start || undefined, usageDateRange.value.end || undefined)
}

onMounted(initUsageStats)
</script>

<template>
  <span v-if="showId" class="cmp-id">{{ componentId }}</span>
  <div class="card" style="display:flex; flex-direction:column; overflow:hidden;">
    <div style="padding:12px; display:flex; flex-direction:column; overflow:hidden;">
      <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px;">
        <h3 style="font-size:13px; font-weight:600;">
          {{ t('settings.usageStats') }}
          <span style="font-size:11px; color:var(--text-muted); font-weight:400;">({{ agentUsageStore.usageStats.length }})</span>
        </h3>
        <button
          class="btn btn-ghost btn-sm"
          style="color:var(--error);"
          @click="openClearDialog"
        >
          <span>{{ t('settings.clearUsageHistory') }}</span>
        </button>
      </div>

      <div style="display:flex; gap:8px; margin-bottom:12px; align-items:center; flex-wrap:wrap;">
        <input
          v-model="usageDateRange.start"
          type="date"
          class="field-input"
          style="width:140px;"
        >
        <span style="font-size:11px; color:var(--text-muted);">~</span>
        <input
          v-model="usageDateRange.end"
          type="date"
          class="field-input"
          style="width:140px;"
        >
        <button
          class="btn btn-ghost btn-sm"
          @click="refreshUsageStats"
        >
          <ArrowPathIcon class="w-3 h-3" />
        </button>
      </div>

      <div
        v-if="agentUsageStore.usageStats.length === 0"
        style="text-align:center; padding:24px; color:var(--text-muted); font-size:13px;"
      >
        {{ t('settings.noUsageData') }}
      </div>

      <div
        v-else
        style="overflow:auto; flex:1; min-height:0;"
      >
        <table style="width:100%; border-collapse:collapse; font-size:12px;">
          <thead>
            <tr style="border-bottom:1px solid var(--border);">
              <th style="padding:6px 8px; text-align:left; width:32px;">
                <input
                  type="checkbox"
                  :checked="selectedIds.length === agentUsageStore.usageStats.length"
                  :indeterminate="selectedIds.length > 0 && selectedIds.length < agentUsageStore.usageStats.length"
                  @change="toggleSelectAll"
                >
              </th>
              <th style="padding:6px 8px; text-align:left;">
                {{ t('settings.dateRange') }}
              </th>
              <th style="padding:6px 8px; text-align:left;">
                {{ t('settings.modelName') }}
              </th>
              <th style="padding:6px 8px; text-align:right;">
                {{ t('settings.requests') }}
              </th>
              <th style="padding:6px 8px; text-align:right;">
                {{ t('settings.promptTokens') }}
              </th>
              <th style="padding:6px 8px; text-align:right;">
                {{ t('settings.completionTokens') }}
              </th>
              <th style="padding:6px 8px; text-align:right;">
                {{ t('settings.totalTokens') }}
              </th>
              <th style="padding:6px 8px; text-align:center; width:60px;">
                {{ t('common.delete') }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="stat in agentUsageStore.usageStats"
              :key="stat.id"
              style="border-bottom:1px solid var(--border);"
              :style="{ background: selectedIds.includes(stat.id) ? 'var(--bg-hover)' : '' }"
            >
              <td style="padding:6px 8px;">
                <input
                  type="checkbox"
                  :checked="selectedIds.includes(stat.id)"
                  @change="(e: any) => { if (e.target.checked) selectedIds.push(stat.id); else selectedIds = selectedIds.filter(id => id !== stat.id) }"
                >
              </td>
              <td style="padding:6px 8px;">
                {{ stat.date }}
              </td>
              <td style="padding:6px 8px;">
                {{ stat.modelName }}
              </td>
              <td style="padding:6px 8px; text-align:right; font-family:var(--font-mono);">
                {{ fmt(stat.requestCount) }}
              </td>
              <td style="padding:6px 8px; text-align:right; font-family:var(--font-mono);">
                {{ fmt(stat.promptTokens) }}
              </td>
              <td style="padding:6px 8px; text-align:right; font-family:var(--font-mono);">
                {{ fmt(stat.completionTokens) }}
              </td>
              <td style="padding:6px 8px; text-align:right; font-family:var(--font-mono);">
                {{ fmt(stat.totalTokens) }}
              </td>
              <td style="padding:6px 8px; text-align:center;">
                <button
                  class="btn btn-ghost btn-sm"
                  style="color:var(--error); padding:2px 6px;"
                  @click="handleDeleteUsageStat(stat.id)"
                >
                  <TrashIcon class="w-3 h-3" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>

        <div
          v-if="selectedIds.length > 0"
          style="margin-top:8px; display:flex; gap:8px; align-items:center;"
        >
          <span style="font-size:11px; color:var(--text-muted);">{{ t('project.selected') }}: {{ selectedIds.length }}</span>
          <button
            class="btn btn-primary btn-sm"
            style="background:var(--error);border-color:var(--error);"
            @click="handleDeleteUsageStatsBatch"
          >
            <TrashIcon class="w-3 h-3" />
            <span>{{ t('common.delete') }} ({{ selectedIds.length }})</span>
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- 清除历史弹窗 -->
  <div
    v-if="showClearDialog"
    class="dialog-overlay"
    @click.self="showClearDialog = false"
  >
    <div
      class="dialog"
      style="width:400px;"
    >
      <div class="dialog-header">
        <h3>{{ t('settings.clearUsageHistory') }}</h3>
        <button
          class="btn btn-ghost btn-sm"
          @click="showClearDialog = false"
        >
          &times;
        </button>
      </div>
      <div class="dialog-body">
        <div style="margin-bottom:12px;">
          <label style="font-size:12px; font-weight:500; margin-bottom:4px; display:block;">{{ t('settings.modelName') }}</label>
          <select
            v-model="clearModelId"
            class="field-input"
            style="width:100%;"
          >
            <option value="">
              {{ t('common.all') }}
            </option>
            <option
              v-for="m in modelConfigStore.models"
              :key="m.id"
              :value="m.id"
            >
              {{ m.name }}
            </option>
          </select>
        </div>
        <div style="display:flex; gap:8px; margin-bottom:12px; align-items:center;">
          <div>
            <label style="font-size:12px; font-weight:500; margin-bottom:4px; display:block;">{{ t('common.startDate') }}</label>
            <input
              v-model="clearStartDate"
              type="date"
              class="field-input"
              style="width:150px;"
            >
          </div>
          <span style="margin-top:20px; font-size:11px; color:var(--text-muted);">~</span>
          <div>
            <label style="font-size:12px; font-weight:500; margin-bottom:4px; display:block;">{{ t('common.endDate') }}</label>
            <input
              v-model="clearEndDate"
              type="date"
              class="field-input"
              style="width:150px;"
            >
          </div>
        </div>
        <div style="display:flex; gap:4px; margin-bottom:12px; flex-wrap:wrap;">
          <button
            class="btn btn-ghost btn-xs"
            @click="setClearQuickRange(7)"
          >
            {{ t('common.last7Days') }}
          </button>
          <button
            class="btn btn-ghost btn-xs"
            @click="setClearQuickRange(30)"
          >
            {{ t('common.last30Days') }}
          </button>
          <button
            class="btn btn-ghost btn-xs"
            @click="setClearQuickRange(null)"
          >
            {{ t('common.all') }}
          </button>
        </div>
      </div>
      <div class="dialog-footer">
        <button
          class="btn btn-ghost"
          @click="showClearDialog = false"
        >
          {{ t('common.cancel') }}
        </button>
        <button
          class="btn btn-primary"
          style="background:var(--error);border-color:var(--error);"
          @click="handleClearByCondition"
        >
          <TrashIcon class="w-3 h-3" />
          <span>{{ t('common.confirm') }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.field-input {
  width: 100%;
  height: 36px;
  padding: 0 12px;
  font-size: 13px;
  font-family: var(--font-mono, 'SF Mono', 'Cascadia Code', monospace);
  color: var(--text-primary);
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 6px;
  outline: none;
  transition: all 0.2s ease;
}
.field-input::placeholder {
  color: var(--text-muted);
  font-style: italic;
}
.field-input:hover {
  border-color: var(--accent);
  background: var(--bg-hover);
}
.field-input:focus {
  border-color: var(--accent);
  background: var(--bg-primary);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15);
}
select.field-input {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
  padding-right: 32px;
}
</style>
