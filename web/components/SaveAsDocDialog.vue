<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import * as api from '@web/services/api'

const props = defineProps<{
  visible: boolean
  msgContent: string
  sessionMessages: { role: string; content: string; reasoning?: string; toolCalls?: any[] }[]
}>()

const emit = defineEmits<{
  close: []
  save: [opts: { mode: 'single' | 'session'; target: 'new' | 'existing'; title: string; noteId?: string }]
}>()

const mode = ref<'single' | 'session'>('single')
const target = ref<'new' | 'existing'>('new')
const title = ref('')
const noteSearch = ref('')
const notes = ref<any[]>([])
const loading = ref(false)
const selectedNoteId = ref('')

watch(() => props.visible, (v) => { if (v) { noteSearch.value = ''; selectedNoteId.value = ''; loadNotes() } })

async function loadNotes() {
  loading.value = true
  try {
    const data = await api.get('/api/notes', { search: noteSearch.value, page_size: '200' })
    notes.value = data.notes || []
  } catch (_) {}
  loading.value = false
}

const filteredNotes = computed(() => {
  const q = noteSearch.value.trim().toLowerCase()
  if (!q) return notes.value
  return notes.value.filter((d: any) => (d.title || '').toLowerCase().includes(q))
})

function selectNote(id: string) {
  selectedNoteId.value = selectedNoteId.value === id ? '' : id
}

function confirm() {
  emit('save', {
    mode: mode.value,
    target: target.value,
    title: title.value || (mode.value === 'single' ? '消息' : '对话') + ' ' + new Date().toLocaleString(),
    noteId: target.value === 'existing' ? selectedNoteId.value : undefined,
  })
}
</script>

<template>
  <div v-if="visible" class="dialog-overlay" @click.self="emit('close')">
    <div class="dialog-box" style="width:460px">
      <h3>保存为笔记</h3>

      <div class="form-group">
        <label class="form-label">保存范围</label>
        <div class="radio-group">
          <label class="radio-item" :class="{ active: mode === 'single' }">
            <input type="radio" v-model="mode" value="single" />
            <span>单条消息</span>
          </label>
          <label class="radio-item" :class="{ active: mode === 'session' }">
            <input type="radio" v-model="mode" value="session" />
            <span>完整对话</span>
          </label>
        </div>
        <div v-if="mode === 'session'" class="form-hint">不包含思考过程和工具调用信息</div>
      </div>

      <div class="form-group">
        <label class="form-label">保存到</label>
        <div class="radio-group">
          <label class="radio-item" :class="{ active: target === 'new' }">
            <input type="radio" v-model="target" value="new" />
            <span>新建笔记</span>
          </label>
          <label class="radio-item" :class="{ active: target === 'existing' }">
            <input type="radio" v-model="target" value="existing" />
            <span>已有笔记</span>
          </label>
        </div>
      </div>

      <div v-if="target === 'new'" class="form-group">
        <label class="form-label">笔记标题</label>
        <input v-model="title" class="dialog-input" placeholder="输入笔记标题（可选）" />
      </div>

      <div v-if="target === 'existing'" class="form-group">
        <label class="form-label">选择笔记</label>
        <input v-model="noteSearch" class="dialog-input" placeholder="搜索笔记标题..." @input="loadNotes" />
        <div v-if="loading" class="note-list-loading">加载中...</div>
        <div v-else-if="filteredNotes.length === 0" class="note-list-empty">暂无匹配笔记</div>
        <div v-else class="note-list">
          <div
            v-for="d in filteredNotes"
            :key="d.id"
            class="note-item"
            :class="{ selected: selectedNoteId === d.id }"
            @click="selectNote(d.id)"
          >
            <div class="note-item-title">{{ d.title || '无标题' }}</div>
          </div>
        </div>
      </div>

      <div class="dialog-actions">
        <button class="dialog-btn" @click="emit('close')">取消</button>
        <button class="dialog-btn primary" @click="confirm" :disabled="target === 'existing' && !selectedNoteId">保存</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.form-group{margin-bottom:14px}
.form-label{display:block;font-size:13px;font-weight:500;color:var(--text-secondary);margin-bottom:6px}
.radio-group{display:flex;gap:10px}
.radio-item{display:flex;align-items:center;gap:6px;padding:6px 12px;border:1px solid var(--border);border-radius:var(--radius-md);cursor:pointer;font-size:13px;color:var(--text);transition:all .15s}
.radio-item:hover{border-color:var(--accent)}
.radio-item.active{border-color:var(--accent);background:var(--accent-light)}
.radio-item input{accent-color:var(--accent)}
.form-hint{font-size:11px;color:var(--text-muted);margin-top:4px}
.note-list{border:1px solid var(--border);border-radius:var(--radius-md);max-height:220px;overflow-y:auto}
.note-item{padding:8px 12px;cursor:pointer;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;transition:background .1s}
.note-item:last-child{border-bottom:none}
.note-item:hover{background:var(--bg-hover)}
.note-item.selected{background:var(--accent-light);border-color:var(--accent)}
.note-item-title{font-size:13px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.note-item-meta{font-size:11px;color:var(--text-muted);flex-shrink:0;margin-left:8px}
.note-list-loading,.note-list-empty{padding:16px;text-align:center;font-size:13px;color:var(--text-muted)}
</style>