<script setup lang="ts">
/**
 * 边详情卡片 — 边点击后展示
 */

import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowRightIcon, SparklesIcon } from '@heroicons/vue/24/outline'
import { isLLMConfigured, explainEdge } from '@/services/llmClient'
import { useComponentId } from '@topo/web-core/composables/useComponentId'

const { showId, componentId } = useComponentId('RP-017')
const { t } = useI18n()

const props = defineProps<{
  edgeId: string
  edgeType: 'CALL' | 'DEPENDENCE'
  source: { name: string; file_id?: string }
  target: { name: string; file_id?: string }
  callSiteNode?: string
  includePath?: string
  isSystem?: boolean
}>()

const emit = defineEmits<{
  aiResult: [content: string]
}>()

const aiLoading = ref(false)
const aiContent = ref('')
const aiError = ref<string | null>(null)
const llmAvailable = isLLMConfigured()

async function handleAIExplain() {
  if (!llmAvailable) {
    aiError.value = t('report.noApiConfig')
    return
  }
  aiLoading.value = true
  aiContent.value = ''
  aiError.value = null

  try {
    const result = await explainEdge(
      {
        edgeType: props.edgeType,
        source: props.source.name,
        target: props.target.name,
        callSite: props.callSiteNode,
        includePath: props.includePath,
        isSystem: props.isSystem,
      },
      (chunk) => { aiContent.value += chunk }
    )
    emit('aiResult', result)
  } catch (e: any) {
    aiError.value = e.message || String(e)
  } finally {
    aiLoading.value = false
  }
}
</script>

<template>
  <div class="edge-detail-card">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div class="card-header">
      <span class="edge-type-badge">{{ edgeType === 'CALL' ? t('report.edgeType.call') : t('report.edgeType.dependency') }}</span>
    </div>

    <div class="edge-flow">
      <div class="flow-node">
        <span class="node-label">{{ source.name }}</span>
      </div>
      <ArrowRightIcon class="w-4 h-4 flow-arrow" />
      <div class="flow-node">
        <span class="node-label">{{ target.name }}</span>
      </div>
    </div>

    <div
      v-if="callSiteNode"
      class="edge-meta"
    >
      <span class="meta-label">{{ t('report.callSite') }}:</span>
      <span class="meta-value">{{ callSiteNode }}</span>
    </div>
    <div
      v-if="includePath"
      class="edge-meta"
    >
      <span class="meta-label">{{ t('report.includePath') }}:</span>
      <span class="meta-value">{{ includePath }}</span>
    </div>
    <div
      v-if="isSystem !== undefined"
      class="edge-meta"
    >
      <span class="meta-label">{{ t('report.systemHeader') }}:</span>
      <span class="meta-value">{{ isSystem ? t('common.yes') : t('common.no') }}</span>
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
        {{ aiContent }}
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
.edge-detail-card {
  padding: calc(10px * var(--ui-scale, 1));
  border: 1px solid var(--border);
  border-radius: calc(6px * var(--ui-scale, 1));
  background: var(--bg-secondary);
}

.card-header {
  margin-bottom: calc(8px * var(--ui-scale, 1));
}

.edge-type-badge {
  font-size: calc(10px * var(--ui-scale, 1));
  padding: 1px calc(6px * var(--ui-scale, 1));
  border-radius: calc(3px * var(--ui-scale, 1));
  background: color-mix(in srgb, var(--accent) 15%, transparent);
  color: var(--accent);
  font-weight: 500;
}

.edge-flow {
  display: flex;
  align-items: center;
  gap: calc(8px * var(--ui-scale, 1));
  margin-bottom: calc(8px * var(--ui-scale, 1));
}

.flow-node {
  flex: 1;
  padding: calc(4px * var(--ui-scale, 1)) calc(8px * var(--ui-scale, 1));
  background: var(--bg-primary);
  border-radius: calc(4px * var(--ui-scale, 1));
  text-align: center;
}

.node-label {
  font-size: calc(12px * var(--ui-scale, 1));
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: block;
}

.flow-arrow {
  color: var(--accent);
  flex-shrink: 0;
}

.edge-meta {
  display: flex;
  gap: calc(6px * var(--ui-scale, 1));
  font-size: calc(11px * var(--ui-scale, 1));
  padding: calc(2px * var(--ui-scale, 1)) 0;
}

.meta-label {
  color: var(--text-muted);
  flex-shrink: 0;
}

.meta-value {
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ai-section { margin-top: calc(8px * var(--ui-scale, 1)); }
.ai-btn { width: 100%; justify-content: center; color: var(--accent); }
.ai-loading { display: flex; align-items: center; gap: calc(6px * var(--ui-scale, 1)); padding: calc(8px * var(--ui-scale, 1)); font-size: calc(11px * var(--ui-scale, 1)); color: var(--text-muted); }
.spinner { width: calc(12px * var(--ui-scale, 1)); height: calc(12px * var(--ui-scale, 1)); border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.6s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.ai-content { padding: calc(8px * var(--ui-scale, 1)); background: var(--bg-primary); border-radius: calc(4px * var(--ui-scale, 1)); font-size: calc(12px * var(--ui-scale, 1)); line-height: 1.6; color: var(--text-primary); max-height: calc(200px * var(--ui-scale, 1)); overflow: auto; }
.ai-error { padding: calc(6px * var(--ui-scale, 1)) calc(8px * var(--ui-scale, 1)); font-size: calc(11px * var(--ui-scale, 1)); color: var(--error); background: color-mix(in srgb, var(--error) 10%, transparent); border-radius: calc(4px * var(--ui-scale, 1)); }
</style>
