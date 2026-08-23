<script setup lang="ts">
/**
 * 符号详情卡片 — 节点点击后展示
 *
 * 显示: 符号名 + 类型 + 文件路径 + 行号 + 代码抽样
 * 支持: 源码链接跳转、AI 解释
 */

import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  CodeBracketIcon,
  DocumentTextIcon,
  SparklesIcon,
} from '@heroicons/vue/24/outline'
import { isLLMConfigured, explainSymbol } from '@/services/llmClient'
import { useComponentId } from '@topo/web-core/composables/useComponentId'

const { showId, componentId } = useComponentId('RP-018')
const { t } = useI18n()

const props = defineProps<{
  symbolId: string
  symbolType: string
  name: string
  className?: string
  filePath: string
  startLine: number
  endLine: number
  codeSnippet: string
  needsSummarize?: boolean
}>()

const emit = defineEmits<{
  openSource: [filePath: string, line: number]
  aiResult: [content: string]
}>()

const aiLoading = ref(false)
const aiContent = ref('')
const aiError = ref<string | null>(null)
const llmAvailable = isLLMConfigured()

const typeLabel = computed(() => {
  const map: Record<string, string> = {
    function: t('report.symbol.type.function'),
    class: t('report.symbol.type.class'),
    method: t('report.symbol.type.method'),
    macro: t('report.symbol.type.macro'),
  }
  return map[props.symbolType] || props.symbolType
})

const displayCode = computed(() => {
  if (props.codeSnippet.length > 2000) {
    return props.codeSnippet.substring(0, 2000) + '\n' + t('report.symbol.codeTooLongHint')
  }
  return props.codeSnippet
})

async function handleAIExplain() {
  if (!llmAvailable) {
    aiError.value = t('report.noApiConfig')
    return
  }
  aiLoading.value = true
  aiContent.value = ''
  aiError.value = null

  try {
    const result = await explainSymbol(
      {
        symbolName: props.name,
        symbolType: props.symbolType,
        codeSnippet: props.codeSnippet,
        fileName: props.filePath,
      },
      (chunk) => {
        aiContent.value += chunk
      }
    )
    emit('aiResult', result)
  } catch (e: any) {
    aiError.value = e.message || String(e)
  } finally {
    aiLoading.value = false
  }
}

function handleOpenSource() {
  emit('openSource', props.filePath, props.startLine)
}
</script>

