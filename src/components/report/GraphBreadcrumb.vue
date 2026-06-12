<script setup lang="ts">
import { ChevronLeftIcon, HomeIcon, ChevronRightIcon } from '@heroicons/vue/24/outline'

const props = defineProps<{
  path: Array<{ key: string; label: string; level?: string }>
}>()

const emit = defineEmits<{
  'click': [index: number]
  'roll-up': []
}>()
</script>

<template>
  <div class="gb-container">
    <button
      class="gb-home"
      :class="{ disabled: props.path.length <= 1 }"
      :disabled="props.path.length <= 1"
      @click="emit('roll-up')"
    >
      <ChevronLeftIcon class="w-3 h-3" />
    </button>
    <template
      v-for="(item, idx) in props.path"
      :key="item.key"
    >
      <ChevronRightIcon
        v-if="idx > 0"
        class="gb-sep w-3 h-3"
      />
      <button
        class="gb-item"
        :class="{ active: idx === props.path.length - 1 }"
        @click="emit('click', idx)"
      >
        {{ item.label }}
      </button>
    </template>
  </div>
</template>

<style scoped>
.gb-container { display: flex; align-items: center; gap: 0.15rem; flex: 1; overflow: hidden; }
.gb-home {
  display: flex; align-items: center; padding: 0.1rem;
  background: none; border: none; color: var(--text-muted); cursor: pointer;
  border-radius: 0.25rem; flex-shrink: 0;
}
.gb-home:hover:not(.disabled) { color: var(--text-primary); background: var(--bg-tertiary); }
.gb-home.disabled { opacity: 0.3; cursor: default; }
.gb-sep { flex-shrink: 0; color: var(--text-muted); opacity: 0.5; }
.gb-item {
  padding: 0.1rem 0.4rem; font-size: 0.75rem;
  background: none; border: none; color: var(--text-muted); cursor: pointer;
  border-radius: 0.25rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  max-width: 160px;
}
.gb-item:hover { color: var(--text-primary); background: var(--bg-tertiary); }
.gb-item.active { color: var(--accent, #7c3aed); font-weight: 500; cursor: default; }
</style>
