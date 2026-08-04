<script setup lang="ts">
defineProps<{ title: string; desc?: string; action?: boolean }>()
</script>

<template>
  <div class="flex items-start justify-between px-5 pt-4 pb-2">
    <div>
      <h1 class="text-lg font-semibold text-ctp-text">
        {{ title }}
      </h1>
      <p
        v-if="desc"
        class="text-xs text-ctp-subtext0 mt-0.5 max-w-3xl"
      >
        {{ desc }}
      </p>
    </div>
    <div
      v-if="action"
      class="shrink-0 ml-4"
    >
      <slot name="action" />
    </div>
  </div>
</template>
