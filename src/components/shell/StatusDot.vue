<template>
  <span
    class="status-dot"
    :class="`status-${status}`"
  >
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span></span>
</template>

<script setup lang="ts">import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('SH-007')
defineProps<{
  status: 'connected' | 'disconnected' | 'connecting' | 'loaded' | 'loading' | 'error' | 'not-installed'
}>()
</script>

<style scoped lang="scss">
.status-dot {
  @apply inline-block w-2 h-2 rounded-full;

  &.status-connected,
  &.status-loaded {
    @apply bg-green-400;
  }

  &.status-disconnected,
  &.status-not-installed {
    @apply bg-gray-400;
  }

  &.status-connecting,
  &.status-loading {
    @apply bg-yellow-400 animate-pulse;
  }

  &.status-error {
    @apply bg-red-400;
  }
}
</style>
