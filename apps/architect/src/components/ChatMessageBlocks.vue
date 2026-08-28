<script setup lang="ts">
import { computed } from 'vue'
import { parseMessageBlocks } from '@/services/parse-message-blocks'
import MarkdownView from '@/components/MarkdownView.vue'
import DiagramCard from '@/components/diagram/DiagramCard.vue'
import TopoDiagram from '@topo/web-core/topoOne/vue/TopoDiagram.vue'
import { themeVariablesFor } from '@topo/web-core/topoOne/vue/themes.ts'
import type { DiagramLang } from '@/composables/useDiagramRenderer'

const props = defineProps<{ content: string }>()

const blocks = computed(() => parseMessageBlocks(props.content))

/** 主题跟随 data-theme(catppuccin 变量随主题切换)。 */
const themeMode = computed<'dark' | 'light'>(() =>
  (typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'light') ? 'light' : 'dark')
const themeVars = computed(() => themeVariablesFor(themeMode.value))
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
      v-else-if="b.type === 'diagram'"
      class="my-1.5 border border-ctp-surface0 rounded-lg overflow-hidden p-1.5"
    >
      <TopoDiagram
        :schema="b.schema"
        engine="auto"
        :theme="themeMode"
        :theme-variables="themeVars"
        security-level="loose"
        auto-play
      />
    </div>
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
