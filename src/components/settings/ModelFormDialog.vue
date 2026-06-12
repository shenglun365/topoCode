<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckCircleIcon, XCircleIcon, ArrowPathIcon, InformationCircleIcon } from '@heroicons/vue/24/outline'
import type { ModelConfigItem } from '@/types/ipc'
import { PROVIDER_DEFAULT_URLS } from '@/constants/providers'
import { useComponentId } from '@/composables/useComponentId'

const props = withDefaults(defineProps<{
  show: boolean
  editMode: boolean
  config?: ModelConfigItem | null
  testing?: boolean
  testResult?: 'success' | 'error' | null
}>(), {
  config: null,
  testing: false,
  testResult: null,
})

const emit = defineEmits<{
  'update:show': [value: boolean]
  save: [data: {
    name: string
    provider: string
    model: string
    url: string
    type: string
    temperature?: number
    maxTokens?: number
    apiKey?: string
    isDefault?: boolean
  }]
  test: []
  'update:testResult': [value: null]
}>()

const { t } = useI18n()

interface ProviderMeta {
  value: string
  label: string
  group: 'local' | 'cloud'
  defaultUrl: string
  needsApiKey: boolean
  hintKey: string
}

const providerOptions: ProviderMeta[] = [
  { value: 'ollama', label: 'Ollama', group: 'local', defaultUrl: PROVIDER_DEFAULT_URLS.ollama, needsApiKey: false, hintKey: 'settings.providerHintOllama' },
  { value: 'lm-studio', label: 'LM Studio', group: 'local', defaultUrl: PROVIDER_DEFAULT_URLS['lm-studio'], needsApiKey: false, hintKey: 'settings.providerHintLmStudio' },
  { value: 'custom-local', label: t('settings.customLocal'), group: 'local', defaultUrl: '', needsApiKey: false, hintKey: 'settings.providerHintCustomLocal' },
  { value: 'deepseek', label: 'DeepSeek', group: 'cloud', defaultUrl: PROVIDER_DEFAULT_URLS.deepseek, needsApiKey: true, hintKey: 'settings.providerHintDeepSeek' },
  { value: 'minimax-cn', label: 'MiniMax CN', group: 'cloud', defaultUrl: PROVIDER_DEFAULT_URLS['minimax-cn'], needsApiKey: true, hintKey: 'settings.providerHintMiniMax' },
  { value: 'minimax-global', label: 'MiniMax Global', group: 'cloud', defaultUrl: PROVIDER_DEFAULT_URLS['minimax-global'], needsApiKey: true, hintKey: 'settings.providerHintMiniMax' },
  { value: 'openrouter', label: 'OpenRouter', group: 'cloud', defaultUrl: PROVIDER_DEFAULT_URLS.openrouter, needsApiKey: true, hintKey: 'settings.providerHintOpenRouter' },
  { value: 'custom-cloud', label: t('settings.customCloud'), group: 'cloud', defaultUrl: '', needsApiKey: true, hintKey: 'settings.providerHintCustomCloud' },
]

const localOptions = providerOptions.filter(p => p.group === 'local')
const cloudOptions = providerOptions.filter(p => p.group === 'cloud')

const form = ref({
  name: '',
  provider: 'ollama' as string,
  model: '',
  url: '',
  type: 'local' as 'local' | 'cloud',
  temperature: 0.7,
  maxTokens: 4096,
  isDefault: false,
  apiKey: '',
})
const emptyModelCount = ref(0)

const currentProviderMeta = computed(() =>
  providerOptions.find(p => p.value === form.value.provider)
)
const { showId, componentId } = useComponentId('MF-001')

watch(() => props.show, (val) => {
  if (val) {
    if (props.editMode && props.config) {
      form.value = {
        name: props.config.name,
        provider: props.config.provider,
        model: props.config.model,
        url: props.config.url,
        type: props.config.type,
        temperature: props.config.temperature ?? 0.7,
        maxTokens: props.config.maxTokens ?? 4096,
        isDefault: props.config.isDefault,
        apiKey: props.config.apiKey || '',
      }
    } else {
      const meta = providerOptions.find(p => p.value === 'ollama')!
      form.value = {
        name: '',
        provider: 'ollama',
        model: '',
        url: meta.defaultUrl,
        type: meta.group,
        temperature: 0.7,
        maxTokens: 4096,
        isDefault: emptyModelCount.value === 0,
        apiKey: '',
      }
    }
  }
})

function onProviderChange(provider: string) {
  const meta = providerOptions.find(p => p.value === provider)
  if (meta) {
    form.value.url = meta.defaultUrl
    form.value.type = meta.group
    if (!meta.needsApiKey) {
      form.value.apiKey = ''
    }
  }
}

function handleTest() {
  if (!form.value.url || !form.value.model) return
  emit('test')
}

function handleSave() {
  emit('save', { ...form.value })
}

function close() {
  emit('update:testResult', null)
  emit('update:show', false)
}
</script>

<template>
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
  <div
    v-if="show"
    class="modal-overlay"
    @click.self="close"
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
              @change="onProviderChange(($event.target as HTMLSelectElement).value)"
            >
              <optgroup :label="t('settings.localModels')">
                <option
                  v-for="opt in localOptions"
                  :key="opt.value"
                  :value="opt.value"
                >
                  {{ opt.label }}
                </option>
              </optgroup>
              <optgroup :label="t('settings.cloudServices')">
                <option
                  v-for="opt in cloudOptions"
                  :key="opt.value"
                  :value="opt.value"
                >
                  {{ opt.label }}
                </option>
              </optgroup>
            </select>
          </div>

          <div
            v-if="currentProviderMeta"
            class="provider-hint"
          >
            <InformationCircleIcon class="w-4 h-4 shrink-0" />
            <span>{{ t(currentProviderMeta.hintKey) }}</span>
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
              :placeholder="currentProviderMeta?.defaultUrl || 'http://...'"
            >
          </div>

          <div
            v-if="currentProviderMeta?.needsApiKey"
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

        <div
          v-if="testResult"
          class="test-result"
          :class="testResult"
        >
          <CheckCircleIcon
            v-if="testResult === 'success'"
            class="w-4 h-4"
          />
          <XCircleIcon
            v-else
            class="w-4 h-4"
          />
          <span v-if="testResult === 'success'">{{ t('settings.connected') }}</span>
          <span v-else>{{ t('settings.testFailed') }}</span>
        </div>
      </div>
      <div class="modal-footer">
        <button
          class="btn btn-ghost btn-test"
          :disabled="testing"
          @click="handleTest"
        >
          <ArrowPathIcon
            class="w-4 h-4"
            :class="{ 'animate-spin': testing }"
          />
          <span>{{ testing ? t('settings.testing') : t('settings.testConnection') }}</span>
        </button>
        <div style="flex:1;" />
        <button
          class="btn btn-ghost"
          @click="close"
        >
          {{ t('common.cancel') }}
        </button>
        <button
          class="btn btn-primary"
          @click="handleSave"
        >
          {{ t('common.save') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
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

.provider-hint {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  background: var(--bg-info, rgba(59, 130, 246, 0.08));
  border: 1px solid var(--border-info, rgba(59, 130, 246, 0.15));
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-info, #3b82f6);
}

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
</style>
