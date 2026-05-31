<script setup lang="ts">
/**
 * 社区节点卡片 — 社区点击后展示
 */

import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Squares2X2Icon, SparklesIcon } from '@heroicons/vue/24/outline'
import { isLLMConfigured, explainCommunity } from '@/services/llmClient'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('RP-016')
const { t } = useI18n()

const props = defineProps<{
  commId: string
  nodeCount: number
  edgeCount: number
  qualityScore: number
  description?: string
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
    const result = await explainCommunity(
      {
        commId: props.commId,
        nodeCount: props.nodeCount,
        edgeCount: props.edgeCount,
        qualityScore: props.qualityScore,
        description: props.description,
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
  <div class="community-card">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div class="card-header">
      <Squares2X2Icon class="w-4 h-4 type-icon" />
      <span class="comm-id">{{ commId }}</span>
    </div>

    <div class="comm-stats">
      <div class="stat-item">
        <span class="stat-value">{{ nodeCount }}</span>
        <span class="stat-label">{{ t('report.nodes') }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-value">{{ edgeCount }}</span>
        <span class="stat-label">{{ t('report.edges') }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-value">{{ qualityScore.toFixed(2) }}</span>
        <span class="stat-label">{{ t('report.qualityScore') }}</span>
      </div>
    </div>

    <div
      v-if="description"
      class="comm-desc"
    >
      {{ description }}
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
.community-card {
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-secondary);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}

.type-icon {
  color: var(--accent);
}

.comm-id {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  font-family: var(--font-mono);
}

.comm-stats {
  display: flex;
  gap: 12px;
  margin-bottom: 8px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.stat-value {
  font-size: 16px;
  font-weight: 600;
  color: var(--accent);
}

.stat-label {
  font-size: 10px;
  color: var(--text-muted);
}

.comm-desc {
  font-size: 11px;
  color: var(--text-muted);
  padding: 4px 0;
  border-top: 1px solid var(--border);
  margin-top: 4px;
}

.ai-section { margin-top: 8px; }
.ai-btn { width: 100%; justify-content: center; color: var(--accent); }
.ai-loading { display: flex; align-items: center; gap: 6px; padding: 8px; font-size: 11px; color: var(--text-muted); }
.spinner { width: 12px; height: 12px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.6s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.ai-content { padding: 8px; background: var(--bg-primary); border-radius: 4px; font-size: 12px; line-height: 1.6; color: var(--text-primary); max-height: 200px; overflow: auto; }
.ai-error { padding: 6px 8px; font-size: 11px; color: var(--error); background: color-mix(in srgb, var(--error) 10%, transparent); border-radius: 4px; }
</style>
