<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useDiagramRenderer } from '@/composables/useDiagramRenderer'
import ChildSection from './ChildSection.vue'
import { useComponentId } from '@/composables/useComponentId'

const props = defineProps<{
  content: string
  taskId?: string
  projectId?: string
  parentLevel?: string
  parentCommId?: string
  parentEdgeType?: string
}>()

const emit = defineEmits<{
  'navigate-community': [payload: { taskId: string; communityId: string; edgeType: string }]
  'open-child-analysis': [payload: { taskId: string; parentLevel: string; parentCommId: string; edgeType: string; projectId?: string }]
  'view-child-md': [payload: { taskId: string; communityId: string; level: string; edgeType: string; parentLevel: string; parentCommId: string; name: string; summary: string; mermaid?: string; plantuml?: string }]
}>()

const loading = ref(false)

const { diagramBlocks, parseAndRender } = useDiagramRenderer()

const renderedContent = computed(() => {
  if (!props.content) return ''

  let html = props.content
  let diagIdx = 0

  html = html.replace(/```(mermaid|plantuml)\n([\s\S]*?)```/g, (_match, lang: string) => {
    const blk = diagramBlocks.value[diagIdx]
    const id = blk ? blk.id : `diagram-${diagIdx}`
    diagIdx++
    return `<div class="diagram-placeholder" id="inline-${id}" data-lang="${lang}"><div class="diagram-loading">${lang === 'mermaid' ? 'Mermaid' : 'PlantUML'} 渲染中...</div></div>`
  })

  html = html.replace(/^\s*\|(.+)\|\n\s*\|[-:| ]+\|\n((?:\s*\|.+\|\n?)*)/gm,
    (_match: string, headerRow: string, bodyRows: string) => {
      const headers = headerRow.split('|').map((h: string) => h.trim()).filter((h: string) => h)
      const rows = bodyRows.trim().split('\n').map((row: string) => {
        const cells = row.split('|').map((c: string) => c.trim()).filter((c: string) => c)
        return `<tr>${cells.map((c: string) => `<td>${c}</td>`).join('')}</tr>`
      })
      return `<table><thead><tr>${headers.map((h: string) => `<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`
    })

  html = html.replace(/\[([^\]]+)\]\(##community:([^:]+):([^)]+)\)/g,
    '<a href="#" class="community-link" data-edge-type="$2" data-community-id="$3">$1</a>')

  const tocAnchorMap = new Map<string, string>()
  html.replace(/\[([^\]]+)\]\(#([^)]+)\)/g, (_m: string, text: string, id: string) => {
    tocAnchorMap.set(text.trim(), id)
    return _m
  })

  function findAnchor(headingText: string): string | undefined {
    if (tocAnchorMap.has(headingText)) return tocAnchorMap.get(headingText)
    const commMatch = headingText.match(/\(([^)]+)\)$/)
    if (commMatch) {
      const commId = commMatch[1].toLowerCase()
      for (const [tocText, anchorId] of tocAnchorMap) {
        if (tocText.toLowerCase().includes(commId)) return anchorId
      }
    }
    return undefined
  }

  html = html.replace(/^### (.*$)/gm, (_m: string, t: string) => {
    const id = findAnchor(t) || ''
    return id ? `<h3 id="${id}">${t}</h3>` : `<h3>${t}</h3>`
  })
  html = html.replace(/^## (.*$)/gm, (_m: string, t: string) => {
    const id = findAnchor(t) || ''
    return id ? `<h2 id="${id}">${t}</h2>` : `<h2>${t}</h2>`
  })
  html = html.replace(/^# (.*$)/gm, (_m: string, t: string) => {
    const id = findAnchor(t) || ''
    return id ? `<h1 id="${id}">${t}</h1>` : `<h1>${t}</h1>`
  })

  html = html.replace(/^---+\s*$/gm, '<hr>')
  html = html.replace(/^\*\s+/gm, '\u2022 ')
  html = html.replace(/^-\s+/gm, '\u2022 ')
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.*?)\*/g, '<em>$1</em>')
  html = html.replace(/`(.*?)`/g, '<code>$1</code>')
  html = html.replace(/\n/g, '<br>')

  return html
})
const { showId, componentId } = useComponentId('SD-001')

watch(() => props.content, (val) => {
  if (val) {
    loading.value = true
    parseAndRender(val)
    nextTick(() => { loading.value = false })
  }
}, { immediate: true })

function onDocContentClick(e: MouseEvent) {
  const link = (e.target as HTMLElement)?.closest?.('.community-link') as HTMLElement | null
  if (!link || !props.taskId) return
  e.preventDefault()
  const communityId = link.dataset.communityId
  const edgeType = link.dataset.edgeType
  if (communityId && edgeType) {
    emit('navigate-community', { taskId: props.taskId, communityId, edgeType })
  }
}

function scrollToHash(targetId: string) {
  nextTick(() => {
    let el = document.getElementById(targetId)
    if (!el) {
      const textMatch = document.evaluate(
        `.//*[contains(text(), '${targetId.replace(/'/g, "\\'")}')]`,
        document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
      )
      el = textMatch.singleNodeValue as HTMLElement | null
    }
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      el.style.outline = '2px solid var(--accent)'
      setTimeout(() => { el!.style.outline = '' }, 2000)
    }
  })
}

