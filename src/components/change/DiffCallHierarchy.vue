<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowRightIcon,
  ArrowDownIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('CH-006')
const { t } = useI18n()

const props = withDefaults(defineProps<{
  incoming?: Array<{ caller: string; callee: string; status: string }>
  outgoing?: Array<{ caller: string; callee: string; status: string }>
}>(), {
  incoming: () => [],
  outgoing: () => [],
})

const statusClass = (status: string) => {
  switch (status) {
    case 'added': return 'status-added'
    case 'removed': return 'status-removed'
    case 'modified': return 'status-modified'
    default: return 'status-unchanged'
  }
}

const statusLabel = (status: string) => {
  switch (status) {
    case 'added': return '+'
    case 'removed': return '−'
    case 'modified': return '~'
    default: return ''
  }
}

const hasData = computed(() => props.incoming.length > 0 || props.outgoing.length > 0)
</script>

<template>
  <div class="diff-call-hierarchy">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>

    <div
      v-if="!hasData"
      class="diff-empty"
    >
      <span>{{ t('change.noCallHierarchyData') }}</span>
    </div>

    <template v-else>
      <div
        v-if="outgoing.length"
        class="diff-section"
      >
        <div class="diff-section-title">
          <ArrowDownIcon class="w-3.5 h-3.5" />
          <span>{{ t('change.outgoingCalls') }} ({{ outgoing.length }})</span>
        </div>
        <div class="diff-calls">
          <div
            v-for="edge in outgoing"
            :key="`out-${edge.caller}-${edge.callee}`"
            class="diff-call-row"
          >
            <span
              class="call-status-badge"
              :class="statusClass(edge.status)"
            >{{ statusLabel(edge.status) }}</span>
            <span class="call-callee">{{ edge.callee }}</span>
          </div>
        </div>
      </div>

      <div
        v-if="incoming.length"
        class="diff-section"
      >
        <div class="diff-section-title">
          <ArrowRightIcon class="w-3.5 h-3.5" />
          <span>{{ t('change.incomingCalls') }} ({{ incoming.length }})</span>
        </div>
        <div class="diff-calls">
          <div
            v-for="edge in incoming"
            :key="`in-${edge.caller}-${edge.callee}`"
            class="diff-call-row"
          >
            <span
              class="call-status-badge"
              :class="statusClass(edge.status)"
            >{{ statusLabel(edge.status) }}</span>
            <span class="call-caller">{{ edge.caller }}</span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.diff-call-hierarchy {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 8px 0;
}

.diff-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
  font-size: 12px;
  color: var(--text-muted);
}

.diff-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.diff-section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  padding: 4px 12px;
}

.diff-calls {
  display: flex;
  flex-direction: column;
}

.diff-call-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px 4px 24px;
  font-size: 12px;
  transition: background 0.1s;
}

.diff-call-row:hover {
  background: var(--bg-hover);
}

.call-status-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  font-family: monospace;
  flex-shrink: 0;
}

.status-added {
  background: color-mix(in srgb, #22c55e 15%, transparent);
  color: #22c55e;
}

.status-removed {
  background: color-mix(in srgb, #ef4444 15%, transparent);
  color: #ef4444;
}

.status-modified {
  background: color-mix(in srgb, #f59e0b 15%, transparent);
  color: #f59e0b;
}

.status-unchanged {
  background: color-mix(in srgb, #6b7280 10%, transparent);
  color: #9ca3af;
}

.call-callee,
.call-caller {
  font-family: monospace;
  font-size: 11px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
