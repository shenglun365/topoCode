<script setup lang="ts">
defineProps<{
  currentTitle: string
  currentModel: string
  models: { id: string; name: string; isDefault?: boolean }[]
  contextLimit: number
  fontSize: number
  tab: 'chat' | 'notes' | 'archives'
  viewingNote: boolean
  viewingNoteTitle: string
  showAnnotations: boolean
  draftsDotVisible: boolean
}>()

const emit = defineEmits<{
  'update:currentModel': [v: string]
  'update:contextLimit': [v: number]
  'update:fontSize': [v: number]
  editNote: []
  editNoteMd: []
  toggleAnnotations: []
  addAnnotation: []
  openDraftsDialog: []
}>()
</script>

<template>
  <header class="topbar">
    <div class="topbar-left">
      <template v-if="viewingNote">
        <span class="topbar-badge badge-note">笔记</span>
        <span class="chat-title note-title-clickable" @click="emit('editNote')" title="编辑笔记">
          {{ viewingNoteTitle || '无标题' }}<svg class="edit-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
        </span>
        <button class="note-topbar-btn" :class="{ active: showAnnotations }" @click="emit('toggleAnnotations')" title="切换批注显示"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M2 18h20"/><path d="M6 6l4 12"/><path d="M14 6l4 12"/></svg></button>
        <button class="note-topbar-btn" @click="emit('addAnnotation')" title="添加批注"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></button>
        <button class="note-topbar-btn" @click="emit('editNoteMd')" title="全文编辑 (Markdown)"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg></button>
      </template>
      <span v-else-if="tab === 'chat'" class="chat-title">{{ currentTitle }}</span>
    </div>
    <div class="topbar-right">
      <button class="drafts-topbar-btn" :class="{ 'has-dot': draftsDotVisible }" @click="emit('openDraftsDialog')" title="待处理便签">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
        <span v-if="draftsDotVisible" class="drafts-dot"></span>
      </button>
      <select :value="currentModel" @change="emit('update:currentModel', ($event.target as HTMLSelectElement).value)">
        <option value="">选择模型</option>
        <option v-for="m in models" :key="m.id" :value="m.id">{{ m.name }}<template v-if="m.isDefault"> ★</template></option>
      </select>
      <select :value="contextLimit" @change="emit('update:contextLimit', Number(($event.target as HTMLSelectElement).value))">
        <option :value="16000">16K</option>
        <option :value="32000">32K</option>
        <option :value="64000">64K</option>
        <option :value="128000">128K</option>
        <option :value="256000">256K</option>
      </select>
      <select :value="fontSize" @change="emit('update:fontSize', Number(($event.target as HTMLSelectElement).value))">
        <option :value="13">13px</option>
        <option :value="15">15px</option>
        <option :value="18">18px</option>
        <option :value="22">22px</option>
        <option :value="26">26px</option>
        <option :value="32">32px</option>
      </select>
    </div>
  </header>
</template>

<style scoped>
.drafts-topbar-btn{position:relative;display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;border:none;background:transparent;color:var(--text-muted,#888);border-radius:6px;cursor:pointer;flex-shrink:0}
.drafts-topbar-btn:hover{background:var(--bg-hover,#f4f4f5);color:var(--text)}
.drafts-topbar-btn.has-dot{color:var(--text)}
.drafts-dot{position:absolute;top:2px;right:2px;width:7px;height:7px;border-radius:50%;background:#ef4444;animation:pulse 1.5s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
</style>
