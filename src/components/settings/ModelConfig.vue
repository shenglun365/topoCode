<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  CpuChipIcon,
  GlobeAltIcon,
  ComputerDesktopIcon,
  PlusIcon,
  PencilIcon,
  TrashIcon,
  ArrowPathIcon,
  CheckCircleIcon,
  XCircleIcon,
  AdjustmentsHorizontalIcon,
  ChevronDownIcon,
  ChevronUpIcon,
} from '@heroicons/vue/24/outline'
import { useSettingsStore } from '@/stores/settings'
import type { ModelConfigItem } from '@/types/ipc'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('ST-001')
const { t } = useI18n()
const settingsStore = useSettingsStore()

// ==================== 对话框状态 ====================
const showDialog = ref(false)
const editMode = ref(false)
const editingId = ref<string | null>(null)
const newModelId = ref<string | null>(null)
const testingId = ref<string | null>(null)
const dialogTesting = ref(false)
const dialogTestResult = ref<'success' | 'error' | null>(null)

const showDeleteConfirm = ref(false)
const deleteTargetId = ref('')
const showTestResult = ref(false)
const testResultMessage = ref('')
const testResultType = ref<'success' | 'error'>('success')
const showValidationAlert = ref(false)
const validationMessage = ref('')

const form = ref({
  name: '',
  provider: 'ollama' as ModelConfigItem['provider'],
  model: '',
  url: '',
  type: 'local' as 'local' | 'cloud',
  temperature: 0.7,
  maxTokens: 4096,
  isDefault: false,
  apiKey: '',
})

// ==================== 用量统计状态 ====================
const showUsageLimitDialog = ref(false)
const editLimitModelId = ref('')
const usageLimitForm = ref({ maxRequestsPerDay: 0, maxTokensPerDay: 0 })

const showStatsPanel = ref(false)
const usageDateRange = ref({ start: '', end: '' })
const selectedIds = ref<number[]>([])
const showClearDialog = ref(false)
const clearModelId = ref('')
const clearStartDate = ref('')
const clearEndDate = ref('')

