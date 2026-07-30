<script setup lang="ts">
import { ref, watch, inject } from 'vue'

const props = defineProps<{
  visible: boolean
  code: string
  lang: 'mermaid' | 'plantuml'
  msgId: string
  diagId: string
}>()

const emit = defineEmits<{
  apply: [newCode: string]
  cancel: []
}>()

const modelId = inject('currentModel', ref(''))
const contextLimit = inject('contextLimit', ref(32000))

const instruction = ref('')
const loading = ref(false)
const currentCode = ref('')
const responseText = ref('')
const history: { role: string; content: string }[] = []
const stepLog = ref<{ step: string; detail: string; type: 'info' | 'success' | 'error' }[]>([])
const showDiff = ref(false)
const error = ref('')

watch(() => props.visible, (v) => {
  if (v) {
    currentCode.value = props.code
    instruction.value = ''
    responseText.value = ''
    stepLog.value = []
    error.value = ''
    showDiff.value = false
  }
})

async function send() {
  if (!instruction.value.trim() || loading.value) return
  loading.value = true
  error.value = ''
  responseText.value = ''
  stepLog.value = [{ step: '解析中', detail: '正在分析图结构…', type: 'info' }]

  try {
    const resp = await fetch('/api/diagram-editor/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        code: currentCode.value,
        lang: props.lang,
        instruction: instruction.value,
        history: history.slice(-6),
        model_id: typeof modelId === 'string' ? modelId : (modelId as any).value,
        context_limit: typeof contextLimit === 'number' ? contextLimit : (contextLimit as any).value,
      }),
    })
    if (!resp.ok) {
      const text = await resp.text()
      throw new Error(text.slice(0, 200) || `HTTP ${resp.status}`)
    }
    const result = await resp.json()

    stepLog.value = []
    if (result.rounds) {
      stepLog.value.push({ step: '执行', detail: `完成 ${result.rounds} 轮工具调用`, type: 'success' })
    }
    if (result.code_changed) {
      stepLog.value.push({ step: '修改', detail: '图代码已更新', type: 'success' })
      currentCode.value = result.updated_code || currentCode.value
      showDiff.value = true
    } else {
      stepLog.value.push({ step: '结果', detail: '图代码未改变', type: 'info' })
    }

    responseText.value = result.response || ''
    history.push({ role: 'user', content: instruction.value })
    history.push({ role: 'assistant', content: result.response || '' })
    instruction.value = ''
  } catch (e: any) {
    error.value = e.message || '处理失败'
    stepLog.value.push({ step: '错误', detail: error.value, type: 'error' })
  } finally {
    loading.value = false
  }
}

function onApply() {
  emit('apply', currentCode.value)
}

function onCancel() {
  emit('cancel')
}

function onOverlayClick(e: MouseEvent) {
  if ((e.target as HTMLElement).classList.contains('dialog-overlay')) onCancel()
}

function getLineCount(s: string) {
  return s ? s.split('\n').length : 0
}
</script>

