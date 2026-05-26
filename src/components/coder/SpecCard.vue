<template>
  <div
    class="spec-card"
    :class="statusClass"
  >
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div class="spec-header">
      <div class="spec-title-area">
        <DocumentTextIcon class="w-5 h-5 spec-icon" />
        <h3 class="spec-title">
          {{ spec.title }}
        </h3>
      </div>
      <span
        class="status-badge"
        :class="status"
      >{{ statusText }}</span>
    </div>

    <p class="spec-summary">
      {{ spec.summary }}
    </p>

    <div class="spec-sections">
      <span class="sections-label">{{ t('coder.specSections') }}:</span>
      <div class="section-tags">
        <span
          v-for="section in spec.sections"
          :key="section"
          class="section-tag"
        >
          {{ section }}
        </span>
      </div>
    </div>

    <div class="spec-meta">
      <span class="meta-item">{{ t('coder.updatedAt') }}: {{ formatDate(spec.updatedAt) }}</span>
    </div>

    <div class="spec-actions">
      <button
        class="action-btn view-btn"
        @click="emit('view', { specId: spec.id })"
      >
        <EyeIcon class="w-4 h-4" />
        {{ t('common.view') }}
      </button>
      <button
        class="action-btn edit-btn"
        @click="emit('edit', { specId: spec.id })"
      >
        <PencilIcon class="w-4 h-4" />
        {{ t('common.edit') }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import {
  DocumentTextIcon,
  EyeIcon,
  PencilIcon,
} from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'
const { showId, componentId } = useComponentId('CD-005')


const { t } = useI18n()

export interface SpecDoc {
  id: string
  title: string
  status: 'draft' | 'reviewed' | 'approved'
  summary: string
  sections: string[]
  createdAt: Date | string
  updatedAt: Date | string
}

const props = defineProps<{
  spec: SpecDoc
}>()

const emit = defineEmits<{
  view: [specId: string]
  edit: [specId: string]
}>()

const statusClass = {
  draft: 'status-draft',
  reviewed: 'status-reviewed',
  approved: 'status-approved',
}[props.spec.status]

const statusText = {
  draft: t('coder.specDraft'),
  reviewed: t('coder.specReviewed'),
  approved: t('coder.specApproved'),
}[props.spec.status]

function formatDate(date: Date | string): string {
  const d = typeof date === 'string' ? new Date(date) : date
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped lang="spec-card">
.spec-card {
  @apply rounded-lg border border-[--border] bg-[--bg-secondary] p-4 transition-all hover:border-[--accent];
  position: relative;
  overflow: hidden;
}

.spec-card::before {
  content: '';
  @apply absolute left-0 top-0 bottom-0 w-1;

  .status-draft & {
    @apply bg-gray-400;
  }

  .status-reviewed & {
    @apply bg-yellow-400;
  }

  .status-approved & {
    @apply bg-green-400;
  }
}

.spec-header {
  @apply flex items-start justify-between mb-3;
}

.spec-title-area {
  @apply flex items-center gap-2;
}

.spec-icon {
  @apply text-[--accent];
}

.spec-title {
  @apply text-sm font-semibold text-[--text-primary];
}

.status-badge {
  @apply px-2 py-0.5 text-xs rounded-full;

  &.draft {
    @apply bg-gray-500/20 text-gray-400;
  }

  &.reviewed {
    @apply bg-yellow-500/20 text-yellow-400;
  }

  &.approved {
    @apply bg-green-500/20 text-green-400;
  }
}

.spec-summary {
  @apply text-xs text-[--text-secondary] mb-3 line-clamp-2;
}

.spec-sections {
  @apply mb-3;
}

.sections-label {
  @apply text-xs text-[--text-muted] mr-2;
}

.section-tags {
  @apply flex flex-wrap gap-1 mt-1;
}

.section-tag {
  @apply px-2 py-0.5 text-xs rounded bg-[--bg-tertiary] text-[--text-secondary];
}

.spec-meta {
  @apply mb-3;
}

.meta-item {
  @apply text-xs text-[--text-muted];
}

.spec-actions {
  @apply flex gap-2;
}

.action-btn {
  @apply flex items-center gap-1 px-3 py-1.5 text-xs rounded transition-colors;

  &.view-btn {
    @apply bg-[--bg-tertiary] text-[--text-secondary] hover:bg-[--bg-hover] hover:text-[--text-primary];
  }

  &.edit-btn {
    @apply bg-[--accent]/20 text-[--accent] hover:bg-[--accent]/30;
  }
}
</style>
