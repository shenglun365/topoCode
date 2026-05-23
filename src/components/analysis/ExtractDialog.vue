<template>
  <Teleport to="body">
  <span v-if="showId" class="cmp-id">{{ componentId }}</span>
    <div v-if="visible" class="dialog-overlay" @click.self="close">
      <div class="dialog-container">
        <div class="dialog-header">
          <h2 class="dialog-title">{{ t('analysis.extractKnowledge') }}</h2>
          <button class="close-btn" @click="close">
            <XMarkIcon class="w-5 h-5" />
          </button>
        </div>

        <div class="dialog-body">
          <!-- 标题 -->
          <div class="form-group">
            <label class="form-label">{{ t('analysis.extractTitle') }} *</label>
            <input
              v-model="formData.title"
              type="text"
              class="form-input"
              :placeholder="t('analysis.titlePlaceholder')"
            />
          </div>

          <!-- 四维标签 -->
          <div class="form-group">
            <label class="form-label">{{ t('analysis.extractDimensions') }}</label>
            <div class="dimension-selectors">
              <div class="dimension-row">
                <span class="dimension-icon lifecycle">
                  <ArrowPathIcon class="w-4 h-4" />
                </span>
                <select v-model="formData.dimensions.lifecycle" class="form-select">
                  <option value="">{{ t('analysis.selectLifecycle') }}</option>
                  <option v-for="tag in dimensions.lifecycle" :key="tag" :value="tag">{{ tag }}</option>
                </select>
              </div>
              <div class="dimension-row">
                <span class="dimension-icon tech">
                  <WrenchScrewdriverIcon class="w-4 h-4" />
                </span>
                <select v-model="formData.dimensions.techStack" class="form-select">
                  <option value="">{{ t('analysis.selectTechStack') }}</option>
                  <option v-for="tag in dimensions.techStack" :key="tag" :value="tag">{{ tag }}</option>
                </select>
              </div>
              <div class="dimension-row">
                <span class="dimension-icon abstraction">
                  <Square3Stack3DIcon class="w-4 h-4" />
                </span>
                <select v-model="formData.dimensions.abstraction" class="form-select">
                  <option value="">{{ t('analysis.selectAbstraction') }}</option>
                  <option v-for="tag in dimensions.abstraction" :key="tag" :value="tag">{{ tag }}</option>
                </select>
              </div>
              <div class="dimension-row">
                <span class="dimension-icon purpose">
                  <TargetIcon class="w-4 h-4" />
                </span>
                <select v-model="formData.dimensions.purpose" class="form-select">
                  <option value="">{{ t('analysis.selectPurpose') }}</option>
                  <option v-for="tag in dimensions.purpose" :key="tag" :value="tag">{{ tag }}</option>
                </select>
              </div>
            </div>
          </div>

          <!-- 内容选择 -->
          <div class="form-group">
            <label class="form-label">{{ t('analysis.contentSelect') }}</label>
            <div class="content-checkboxes">
              <label class="checkbox-item">
                <input type="checkbox" v-model="formData.content.summary" />
                <span class="checkbox-label">{{ t('analysis.summary') }}</span>
              </label>
              <label class="checkbox-item">
                <input type="checkbox" v-model="formData.content.ast" />
                <span class="checkbox-label">{{ t('analysis.ast') }}</span>
              </label>
              <label class="checkbox-item">
                <input type="checkbox" v-model="formData.content.callChain" />
                <span class="checkbox-label">{{ t('analysis.callChain') }}</span>
              </label>
              <label class="checkbox-item">
                <input type="checkbox" v-model="formData.content.dependency" />
                <span class="checkbox-label">{{ t('analysis.dependency') }}</span>
              </label>
              <label class="checkbox-item">
                <input type="checkbox" v-model="formData.content.dataFlow" />
                <span class="checkbox-label">{{ t('analysis.extractDataFlow') }}</span>
              </label>
              <label class="checkbox-item">
                <input type="checkbox" v-model="formData.content.logs" />
                <span class="checkbox-label">{{ t('analysis.logs') }}</span>
              </label>
            </div>
          </div>

          <!-- 备注 -->
          <div class="form-group">
            <label class="form-label">{{ t('analysis.notes') }}</label>
            <textarea
              v-model="formData.notes"
              class="form-textarea"
              :placeholder="t('analysis.notesPlaceholder')"
              rows="3"
            ></textarea>
          </div>
        </div>

        <div class="dialog-footer">
          <button class="btn-cancel" @click="close">{{ t('common.cancel') }}</button>
          <button class="btn-confirm" @click="confirmExtract" :disabled="!canExtract">
            {{ t('analysis.confirmExtract') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  XMarkIcon,
  ArrowPathIcon,
  WrenchScrewdriverIcon,
  Square3Stack3DIcon,
  TargetIcon,
} from '@heroicons/vue/24/outline'
import type { Dimensions } from '@/types/ipc'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('AN-007')
const { t } = useI18n()

const props = defineProps<{
  visible: boolean
  task?: any
  dimensions: Dimensions
}>()

const emit = defineEmits<{
  close: []
  extract: [data: ExtractData]
}>()

export interface ExtractData {
  title: string
  dimensions: {
    lifecycle: string
    techStack: string
    abstraction: string
    purpose: string
  }
  content: {
    summary: boolean
    ast: boolean
    callChain: boolean
    dependency: boolean
    dataFlow: boolean
    logs: boolean
  }
  notes: string
  sourceTaskId: string
}

const formData = ref<ExtractData>({
  title: '',
  dimensions: {
    lifecycle: '',
    techStack: '',
    abstraction: '',
    purpose: '',
  },
  content: {
    summary: true,
    ast: true,
    callChain: true,
    dependency: false,
    dataFlow: false,
    logs: false,
  },
  notes: '',
  sourceTaskId: '',
})

const canExtract = computed(() => {
  return formData.value.title.trim().length > 0
})

watch(() => props.visible, (visible) => {
  if (visible && props.task) {
    formData.value.title = props.task.name || ''
    formData.value.sourceTaskId = props.task.id || ''
  }
})

function close() {
  emit('close')
}

function confirmExtract() {
  if (!canExtract.value) return
  emit('extract', formData.value)
  close()
}
</script>

<style scoped lang="scss">
.dialog-overlay {
  @apply fixed inset-0 z-50 flex items-center justify-center bg-black/50;
}

.dialog-container {
  @apply bg-[--bg-secondary] rounded-lg shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto;
}

.dialog-header {
  @apply flex items-center justify-between p-4 border-b border-[--border];
}

.dialog-title {
  @apply text-sm font-semibold text-[--text-primary];
}

.close-btn {
  @apply p-1 text-[--text-muted] hover:text-[--text-primary] transition-colors;
}

.dialog-body {
  @apply p-4 flex flex-col gap-4;
}

.form-group {
  @apply flex flex-col gap-1;
}

.form-label {
  @apply text-xs text-[--text-secondary];
}

.form-input {
  @apply w-full px-3 py-2 text-xs rounded bg-[--bg-tertiary] border border-[--border] text-[--text-primary] focus:border-[--accent] focus:outline-none;
}

.form-select {
  @apply flex-1 px-3 py-2 text-xs rounded bg-[--bg-tertiary] border border-[--border] text-[--text-primary] focus:border-[--accent] focus:outline-none;
}

.form-textarea {
  @apply w-full px-3 py-2 text-xs rounded bg-[--bg-tertiary] border border-[--border] text-[--text-primary] focus:border-[--accent] focus:outline-none resize-none;
}

.dimension-selectors {
  @apply flex flex-col gap-2;
}

.dimension-row {
  @apply flex items-center gap-2;
}

.dimension-icon {
  @apply flex items-center justify-center w-6 h-6 rounded;

  &.lifecycle {
    @apply bg-blue-500/20 text-blue-400;
  }

  &.tech {
    @apply bg-green-500/20 text-green-400;
  }

  &.abstraction {
    @apply bg-purple-500/20 text-purple-400;
  }

  &.purpose {
    @apply bg-orange-500/20 text-orange-400;
  }
}

.content-checkboxes {
  @apply grid grid-cols-2 gap-2;
}

.checkbox-item {
  @apply flex items-center gap-2;
}

.checkbox-label {
  @apply text-xs text-[--text-secondary];
}

.dialog-footer {
  @apply flex justify-end gap-2 p-4 border-t border-[--border];
}

.btn-cancel {
  @apply px-4 py-2 text-xs rounded bg-[--bg-tertiary] text-[--text-secondary] hover:bg-[--bg-hover] transition-colors;
}

.btn-confirm {
  @apply px-4 py-2 text-xs rounded bg-[--accent] text-white hover:bg-[--accent-hover] transition-colors disabled:opacity-50 disabled:cursor-not-allowed;
}
</style>
