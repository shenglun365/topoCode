<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('CH-001')
const { t } = useI18n()

const props = withDefaults(defineProps<{
  level?: string
  size?: 'sm' | 'md' | 'lg'
  showLabel?: boolean
}>(), {
  level: 'none',
  size: 'md',
  showLabel: true,
})

const levelColor = computed(() => {
  switch (props.level) {
    case 'critical': return 'risk-critical'
    case 'high': return 'risk-high'
    case 'medium': return 'risk-medium'
    case 'low': return 'risk-low'
    default: return 'risk-none'
  }
})

const levelLabel = computed(() => {
  switch (props.level) {
    case 'critical': return t('change.riskCritical')
    case 'high': return t('change.riskHigh')
    case 'medium': return t('change.riskMedium')
    case 'low': return t('change.riskLow')
    default: return t('change.riskNone')
  }
})

const sizeClass = computed(() => `badge-${props.size}`)
</script>

<template>
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
  <span
    class="change-risk-badge"
    :class="[levelColor, sizeClass]"
  >
    <span class="risk-dot" />
    <span v-if="showLabel">{{ levelLabel }}</span>
  </span>
</template>

<style scoped>
.change-risk-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 500;
  line-height: 1.3;
}

.risk-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.badge-sm {
  font-size: 10px;
  padding: 1px 6px;
}

.badge-md {
  font-size: 11px;
}

.badge-lg {
  font-size: 13px;
  padding: 4px 12px;
}

.risk-critical {
  background: color-mix(in srgb, #ef4444 15%, transparent);
  color: #ef4444;
}

.risk-critical .risk-dot {
  background: #ef4444;
}

.risk-high {
  background: color-mix(in srgb, #f97316 15%, transparent);
  color: #f97316;
}

.risk-high .risk-dot {
  background: #f97316;
}

.risk-medium {
  background: color-mix(in srgb, #f59e0b 15%, transparent);
  color: #f59e0b;
}

.risk-medium .risk-dot {
  background: #f59e0b;
}

.risk-low {
  background: color-mix(in srgb, #22c55e 15%, transparent);
  color: #22c55e;
}

.risk-low .risk-dot {
  background: #22c55e;
}

.risk-none {
  background: color-mix(in srgb, #6b7280 10%, transparent);
  color: #9ca3af;
}

.risk-none .risk-dot {
  background: #6b7280;
}
</style>
