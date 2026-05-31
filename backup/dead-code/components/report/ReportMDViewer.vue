<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { DocumentTextIcon } from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'

const { t } = useI18n()

const props = defineProps<{
  content: string
}>()

const emit = defineEmits<{
  'community-click': [commId: string]
}>()

const renderedHTML = ref('')
const mermaidBlocks = ref<Array<{ id: string; code: string }>>([])

const { showId, componentId } = useComponentId('RP-003')

function renderMarkdown(md: string): string {
  let html = md
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  html = html.replace(/^### (.*$)/gm, '<h3>$1</h3>')
  html = html.replace(/^## (.*$)/gm, '<h2>$1</h2>')
  html = html.replace(/^# (.*$)/gm, '<h1>$1</h1>')
  html = html.replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>')
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.*?)\*/g, '<em>$1</em>')
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')

  html = html.replace(/\[\[explain:([\w-]+)\]\]/g, '<button class="comm-link" data-comm-id="$1">$1</button>')

  html = html.replace(/^- (.*$)/gm, '<li>$1</li>')
  html = html.replace(/(<li>.*<\/li>
?)+/g, '<ul>$&</ul>')

  html = html.replace(/
/g, '<br>')

  return html
}

function extractMermaidBlocks(md: string) {
  const blocks: Array<{ id: string; code: string }> = []
  const regex = /```mermaid
([\s\S]*?)```/g
  let match
  let idx = 0
  while ((match = regex.exec(md)) !== null) {
    blocks.push({ id: `mermaid-${idx++}`, code: match[1].trim() })
  }
  return blocks
}

function processContent(content: string) {
  mermaidBlocks.value = extractMermaidBlocks(content)

  let html = content
  html = html.replace(/```mermaid
[\s\S]*?```/g, (match) => {
    const block = extractMermaidBlocks(match)
    if (block.length > 0) {
      return `<div class="mermaid-container" id="${block[0].id}"><div class="mermaid-loading">${t('report.mermaidRendering')}</div></div>`
    }
    return match
  })

  html = html.replace(/```plantuml
[\s\S]*?```/g, '<div class="plantuml-container"><span class="text-muted">PlantUML</span></div>')

  html = html.replace(/```(\w*)
([\s\S]*?)```/g, '<pre><code>$2</code></pre>')

  renderedHTML.value = renderMarkdown(html)
}

function handleContentClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (target.classList.contains('comm-link')) {
    const commId = target.getAttribute('data-comm-id')
    if (commId) {
      emit('community-click', commId)
    }
  }
}

onMounted(() => {
  processContent(props.content)
})

watch(() => props.content, (val) => {
  processContent(val)
})
</script>

<template>
  <div class="report-md-viewer" @click="handleContentClick">
    <span v-if="showId" class="cmp-id">{{ componentId }}</span>
    <div class="md-content" v-html="renderedHTML"></div>
    <div v-if="!content" class="empty-state">
      <DocumentTextIcon class="w-12 h-12" />
      <div class="empty-title">{{ t('report.noReportContent') }}</div>
    </div>
  </div>
</template>

<style scoped>
.report-md-viewer {
  height: 100%;
  overflow-y: auto;
  padding: 16px 24px;
}

.md-content {
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-primary);
}

.md-content :deep(h1) {
  font-size: 20px;
  font-weight: 700;
  margin: 20px 0 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}

.md-content :deep(h2) {
  font-size: 16px;
  font-weight: 600;
  margin: 16px 0 8px;
}

.md-content :deep(h3) {
  font-size: 14px;
  font-weight: 600;
  margin: 12px 0 6px;
}

.md-content :deep(p) {
  margin: 6px 0;
}

.md-content :deep(code) {
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--bg-tertiary);
  font-family: var(--font-mono);
  font-size: 12px;
}

.md-content :deep(pre) {
  padding: 10px 14px;
  border-radius: 6px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  overflow-x: auto;
  margin: 8px 0;
}

.md-content :deep(pre code) {
  background: none;
  padding: 0;
  font-size: 12px;
  line-height: 1.5;
}

.md-content :deep(ul) {
  padding-left: 20px;
  margin: 6px 0;
}

.md-content :deep(li) {
  margin: 3px 0;
}

.md-content :deep(strong) {
  font-weight: 600;
  color: var(--accent);
}

.md-content :deep(.comm-link) {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 1px 8px;
  font-size: 11px;
  font-weight: 500;
  border: none;
  border-radius: 8px;
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  color: var(--accent);
  cursor: pointer;
  transition: all 0.15s;
}

.md-content :deep(.comm-link:hover) {
  background: var(--accent);
  color: white;
}

.md-content :deep(.mermaid-container) {
  padding: 12px;
  margin: 8px 0;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  min-height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.mermaid-loading {
  font-size: 11px;
  color: var(--text-muted);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 8px;
  color: var(--text-muted);
}

.empty-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}
</style>
