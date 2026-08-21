<script setup lang="ts">
import { computed } from 'vue'
import { parseMessageBlocks } from '@/services/parse-message-blocks'
import MarkdownView from '@/components/MarkdownView.vue'
import DiagramCard from '@/components/diagram/DiagramCard.vue'
import type { DiagramLang } from '@/composables/useDiagramRenderer'

const props = defineProps<{ content: string }>()

const blocks = computed(() => parseMessageBlocks(props.content))
</script>

<template>
  <div
    v-for="(b, bi) in blocks"
    :key="bi"
    class="min-w-0"
  >
    <MarkdownView
      v-if="b.type === 'text'"
      :content="b.text"
    />
    <div
      v-else
      class="my-1.5 border border-ctp-surface0 rounded-lg overflow-hidden"
    >
      <DiagramCard
        :title="b.type"
        :diagrams="{ [b.type]: b.code } as Partial<Record<DiagramLang, string>>"
        :default-lang="b.type"
      />
    </div>
  </div>
</template>
