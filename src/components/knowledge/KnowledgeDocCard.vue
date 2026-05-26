<script setup lang="ts">
import {
  FolderIcon,
  DocumentTextIcon,
  StarIcon,
  PaperClipIcon,
  EllipsisVerticalIcon,
} from '@heroicons/vue/24/outline'
import { StarIcon as StarSolidIcon } from '@heroicons/vue/24/solid'
import { useI18n } from 'vue-i18n'
import type { KnowledgeDoc } from '@/types'
import { dimensionColors, formatTime } from '@/utils/mock'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('KN-001')
const { t } = useI18n()

defineProps<{
  doc: KnowledgeDoc
}>()

const emit = defineEmits<{
  select: [doc: KnowledgeDoc]
  toggleFavorite: [docId: string]
  togglePin: [docId: string]
}>()

function getStatusBadge(status: string): string {
  switch (status) {
    case 'reviewed': return 'badge-green'
    case 'pending': return 'badge-yellow'
    case 'draft': return 'badge-gray'
    default: return 'badge-gray'
  }
}

function getStatusText(status: string): string {
  switch (status) {
    case 'reviewed': return t('common.completed')
    case 'pending': return t('common.pending')
    case 'draft': return t('common.draft')
    default: return ''
  }
}
</script>

<template>
  <div
    class="kb-doc-card card card-clickable"
    @click="emit('select', doc)"
  >
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div style="display:flex; align-items:center; gap:10px;">
      <!-- 图标 -->
      <div style="display:flex; flex-direction:column; align-items:center; min-width:36px;">
        <DocumentTextIcon class="w-5 h-5 text-accent" />
        <span style="font-size:9px; color:var(--text-muted);">{{ t('knowledge.documents') }}</span>
      </div>

      <!-- 内容 -->
      <div style="flex:1; min-width:0;">
        <div style="display:flex; align-items:center; gap:6px; margin-bottom:2px;">
          <span style="font-size:13px; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
            {{ doc.title }}
          </span>
          <span
            class="badge badge-blue"
            style="font-size:8px;"
          >{{ t('knowledge.documents') }}</span>
          <span
            :class="`badge ${getStatusBadge(doc.status)}`"
            style="font-size:8px;"
          >
            {{ getStatusText(doc.status) }}
          </span>
          <span
            v-if="doc.favorite"
            class="badge badge-yellow"
            style="font-size:8px;"
          >⭐</span>
          <span
            v-if="doc.pinned"
            class="badge badge-gray"
            style="font-size:8px;"
          >📌</span>
        </div>
        <div style="font-size:10px; color:var(--text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
          {{ doc.description }}
        </div>
      </div>

      <!-- 四维标签 -->
      <div style="display:flex; gap:4px; align-items:center; flex-shrink:0;">
        <span
          v-if="doc.tags.lifecycle.length > 0"
          :class="`badge ${dimensionColors.lifecycle}`"
          style="font-size:8px;"
        >
          {{ doc.tags.lifecycle[0] }}
        </span>
        <span
          v-if="doc.tags.techStack.length > 0"
          :class="`badge ${dimensionColors.techStack}`"
          style="font-size:8px;"
        >
          {{ doc.tags.techStack[0] }}
        </span>
        <span
          v-if="doc.tags.abstraction.length > 0"
          :class="`badge ${dimensionColors.abstraction}`"
          style="font-size:8px;"
        >
          {{ doc.tags.abstraction[0] }}
        </span>
        <span
          v-if="doc.tags.purpose.length > 0"
          :class="`badge ${dimensionColors.purpose}`"
          style="font-size:8px;"
        >
          {{ doc.tags.purpose[0] }}
        </span>
      </div>

      <!-- 时间 -->
      <div style="font-size:10px; color:var(--text-muted); flex-shrink:0; min-width:60px; text-align:right;">
        {{ formatTime(doc.updatedAt) }}
      </div>

      <!-- 操作按钮 -->
      <div style="display:flex; gap:2px; flex-shrink:0;">
        <button
          class="btn btn-ghost btn-sm"
          :title="doc.favorite ? t('common.unfavorite') : t('common.favorite')"
          @click.stop="emit('toggleFavorite', doc.id)"
        >
          <StarSolidIcon
            v-if="doc.favorite"
            class="w-3.5 h-3.5 text-yellow-400"
          />
          <StarIcon
            v-else
            class="w-3.5 h-3.5"
          />
        </button>
        <button
          class="btn btn-ghost btn-sm"
          :title="doc.pinned ? t('common.unpin') : t('common.pin')"
          @click.stop="emit('togglePin', doc.id)"
        >
          <PaperClipIcon class="w-3.5 h-3.5" />
        </button>
        <button
          class="btn btn-ghost btn-sm"
          :title="t('common.more')"
        >
          <EllipsisVerticalIcon class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.kb-doc-card {
  padding: 10px 12px;
}
</style>
