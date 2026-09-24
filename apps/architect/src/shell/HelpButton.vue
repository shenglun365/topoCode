<!-- SYNC-WITH: packages/web-core/src/shell/HelpButton.vue（MS3-U1 独立化拷贝——改一方须 diff 另一方） -->
<script setup lang="ts">
import './toolbar.css'
import { tShell } from './i18n'

const props = withDefaults(defineProps<{
  href?: string
  title?: string
}>(), {
  href: '/',
  title: '',
})

function onClick() {
  if (props.href) window.location.href = props.href
}
</script>

<template>
  <button class="toolbar-btn" type="button" :title="title || tShell('help')" :aria-label="title || tShell('help')" @click="onClick">
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <circle cx="12" cy="12" r="10" />
      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
      <path d="M12 17h.01" />
    </svg>
  </button>
</template>
