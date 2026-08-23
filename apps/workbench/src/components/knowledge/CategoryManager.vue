<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import {
  ArrowPathIcon,
  WrenchScrewdriverIcon,
  CubeIcon,
  SparklesIcon,
  PlusIcon,
  LightBulbIcon,
} from '@heroicons/vue/24/outline'
import { knowledgeDimensions } from '@/utils/mock'
import { useComponentId } from '@topo/web-core/composables/useComponentId'

const { showId, componentId } = useComponentId('KN-005')
const { t } = useI18n()

const dimensions = [
  {
    key: 'lifecycle' as const,
    name: () => t('knowledge.lifecycle'),
    icon: ArrowPathIcon,
    tags: knowledgeDimensions.lifecycle,
  },
  {
    key: 'techStack' as const,
    name: () => t('knowledge.techStack'),
    icon: WrenchScrewdriverIcon,
    tags: knowledgeDimensions.techStack,
  },
  {
    key: 'abstraction' as const,
    name: () => t('knowledge.abstractionLevel'),
    icon: CubeIcon,
    tags: knowledgeDimensions.abstraction,
  },
  {
    key: 'purpose' as const,
    name: () => t('knowledge.knowledgeAttribute'),
    icon: SparklesIcon,
    tags: knowledgeDimensions.purpose,
  },
]
</script>

<template>
  <div class="category-manager">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 头部 -->
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:calc(12px * var(--ui-scale, 1));">
      <div>
        <h2 style="font-size:calc(16px * var(--ui-scale, 1)); font-weight:600;">
          {{ t('knowledge.categories') }}
        </h2>
        <p
          class="text-muted"
          style="font-size:calc(12px * var(--ui-scale, 1)); margin-top:calc(4px * var(--ui-scale, 1));"
        >
          {{ t('knowledge.filterByDimension') }}
        </p>
      </div>
      <button class="btn btn-ghost btn-sm">
        <LightBulbIcon class="w-4 h-4" />
        <span>{{ t('knowledge.recommendTags') }}</span>
      </button>
    </div>

    <!-- 维度卡片 -->
    <div
      v-for="dim in dimensions"
      :key="dim.key"
      class="card"
      style="padding:calc(14px * var(--ui-scale, 1)); margin-bottom:calc(12px * var(--ui-scale, 1));"
    >
      <!-- 维度头部 -->
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:calc(10px * var(--ui-scale, 1));">
        <div style="display:flex; align-items:center; gap:calc(8px * var(--ui-scale, 1));">
          <component
            :is="dim.icon"
            class="w-5 h-5 text-accent"
          />
          <span style="font-size:calc(13px * var(--ui-scale, 1)); font-weight:600;">{{ dim.name() }}</span>
          <span
            class="badge badge-blue"
            style="font-size:calc(9px * var(--ui-scale, 1));"
          >{{ dim.tags.length }} {{ t('common.tag') }}</span>
        </div>
        <div style="display:flex; gap:calc(4px * var(--ui-scale, 1));">
          <button class="btn btn-ghost btn-sm">
            <PlusIcon class="w-3 h-3" />
            <span>{{ t('common.add') }}</span>
          </button>
          <button class="btn btn-ghost btn-sm">
            <LightBulbIcon class="w-3 h-3" />
            <span>{{ t('knowledge.recommendTags') }}</span>
          </button>
        </div>
      </div>

      <!-- 标签列表 -->
      <div style="display:flex; flex-wrap:wrap; gap:calc(6px * var(--ui-scale, 1));">
        <span
          v-for="tag in dim.tags"
          :key="tag"
          class="kb-tag"
          :class="`kb-tag-${dim.key}`"
          style="cursor:pointer;"
        >
          {{ tag }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.category-manager {
  height: 100%;
  overflow: auto;
  padding: calc(16px * var(--ui-scale, 1));
}

.kb-tag {
  display: inline-block;
  padding: calc(4px * var(--ui-scale, 1)) calc(10px * var(--ui-scale, 1));
  font-size: calc(11px * var(--ui-scale, 1));
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  transition: all 0.15s;
}

.kb-tag:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 5%, transparent);
}

/* 维度颜色 */
.kb-tag-lifecycle {
  border-color: var(--accent);
  color: var(--accent);
}
.kb-tag-techStack {
  border-color: var(--success);
  color: var(--success);
}
.kb-tag-abstraction {
  border-color: var(--warning);
  color: var(--warning);
}
.kb-tag-purpose {
  border-color: var(--error);
  color: var(--error);
}
</style>