<template>
  <div class="symbol-detail-card">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 头部 -->
    <div class="card-header">
      <CodeBracketIcon class="w-4 h-4 type-icon" />
      <span class="type-badge">{{ typeLabel }}</span>
      <span class="symbol-name">{{ name }}</span>
      <span
        v-if="className"
        class="class-prefix"
      >{{ className }}::</span>
    </div>

    <!-- 文件信息 -->
    <div
      class="file-info"
      @click="handleOpenSource"
    >
      <DocumentTextIcon class="w-3.5 h-3.5" />
      <span
        class="file-path"
        :title="filePath"
      >{{ filePath }}</span>
      <span class="line-range">{{ startLine }}-{{ endLine }}</span>
    </div>

    <!-- 代码抽样 -->
    <div
      v-if="codeSnippet"
      class="code-section"
    >
      <div class="code-header">
        <span>{{ t('common.code') }}</span>
        <span
          v-if="needsSummarize"
          class="summarize-hint"
        >{{ t('report.needsSummarize') }}</span>
      </div>
      <pre class="code-block"><code>{{ displayCode }}</code></pre>
    </div>

    <!-- AI 解释 -->
    <div class="ai-section">
      <button
        v-if="!aiContent && !aiLoading"
        class="btn btn-ghost btn-sm ai-btn"
        :disabled="!llmAvailable"
        @click="handleAIExplain"
      >
        <SparklesIcon class="w-4 h-4" />
        <span>{{ t('report.aiExplain') }}</span>
      </button>

      <div
        v-if="aiLoading"
        class="ai-loading"
      >
        <span class="spinner" />
        <span>{{ t('report.aiExplainLoading') }}</span>
      </div>

      <div
        v-if="aiContent"
        class="ai-content"
      >
        <div class="ai-text">
          {{ aiContent }}
        </div>
      </div>

      <div
        v-if="aiError"
        class="ai-error"
      >
        {{ aiError }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.symbol-detail-card {
  padding: calc(10px * var(--ui-scale, 1));
  border: 1px solid var(--border);
  border-radius: calc(6px * var(--ui-scale, 1));
  background: var(--bg-secondary);
}

.card-header {
  display: flex;
  align-items: center;
  gap: calc(6px * var(--ui-scale, 1));
  margin-bottom: calc(8px * var(--ui-scale, 1));
}

.type-icon {
  color: var(--accent);
}

.type-badge {
  font-size: calc(10px * var(--ui-scale, 1));
  padding: 1px calc(6px * var(--ui-scale, 1));
  border-radius: calc(3px * var(--ui-scale, 1));
  background: color-mix(in srgb, var(--accent) 15%, transparent);
  color: var(--accent);
  font-weight: 500;
}

.symbol-name {
  font-size: calc(13px * var(--ui-scale, 1));
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.class-prefix {
  font-size: calc(11px * var(--ui-scale, 1));
  color: var(--text-muted);
}

.file-info {
  display: flex;
  align-items: center;
  gap: calc(4px * var(--ui-scale, 1));
  padding: calc(4px * var(--ui-scale, 1)) calc(6px * var(--ui-scale, 1));
  margin-bottom: calc(8px * var(--ui-scale, 1));
  border-radius: calc(4px * var(--ui-scale, 1));
  cursor: pointer;
  transition: background 0.15s;
}

.file-info:hover {
  background: var(--bg-hover);
}

.file-path {
  font-size: calc(11px * var(--ui-scale, 1));
  color: var(--accent);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.line-range {
  font-size: calc(10px * var(--ui-scale, 1));
  color: var(--text-muted);
  flex-shrink: 0;
}

.code-section {
  margin-bottom: calc(8px * var(--ui-scale, 1));
}

.code-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: calc(11px * var(--ui-scale, 1));
  color: var(--text-muted);
  margin-bottom: calc(4px * var(--ui-scale, 1));
}

.summarize-hint {
  font-size: calc(10px * var(--ui-scale, 1));
  color: var(--warning);
}

.code-block {
  max-height: calc(160px * var(--ui-scale, 1));
  overflow: auto;
  padding: calc(8px * var(--ui-scale, 1));
  background: var(--bg-primary);
  border-radius: calc(4px * var(--ui-scale, 1));
  font-size: calc(11px * var(--ui-scale, 1));
  line-height: 1.5;
  font-family: var(--font-mono);
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-all;
}

.ai-section {
  margin-top: calc(8px * var(--ui-scale, 1));
}

.ai-btn {
  width: 100%;
  justify-content: center;
  color: var(--accent);
}

.ai-loading {
  display: flex;
  align-items: center;
  gap: calc(6px * var(--ui-scale, 1));
  padding: calc(8px * var(--ui-scale, 1));
  font-size: calc(11px * var(--ui-scale, 1));
  color: var(--text-muted);
}

.spinner {
  width: calc(12px * var(--ui-scale, 1));
  height: calc(12px * var(--ui-scale, 1));
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.ai-content {
  padding: calc(8px * var(--ui-scale, 1));
  background: var(--bg-primary);
  border-radius: calc(4px * var(--ui-scale, 1));
  font-size: calc(12px * var(--ui-scale, 1));
  line-height: 1.6;
  color: var(--text-primary);
  max-height: calc(200px * var(--ui-scale, 1));
  overflow: auto;
}

.ai-error {
  padding: calc(6px * var(--ui-scale, 1)) calc(8px * var(--ui-scale, 1));
  font-size: calc(11px * var(--ui-scale, 1));
  color: var(--error);
  background: color-mix(in srgb, var(--error) 10%, transparent);
  border-radius: calc(4px * var(--ui-scale, 1));
}
</style>
