<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'

const props = defineProps<{
  visible: boolean
  title: string
  generating: boolean
}>()

const emit = defineEmits<{
  'update:title': [v: string]
  close: []
  submit: []
  aiRename: []
}>()

const renameInput = ref<HTMLElement>()

watch(() => props.visible, (v) => { if (v) nextTick(() => renameInput.value?.focus()) })
</script>

<template>
  <div v-if="visible" class="dialog-overlay" @click.self="emit('close')">
    <div class="dialog-box" style="width:360px">
      <h3>重命名会话</h3>
      <input
        ref="renameInput"
        :value="title"
        @input="emit('update:title', ($event.target as HTMLInputElement).value)"
        class="dialog-input"
        placeholder="输入新标题"
        @keydown.enter="emit('submit')"
      />
      <div class="dialog-actions">
        <button class="dialog-btn" @click="emit('close')">取消</button>
        <button class="dialog-btn" :disabled="generating" @click="emit('aiRename')">{{ generating ? '生成中...' : 'AI 生成' }}</button>
        <button class="dialog-btn primary" @click="emit('submit')">确认</button>
      </div>
    </div>
  </div>
</template>