function onHashChange() {
  const hash = window.location.hash
  if (hash) scrollToHash(hash.slice(1))
}

onMounted(() => {
  if (window.location.hash) {
    setTimeout(() => onHashChange(), 300)
  }
  window.addEventListener('hashchange', onHashChange)
})

onUnmounted(() => {
  window.removeEventListener('hashchange', onHashChange)
})
</script>

<template>
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
  <div
    v-if="loading"
    class="loading-state"
  >
    <div class="loading-spinner" />
    <span class="text-muted">加载中...</span>
  </div>
  <div
    v-else-if="content"
    class="subdoc-preview"
  >
    <div
      class="doc-content"
      @click="onDocContentClick"
      v-html="renderedContent"
    />

    <ChildSection
      v-if="taskId && parentLevel && parentCommId && parentEdgeType"
      :task-id="taskId!"
      :parent-level="parentLevel!"
      :parent-comm-id="parentCommId!"
      :edge-type="parentEdgeType!"
      :project-id="projectId"
      @open-child-analysis="(p: any) => emit('open-child-analysis', p)"
      @view-community-md="(p: any) => emit('view-child-md', p)"
    />
  </div>
</template>

<style scoped>
.loading-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; padding: 20px; color: var(--text-muted); font-size: 12px; height: 100%;
}
.loading-spinner {
  width: 24px; height: 24px; border: 2px solid var(--border);
  border-top-color: var(--accent); border-radius: 50%; animation: spin .6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.subdoc-preview {
  flex: 1; overflow-y: auto; padding: 16px 20px;
}

.doc-content {
  line-height: 1.7; color: var(--text-primary);
}

.doc-content :deep(h1) { font-size: 21px; font-weight: 700; margin: 20px 0 12px; }
.doc-content :deep(h2) { font-size: 17px; font-weight: 600; margin: 18px 0 10px; padding-bottom: 4px; border-bottom: 1px solid var(--border); }
.doc-content :deep(h3) { font-size: 14px; font-weight: 600; margin: 14px 0 8px; }
.doc-content :deep(p) { margin: 6px 0; }
.doc-content :deep(code) {
  background: var(--bg-tertiary); padding: 1px 5px; border-radius: 3px;
  font-family: var(--font-mono); font-size: 11px;
}
.doc-content :deep(pre) {
  background: var(--bg-secondary); padding: 10px 14px; border-radius: 6px;
  overflow-x: auto; margin: 8px 0;
}
.doc-content :deep(pre code) { background: none; padding: 0; }
.doc-content :deep(table) {
  border-collapse: collapse; width: 100%; margin: 8px 0;
}
.doc-content :deep(th), .doc-content :deep(td) {
  border: 1px solid var(--border); padding: 6px 10px; text-align: left; font-size: 12px;
}
.doc-content :deep(th) { background: var(--bg-tertiary); font-weight: 600; }
.doc-content :deep(a) { color: var(--accent); }
.doc-content :deep(a:hover) { text-decoration: underline; }
.doc-content :deep(hr) { border: none; border-top: 1px solid var(--border); margin: 12px 0; }

.doc-content :deep(.diagram-placeholder) {
  margin: 12px 0; padding: 24px 16px; border-radius: 8px;
  background: var(--bg-secondary); border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center; min-height: 200px;
  overflow-x: auto;
}
.doc-content :deep(.diagram-loading) { color: var(--text-muted); font-size: 12px; }
.doc-content :deep(.diagram-placeholder svg) { max-width: 100%; height: auto; }
.doc-content :deep(.diagram-error) {
  color: var(--error); font-size: 11px; margin-top: 8px; word-break: break-all;
}
.doc-content :deep(.fallback-diagram-header) {
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;
}
.doc-content :deep(.fallback-diagram-lang) {
  font-size: 10px; font-weight: 600; color: var(--text-muted); text-transform: uppercase;
}
.doc-content :deep(.fallback-diagram-copy) {
  background: var(--bg-tertiary); border: 1px solid var(--border); border-radius: 4px;
  padding: 2px 8px; font-size: 10px; color: var(--text-secondary); cursor: pointer;
}
.doc-content :deep(.fallback-code) {
  background: var(--bg-tertiary); padding: 8px 12px; border-radius: 4px;
  overflow-x: auto; font-size: 11px; max-height: 300px; overflow-y: auto;
}
.doc-content :deep(.community-link) {
  color: var(--accent); cursor: pointer;
}
.doc-content :deep(.community-link:hover) { text-decoration: underline; }
</style>
