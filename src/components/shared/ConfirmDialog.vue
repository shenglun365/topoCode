<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { XMarkIcon, ExclamationTriangleIcon, TrashIcon } from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('SD-001')
const { t } = useI18n()

const props = withDefaults(defineProps<{
  visible?: boolean
  title: string
  message?: string
  confirmLabel?: string
  cancelLabel?: string
  variant?: 'danger' | 'warning' | 'info'
}>(), {
  visible: true,
  message: '',
  confirmLabel: () => undefined,
  cancelLabel: () => undefined,
  variant: 'danger',
})

const emit = defineEmits<{
  confirm: []
  cancel: []
  'update:visible': [value: boolean]
}>()

const confirmLabel = computed(() => props.confirmLabel || t('common.confirm'))
const cancelLabel = computed(() => props.cancelLabel || t('common.cancel'))

const variantClass = computed(() => {
  switch (props.variant) {
    case 'danger': return 'variant-danger'
    case 'warning': return 'variant-warning'
    case 'info': return 'variant-info'
    default: return 'variant-danger'
  }
})

const iconMap = {
  danger: TrashIcon,
  warning: ExclamationTriangleIcon,
  info: ExclamationTriangleIcon,
}
const IconComponent = iconMap[props.variant] || ExclamationTriangleIcon

function handleConfirm() {
  emit('update:visible', false)
  emit('confirm')
}

function handleCancel() {
  emit('update:visible', false)
  emit('cancel')
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') handleCancel()
}
</script>

<template>
  <Teleport to="body">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div
      v-if="props.visible"
      class="confirm-dialog-overlay"
      role="dialog"
      aria-modal="true"
      @click.self="handleCancel"
      @keydown="handleKeydown"
    >
      <div
        class="confirm-dialog-card"
        :class="variantClass"
      >
        <div class="confirm-dialog-icon">
          <component
            :is="IconComponent"
            class="w-8 h-8"
          />
        </div>
        <div class="confirm-dialog-title">
          {{ title }}
        </div>
        <div class="confirm-dialog-message">
          <slot name="message">
            <span v-html="message" />
          </slot>
        </div>
        <div class="confirm-dialog-actions">
          <button
            class="btn btn-ghost"
            @click="handleCancel"
          >
            {{ cancelLabel }}
          </button>
          <button
            class="btn btn-primary"
            :class="{ 'btn-danger': variant === 'danger', 'btn-warning': variant === 'warning' }"
            @click="handleConfirm"
          >
            {{ confirmLabel }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.confirm-dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 10000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  animation: fadeIn 0.15s ease;
}

.confirm-dialog-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 24px;
  max-width: 440px;
  min-width: 320px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  animation: scaleIn 0.2s ease;
  text-align: center;
}

.confirm-dialog-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  margin-bottom: 16px;
}

.variant-danger .confirm-dialog-icon {
  background: color-mix(in srgb, #ef4444 15%, transparent);
  color: #ef4444;
}

.variant-warning .confirm-dialog-icon {
  background: color-mix(in srgb, #f59e0b 15%, transparent);
  color: #f59e0b;
}

.variant-info .confirm-dialog-icon {
  background: color-mix(in srgb, #3b82f6 15%, transparent);
  color: #3b82f6;
}

.confirm-dialog-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.confirm-dialog-message {
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.6;
  margin-bottom: 20px;
  white-space: pre-wrap;
}

.confirm-dialog-actions {
  display: flex;
  gap: 8px;
  justify-content: center;
}

.confirm-dialog-actions .btn {
  min-width: 100px;
}

.btn-danger {
  background: #ef4444;
  color: white;
}

.btn-danger:hover {
  background: #dc2626;
}

.btn-warning {
  background: #f59e0b;
  color: white;
}

.btn-warning:hover {
  background: #d97706;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes scaleIn {
  from { opacity: 0; transform: scale(0.95); }
  to { opacity: 1; transform: scale(1); }
}
</style>
