<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useReportStore } from '@/stores/report-store'
import { useCommunityStore } from '@/stores/community-store'
import { useComponentId } from '@/composables/useComponentId'

const { t } = useI18n()
const reportStore = useReportStore()
const communityStore = useCommunityStore()

const props = defineProps<{
  visible: boolean
  regenerationType: 'community' | 'overall'
  taskId: string
  projectId: string
  existingMermaid: string
  existingPlantuml: string
  parentCommId?: string
  parentLevel?: string
  parentEdgeType?: string
}>()

const emit = defineEmits<{
  close: []
  regenerated: [payload: { content: string; mode: 'full' | 'mermaid' | 'plantuml' }]
}>()

const regenMode = ref<'full' | 'mermaid' | 'plantuml'>('full')
const regenSubMode = ref<'ai' | 'manual'>('ai')
const regenPrompt = ref('')
const regenManualCode = ref('')
const regenLoading = ref(false)
const regenError = ref('')

const existingDiagramCode = computed(() => {
  if (regenMode.value === 'mermaid') return props.existingMermaid
  if (regenMode.value === 'plantuml') return props.existingPlantuml
  return ''
})
const { showId, componentId } = useComponentId('SR-001')

watch(regenSubMode, (val) => {
  if (val === 'manual' && !regenManualCode.value) {
    regenManualCode.value = existingDiagramCode.value
  }
})

watch(() => props.visible, (val) => {
  if (val) {
    regenMode.value = 'full'
    regenSubMode.value = 'ai'
    regenPrompt.value = ''
    regenManualCode.value = ''
    regenError.value = ''
  }
})

async function submitRegen() {
  if (!props.taskId || !props.projectId) return
  if (props.regenerationType === 'community' && (!props.parentCommId || !props.parentLevel || !props.parentEdgeType)) {
    regenError.value = 'Missing community context for regeneration'
    return
  }
  regenLoading.value = true
  regenError.value = ''

  try {
    if (regenMode.value === 'mermaid' || regenMode.value === 'plantuml') {
      if (regenSubMode.value === 'manual') {
        if (!regenManualCode.value.trim()) {
          regenError.value = 'Please enter diagram code'
          regenLoading.value = false
          return
        }
        const current = await window.api?.analysis.getCommunityResult({
          taskId: props.taskId, edgeType: props.parentEdgeType!,
          commLv: props.parentLevel!, commId: props.parentCommId!,
        }).catch(() => null)
        const code = regenManualCode.value.trim()
        await communityStore.saveCommunityResult({
          taskId: props.taskId, edgeType: props.parentEdgeType || '',
          commLv: props.parentLevel || '', commId: props.parentCommId || '',
          name: current?.name || props.parentCommId,
          summary: current?.summary || '',
          mermaid: regenMode.value === 'mermaid' ? code : (current?.mermaid || ''),
          plantuml: regenMode.value === 'plantuml' ? code : (current?.plantuml || ''),
          modelId: current?.model_id,
          templateId: current?.template_id || 'community_analyze',
        })
        emit('regenerated', { content: code, mode: regenMode.value })
        regenLoading.value = false
        return
      }

      const existing = regenMode.value === 'mermaid' ? props.existingMermaid : props.existingPlantuml
      if (!existing) {
        regenError.value = `No existing ${regenMode.value} code found in document`
        regenLoading.value = false
        return
      }
      const result = await reportStore.regenerateCommunityDiagram(
        props.taskId, props.parentCommId || '', props.parentLevel || '', props.parentEdgeType || '',
        props.projectId, existing, regenPrompt.value, regenMode.value,
      )
      if (result.success && result.code) {
        emit('regenerated', { content: result.code, mode: regenMode.value })
      } else {
        regenError.value = result.error || 'Unknown error'
      }
      regenLoading.value = false
      return
    }

    let result: { success: boolean; content?: string; error?: string }
    if (props.regenerationType === 'community') {
      result = await reportStore.regenerateCommunityDoc(
        props.taskId, props.parentCommId || '', props.parentLevel || '', props.parentEdgeType || '',
        props.projectId, regenPrompt.value,
      )
    } else {
      result = await reportStore.regenerateOverallDoc(props.taskId, props.projectId, regenPrompt.value)
    }

    if (result.success && result.content) {
      emit('regenerated', { content: result.content, mode: 'full' })
    } else {
      regenError.value = result.error || 'Unknown error'
    }
  } catch (e: unknown) {
    regenError.value = e instanceof Error ? (e as Error).message : String(e)
  } finally {
    regenLoading.value = false
  }
}
</script>

