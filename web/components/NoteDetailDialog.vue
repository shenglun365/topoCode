<script setup lang="ts">
import type { Note } from '@web/types'

defineProps<{
  note: Note | null
}>()

const emit = defineEmits<{
  close: []
  delete: [id: string]
  execute: [n: Note]
}>()
</script>

<template>
  <div v-if="note" class="dialog-overlay" @click.self="emit('close')">
    <div class="dialog-box" style="width:560px">
      <h3>{{ note.title || '便签详情' }}</h3>

      <div v-if="note.userText" class="section">
        <div class="section-title">用户备注</div>
        <div class="section-content">{{ note.userText }}</div>
      </div>

      <div class="section">
        <div class="section-title">内容</div>
        <div class="section-content note-content">{{ note.content || '（空）' }}</div>
      </div>

      <div v-if="note.refs?.length" class="section">
        <div class="section-title">引用上下文（{{ note.refs.length }}）</div>
        <div v-for="(r, i) in note.refs" :key="i" class="ref-item-full">
          <div class="ref-label">{{ r.label || r.projectName || '引用 ' + (i+1) }}</div>
          <div v-if="r.text" class="ref-text">{{ r.text.slice(0, 200) }}{{ r.text.length > 200 ? '...' : '' }}</div>
          <div v-if="r.type" class="ref-meta">{{ r.type }}{{ r.projectName ? ' · ' + r.projectName : '' }}</div>
        </div>
      </div>

      <div class="dialog-actions">
        <button class="dialog-btn primary" @click="emit('execute', note)">执行</button>
        <button class="dialog-btn" style="color:#ef4444" @click="emit('delete', note.id)">删除</button>
        <button class="dialog-btn" @click="emit('close')">关闭</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.section{margin-bottom:14px}
.section-title{font-size:12px;color:var(--text-muted,#888);margin-bottom:4px;font-weight:600}
.section-content{font-size:var(--ui-font-size);color:var(--text);line-height:1.5}
.note-content{white-space:pre-wrap;max-height:180px;overflow-y:auto;padding:8px;background:var(--bg-hover,#f4f4f5);border-radius:6px}
.ref-item-full{margin-bottom:8px;padding:8px;background:var(--bg-hover,#f4f4f5);border-radius:6px}
.ref-label{font-weight:500;font-size:13px;color:var(--accent,#4d6bfe);margin-bottom:2px}
.ref-text{font-size:12px;color:var(--text-secondary,#666);line-height:1.4;white-space:pre-wrap}
.ref-meta{font-size:11px;color:var(--text-muted,#888);margin-top:2px}
</style>
