<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useDiagramRenderer } from '@/composables/useDiagramRenderer'
import { useComponentId } from '@topo/web-core/composables/useComponentId'

const { t } = useI18n()

const props = defineProps<{
  content: string
  taskId?: string
}>()

const emit = defineEmits<{
  'navigate-community': [payload: { taskId: string; communityId: string; edgeType: string }]
}>()

const loading = ref(false)

const { diagramBlocks, parseAndRender } = useDiagramRenderer()

const renderedContent = computed(() => {
  if (!props.content) return ''

  let html = props.content
  let diagIdx = 0

  // 将子组件列表按 依赖分析(INCLUDE) / 调用分析(CALL) 分组
  html = html.replace(/^## 子组件（(\d+)）\n([\s\S]+?)(?=\n## |\n---\n|$)/m,
    (_match: string, count: string, body: string) => {
      const lines = body.trim().split('\n')
      const includeLines: string[] = []
      const callLines: string[] = []
      for (const line of lines) {
        if (/\]\(##community:CALL:/.test(line)) callLines.push(line)
        else if (/\]\(##community:INCLUDE:/.test(line)) includeLines.push(line)
      }
      const parts: string[] = [`## ${t('report.structuralReport')}（${count}）`]
      if (includeLines.length > 0) {
        parts.push('', `### ${t('report.edgeType.dependency')}（${includeLines.length}）`, '', ...includeLines)
      }
      if (callLines.length > 0) {
        parts.push('', `### ${t('report.edgeType.call')}（${callLines.length}）`, '', ...callLines)
      }
      return parts.join('\n')
    })

  html = html.replace(/```(mermaid|plantuml)\n([\s\S]*?)```/g, (_match, lang: string) => {
    const blk = diagramBlocks.value[diagIdx]
    const id = blk ? blk.id : `diagram-${diagIdx}`
    diagIdx++
    return `<div class="diagram-placeholder" id="inline-${id}" data-lang="${lang}"><div class="diagram-loading">${lang === 'mermaid' ? 'Mermaid' : 'PlantUML'} ${t('report.diagram.rendering')}</div></div>`
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
    <span class="text-muted">{{ t('common.loading') }}</span>
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
  </div>
</template>

<style scoped>
.loading-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: calc(8px * var(--ui-scale, 1)); padding: calc(20px * var(--ui-scale, 1)); color: var(--text-muted); font-size: calc(12px * var(--ui-scale, 1)); height: 100%;
}
.loading-spinner {
  width: calc(24px * var(--ui-scale, 1)); height: calc(24px * var(--ui-scale, 1)); border: 2px solid var(--border);
  border-top-color: var(--accent); border-radius: 50%; animation: spin .6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.subdoc-preview {
  flex: 1; overflow-y: auto; padding: calc(16px * var(--ui-scale, 1)) calc(20px * var(--ui-scale, 1));
}

.doc-content {
  line-height: 1.7; color: var(--text-primary); white-space: pre-wrap;
}

.doc-content :deep(h1) { font-size: calc(21px * var(--ui-scale, 1)); font-weight: 700; margin: calc(20px * var(--ui-scale, 1)) 0 calc(12px * var(--ui-scale, 1)); }
.doc-content :deep(h2) { font-size: calc(17px * var(--ui-scale, 1)); font-weight: 600; margin: calc(18px * var(--ui-scale, 1)) 0 calc(10px * var(--ui-scale, 1)); padding-bottom: calc(4px * var(--ui-scale, 1)); border-bottom: 1px solid var(--border); }
.doc-content :deep(h3) { font-size: calc(14px * var(--ui-scale, 1)); font-weight: 600; margin: calc(14px * var(--ui-scale, 1)) 0 calc(8px * var(--ui-scale, 1)); }
.doc-content :deep(p) { margin: calc(6px * var(--ui-scale, 1)) 0; }
.doc-content :deep(code) {
  background: var(--bg-tertiary); padding: 1px calc(5px * var(--ui-scale, 1)); border-radius: calc(3px * var(--ui-scale, 1));
  font-family: var(--font-mono); font-size: calc(11px * var(--ui-scale, 1));
}
.doc-content :deep(pre) {
  background: var(--bg-secondary); padding: calc(10px * var(--ui-scale, 1)) calc(14px * var(--ui-scale, 1)); border-radius: calc(6px * var(--ui-scale, 1));
  overflow-x: auto; margin: calc(8px * var(--ui-scale, 1)) 0;
}
.doc-content :deep(pre code) { background: none; padding: 0; }
.doc-content :deep(table) {
  border-collapse: collapse; width: 100%; margin: calc(8px * var(--ui-scale, 1)) 0;
}
.doc-content :deep(th), .doc-content :deep(td) {
  border: 1px solid var(--border); padding: calc(6px * var(--ui-scale, 1)) calc(10px * var(--ui-scale, 1)); text-align: left; font-size: calc(12px * var(--ui-scale, 1));
}
.doc-content :deep(th) { background: var(--bg-tertiary); font-weight: 600; }
.doc-content :deep(a) { color: var(--accent); }
.doc-content :deep(a:hover) { text-decoration: underline; }
.doc-content :deep(hr) { border: none; border-top: 1px solid var(--border); margin: calc(12px * var(--ui-scale, 1)) 0; }

.doc-content :deep(.diagram-placeholder) {
  margin: calc(12px * var(--ui-scale, 1)) 0; padding: calc(24px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); border-radius: calc(8px * var(--ui-scale, 1));
  background: var(--bg-secondary); border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center; min-height: calc(200px * var(--ui-scale, 1));
  overflow-x: auto;
}
.doc-content :deep(.diagram-loading) { color: var(--text-muted); font-size: calc(12px * var(--ui-scale, 1)); }
.doc-content :deep(.diagram-placeholder svg) { max-width: 100%; height: auto; }
.doc-content :deep(.diagram-error) {
  color: var(--error); font-size: calc(11px * var(--ui-scale, 1)); margin-top: calc(8px * var(--ui-scale, 1)); word-break: break-all;
}
.doc-content :deep(.fallback-diagram-header) {
  display: flex; justify-content: space-between; align-items: center; margin-bottom: calc(8px * var(--ui-scale, 1));
}
.doc-content :deep(.fallback-diagram-lang) {
  font-size: calc(10px * var(--ui-scale, 1)); font-weight: 600; color: var(--text-muted); text-transform: uppercase;
}
.doc-content :deep(.fallback-diagram-copy) {
  background: var(--bg-tertiary); border: 1px solid var(--border); border-radius: calc(4px * var(--ui-scale, 1));
  padding: calc(2px * var(--ui-scale, 1)) calc(8px * var(--ui-scale, 1)); font-size: calc(10px * var(--ui-scale, 1)); color: var(--text-secondary); cursor: pointer;
}
.doc-content :deep(.fallback-code) {
  background: var(--bg-tertiary); padding: calc(8px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1)); border-radius: calc(4px * var(--ui-scale, 1));
  overflow-x: auto; font-size: calc(11px * var(--ui-scale, 1)); max-height: calc(300px * var(--ui-scale, 1)); overflow-y: auto;
}
.doc-content :deep(.community-link) {
  color: var(--accent); cursor: pointer;
}
.doc-content :deep(.community-link:hover) { text-decoration: underline; }
</style>