<template>
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
  <Teleport to="body">
    <div
      v-if="visible"
      class="dialog-overlay"
    >
      <div
        class="dialog"
        style="width:480px;"
      >
        <div class="dialog-header">
          <h3>{{ t('report.regenerate') }}</h3>
          <button
            class="btn btn-ghost btn-sm"
            @click="emit('close')"
          >
            &times;
          </button>
        </div>
        <div class="dialog-body">
          <div
            v-if="regenError"
            class="dialog-error"
          >
            {{ regenError }}
          </div>

          <div class="form-field">
            <label class="field-label">{{ t('report.regenerationMode') }}</label>
            <div style="display:flex; gap:4px;">
              <button
                :class="['btn btn-xs', regenMode === 'full' ? 'btn-primary' : 'btn-ghost']"
                @click="regenMode = 'full'"
              >
                {{ t('report.regenerateFull') }}
              </button>
              <button
                :class="['btn btn-xs', regenMode === 'mermaid' ? 'btn-primary' : 'btn-ghost']"
                @click="regenMode = 'mermaid'"
              >
                Mermaid
              </button>
              <button
                :class="['btn btn-xs', regenMode === 'plantuml' ? 'btn-primary' : 'btn-ghost']"
                @click="regenMode = 'plantuml'"
              >
                PlantUML
              </button>
            </div>
          </div>

          <div
            v-if="regenMode !== 'full'"
            class="form-field"
          >
            <label class="field-label">{{ t('report.regenerationSubMode') }}</label>
            <div style="display:flex; gap:4px;">
              <button
                :class="['btn btn-xs', regenSubMode === 'ai' ? 'btn-primary' : 'btn-ghost']"
                @click="regenSubMode = 'ai'"
              >
                {{ t('report.regenerateAI') }}
              </button>
              <button
                :class="['btn btn-xs', regenSubMode === 'manual' ? 'btn-primary' : 'btn-ghost']"
                @click="regenSubMode = 'manual'"
              >
                {{ t('report.regenerateManual') }}
              </button>
            </div>
          </div>

          <div
            v-if="regenSubMode === 'manual' && regenMode !== 'full'"
            class="form-field"
          >
            <label class="field-label">{{ t('report.regenerateDiagramCode') }}</label>
            <textarea
              v-model="regenManualCode"
              class="field-textarea"
              rows="6"
            />
          </div>

          <div class="form-field">
            <label class="field-label">{{ t('report.regeneratePrompt') }}</label>
            <textarea
              v-model="regenPrompt"
              class="field-textarea"
              rows="3"
              :placeholder="t('report.regeneratePromptPlaceholder')"
            />
          </div>
        </div>
        <div class="dialog-footer">
          <button
            class="btn btn-ghost"
            @click="emit('close')"
          >
            {{ t('common.cancel') }}
          </button>
          <button
            class="btn btn-primary"
            :disabled="regenLoading"
            @click="submitRegen"
          >
            <span v-if="regenLoading">{{ t('common.loading') }}...</span>
            <span v-else>{{ t('common.confirm') }}</span>
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.dialog {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  max-height: 80vh;
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}

.dialog-body {
  padding: 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.dialog-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border);
}

.dialog-error { background: color-mix(in srgb, var(--error) 10%, transparent); color: var(--error); padding: 8px 12px; border-radius: 6px; font-size: 11px; }
.form-field { display: flex; flex-direction: column; gap: 4px; }
.field-label { font-size: 11px; font-weight: 500; color: var(--text-secondary); }
.field-textarea { width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-primary); color: var(--text-primary); font-size: 12px; font-family: var(--font-mono); outline: none; resize: vertical; box-sizing: border-box; }
.field-textarea:focus { border-color: var(--accent); }
</style>
