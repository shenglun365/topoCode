<script setup lang="ts">
import type { ChatSession, Note } from '@web/types'

defineProps<{
  tab: 'chat' | 'notes' | 'docs' | 'archives'
  sessions: ChatSession[]
  currentId: string
  notes: Note[]
  pendingDrafts: any[]
  archives: any[]
  documents: any[]
  docSearch: string
  viewingDoc: any
}>()

const emit = defineEmits<{
  'update:tab': [v: 'chat' | 'notes' | 'docs' | 'archives']
  'update:docSearch': [v: string]
  createSession: []
  switchSession: [id: string]
  deleteSession: [id: string]
  openRename: [s: ChatSession]
  viewNote: [n: Note]
  deleteNote: [id: string]
  execPendingDraft: [d: any]
  deleteArchive: [id: string]
  loadDocs: []
  viewDoc: [d: any]
  deleteDoc: [id: string]
  copyId: [id: string]
}>()

const tabKeys = ['chat', 'notes', 'docs'] as const
const tabLabels: Record<string, string> = { chat: '对话', notes: '便签', docs: '文档' }
</script>

<template>
  <aside class="sidebar">
    <div class="sidebar-header">
      <div class="logo">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="5" r="2.5"/><circle cx="5" cy="19" r="2.5"/><circle cx="19" cy="19" r="2.5"/><line x1="11" y1="7" x2="6" y2="17"/><line x1="13" y1="7" x2="18" y2="17"/><line x1="7" y1="19" x2="17" y2="19"/></svg>
        <span>TopoCode</span>
      </div>
    </div>
    <div class="sidebar-tabs">
      <div v-for="tk in tabKeys" :key="tk" class="sidebar-tab" :class="{ active: tab === tk }" @click="emit('update:tab', tk)">
        {{ tabLabels[tk] }}
      </div>
    </div>

    <div v-if="tab === 'chat'" class="sidebar-content">
      <button class="btn-new" @click="emit('createSession')">新对话</button>
      <div v-for="s in sessions" :key="s.id" class="session-item" :class="{ active: s.id === currentId }" @click="emit('switchSession', s.id)">
        <span class="title">{{ s.title }}</span>
        <button class="del-btn" @click.stop="emit('deleteSession', s.id)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
        <button class="copy-id-btn" @click.stop="emit('copyId', s.id)" title="复制会话 ID"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></button>
        <button class="rename-btn" @click.stop="emit('openRename', s)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button>
      </div>
      <div v-if="!sessions.length" class="note-empty">暂无对话</div>
    </div>

    <div v-else-if="tab === 'notes'" class="sidebar-content">
      <div v-for="n in notes" :key="n.id" class="note-item" @click="emit('viewNote', n)">
        <span class="status-dot" :class="n.status"></span>
        <span class="title">{{ n.title || '无标题' }}</span>
        <span class="ref-count">{{ n.refs?.length || 0 }} 项</span>
        <button class="del-btn" @click.stop="emit('deleteNote', n.id)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
      </div>
      <div v-if="!notes.length && !pendingDrafts.length" class="note-empty">暂无便签</div>
      <div v-if="pendingDrafts.length" class="pending-section">
        <div v-for="d in pendingDrafts" :key="d.id" class="pending-item">
          <span class="title">{{ d.userText?.slice(0, 20) || `#${d.seq}` }}</span>
          <button class="send-btn" @click="emit('execPendingDraft', d)">执行</button>
        </div>
      </div>
    </div>

    <div v-else-if="tab === 'archives'" class="sidebar-content">
      <div v-for="a in archives" :key="a.id" class="note-item">
        <span class="title">{{ a.title || a.id.slice(0,16) }}</span>
        <span class="ref-count">{{ a.category }}</span>
        <button class="del-btn" @click.stop="emit('deleteArchive', a.id)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
      </div>
      <div v-if="!archives.length" class="note-empty">暂无归档</div>
    </div>

    <div v-else class="sidebar-content">
      <input :value="docSearch" @input="emit('update:docSearch', ($event.target as HTMLInputElement).value); emit('loadDocs')" class="sidebar-search" placeholder="搜索文档..." />
      <div v-for="d in documents" :key="d.id" class="note-item" :class="{ active: viewingDoc?.id === d.id }" @click="emit('viewDoc', d)">
        <span class="title">{{ d.title || d.id }}</span>
        <span class="ref-count">{{ d.updated_at?.slice(0,10) || '' }}</span>
        <button class="copy-id-btn" @click.stop="emit('copyId', d.id)" title="复制文档 ID"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></button>
        <button class="del-btn" @click.stop="emit('deleteDoc', d.id)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
      </div>
      <div v-if="!documents.length" class="note-empty">暂无文档</div>
    </div>
  </aside>
</template>
