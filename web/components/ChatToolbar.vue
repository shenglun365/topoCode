<script setup lang="ts">
defineProps<{
  currentTitle: string
  currentModel: string
  models: { id: string; name: string; isDefault?: boolean }[]
  contextLimit: number
  fontSize: number
  viewingDoc: boolean
  viewingDocTitle: string
  showAnnotations: boolean
  notesDotVisible: boolean
}>()

const emit = defineEmits<{
  'update:currentModel': [v: string]
  'update:contextLimit': [v: number]
  'update:fontSize': [v: number]
  editDoc: []
  toggleAnnotations: []
  addAnnotation: []
  openNotesDialog: []
}>()
</script>

<template>
  <header class="topbar">
    <div class="topbar-left">
      <template v-if="viewingDoc">
        <span class="topbar-badge badge-doc">文档</span>
        <span class="chat-title doc-title-clickable" @click="emit('editDoc')" title="编辑文档">
          {{ viewingDocTitle || '无标题' }}<svg class="edit-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
        </span>
        <button class="doc-topbar-btn" :class="{ active: showAnnotations }" @click="emit('toggleAnnotations')" title="切换批注显示"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M2 18h20"/><path d="M6 6l4 12"/><path d="M14 6l4 12"/></svg></button>
        <button class="doc-topbar-btn" @click="emit('addAnnotation')" title="添加批注"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></button>
      </template>
      <span v-else class="chat-title">{{ currentTitle }}</span>
    </div>
    <div class="topbar-right">
      <button class="notes-topbar-btn" :class="{ 'has-dot': notesDotVisible }" @click="emit('openNotesDialog')" title="待处理便签">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
        <span v-if="notesDotVisible" class="notes-dot"></span>
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
.notes-topbar-btn{position:relative;display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;border:none;background:transparent;color:var(--text-muted,#888);border-radius:6px;cursor:pointer;flex-shrink:0}
.notes-topbar-btn:hover{background:var(--bg-hover,#f4f4f5);color:var(--text)}
.notes-topbar-btn.has-dot{color:var(--text)}
.notes-dot{position:absolute;top:2px;right:2px;width:7px;height:7px;border-radius:50%;background:#ef4444;animation:pulse 1.5s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
</style>
