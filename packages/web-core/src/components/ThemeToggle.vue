<script setup lang="ts">
import { useTheme } from '../composables/useTheme'

const props = defineProps<{
  appKey: string
  size?: number
}>()

const { theme, toggle } = useTheme(props.appKey)
</script>

<template>
  <button
    class="theme-toggle"
    type="button"
    :title="theme === 'dark' ? '切换到亮色' : '切换到暗色'"
    :style="{ width: 'calc(' + size + 'px * var(--ui-scale, 1))', height: 'calc(' + size + 'px * var(--ui-scale, 1))' }"
    @click="toggle"
  >
    <svg
      v-if="theme === 'dark'"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
    </svg>
    <svg
      v-else
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  </button>
</template>

<style scoped>
.theme-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border, #e4e4e7);
  border-radius: var(--radius-sm, 6px);
  background: var(--bg-card, #ffffff);
  color: var(--text-secondary, #6b6b76);
  cursor: pointer;
  flex-shrink: 0;
  transition: border-color 0.18s ease, color 0.18s ease;
}
.theme-toggle:hover {
  border-color: var(--accent, #4d6bfe);
  color: var(--accent, #4d6bfe);
}
.theme-toggle svg {
  width: calc(16px * var(--ui-scale, 1));
  height: calc(16px * var(--ui-scale, 1));
  flex-shrink: 0;
}
</style>
