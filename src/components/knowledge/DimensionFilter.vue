<template>
  <div class="dimension-filter">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div class="filter-header">
      <span class="filter-title">{{ t('knowledge.dimensionFilter') }}</span>
      <button
        v-if="hasSelection"
        class="clear-btn"
        @click="clearAll"
      >
        <XMarkIcon class="w-3.5 h-3.5" />
        {{ t('knowledge.clearFilters') }}
      </button>
    </div>

    <div class="filter-dimensions">
      <!-- 开发生命周期 -->
      <div class="dimension-item">
        <button
          class="dimension-header"
          @click="toggleDimension('lifecycle')"
        >
          <div class="dimension-icon lifecycle">
            <ArrowPathIcon class="w-4 h-4" />
          </div>
          <span class="dimension-name">{{ t('knowledge.lifecycle') }}</span>
          <span class="dimension-count">{{ dimensions.lifecycle.length }}</span>
          <ChevronRightIcon :class="['dimension-arrow', { expanded: expandedDimensions.lifecycle }]" />
        </button>
        <div
          v-if="expandedDimensions.lifecycle"
          class="dimension-tags"
        >
          <button
            v-for="tag in dimensions.lifecycle"
            :key="tag"
            class="tag-chip lifecycle"
            :class="{ selected: isSelected('lifecycle', tag) }"
            @click="toggleTag('lifecycle', tag)"
          >
            <CheckIcon
              v-if="isSelected('lifecycle', tag)"
              class="w-3 h-3"
            />
            {{ tag }}
          </button>
        </div>
      </div>

      <!-- 技术栈工具链 -->
      <div class="dimension-item">
        <button
          class="dimension-header"
          @click="toggleDimension('techStack')"
        >
          <div class="dimension-icon tech">
            <WrenchScrewdriverIcon class="w-4 h-4" />
          </div>
          <span class="dimension-name">{{ t('knowledge.techStack') }}</span>
          <span class="dimension-count">{{ dimensions.techStack.length }}</span>
          <ChevronRightIcon :class="['dimension-arrow', { expanded: expandedDimensions.techStack }]" />
        </button>
        <div
          v-if="expandedDimensions.techStack"
          class="dimension-tags"
        >
          <button
            v-for="tag in dimensions.techStack"
            :key="tag"
            class="tag-chip tech"
            :class="{ selected: isSelected('techStack', tag) }"
            @click="toggleTag('techStack', tag)"
          >
            <CheckIcon
              v-if="isSelected('techStack', tag)"
              class="w-3 h-3"
            />
            {{ tag }}
          </button>
        </div>
      </div>

      <!-- 抽象层级 -->
      <div class="dimension-item">
        <button
          class="dimension-header"
          @click="toggleDimension('abstraction')"
        >
          <div class="dimension-icon abstraction">
            <Square3Stack3DIcon class="w-4 h-4" />
          </div>
          <span class="dimension-name">{{ t('knowledge.abstraction') }}</span>
          <span class="dimension-count">{{ dimensions.abstraction.length }}</span>
          <ChevronRightIcon :class="['dimension-arrow', { expanded: expandedDimensions.abstraction }]" />
        </button>
        <div
          v-if="expandedDimensions.abstraction"
          class="dimension-tags"
        >
          <button
            v-for="tag in dimensions.abstraction"
            :key="tag"
            class="tag-chip abstraction"
            :class="{ selected: isSelected('abstraction', tag) }"
            @click="toggleTag('abstraction', tag)"
          >
            <CheckIcon
              v-if="isSelected('abstraction', tag)"
              class="w-3 h-3"
            />
            {{ tag }}
          </button>
        </div>
      </div>

      <!-- 知识属性 -->
      <div class="dimension-item">
        <button
          class="dimension-header"
          @click="toggleDimension('purpose')"
        >
          <div class="dimension-icon purpose">
            <TargetIcon class="w-4 h-4" />
          </div>
          <span class="dimension-name">{{ t('knowledge.purpose') }}</span>
          <span class="dimension-count">{{ dimensions.purpose.length }}</span>
          <ChevronRightIcon :class="['dimension-arrow', { expanded: expandedDimensions.purpose }]" />
        </button>
        <div
          v-if="expandedDimensions.purpose"
          class="dimension-tags"
        >
          <button
            v-for="tag in dimensions.purpose"
            :key="tag"
            class="tag-chip purpose"
            :class="{ selected: isSelected('purpose', tag) }"
            @click="toggleTag('purpose', tag)"
          >
            <CheckIcon
              v-if="isSelected('purpose', tag)"
              class="w-3 h-3"
            />
            {{ tag }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowPathIcon,
  WrenchScrewdriverIcon,
  Square3Stack3DIcon,
  TargetIcon,
  ChevronRightIcon,
  CheckIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'
import type { Dimensions } from '@/types/ipc'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('KN-004')
const { t } = useI18n()

const props = defineProps<{
  dimensions: Dimensions
  selectedTags: Record<string, string[]>
}>()

const emit = defineEmits<{
  'toggle-dimension': [dimension: string]
  'toggle-tag': [dimension: string, tag: string]
  'clear': []
}>()

const expandedDimensions = ref<Record<string, boolean>>({
  lifecycle: true,
  techStack: false,
  abstraction: false,
  purpose: false,
})

const hasSelection = computed(() => {
  return Object.values(props.selectedTags).some(tags => tags.length > 0)
})

function toggleDimension(dimension: string) {
  expandedDimensions.value[dimension] = !expandedDimensions.value[dimension]
  emit('toggle-dimension', dimension)
}

function isSelected(dimension: string, tag: string): boolean {
  return (props.selectedTags[dimension] || []).includes(tag)
}

function toggleTag(dimension: string, tag: string) {
  emit('toggle-tag', dimension, tag)
}

function clearAll() {
  emit('clear')
}
</script>

<style scoped lang="scss">
.dimension-filter {
  @apply rounded-lg border border-[--border] bg-[--bg-secondary] p-3;
}

.filter-header {
  @apply flex items-center justify-between mb-2;
}

.filter-title {
  @apply text-xs font-semibold text-[--text-secondary] uppercase;
}

.clear-btn {
  @apply flex items-center gap-1 px-2 py-1 text-xs text-[--accent] hover:text-[--accent-hover] hover:bg-[--bg-hover] rounded transition-colors;
}

.filter-dimensions {
  @apply flex flex-col gap-1;
}

.dimension-item {
  @apply border-b border-[--border] last:border-b-0;
}

.dimension-header {
  @apply w-full flex items-center gap-2 px-2 py-2 text-left hover:bg-[--bg-hover] rounded transition-colors;
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

.dimension-name {
  @apply text-xs font-semibold text-[--text-primary] flex-1;
}

.dimension-count {
  @apply text-xs text-[--text-muted];
}

.dimension-arrow {
  @apply w-4 h-4 text-[--text-muted] transition-transform;

  &.expanded {
    @apply rotate-90;
  }
}

.dimension-tags {
  @apply flex flex-wrap gap-1 px-2 pb-2;
}

.tag-chip {
  @apply inline-flex items-center gap-1 px-2 py-1 text-xs rounded-full border transition-colors;

  &.lifecycle {
    @apply border-blue-500/30 text-blue-400 hover:bg-blue-500/20;

    &.selected {
      @apply bg-blue-500/30 border-blue-500/50;
    }
  }

  &.tech {
    @apply border-green-500/30 text-green-400 hover:bg-green-500/20;

    &.selected {
      @apply bg-green-500/30 border-green-500/50;
    }
  }

  &.abstraction {
    @apply border-purple-500/30 text-purple-400 hover:bg-purple-500/20;

    &.selected {
      @apply bg-purple-500/30 border-purple-500/50;
    }
  }

  &.purpose {
    @apply border-orange-500/30 text-orange-400 hover:bg-orange-500/20;

    &.selected {
      @apply bg-orange-500/30 border-orange-500/50;
    }
  }
}
</style>
