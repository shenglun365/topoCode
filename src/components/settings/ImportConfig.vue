<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSettingsStore } from '@/stores/settings-store'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('ST-006')
const { t } = useI18n()
const settingsStore = useSettingsStore()

const saving = ref(false)
const saved = ref(false)

const localMode = ref<'standard' | 'strict' | 'minimal'>('strict')
const localPatterns = ref<string[]>([])
const localExtraFiles = ref<string[]>([])
const newPattern = ref('')
const newFile = ref('')

onMounted(async () => {
  await settingsStore.loadImportConfig()
  localMode.value = settingsStore.importConfig.ignoreMode
  localPatterns.value = [...(settingsStore.importConfig.customPatterns || [])]
  localExtraFiles.value = [...(settingsStore.importConfig.extraIgnoreFiles || [])]
})

async function handleSave() {
  saving.value = true
  saved.value = false
  try {
    await settingsStore.saveImportConfig({
      ignoreMode: localMode.value,
      customPatterns: localPatterns.value,
      extraIgnoreFiles: localExtraFiles.value,
    })
    saved.value = true
    setTimeout(() => { saved.value = false }, 2000)
  } finally {
    saving.value = false
  }
}

function addPattern() {
  const val = newPattern.value.trim()
  if (val && !localPatterns.value.includes(val)) {
    localPatterns.value.push(val)
    newPattern.value = ''
  }
}

function removePattern(idx: number) {
  localPatterns.value.splice(idx, 1)
}

function addExtraFile() {
  const val = newFile.value.trim()
  if (val && !localExtraFiles.value.includes(val)) {
    localExtraFiles.value.push(val)
    newFile.value = ''
  }
}

function removeExtraFile(idx: number) {
  localExtraFiles.value.splice(idx, 1)
}

const modeOptions = [
  { value: 'standard', label: t('settings.import.modeStandard') },
  { value: 'strict', label: t('settings.import.modeStrict') },
  { value: 'minimal', label: t('settings.import.modeMinimal') },
]

const modeDescriptions: Record<string, string> = {
  standard: t('settings.import.modeStandardDesc'),
  strict: t('settings.import.modeStrictDesc'),
  minimal: t('settings.import.modeMinimalDesc'),
}
</script>

<template>
  <div class="import-config">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>

    <div class="section">
      <h3 class="section-title">
        {{ t('settings.import.ignoreMode') }}
      </h3>
      <p class="section-desc">
        {{ t('settings.import.ignoreModeDesc') }}
      </p>
      <div class="mode-selector">
        <label
          v-for="opt in modeOptions"
          :key="opt.value"
          class="mode-option"
          :class="{ active: localMode === opt.value }"
        >
          <input
            v-model="localMode"
            type="radio"
            :value="opt.value"
          >
          <div class="mode-content">
            <span class="mode-label">{{ opt.label }}</span>
            <span class="mode-desc">{{ modeDescriptions[opt.value] }}</span>
          </div>
        </label>
      </div>
    </div>

    <div class="section">
      <h3 class="section-title">
        {{ t('settings.import.customPatterns') }}
      </h3>
      <p class="section-desc">
        {{ t('settings.import.customPatternsDesc') }}
      </p>
      <div class="tag-list">
        <span
          v-for="(pat, idx) in localPatterns"
          :key="idx"
          class="tag"
        >
          <code>{{ pat }}</code>
          <button
            class="tag-remove"
            @click="removePattern(idx)"
          >&times;</button>
        </span>
        <span class="tag-input-wrap">
          <input
            v-model="newPattern"
            class="tag-input"
            :placeholder="t('settings.import.patternPlaceholder')"
            @keydown.enter.prevent="addPattern"
            @keydown.tab.prevent="addPattern"
          >
          <button
            v-if="newPattern.trim()"
            class="tag-add-btn"
            @click="addPattern"
          >+</button>
        </span>
      </div>
    </div>

    <div class="section">
      <h3 class="section-title">
        {{ t('settings.import.extraIgnoreFiles') }}
      </h3>
      <p class="section-desc">
        {{ t('settings.import.extraIgnoreFilesDesc') }}
      </p>
      <div class="tag-list">
        <span
          v-for="(fname, idx) in localExtraFiles"
          :key="idx"
          class="tag"
        >
          <code>{{ fname }}</code>
          <button
            class="tag-remove"
            @click="removeExtraFile(idx)"
          >&times;</button>
        </span>
        <span class="tag-input-wrap">
          <input
            v-model="newFile"
            class="tag-input"
            :placeholder="t('settings.import.filePlaceholder')"
            @keydown.enter.prevent="addExtraFile"
            @keydown.tab.prevent="addExtraFile"
          >
          <button
            v-if="newFile.trim()"
            class="tag-add-btn"
            @click="addExtraFile"
          >+</button>
        </span>
      </div>
    </div>

    <div class="actions">
      <button
        class="btn btn-primary"
        :disabled="saving"
        @click="handleSave"
      >
        <span v-if="saving">{{ t('common.saving') }}...</span>
        <span v-else-if="saved">{{ t('common.saved') }}</span>
        <span v-else>{{ t('common.save') }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.import-config {
  @apply flex flex-col gap-6;
}

.section {
  @apply flex flex-col gap-2;
}

.section-title {
  @apply text-sm font-semibold text-[--text-primary];
}

.section-desc {
  @apply text-xs text-[--text-muted];
}

.mode-selector {
  @apply flex flex-col gap-2 mt-1;
}

.mode-option {
  @apply flex items-center gap-3 p-3 rounded-lg border border-[--border] cursor-pointer
    transition-colors hover:border-[--accent] hover:bg-[--bg-hover];
}

.mode-option.active {
  @apply border-[--accent];
  background: color-mix(in srgb, var(--accent) 5%, transparent);
}

.mode-option input[type="radio"] {
  @apply accent-[--accent];
}

.mode-content {
  @apply flex flex-col gap-0.5;
}

.mode-label {
  @apply text-sm font-medium text-[--text-primary];
}

.mode-desc {
  @apply text-xs text-[--text-muted];
}

.tag-list {
  @apply flex flex-wrap gap-2 p-3 rounded-lg border border-[--border] bg-[--bg-secondary] min-h-[42px];
}

.tag {
  @apply inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs
    bg-[--bg-tertiary] border border-[--border] text-[--text-primary];
}

.tag code {
  @apply text-xs;
}

.tag-remove {
  @apply ml-0.5 text-[--text-muted] hover:text-red-400 transition-colors leading-none text-sm;
}

.tag-input-wrap {
  @apply inline-flex items-center gap-1;
}

.tag-input {
  @apply bg-transparent border-none outline-none text-xs text-[--text-primary] min-w-[120px];
}

.tag-add-btn {
  @apply w-5 h-5 flex items-center justify-center rounded bg-[--accent] text-white text-xs
    hover:bg-[--accent-hover] transition-colors;
}

.actions {
  @apply flex justify-end pt-2;
}
</style>
