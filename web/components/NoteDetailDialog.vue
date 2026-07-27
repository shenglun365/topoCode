<script setup lang="ts">
import type { Note } from '@web/types'

defineProps<{
  note: Note | null
}>()

const emit = defineEmits<{
  close: []
  delete: [id: string]
}>()
</script>

<template>
  <div v-if="note" class="dialog-overlay" @click.self="emit('close')">
    <div class="dialog-box" style="width:500px">
      <h3>{{ note.title || '便签详情' }}</h3>
      <div class="note-detail-content">{{ note.content || '无内容' }}</div>
      <div v-if="note.refs?.length" class="note-detail-refs">
        <div class="ref-section-title">引用 ({{ note.refs.length }})</div>
        <div v-for="(r, i) in note.refs" :key="i" class="ref-item">{{ r.label || r.text?.slice(0, 50) || `引用 ${i+1}` }}</div>
      </div>
      <div class="dialog-actions">
        <button class="dialog-btn" style="color:#ef4444" @click="emit('delete', note.id)">删除</button>
        <button class="dialog-btn" @click="emit('close')">关闭</button>
      </div>
    </div>
  </div>
</template>
