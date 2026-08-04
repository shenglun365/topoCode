<script setup lang="ts">
import { onMounted, ref } from 'vue'
import MarkdownIt from 'markdown-it'

const props = defineProps<{ content: string }>()

const md = new MarkdownIt({ html: true, linkify: true, breaks: true })
const html = ref('')

onMounted(() => {
  html.value = md.render(props.content)
})
</script>

<template>
  <!-- eslint-disable vue/no-v-html -->
  <div
    class="md-body"
    v-html="html"
  />
  <!-- eslint-enable vue/no-v-html -->
</template>
