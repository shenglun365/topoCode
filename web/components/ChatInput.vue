<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  streaming: boolean
  modelValue: string
}>()

const emit = defineEmits<{
  'update:modelValue': [v: string]
  send: [text: string]
  abortStream: []
}>()

const textareaRef = ref<HTMLElement>()

const autoCompleteItems = ref<any[]>([])
const autoCompleteVisible = ref(false)
const autoCompleteIdx = ref(-1)
const AC_COMMANDS = [
  { trigger: '/compress', hint: '压缩当前会话' },
  { trigger: '/help', hint: '显示帮助' },
]
const AC_REF_TYPES = [
  { trigger: '@community:', hint: '社区ID' },
  { trigger: '@project:', hint: '项目ID' },
  { trigger: '@file:', hint: '文件路径' },
  { trigger: '@symbol:', hint: '符号名称' },
  { trigger: '@session:', hint: '会话ID' },
]

function onInputChange(e: Event) {
  const val = (e.target as HTMLTextAreaElement).value
  emit('update:modelValue', val)
  const ta = textareaRef.value
  const cursorPos = ta ? ta.selectionStart : val.length
  const before = val.slice(0, cursorPos)
  const slashMatch = before.match(/\/(\w*)$/)
  const atMatch = before.match(/@(\w*:?\w*)$/)

  if (slashMatch) {
    const prefix = '/' + slashMatch[1]
    autoCompleteItems.value = AC_COMMANDS.filter(c => c.trigger.startsWith(prefix) || prefix.startsWith(c.trigger)).slice(0, 8)
    autoCompleteVisible.value = autoCompleteItems.value.length > 0
    autoCompleteIdx.value = 0
  } else if (atMatch) {
    const atPrefix = atMatch[1]
    if (atPrefix.includes(':')) {
      const [type, q] = atPrefix.split(':')
      const matched = AC_REF_TYPES.find(r => r.trigger.slice(1, -1) === type)
      if (matched && q.length >= 1) {
        autoCompleteVisible.value = false
      }
    } else {
      autoCompleteItems.value = AC_REF_TYPES.filter(r => r.trigger.slice(1, -1).startsWith(atPrefix)).slice(0, 8)
      autoCompleteVisible.value = autoCompleteItems.value.length > 0
      autoCompleteIdx.value = 0
    }
  } else {
    autoCompleteVisible.value = false
  }
}

function onInputKeydown(e: KeyboardEvent) {
  if (!autoCompleteVisible.value) return
  const items = autoCompleteItems.value
  if (e.key === 'ArrowDown') { e.preventDefault(); autoCompleteIdx.value = Math.min(autoCompleteIdx.value + 1, items.length - 1) }
  else if (e.key === 'ArrowUp') { e.preventDefault(); autoCompleteIdx.value = Math.max(autoCompleteIdx.value - 1, 0) }
  else if (e.key === 'Enter' || e.key === 'Tab') {
    if (autoCompleteIdx.value >= 0 && items[autoCompleteIdx.value]) {
      e.preventDefault()
      const item = items[autoCompleteIdx.value]
      const ta = textareaRef.value
      if (ta) {
        const val = ta.value
        const pos = ta.selectionStart
        const before = val.slice(0, pos)
        const match = before.match(/(\/\w*)$|(@\w*:?\w*)$/)
        if (match) {
          const start = pos - match[1].length
          const newVal = val.slice(0, start) + item.trigger + val.slice(pos)
          ta.value = newVal
          emit('update:modelValue', newVal)
          ta.selectionStart = ta.selectionEnd = start + item.trigger.length
          ta.focus()
        }
      }
      autoCompleteVisible.value = false
    }
  } else if (e.key === 'Escape') { autoCompleteVisible.value = false }
}

function send() {
  if (!props.modelValue.trim()) return
  emit('send', props.modelValue)
  emit('update:modelValue', '')
}

function onEnter(e: KeyboardEvent) {
  if (!e.shiftKey) {
    e.preventDefault()
    if (!props.streaming) send()
  }
}
</script>

<template>
  <div class="input-area">
    <div class="input-wrapper">
      <div class="input-row" style="position:relative">
        <div class="autocomplete-wrap">
          <textarea
            ref="textareaRef"
            :value="modelValue"
            @input="onInputChange"
            @keydown.enter.exact="onEnter"
            @keydown="onInputKeydown"
            :placeholder="streaming ? 'AI 正在回复...' : '输入消息...'"
            rows="3"
            :disabled="streaming"
          />
          <div v-if="autoCompleteVisible" class="autocomplete-panel open">
            <div v-for="(item, idx) in autoCompleteItems" :key="idx" class="ac-item" :class="{ active: idx === autoCompleteIdx }" @mousedown.prevent="">
              <span class="ac-trigger">{{ item.trigger }}</span>
              <span class="ac-hint">{{ item.hint }}</span>
            </div>
          </div>
        </div>
        <button class="btn-send" :class="{ 'stop-btn': streaming }" :disabled="!streaming && !modelValue.trim()" @click="streaming ? emit('abortStream') : send()">
          <svg v-if="!streaming" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>
          <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
        </button>
      </div>
    </div>
  </div>
</template>
