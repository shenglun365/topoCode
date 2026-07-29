<script setup lang="ts">
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { renderMarkdown, codeFullscreen, autoFitCodeBlock } from '@web/services/render'
import { parseMessageContent } from '@web/services/parseContent'
import type { ChatMessage } from '@web/types'
import MermaidViewer from '@web/components/MermaidViewer.vue'
import PlantUmlViewer from '@web/components/PlantUmlViewer.vue'

const props = defineProps<{
  message: ChatMessage
  deleteMode: boolean
  isSelected: boolean
  showReasoning?: boolean
  showToolCalls?: boolean
  debug?: boolean
}>()

const emit = defineEmits<{
  toggleSelect: [id: string]
  copyMessage: [m: ChatMessage]
  quoteMessage: [m: ChatMessage]
  continueAssistant: [m: ChatMessage]
  saveMsgAsDoc: [m: ChatMessage]
  deleteSingle: [id: string]
  codeChange: [msgId: string, diagId: string, newCode: string]
  'state-change': []
  'save-state': []
  toggleReasoning: []
  toggleToolCalls: []
}>()

const blocks = computed(() => parseMessageContent(props.message.content || '', props.message.id))

function onCodeChange(diagId: string, newCode: string) {
  if (props.message.id) emit('codeChange', props.message.id, diagId, newCode)
}

function onBubbleClick(e: MouseEvent) {
  const btn = (e.target as HTMLElement).closest('.code-fs-btn')
  if (!btn) return
  const wrap = btn.closest('.code-block-wrap')
  if (!wrap) return
  const codeEl = wrap.querySelector('code')
  if (!codeEl) return
  const text = codeEl.textContent || ''
  if (text) codeFullscreen(text)
}

const bubbleRef = ref<HTMLElement>()

function fitCodeBlocks() {
  if (!bubbleRef.value) return
  bubbleRef.value.querySelectorAll<HTMLElement>('.code-block-wrap').forEach(autoFitCodeBlock)
}

const showReasoningToggle = computed(() => {
  if (!props.message.reasoning) return false
  if ((props.message as any)._fromToolRounds && !props.debug) return false
  return true
})

onMounted(() => nextTick(fitCodeBlocks))
watch(() => props.message.content, () => nextTick(fitCodeBlocks))
</script>

<template>
  <div class="message" :class="message.role" :data-msg-id="message.id || ''" @click.stop>
    <div v-if="deleteMode && message.id" class="cbox-wrap">
      <input type="checkbox" :checked="isSelected" @change="emit('toggleSelect', message.id)" />
    </div>
    <div v-if="message.role !== 'user'" class="message-avatar ai">AI</div>
    <div class="msg-content">
      <div v-if="message.role === 'assistant'" class="sender">TopoCode</div>
      <div v-if="message.role === 'assistant' && !message.content && message.isStreaming" class="loading-dots"><span></span><span></span><span></span></div>
      <div v-if="message.qualityLow" class="quality-low-banner">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="vertical-align:-2px;margin-right:4px"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> 本次分析未能生成有效回答
      </div>
      <div v-if="showReasoningToggle" class="reasoning-toggle" @click="emit('toggleReasoning')">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" class="arrow" :class="{ open: showReasoning }"><polyline points="9 18 15 12 9 6"/></svg>
        <span>{{ showReasoning ? '收起思考过程' : '查看思考过程' }}<span v-if="message.reasoning.length > 10" class="reasoning-tokens">({{ Math.round(message.reasoning.length / 2) }} tokens)</span></span>
      </div>
      <div v-if="message.reasoning && showReasoning" class="reasoning-content" v-html="renderMarkdown(message.reasoning)"></div>
      <template v-if="debug">
        <div v-if="message.toolCalls?.length" class="tool-toggle" @click="emit('toggleToolCalls')">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" class="arrow" :class="{ open: showToolCalls }"><polyline points="9 18 15 12 9 6"/></svg>
          <span>调用 {{ message.toolCalls.length }} 次工具</span>
        </div>
        <div v-if="message.toolCalls?.length && showToolCalls" class="tool-detail">
          <div v-for="tc in message.toolCalls" :key="tc.id" class="tool-call-item">
            <div class="tool-call-name"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="vertical-align:-2px;margin-right:4px"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg> {{ tc.name }}</div>
            <div class="tool-label">参数</div>
            <pre>{{ JSON.stringify(tc.arguments, null, 2) }}</pre>
            <div v-if="tc.result" class="tool-label">执行结果</div>
            <pre v-if="tc.result">{{ tc.result }}</pre>
          </div>
        </div>
      </template>
      <div v-if="message.content" class="bubble" ref="bubbleRef" @click="onBubbleClick">
        <template v-for="(b, i) in blocks" :key="i">
          <span v-if="b.type === 'text'" v-html="b.html"></span>
          <MermaidViewer
            v-else-if="b.type === 'mermaid'"
            :code="b.code!"
            :diag-id="b.diagId!"
            :msg-id="message.id"
            :initial-state="b.initialState"
            @code-change="onCodeChange"
            @state-change="emit('state-change')"
            @save-state="emit('save-state')"
          />
          <PlantUmlViewer
            v-else-if="b.type === 'plantuml'"
            :code="b.code!"
            :diag-id="b.diagId!"
            :msg-id="message.id"
            :initial-state="b.initialState"
            @code-change="onCodeChange"
            @state-change="emit('state-change')"
            @save-state="emit('save-state')"
          />
        </template>
      </div>
      <div v-if="message.id && !deleteMode" class="message-actions">
        <button class="msg-act-btn" @click="emit('copyMessage', message)" title="复制"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>
        <button class="msg-act-btn" @click="emit('quoteMessage', message)" title="引用"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></button>
        <button class="msg-act-btn" @click="emit('continueAssistant', message)" title="继续"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg></button>
        <button class="msg-act-btn" @click="emit('saveMsgAsDoc', message)" title="保存为文档"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg></button>
        <button class="msg-act-btn del-msg" @click="emit('deleteSingle', message.id)" title="删除"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg></button>
      </div>
    </div>
  </div>
</template>

<style>
.code-block-wrap{position:relative}
.code-block-wrap .code-fs-btn{position:absolute;top:4px;right:4px;width:28px;height:28px;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.4);border:none;border-radius:4px;color:#fff;cursor:pointer;opacity:0;transition:opacity .15s;z-index:1}
.code-block-wrap:hover .code-fs-btn{opacity:1}
.code-block-wrap .code-fs-btn:hover{background:rgba(0,0,0,.6)}
.code-fs-content{max-width:92%;max-height:88vh;overflow:auto;transform-origin:0 0;background:#1e1e1e;border-radius:8px;padding:24px;box-shadow:0 8px 40px rgba(0,0,0,.4)}
.code-fs-content pre{margin:0;white-space:pre;font-family:var(--font-mono,monospace);font-size:14px;line-height:1.6;color:#d4d4d4}
.code-fs-content code{background:transparent!important;padding:0!important;font-family:inherit;color:inherit}
</style>