function todayStr(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function todayUsageForModel(modelId: string) {
  const today = todayStr()
  return settingsStore.usageStats.find(s => s.modelId === modelId && s.date === today)
}

function openUsageLimitDialog(config: ModelConfigItem) {
  editLimitModelId.value = config.id
  usageLimitForm.value = {
    maxRequestsPerDay: config.maxRequestsPerDay ?? 0,
    maxTokensPerDay: config.maxTokensPerDay ?? 0,
  }
  showUsageLimitDialog.value = true
}

async function saveUsageLimit() {
  await settingsStore.updateModel({
    id: editLimitModelId.value,
    maxRequestsPerDay: usageLimitForm.value.maxRequestsPerDay,
    maxTokensPerDay: usageLimitForm.value.maxTokensPerDay,
  })
  showUsageLimitDialog.value = false
}

async function initUsageStats() {
  const end = todayStr()
  const startDate = new Date()
  startDate.setDate(startDate.getDate() - 30)
  const start = `${startDate.getFullYear()}-${String(startDate.getMonth() + 1).padStart(2, '0')}-${String(startDate.getDate()).padStart(2, '0')}`
  usageDateRange.value = { start, end }
  await settingsStore.loadUsageStats(undefined, start, end)
}

function toggleSelectAll() {
  if (selectedIds.value.length === settingsStore.usageStats.length) {
    selectedIds.value = []
  } else {
    selectedIds.value = settingsStore.usageStats.map(s => s.id)
  }
}

async function handleDeleteUsageStat(id: number) {
  await settingsStore.deleteUsageStat(id)
}

async function handleDeleteUsageStatsBatch() {
  if (selectedIds.value.length === 0) return
  await settingsStore.deleteUsageStatsBatch(selectedIds.value)
  selectedIds.value = []
}

function openClearDialog() {
  clearModelId.value = ''
  const now = new Date()
  const end = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  const weekAgo = new Date(now)
  weekAgo.setDate(weekAgo.getDate() - 7)
  const start = `${weekAgo.getFullYear()}-${String(weekAgo.getMonth() + 1).padStart(2, '0')}-${String(weekAgo.getDate()).padStart(2, '0')}`
  clearStartDate.value = start
  clearEndDate.value = end
  showClearDialog.value = true
}

function setClearQuickRange(days: number | null) {
  const now = new Date()
  const end = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  clearEndDate.value = end
  if (days === null) {
    clearStartDate.value = ''
  } else {
    const d = new Date(now)
    d.setDate(d.getDate() - days)
    clearStartDate.value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  }
}

async function handleClearByCondition() {
  await settingsStore.deleteUsageStatsByCondition({
    modelId: clearModelId.value || undefined,
    startDate: clearStartDate.value || undefined,
    endDate: clearEndDate.value || undefined,
  })
  showClearDialog.value = false
}

async function refreshUsageStats() {
  await settingsStore.loadUsageStats(undefined, usageDateRange.value.start || undefined, usageDateRange.value.end || undefined)
}

// ==================== 计算属性 ====================
const defaultModel = computed(() => settingsStore.models.find(m => m.isDefault) || null)

// ==================== 工具函数 ====================
function getProviderIcon(provider: string): any {
  switch (provider) {
    case 'ollama': return ComputerDesktopIcon
    case 'openai': return GlobeAltIcon
    case 'lm-studio': return ComputerDesktopIcon
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

function fmt(n: number | undefined | null): string {
  if (n == null) return ''
  return n.toLocaleString()
}

function getStatusText(status: string): string {
  switch (status) {
    case 'connected': return t('settings.connected')
    case 'offline': return t('settings.offline')
    case 'error': return t('common.error')
    default: return ''
  }
}

// ==================== 对话框操作 ====================
function openAddDialog() {
  editMode.value = false
  editingId.value = null
  dialogTestResult.value = null
  form.value = {
    name: '',
    provider: 'ollama',
    model: '',
    url: '',
    type: 'local',
    temperature: 0.7,
    maxTokens: 4096,
    isDefault: settingsStore.models.length === 0,
    apiKey: '',
  }
  showDialog.value = true
}

function openEditDialog(config: ModelConfigItem) {
  editMode.value = true
  editingId.value = config.id
  dialogTestResult.value = null
  form.value = {
    name: config.name,
    provider: config.provider,
    model: config.model,
    url: config.url,
    type: config.type,
    temperature: config.temperature ?? 0.7,
    maxTokens: config.maxTokens ?? 4096,
    isDefault: config.isDefault,
    apiKey: config.apiKey || '',
  }
  showDialog.value = true
}

async function saveModel() {
  if (!form.value.name || !form.value.model || !form.value.url) {
    validationMessage.value = t('settings.fillRequired')
    showValidationAlert.value = true
    return
  }

  if (editMode.value && editingId.value) {
    await settingsStore.updateModel({
      id: editingId.value,
      name: form.value.name,
      provider: form.value.provider,
      model: form.value.model,
      url: form.value.url,
      temperature: form.value.temperature,
      maxTokens: form.value.maxTokens,
      isDefault: form.value.isDefault,
      apiKey: form.value.apiKey || undefined,
    })
  } else {
    const addParams: {
      name: string
      provider: string
      model: string
      url: string
      type: string
      temperature?: number
      maxTokens?: number
      apiKey?: string
      isDefault?: boolean
    } = {
      name: form.value.name,
      provider: form.value.provider,
      model: form.value.model,
      url: form.value.url,
      type: form.value.type,
    }
    if (form.value.temperature != null) addParams.temperature = form.value.temperature
    if (form.value.maxTokens != null) addParams.maxTokens = form.value.maxTokens
    if (form.value.apiKey) addParams.apiKey = form.value.apiKey
    if (form.value.isDefault) addParams.isDefault = true

    await settingsStore.addModel(addParams)
  }

  showDialog.value = false
}

async function removeModel(id: string) {
  deleteTargetId.value = id
  showDeleteConfirm.value = true
}

async function confirmDelete() {
  await settingsStore.removeModel(deleteTargetId.value)
  showDeleteConfirm.value = false
  deleteTargetId.value = ''
}

async function testModel(id: string) {
  testingId.value = id
  try {
    const result = await settingsStore.testModel(id)
    if (result.status === 'connected') {
      testResultType.value = 'success'
      testResultMessage.value = `${t('settings.connected')} - ${t('settings.latency')} ${result.latency}ms`
    } else {
      testResultType.value = 'error'
      testResultMessage.value = `${t('settings.testFailed')}: ${result.error || 'Unknown error'}`
    }
  } catch (err: any) {
    testResultType.value = 'error'
    testResultMessage.value = `${t('settings.testFailed')}: ${err.message}`
  } finally {
    testingId.value = null
    showTestResult.value = true
  }
}

async function setDefaultModel(id: string) {
  await settingsStore.updateModel({ id, isDefault: true })
}

// ==================== 弹窗内测试 ====================
async function testCurrentForm() {
  if (!form.value.url || !form.value.model) {
    dialogTestResult.value = 'error'
    return
  }

  dialogTesting.value = true
  dialogTestResult.value = null

  try {
    // v2: 先暂存配置到 DB，然后通过后端 API 测试连接
    // 如果是编辑已有模型，直接用其 ID；否则先保存再测试
    if (editingId.value) {
      const result = await window.api.settings.testModel(editingId.value)
      dialogTestResult.value = result.status === 'connected' ? 'success' : 'error'
    } else {
      // 新建场景：先保存再测试
      const saved = await window.api.settings.addModel({
        name: form.value.name || form.value.model,
        provider: form.value.provider,
        model: form.value.model,
        url: form.value.url,
        type: form.value.type || 'chat',
        temperature: form.value.temperature,
        maxTokens: form.value.maxTokens,
      })
      const result = await window.api.settings.testModel(saved.id)
      dialogTestResult.value = result.status === 'connected' ? 'success' : 'error'
      // 清理临时记录（用户可以选择正式保存）
      newModelId.value = saved.id
    }
  } catch {
    dialogTestResult.value = 'error'
  } finally {
    dialogTesting.value = false
  }
}

//  provider 切换时自动填充 URL
function onProviderChange(provider: string) {
  switch (provider) {
    case 'ollama':
      form.value.url = 'http://localhost:11434'
      form.value.type = 'local'
      break
    case 'openai':
      form.value.url = 'https://api.openai.com'
      form.value.type = 'cloud'
      break
    case 'lm-studio':
      form.value.url = 'http://localhost:1234'
      form.value.type = 'local'
      break
    case 'custom':
      form.value.type = 'cloud'
      break
  }
}

// 初始化用量统计
initUsageStats()
</script>

<template>
  <div class="model-config">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <h2 style="font-size:16px; font-weight:600; margin-bottom:4px;">
      {{ t('settings.aiModelConfig') }}
    </h2>
    <p
      class="text-muted"
      style="font-size:12px; margin-bottom:20px;"
    >
      {{ t('settings.aiModelDesc') }}
    </p>

    <div style="display:flex; gap:24px; align-items:stretch;">
      <div style="flex:1; min-width:0;">
        <!-- 当前使用 -->
        <div
          class="card"
          style="margin-bottom:16px; border-left:3px solid var(--accent);"
        >
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div>
              <div style="font-size:11px; color:var(--text-muted); margin-bottom:2px;">
                {{ t('settings.currentlyUsing') }}
              </div>
              <div style="font-size:14px; font-weight:600;">
                {{ defaultModel?.name || t('settings.notConfigured') }}
              </div>
              <div
                class="text-muted"
                style="font-size:11px;"
              >
                {{ defaultModel?.url }}
              </div>
            </div>
            <div
              v-if="defaultModel"
              style="display:flex; align-items:center; gap:8px;"
            >
              <span
                :class="`badge ${getStatusBadge(defaultModel.status)}`"
              >● {{ getStatusText(defaultModel.status) }}</span>
              <span
                v-if="defaultModel.latency"
                style="font-size:10px; color:var(--text-muted);"
              >
                {{ t('settings.latency') }} {{ fmt(defaultModel.latency) }}ms
              </span>
            </div>
          </div>
        </div>

        <!-- 配置列表 -->
        <div style="margin-bottom:16px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <h3 style="font-size:13px; font-weight:600;">
              {{ t('settings.savedConfigs') }}
            </h3>
            <button
              class="btn btn-primary btn-sm"
              @click="openAddDialog"
            >
              <PlusIcon class="w-4 h-4" />
              <span>{{ t('settings.addConfig') }}</span>
            </button>
          </div>

          <!-- 空状态 -->
          <div
            v-if="settingsStore.models.length === 0"
            style="text-align:center; padding:40px 20px; color:var(--text-muted);"
          >
            <p>{{ t('settings.noModelsYet') }}</p>
            <p style="font-size:12px;">
              {{ t('settings.addFirstModel') }}
            </p>
          </div>

          <!-- 配置项 -->
          <div
            v-for="config in settingsStore.models"
            :key="config.id"
            class="card"
            style="padding:12px; margin-bottom:8px; position:relative;"
            :style="{ border: config.isDefault ? '1px solid var(--accent)' : '1px solid var(--border)' }"
          >
        <div
          v-if="config.isDefault"
          class="default-badge"
        >
          {{ t('common.default') }}
        </div>
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
            </div>
            <div style="font-size:11px; color:var(--text-muted); font-family:var(--font-mono);">
              {{ config.url }} / {{ config.model }}
            </div>
            <div style="display:flex; gap:6px; margin-top:6px; flex-wrap:wrap;">
              <span
                :class="`badge ${config.type === 'local' ? 'badge-green' : 'badge-yellow'}`"
                style="font-size:9px;"
              >
                {{ config.type === 'local' ? t('settings.local') : t('settings.cloud') }}
              </span>
              <span
                v-if="config.temperature !== undefined"
                class="badge badge-gray"
                style="font-size:9px;"
              >
                {{ t('settings.modelTemperature') }}: {{ fmt(config.temperature) }}
              </span>
              <span
                v-if="config.maxTokens !== undefined"
                class="badge badge-gray"
                style="font-size:9px;"
              >
                {{ t('settings.modelMaxTokens') }}: {{ fmt(config.maxTokens) }}
              </span>
            </div>
          </div>
        </div>

        <!-- 操作按钮 -->
        <div style="display:flex; gap:4px; margin-top:10px; padding-top:10px; border-top:1px solid var(--border);">
          <button
            class="btn btn-ghost btn-sm"
            :disabled="testingId === config.id"
            @click="testModel(config.id)"
          >
            <ArrowPathIcon
              class="w-3 h-3"
              :class="{ 'animate-spin': testingId === config.id }"
            />
            <span>{{ testingId === config.id ? t('settings.testing') : t('settings.testConnection') }}</span>
          </button>
          <button
            v-if="!config.isDefault"
            class="btn btn-ghost btn-sm"
            @click="setDefaultModel(config.id)"
          >
            {{ t('settings.setDefault') }}
          </button>
          <button
            class="btn btn-ghost btn-sm"
            @click="openEditDialog(config)"
          >
            <PencilIcon class="w-3 h-3" />
            <span>{{ t('common.edit') }}</span>
          </button>
          <button
            class="btn btn-ghost btn-sm"
            @click="openUsageLimitDialog(config)"
          >
            <AdjustmentsHorizontalIcon class="w-3 h-3" />
            <span>{{ t('settings.usageLimit') }}</span>
          </button>
          <div style="flex:1;" />
          <button
            class="btn btn-ghost btn-sm"
            style="color:var(--error);"
            @click="removeModel(config.id)"
          >
            <TrashIcon class="w-3 h-3" />
            <span>{{ t('common.delete') }}</span>
          </button>
        </div>
        <!-- 今日用量概览 -->
        <div
          v-if="todayUsageForModel(config.id)"
          style="margin-top:8px; padding-top:8px; border-top:1px solid var(--border); font-size:11px; color:var(--text-muted); display:flex; gap:12px;"
        >
          <span>{{ t('settings.todayUsage') }}:</span>
          <span>{{ t('settings.requests') }} {{ fmt(todayUsageForModel(config.id)?.requestCount) }}{{ config.maxRequestsPerDay ? ' / ' + fmt(config.maxRequestsPerDay) : '' }}</span>
          <span>Token {{ fmt(todayUsageForModel(config.id)?.totalTokens) }}{{ config.maxTokensPerDay ? ' / ' + fmt(config.maxTokensPerDay) : '' }}</span>
        </div>
      </div>
    </div>
  </div>

  <!-- ==================== 模型用量统计面板（右侧）==================== -->
  <div style="flex:1; min-width:0;">
    <div
      class="card"
      style="margin-bottom:16px;"
    >
      <div style="padding:12px;">
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px;">
          <h3 style="font-size:13px; font-weight:600;">
            {{ t('settings.usageStats') }}
            <span style="font-size:11px; color:var(--text-muted); font-weight:400;">({{ settingsStore.usageStats.length }})</span>
          </h3>
          <button
            class="btn btn-ghost btn-sm"
            style="color:var(--error);"
            @click="openClearDialog"
          >
            <span>{{ t('settings.clearUsageHistory') }}</span>
          </button>
        </div>
        <!-- 工具栏 -->
        <div style="display:flex; gap:8px; margin-bottom:12px; align-items:center; flex-wrap:wrap;">
          <input
            v-model="usageDateRange.start"
            type="date"
            class="field-input"
            style="width:140px;"
          />
          <span style="font-size:11px; color:var(--text-muted);">~</span>
          <input
            v-model="usageDateRange.end"
            type="date"
            class="field-input"
            style="width:140px;"
          />
          <button
            class="btn btn-ghost btn-sm"
            @click="refreshUsageStats"
          >
            <ArrowPathIcon class="w-3 h-3" />
          </button>
        </div>

        <!-- 空状态 -->
        <div
          v-if="settingsStore.usageStats.length === 0"
          style="text-align:center; padding:24px; color:var(--text-muted); font-size:13px;"
        >
          {{ t('settings.noUsageData') }}
        </div>

        <!-- 表格 -->
        <div
          v-else
          style="overflow-x:auto;"
        >
          <table style="width:100%; border-collapse:collapse; font-size:12px;">
            <thead>
              <tr style="border-bottom:1px solid var(--border);">
                <th style="padding:6px 8px; text-align:left; width:32px;">
                  <input
                    type="checkbox"
                    :checked="selectedIds.length === settingsStore.usageStats.length"
                    :indeterminate="selectedIds.length > 0 && selectedIds.length < settingsStore.usageStats.length"
                    @change="toggleSelectAll"
                  />
                </th>
                <th style="padding:6px 8px; text-align:left;">{{ t('settings.dateRange') }}</th>
                <th style="padding:6px 8px; text-align:left;">{{ t('settings.modelName') }}</th>
                <th style="padding:6px 8px; text-align:right;">{{ t('settings.requests') }}</th>
                <th style="padding:6px 8px; text-align:right;">{{ t('settings.promptTokens') }}</th>
                <th style="padding:6px 8px; text-align:right;">{{ t('settings.completionTokens') }}</th>
                <th style="padding:6px 8px; text-align:right;">{{ t('settings.totalTokens') }}</th>
                <th style="padding:6px 8px; text-align:center; width:60px;">{{ t('common.delete') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="stat in settingsStore.usageStats"
                :key="stat.id"
                style="border-bottom:1px solid var(--border);"
                :style="{ background: selectedIds.includes(stat.id) ? 'var(--bg-hover)' : '' }"
              >
                <td style="padding:6px 8px;">
                  <input
                    type="checkbox"
                    :checked="selectedIds.includes(stat.id)"
                    @change="(e: any) => { if (e.target.checked) selectedIds.push(stat.id); else selectedIds = selectedIds.filter(id => id !== stat.id) }"
                  />
                </td>
                <td style="padding:6px 8px;">{{ stat.date }}</td>
                <td style="padding:6px 8px;">{{ stat.modelName }}</td>
                <td style="padding:6px 8px; text-align:right; font-family:var(--font-mono);">{{ fmt(stat.requestCount) }}</td>
                <td style="padding:6px 8px; text-align:right; font-family:var(--font-mono);">{{ fmt(stat.promptTokens) }}</td>
                <td style="padding:6px 8px; text-align:right; font-family:var(--font-mono);">{{ fmt(stat.completionTokens) }}</td>
                <td style="padding:6px 8px; text-align:right; font-family:var(--font-mono);">{{ fmt(stat.totalTokens) }}</td>
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

          <!-- 批量删除 -->
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
    </div>
  </div>

  <!-- ==================== 用量限制编辑对话框 ==================== -->
  <Teleport to="body">
    <div v-if="showUsageLimitDialog" class="modal-overlay" @click.self="showUsageLimitDialog = false">
      <div class="modal" style="width:420px;">
        <div class="modal-header">
          <h3>{{ t('settings.editUsageLimit') }}</h3>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <div class="form-field">
              <label class="field-label">{{ t('settings.dailyRequests') }}</label>
              <input
                v-model.number="usageLimitForm.maxRequestsPerDay"
                type="number"
                min="0"
                class="field-input"
                placeholder="0 = unlimited"
              />
            </div>
            <div class="form-field">
              <label class="field-label">{{ t('settings.dailyTokens') }}</label>
              <input
                v-model.number="usageLimitForm.maxTokensPerDay"
                type="number"
                min="0"
                class="field-input"
                placeholder="0 = unlimited"
              />
            </div>
          </div>
          <p style="font-size:11px; color:var(--text-muted); margin-top:12px;">{{ t('settings.zeroMeansUnlimited') }}</p>
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost" @click="showUsageLimitDialog = false">{{ t('common.cancel') }}</button>
          <button class="btn btn-primary" @click="saveUsageLimit">{{ t('common.save') }}</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- ==================== 按条件清除对话框 ==================== -->
  <Teleport to="body">
    <div v-if="showClearDialog" class="modal-overlay" @click.self="showClearDialog = false">
      <div class="modal" style="width:420px;">
        <div class="modal-header">
          <h3>{{ t('settings.deleteUsageByCondition') }}</h3>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <div class="form-field">
              <label class="field-label">{{ t('settings.selectModel') }}</label>
              <select v-model="clearModelId" class="field-input">
                <option value="">{{ t('settings.allModels') }}</option>
                <option
                  v-for="m in settingsStore.models"
                  :key="m.id"
                  :value="m.id"
                >{{ m.name }}</option>
              </select>
            </div>
            <div class="form-field">
              <label class="field-label">{{ t('settings.dateRange') }} ({{ t('common.optional') }})</label>
              <div style="display:flex; gap:8px; align-items:center;">
                <input
                  v-model="clearStartDate"
                  type="date"
                  class="field-input"
                  style="flex:1;"
                />
                <span style="font-size:11px; color:var(--text-muted);">~</span>
                <input
                  v-model="clearEndDate"
                  type="date"
                  class="field-input"
                  style="flex:1;"
                />
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost" @click="showClearDialog = false">{{ t('common.cancel') }}</button>
          <button class="btn btn-primary" style="background:var(--error);border-color:var(--error);" @click="handleClearByCondition">{{ t('common.delete') }}</button>
          <div style="flex:1;" />
          <button class="btn btn-ghost btn-sm" @click="setClearQuickRange(3)">{{ t('settings.lastThreeDays') }}</button>
          <button class="btn btn-ghost btn-sm" @click="setClearQuickRange(7)">{{ t('settings.lastWeek') }}</button>
          <button class="btn btn-ghost btn-sm" @click="setClearQuickRange(null)">{{ t('settings.allHistory') }}</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- 添加/编辑对话框 -->
  <div
    v-if="showDialog"
    class="modal-overlay"
  >
    <div class="modal">
      <div class="modal-header">
        <h3>{{ editMode ? `${t('common.edit')} - ${form.name}` : t('settings.addConfig') }}</h3>
      </div>
      <div class="modal-body">
        <div class="form-grid">
          <div class="form-field">
            <label class="field-label">{{ t('settings.modelName') }}</label>
            <input
              v-model="form.name"
              class="field-input"
              :placeholder="t('settings.modelName')"
            >
          </div>

          <div class="form-field">
            <label class="field-label">{{ t('settings.provider') }}</label>
            <select
              v-model="form.provider"
              class="field-input"
              @change="onProviderChange((($event.target) as HTMLSelectElement).value)"
            >
              <option value="ollama">
                Ollama
              </option>
              <option value="openai">
                OpenAI
              </option>
              <option value="lm-studio">
                LM-Studio
              </option>
              <option value="custom">
                Custom
              </option>
            </select>
          </div>

          <div class="form-field">
            <label class="field-label">{{ t('settings.model') }}</label>
            <input
              v-model="form.model"
              class="field-input"
              placeholder="qwen2.5-coder:7b"
            >
          </div>

          <div class="form-field">
            <label class="field-label">{{ t('settings.baseUrl') }}</label>
            <input
              v-model="form.url"
              class="field-input"
              placeholder="http://localhost:11434"
            >
          </div>

          <div
            v-if="form.provider === 'openai' || form.provider === 'custom'"
            class="form-field"
          >
            <label class="field-label">{{ t('settings.apiKey') }}</label>
            <input
              v-model="form.apiKey"
              class="field-input"
              type="password"
              :placeholder="t('settings.apiKeyPlaceholder')"
            >
          </div>

          <div class="form-field">
            <label class="field-label">{{ t('settings.modelTemperature') }}</label>
            <input
              v-model.number="form.temperature"
              type="number"
              step="0.1"
              min="0"
              max="2"
              class="field-input"
            >
          </div>

          <div class="form-field">
            <label class="field-label">{{ t('settings.modelMaxTokens') }}</label>
            <input
              v-model.number="form.maxTokens"
              type="number"
              step="256"
              min="256"
              class="field-input"
            >
          </div>

          <div
            v-if="!editMode"
            class="form-field"
          >
            <label class="field-label">{{ t('settings.type') }}</label>
            <select
              v-model="form.type"
              class="field-input"
            >
              <option value="local">
                {{ t('settings.local') }}
              </option>
              <option value="cloud">
                {{ t('settings.cloud') }}
              </option>
            </select>
          </div>

          <div
            v-if="!editMode"
            class="form-field form-field-toggle"
          >
            <label class="field-label">{{ t('settings.setDefault') }}</label>
            <label class="toggle">
              <input
                v-model="form.isDefault"
                type="checkbox"
              >
              <span class="toggle-slider" />
            </label>
          </div>
        </div>

        <!-- 测试结果 -->
        <div
          v-if="dialogTestResult"
          class="test-result"
          :class="dialogTestResult"
        >
          <CheckCircleIcon
            v-if="dialogTestResult === 'success'"
            class="w-4 h-4"
          />
          <XCircleIcon
            v-else
            class="w-4 h-4"
          />
          <span v-if="dialogTestResult === 'success'">{{ t('settings.connected') }}</span>
          <span v-else>{{ t('settings.testFailed') }}</span>
        </div>
      </div>
      <div class="modal-footer">
        <button
          class="btn btn-ghost btn-test"
          :disabled="dialogTesting"
          @click="testCurrentForm"
        >
          <ArrowPathIcon
            class="w-4 h-4"
            :class="{ 'animate-spin': dialogTesting }"
          />
          <span>{{ dialogTesting ? t('settings.testing') : t('settings.testConnection') }}</span>
        </button>
        <div style="flex:1;" />
        <button
          class="btn btn-ghost"
          @click="showDialog = false"
        >
          {{ t('common.cancel') }}
        </button>
        <button
          class="btn btn-primary"
          @click="saveModel"
        >
          {{ t('common.save') }}
        </button>
      </div>
    </div>
  </div>

  <!-- 删除确认弹窗 -->
  <Teleport to="body">
    <div v-if="showDeleteConfirm" class="modal-overlay" @click.self="showDeleteConfirm = false">
      <div class="modal" style="width:400px;">
        <div class="modal-header">
          <h3>{{ t('common.confirm') }}</h3>
        </div>
        <div class="modal-body">
          <p style="font-size:13px; color:var(--text-primary);">{{ t('settings.confirmDeleteModel') }}</p>
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost" @click="showDeleteConfirm = false">{{ t('common.cancel') }}</button>
          <button class="btn btn-primary" style="background:var(--error);border-color:var(--error);" @click="confirmDelete">{{ t('common.delete') }}</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- 测试结果弹窗 -->
  <Teleport to="body">
    <div v-if="showTestResult" class="modal-overlay" @click.self="showTestResult = false">
      <div class="modal" style="width:400px;">
        <div class="modal-header">
          <h3>{{ testResultType === 'success' ? t('settings.testConnection') : t('settings.testFailed') }}</h3>
        </div>
        <div class="modal-body">
          <div style="display:flex; align-items:center; gap:10px;">
            <svg v-if="testResultType === 'success'" class="w-6 h-6" style="color:var(--success);flex-shrink:0;" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>
            <svg v-else class="w-6 h-6" style="color:var(--error);flex-shrink:0;" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
            <span style="font-size:13px; color:var(--text-primary);">{{ testResultMessage }}</span>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-primary" @click="showTestResult = false">{{ t('common.confirm') }}</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- 验证提示弹窗 -->
  <Teleport to="body">
    <div v-if="showValidationAlert" class="modal-overlay" @click.self="showValidationAlert = false">
      <div class="modal" style="width:380px;">
        <div class="modal-header">
          <h3>{{ t('common.info') }}</h3>
        </div>
        <div class="modal-body">
          <p style="font-size:13px; color:var(--text-primary);">{{ validationMessage }}</p>
        </div>
        <div class="modal-footer">
          <button class="btn btn-primary" @click="showValidationAlert = false">{{ t('common.confirm') }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</div>
</template>

<style scoped>
.model-config {
  width: 100%;
}

/* 模态框 */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  padding: 20px;
}

.modal {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg, 8px);
  width: 560px;
  max-width: 100%;
  max-height: 85vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4);
}

.modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.modal-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.modal-body {
  padding: 20px;
  overflow-y: auto;
}

.modal-footer {
  padding: 12px 20px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 表单网格 */
.form-grid {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-field-toggle {
  flex-direction: row;
  align-items: center;
  padding-top: 8px;
  margin-top: 4px;
  border-top: 1px solid var(--border);
}

.field-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  line-height: 1;
}

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
  appearance: none;
  -webkit-appearance: none;
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

/* 测试结果 */
.test-result {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  margin-top: 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  animation: fadeIn 0.2s ease;
}

.test-result.success {
  background: rgba(34, 197, 94, 0.1);
  color: #22c55e;
  border: 1px solid rgba(34, 197, 94, 0.2);
}

.test-result.error {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
  border: 1px solid rgba(239, 68, 68, 0.2);
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}

.btn-test:hover {
  color: var(--accent);
  background: rgba(99, 102, 241, 0.08);
}

.default-badge {
  position: absolute;
  top: -1px;
  right: -1px;
  font-size: 9px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 0 7px 0 6px;
  color: #fff;
  background: var(--accent);
}
</style>
