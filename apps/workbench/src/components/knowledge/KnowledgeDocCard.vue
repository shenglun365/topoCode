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
import { useComponentId } from '@topo/web-core/composables/useComponentId'

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
    <div style="display:flex; align-items:center; gap:calc(10px * var(--ui-scale, 1));">
      <!-- 图标 -->
      <div style="display:flex; flex-direction:column; align-items:center; min-width:calc(36px * var(--ui-scale, 1));">
        <DocumentTextIcon class="w-5 h-5 text-accent" />
        <span style="font-size:calc(9px * var(--ui-scale, 1)); color:var(--text-muted);">{{ t('knowledge.documents') }}</span>
      </div>

      <!-- 内容 -->
      <div style="flex:1; min-width:0;">
        <div style="display:flex; align-items:center; gap:calc(6px * var(--ui-scale, 1)); margin-bottom:calc(2px * var(--ui-scale, 1));">
          <span style="font-size:calc(13px * var(--ui-scale, 1)); font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
            {{ doc.title }}
          </span>
          <span
            class="badge badge-blue"
            style="font-size:calc(8px * var(--ui-scale, 1));"
          >{{ t('knowledge.documents') }}</span>
          <span
            :class="`badge ${getStatusBadge(doc.status)}`"
            style="font-size:calc(8px * var(--ui-scale, 1));"
          >
            {{ getStatusText(doc.status) }}
          </span>
          <span
            v-if="doc.favorite"
            class="badge badge-yellow"
            style="font-size:calc(8px * var(--ui-scale, 1));"
          >⭐</span>
          <span
            v-if="doc.pinned"
            class="badge badge-gray"
            style="font-size:calc(8px * var(--ui-scale, 1));"
          >📌</span>
        </div>
        <div style="font-size:calc(10px * var(--ui-scale, 1)); color:var(--text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
          {{ doc.description }}
        </div>
      </div>

      <!-- 四维标签 -->
      <div style="display:flex; gap:calc(4px * var(--ui-scale, 1)); align-items:center; flex-shrink:0;">
        <span
          v-if="doc.tags?.lifecycle?.length"
          :class="`badge ${dimensionColors.lifecycle}`"
          style="font-size:calc(8px * var(--ui-scale, 1));"
        >
          {{ doc.tags?.lifecycle?.[0] }}
        </span>
        <span
          v-if="doc.tags?.techStack?.length"
          :class="`badge ${dimensionColors.techStack}`"
          style="font-size:calc(8px * var(--ui-scale, 1));"
        >
          {{ doc.tags?.techStack?.[0] }}
        </span>
        <span
          v-if="doc.tags?.abstraction?.length"
          :class="`badge ${dimensionColors.abstraction}`"
          style="font-size:calc(8px * var(--ui-scale, 1));"
        >
          {{ doc.tags?.abstraction?.[0] }}
        </span>
        <span
          v-if="doc.tags?.purpose?.length"
          :class="`badge ${dimensionColors.purpose}`"
          style="font-size:calc(8px * var(--ui-scale, 1));"
        >
          {{ doc.tags?.purpose?.[0] }}
        </span>
      </div>

      <!-- 时间 -->
      <div style="font-size:calc(10px * var(--ui-scale, 1)); color:var(--text-muted); flex-shrink:0; min-width:calc(60px * var(--ui-scale, 1)); text-align:right;">
        {{ formatTime(doc.updatedAt) }}
      </div>

      <!-- 操作按钮 -->
      <div style="display:flex; gap:calc(2px * var(--ui-scale, 1)); flex-shrink:0;">
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
  padding: calc(10px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
}
</style>