<template>
  <div v-if="visible" class="dialog-overlay" @click="onOverlayClick">
    <div class="diagram-subagent-dialog">
      <div class="ds-header">
        <span class="ds-title">🤖 AI 修图 · {{ lang === 'mermaid' ? 'Mermaid' : 'PlantUML' }}</span>
        <button class="ds-close" @click="onCancel">✕</button>
      </div>

      <div class="ds-body">
        <div class="ds-code-panel">
          <div class="ds-code-header">
            <span>图代码 ({{ getLineCount(currentCode) }} 行)</span>
            <label class="ds-diff-toggle">
              <input type="checkbox" v-model="showDiff" :disabled="!responseText" />
              diff 高亮
            </label>
          </div>
          <textarea
            class="ds-textarea"
            :value="currentCode"
            @input="(e: any) => currentCode = e.target.value"
            spellcheck="false"
          ></textarea>
        </div>

        <div class="ds-chat-panel">
          <div class="ds-response-area">
            <div v-if="stepLog.length" class="ds-step-log">
              <div v-for="(s, i) in stepLog" :key="i" :class="'ds-step ds-step-' + s.type">
                <span class="ds-step-icon">{{ s.type === 'info' ? '→' : s.type === 'success' ? '✓' : '✗' }}</span>
                <span class="ds-step-detail">{{ s.detail }}</span>
              </div>
            </div>
            <div v-if="responseText" class="ds-response">{{ responseText }}</div>
            <div v-if="error" class="ds-error">{{ error }}</div>
            <div v-if="!stepLog.length && !responseText && !error" class="ds-placeholder">
              在下方描述你要做的修改，AI 会逐步处理。
            </div>
          </div>

          <div class="ds-input-area">
            <input
              v-model="instruction"
              class="ds-input"
              placeholder="描述修改…"
              @keydown.enter.prevent="send"
              :disabled="loading"
            />
            <button class="ds-send-btn" @click="send" :disabled="loading || !instruction.trim()">
              {{ loading ? '处理中…' : '发送' }}
            </button>
          </div>

          <div class="ds-actions">
            <button class="ds-btn ds-btn-primary" @click="onApply" :disabled="!responseText && !error">
              应用到对话
            </button>
            <button class="ds-btn ds-btn-secondary" @click="onCancel">取消</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dialog-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.4); z-index: 1000;
  display: flex; align-items: center; justify-content: center;
}
.diagram-subagent-dialog {
  background: var(--bg-primary,#fff); border-radius: 12px; width: 90vw; max-width: 1100px;
  height: 80vh; display: flex; flex-direction: column; overflow: hidden;
  box-shadow: 0 8px 40px rgba(0,0,0,0.15);
}
.ds-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--border,#e4e4e7);
}
.ds-title { font-weight: 600; font-size: 15px; }
.ds-close { background: none; border: none; font-size: 18px; cursor: pointer; color: var(--text-muted); padding: 4px 8px; border-radius: 6px; }
.ds-close:hover { background: var(--bg-hover); }
.ds-body { display: flex; flex: 1; overflow: hidden; }
.ds-code-panel { flex: 1; display: flex; flex-direction: column; border-right: 1px solid var(--border,#e4e4e7); }
.ds-code-header { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; font-size: 12px; color: var(--text-muted); }
.ds-diff-toggle { display: flex; align-items: center; gap: 4px; cursor: pointer; }
.ds-diff-toggle input { margin: 0; }
.ds-textarea { flex: 1; border: none; resize: none; padding: 12px; font-family: monospace; font-size: 13px; line-height: 1.5; outline: none; background: var(--bg-code,#f8f8fa); }
.ds-chat-panel { width: 380px; display: flex; flex-direction: column; }
.ds-response-area { flex: 1; overflow-y: auto; padding: 12px; }
.ds-step-log { margin-bottom: 8px; }
.ds-step { padding: 4px 8px; margin-bottom: 4px; border-radius: 6px; font-size: 13px; display: flex; align-items: center; gap: 6px; }
.ds-step-info { background: var(--bg-hover,#f0f0f2); }
.ds-step-success { background: #ecfdf3; color: #067647; }
.ds-step-error { background: #fef3f2; color: #b42318; }
.ds-step-icon { font-weight: bold; }
.ds-response { background: var(--bg-hover,#f0f0f2); padding: 10px; border-radius: 8px; font-size: 13px; line-height: 1.5; white-space: pre-wrap; }
.ds-error { color: #b42318; font-size: 13px; padding: 8px; }
.ds-placeholder { color: var(--text-muted,#aaa); font-size: 13px; text-align: center; padding: 40px 20px; }
.ds-input-area { display: flex; gap: 6px; padding: 8px 12px; border-top: 1px solid var(--border,#e4e4e7); }
.ds-input { flex: 1; border: 1px solid var(--border,#e4e4e7); border-radius: 8px; padding: 8px 12px; font-size: 13px; outline: none; }
.ds-input:focus { border-color: var(--accent,#4d6bfe); }
.ds-send-btn { background: var(--accent,#4d6bfe); color: #fff; border: none; border-radius: 8px; padding: 8px 16px; font-size: 13px; cursor: pointer; white-space: nowrap; }
.ds-send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ds-actions { display: flex; gap: 8px; padding: 10px 12px; border-top: 1px solid var(--border,#e4e4e7); }
.ds-btn { flex: 1; padding: 8px 16px; border-radius: 8px; font-size: 13px; cursor: pointer; border: 1px solid var(--border,#e4e4e7); text-align: center; }
.ds-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ds-btn-primary { background: var(--accent,#4d6bfe); color: #fff; border-color: var(--accent,#4d6bfe); }
.ds-btn-secondary { background: var(--bg-primary,#fff); color: var(--text-secondary); }
</style>
