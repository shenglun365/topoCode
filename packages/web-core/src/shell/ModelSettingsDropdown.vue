<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import './toolbar.css'
import {
  CONTEXT_OPTIONS,
  readContextPref,
  readModelPref,
  writeContextPref,
  writeModelPref,
} from './useAppPrefs'
import type { ModelSettingsProvider, ModelInfo } from './model-provider'
import { tShell } from './i18n'

/**
 * 统一模型设置下拉（P2）：点击显示列表，设置模型 + 最大生成（max_tokens）。
 * 偏好持久化到 localStorage（`topoone-model-{app}` / `topoone-context-{app}`），
 * 后端写操作经 `provider` 注入（各子模块实现各自数据源）。
 */
const props = withDefaults(defineProps<{
  appKey: string
  provider: ModelSettingsProvider
  contextOptions?: number[]
  modelLabel?: string
  contextLabel?: string
  initialModel?: string
  initialContext?: number
}>(), {
  contextOptions: () => [...CONTEXT_OPTIONS],
  modelLabel: '',
  contextLabel: '',
})

const emit = defineEmits<{
  (e: 'model', id: string): void
  (e: 'context', tokens: number): void
}>()

const root = ref<HTMLElement | null>(null)
const open = ref(false)
const loading = ref(true)
const models = ref<ModelInfo[]>([])
const modelId = ref('')
const currentName = ref('')
const currentContext = ref(props.initialContext ?? readContextPref(props.appKey))

onMounted(async () => {
  try {
    models.value = await props.provider.listModels()
  } catch (e) {
    console.error('[ModelSettingsDropdown] listModels failed:', e)
  } finally {
    loading.value = false
  }
  const saved = props.initialModel || readModelPref(props.appKey)
  const matched = models.value.find((m) => m.id === saved)
  const def = models.value.find((m) => (m as ModelInfo & { isDefault?: boolean }).isDefault)
  const next = (matched || def || models.value[0] || { id: '' }).id
  modelId.value = next
  currentName.value = (models.value.find((m) => m.id === next) || { name: '' }).name
  if (saved !== next && next) writeModelPref(props.appKey, next)
})

function onDocClick(e: MouseEvent) {
  if (!open.value) return
  if (root.value && !root.value.contains(e.target as Node)) open.value = false
}
onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))

function toggle() {
  open.value = !open.value
}

async function onModelChange(e: Event) {
  const id = (e.target as HTMLSelectElement).value
  if (!id) return
  modelId.value = id
  currentName.value = (models.value.find((m) => m.id === id) || { name: id }).name
  writeModelPref(props.appKey, id)
  emit('model', id)
  try {
    await props.provider.saveModel?.(id)
  } catch (err) {
    console.error('[ModelSettingsDropdown] saveModel failed:', err)
  }
}

async function onContextChange(e: Event) {
  const n = Number((e.target as HTMLSelectElement).value)
  currentContext.value = n
  writeContextPref(props.appKey, n)
  emit('context', n)
  try {
    await props.provider.saveContext?.(n)
  } catch (err) {
    console.error('[ModelSettingsDropdown] saveContext failed:', err)
  }
}
</script>

<template>
  <div ref="root" class="model-dropdown">
    <button class="toolbar-btn" type="button" :title="modelLabel" @click.stop="toggle">
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <rect x="4" y="4" width="16" height="16" rx="2" />
        <path d="M9 9h6M9 13h6M9 17h3" />
      </svg>
      <span v-if="currentName" class="model-name">{{ currentName }}</span>
    </button>
      <div v-if="open" class="toolbar-popover" @click.stop>
      <div class="popover-row">
        <label>{{ modelLabel || tShell('model') }}</label>
        <select class="toolbar-select" :value="modelId" :disabled="loading" @change="onModelChange">
          <option v-if="loading" value="">{{ tShell('loading') }}</option>
          <option v-for="m in models" :key="m.id" :value="m.id">{{ m.name }}</option>
        </select>
      </div>
      <div class="popover-row">
        <label>{{ contextLabel || tShell('context') }}</label>
        <select class="toolbar-select" :value="currentContext" @change="onContextChange">
          <option v-for="c in contextOptions" :key="c" :value="c">{{ c / 1000 }}K</option>
        </select>
      </div>
    </div>
  </div>
</template>
