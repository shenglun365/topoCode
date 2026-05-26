<script setup lang="ts">
import {
  DocumentTextIcon,
  CodeBracketIcon,
  ChartBarIcon,
  ArrowTopRightOnSquareIcon,
} from '@heroicons/vue/24/outline'
import { useI18n } from 'vue-i18n'
import type { ContextCard } from '@/utils/mock'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('CD-008')
const { t } = useI18n()

defineProps<{
  cards: ContextCard[]
}>()

function getIcon(type: string): any {
  switch (type) {
    case 'knowledge': return DocumentTextIcon
    case 'code': return CodeBracketIcon
    case 'analysis': return ChartBarIcon
    default: return DocumentTextIcon
  }
}

function getColor(type: string): string {
  switch (type) {
    case 'knowledge': return 'text-blue-400'
    case 'code': return 'text-green-400'
    case 'analysis': return 'text-yellow-400'
    default: return 'text-muted'
  }
}
</script>

<template>
  <div class="context-cards">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div
      v-for="card in cards"
      :key="card.id"
      class="context-card card"
    >
      <!-- 图标 -->
      <div
        class="ctx-icon"
        :class="getColor(card.type)"
      >
        <component
          :is="getIcon(card.type)"
          class="w-5 h-5"
        />
      </div>

      <!-- 信息 -->
      <div class="ctx-info">
        <div class="ctx-title">
          {{ card.title }}
        </div>
        <div class="ctx-desc">
          {{ card.description }}
        </div>
      </div>

      <!-- 打开按钮 -->
      <button class="btn btn-ghost btn-sm ctx-open-btn">
        <ArrowTopRightOnSquareIcon class="w-3.5 h-3.5" />
        <span>{{ t('common.open') }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.context-cards {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}

.context-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
}

.ctx-icon {
  flex-shrink: 0;
}

.ctx-info {
  flex: 1;
  min-width: 0;
}

.ctx-title {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 2px;
}

.ctx-desc {
  font-size: 10px;
  color: var(--text-muted);
}

.ctx-open-btn {
  flex-shrink: 0;
}
</style>
