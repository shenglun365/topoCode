<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import * as api from '@web/services/api'
import { renderMarkdown, renderDiagrams } from '@web/services/render'
import { useToast } from '@web/composables/useToast'
import { useDialog } from '@web/composables/useDialog'
import AppDialog from '@web/components/shared/AppDialog.vue'
import type { ChatSession, ChatMessage, ModelConfig, Note } from '@web/types'

const { toast } = useToast()
const { dialog, confirm, prompt, alert, close: closeDialog } = useDialog()

const sessions = ref<ChatSession[]>([])
const messages = ref<ChatMessage[]>([])
const models = ref<ModelConfig[]>([])
const notes = ref<Note[]>([])
const currentId = ref('')
const currentModel = ref('')
const input = ref('')
const streaming = ref(false)
const msgArea = ref<HTMLElement>()
const tab = ref<'chat' | 'notes' | 'docs' | 'archives'>('chat')
const documents = ref<any[]>([])
const docSearch = ref('')
const viewingDoc = ref<any>(null)
const showDocEditor = ref(false)
const docEditTitle = ref('')
const docEditContent = ref('')
const docPreview = ref(false)

const taskId = ref(new URLSearchParams(location.search).get('taskId') || '')
const sessionId = ref(new URLSearchParams(location.search).get('sessionId') || '')
const fontSize = ref(parseInt(localStorage.getItem('topoone-font-size') || '18'))
const contextLimit = ref(parseInt(localStorage.getItem('topo_context_limit') || '32000'))

// Archives
const archives = ref<any[]>([])

// Pending drafts from notes
const pendingDrafts = ref<any[]>([])
const pendingRefs = ref<any[]>([])

// Rename dialog
const renameDialog = ref<ChatSession | null>(null)
const renameText = ref('')
const renameGenerating = ref(false)

// Note detail
const viewNoteData = ref<Note | null>(null)

// Autocomplete
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

// Batch delete
const deleteMode = ref(false)
const selectedIds = ref(new Set<string>())

const allSelected = computed(() => {
  const ids = messages.value.filter(m => m.id).map(m => m.id)
  return selectedIds.value.size === ids.length && ids.length > 0
})

const currentTitle = computed(() => {
  const s = sessions.value.find(x => x.id === currentId.value)
  return s ? s.title : 'TopoCode AI'
})

// BroadcastChannel for cross-tab notes sync
const bc = new BroadcastChannel('topo_notes' + (taskId.value ? '_' + taskId.value : ''))
bc.onmessage = () => { if (tab.value === 'notes') loadNotes() }

// localStorage capacity warning
function checkStorage() {
  const KB = 1024, MB = KB * KB, LIMIT = 5 * MB, WARN_AT = LIMIT * 0.8
  let total = 0
  try {
    for (const k in localStorage) {
      if (localStorage.hasOwnProperty(k) && k.startsWith('topo_'))
        total += (k.length + (localStorage[k] || '').length) * 2
    }
  } catch (_) {}
  if (total > WARN_AT) {
    const usedMB = (total / MB).toFixed(1)
    setTimeout(() => {
      if (confirm(`存储空间不足 (已用 ${usedMB}MB / 5MB)。是否清除缓存？`)) {
        const keys: string[] = []
        for (const k in localStorage) {
          if (localStorage.hasOwnProperty(k) && k.indexOf('topo_') === 0) keys.push(k)
        }
        keys.forEach(k => localStorage.removeItem(k))
        toast('缓存已清除')
      }
    }, 2000)
  }
}

// Pending drafts pending execution
const loadPendingDrafts = () => {
  try {
    const raw = localStorage.getItem(`topo_notes_${taskId.value}`)
    if (raw) {
      const all = JSON.parse(raw)
      pendingDrafts.value = all.filter((d: any) => d.status === 'pending')
    }
  } catch (_) { pendingDrafts.value = [] }
}

// ── Scroll ──
function scrollToBottom() {
  nextTick(() => { if (msgArea.value) msgArea.value.scrollTop = msgArea.value.scrollHeight })
}

// ── Font ──
function applyFontSize(val: number) {
  document.documentElement.style.setProperty('--content-font-size', val + 'px')
  document.documentElement.style.setProperty('--ui-font-size', Math.min(Math.round(val * 0.8), 18) + 'px')
  try { localStorage.setItem('topoone-font-size', String(val)) } catch (_) {}
}
watch(fontSize, applyFontSize)
watch(contextLimit, (val) => { try { localStorage.setItem('topo_context_limit', String(val)) } catch (_) {} })

// ── Sessions ──
async function loadSessions() {
  try {
    const data = await api.listSessions()
    sessions.value = data.sessions
    if (sessionId.value) {
      currentId.value = sessionId.value
      await loadMessages()
    } else if (data.sessions.length > 0) {
      currentId.value = data.sessions[0].id
      await loadMessages()
    }
  } catch (_) {}
}

async function createSession() {
  try {
    const s = await api.createSession('新对话', currentModel.value || undefined)
    sessions.value.unshift(s)
    currentId.value = s.id
    messages.value = []
    scrollToBottom()
  } catch (_) { toast('创建失败') }
}

async function switchSession(id: string) {
  if (streaming.value) return
  currentId.value = id
  await loadMessages()
  scrollToBottom()
}

async function deleteSession(id: string) {
  const ok = await confirm('确定删除此会话？')
  if (!ok) return
  try {
    await api.deleteSession(id)
    sessions.value = sessions.value.filter(s => s.id !== id)
    if (currentId.value === id) {
      currentId.value = sessions.value[0]?.id || ''
      if (currentId.value) await loadMessages(); else messages.value = []
    }
  } catch (_) { toast('删除失败') }
}

function openRename(s: ChatSession) {
  renameDialog.value = s
  renameText.value = s.title || ''
  renameGenerating.value = false
}

async function submitRename() {
  const s = renameDialog.value
  if (!s || !renameText.value.trim()) return
  try {
    await api.updateSession(s.id, { title: renameText.value.trim() } as any)
    s.title = renameText.value.trim()
    renameDialog.value = null
  } catch (_) { toast('重命名失败') }
}

async function aiRename() {
  const s = renameDialog.value
  if (!s) return
  renameGenerating.value = true
  try {
    const resp = await fetch(`/api/chat/sessions/${s.id}/auto-title`, { method: 'POST' })
    const data = await resp.json()
    if (data.title) { renameText.value = data.title; s.title = data.title; renameDialog.value = null }
  } catch (_) { toast('AI 生成失败') }
  finally { renameGenerating.value = false }
}

// ── Messages ──
async function loadMessages() {
  if (!currentId.value) return
  try {
    const data = await api.getMessages(currentId.value)
    messages.value = data.messages.filter(m => m.role !== 'system')
    loadPendingDrafts()
    nextTick(() => { if (msgArea.value) renderDiagrams(msgArea.value) })
  } catch (_) {}
}

async function send() {
  const text = input.value.trim()
  if (!text || streaming.value || !currentId.value) return

  const userMsg: ChatMessage = { id: `tmp-${Date.now()}`, role: 'user', content: text, createdAt: new Date().toISOString() }
  messages.value.push(userMsg)
  input.value = ''
  streaming.value = true
  scrollToBottom()

  asstMsg.toolCalls = []
  asstMsg.reasoning = ''
  const msg: ChatMessage = asstMsg
  const tcById: Record<string, any> = {}
  let contentChunks = 0

  messages.value.push(msg)
  scrollToBottom()

  try {
    const body: any = { content: text, modelId: currentModel.value, contextLimit: contextLimit.value }
    if (pendingRefs.value.length) { body.refs = pendingRefs.value; pendingRefs.value = [] }

    const resp = await fetch(`/api/chat/sessions/${currentId.value}/messages`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    if (!resp.ok) throw new Error(`API ${resp.status}`)
    const reader = resp.body?.getReader()
    if (!reader) throw new Error('No reader')

    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6))
            if (data.type === 'chunk' && data.text) { msg.content += data.text; contentChunks++; scrollToBottom() }
            else if (data.type === 'done') {
              msg.isStreaming = false
              if (data.quality === 'low') msg.qualityLow = true
              if (data.content) msg.content = data.content
              scrollToBottom()
            }
            else if (data.type === 'error') { msg.isStreaming = false; msg.role = 'error'; msg.content = data.message || '请求失败'; scrollToBottom() }
            else if (data.type === 'reasoning' && data.text) {
              msg.reasoning = (msg.reasoning || '') + data.text
            }
            else if (data.type === 'tool_call') {
              if (!msg.toolCalls) msg.toolCalls = []
              msg.toolCalls.push({ id: data.id, name: data.name, arguments: data.arguments || {} })
            }
            else if (data.type === 'tool_result') {
              const tc = msg.toolCalls?.find(t => t.id === data.id)
              if (tc) tc.result = typeof data.result === 'string' ? data.result.slice(0, 500) : JSON.stringify(data.result).slice(0, 500)
            }
          } catch (_) {}
        }
      }
    }
  } catch (e: any) {
    asstMsg.isStreaming = false; asstMsg.role = 'error'; asstMsg.content = e.message || '请求失败'
  } finally {
    streaming.value = false; scrollToBottom()
    nextTick(() => { if (msgArea.value) renderDiagrams(msgArea.value) })
  }
}

function abortStream() {
  if (currentId.value) fetch(`/api/chat/sessions/${currentId.value}/stream/abort`, { method: 'POST' }).catch(() => {})
  streaming.value = false
}

function clearChat() { messages.value = [] }

function toggleSelect(id: string) {
  const s = selectedIds.value
  if (s.has(id)) s.delete(id); else s.add(id)
  selectedIds.value = new Set(s)
}

function toggleDeleteMode() { deleteMode.value = !deleteMode.value; if (!deleteMode.value) selectedIds.value = new Set() }

function selectAll() {
  if (allSelected.value) selectedIds.value = new Set()
  else selectedIds.value = new Set(messages.value.map(m => m.id).filter(Boolean))
}

async function deleteSingle(id: string) {
  if (!currentId.value) return
  try { await api.deleteMessages(currentId.value, id); await loadMessages() } catch (_) { toast('删除失败') }
}

async function deleteSelected() {
  if (!currentId.value || !selectedIds.value.size) return
  const ids = Array.from(selectedIds.value).join(',')
  try { await api.deleteMessages(currentId.value, ids); selectedIds.value = new Set(); await loadMessages() } catch (_) { toast('删除失败') }
}

function copyMessage(m: ChatMessage) {
  const prefix = m.role === 'user' ? '用户: ' : 'AI: '
  navigator.clipboard.writeText(prefix + m.content.slice(0, 4000)).then(() => toast('已复制')).catch(() => {})
}

function quoteMessage(m: ChatMessage) {
  const prefix = m.role === 'user' ? '用户说' : 'AI说'
  input.value = `> ${prefix}:\n> ${m.content.slice(0, 200)}\n\n` + input.value
}

async function continueAssistant(m: ChatMessage) {
  if (streaming.value) return
  input.value = '请继续...'
  if (!currentId.value) { await createSession() }
  await send()
}

async function saveMsgAsDoc(m: ChatMessage) {
  const title = await prompt('请输入文档标题:', m.content.slice(0, 30) + '...')
  if (!title) return
  try {
    await api.post('/api/documents', { title, content: m.content })
    toast('已保存为文档')
  } catch (_) { toast('保存失败') }
}

// ── Notes ──
async function loadNotes() {
  try { const data = await api.listNotes(); notes.value = data.notes } catch (_) {}
}

function viewNote(n: Note) { viewNoteData.value = n }

async function deleteNote(id: string) {
  try { await api.deleteNote(id); notes.value = notes.value.filter(n => n.id !== id); viewNoteData.value = null } catch (_) { toast('删除失败') }
}

async function execPendingDraft(d: any) {
  if (!d.refs || !d.refs.length) { toast('草稿无引用'); return }
  if (!currentId.value) {
    const s = await api.createSession(`便签分析 #${d.seq || ''}`, currentModel.value || undefined)
    sessions.value.unshift(s)
    currentId.value = s.id
    messages.value = []
  }
  pendingRefs.value = d.refs || []
  input.value = d.userText || '分析这些内容'
  // Remove from pending
  try {
    const raw = localStorage.getItem(`topo_notes_${taskId.value}`)
    if (raw) {
      const all = JSON.parse(raw)
      const idx = all.findIndex((x: any) => x.id === d.id)
      if (idx >= 0) { all.splice(idx, 1); localStorage.setItem(`topo_notes_${taskId.value}`, JSON.stringify(all)) }
    }
  } catch (_) {}
  loadPendingDrafts()
  await send()
}

// ── Documents ──
async function loadDocs() {
  try {
    const data = await api.get('/api/documents', { search: docSearch.value, page_size: '100' })
    documents.value = data.documents || []
  } catch (_) {}
}

async function viewDoc(d: any) {
  try { const data = await api.get(`/api/documents/${d.id}`); viewingDoc.value = data } catch (_) { toast('加载失败') }
}

function openDocEditor() {
  if (!viewingDoc.value) return
  docEditTitle.value = viewingDoc.value.title || ''
  docEditContent.value = viewingDoc.value.content || ''
  docPreview.value = true
  showDocEditor.value = true
}

async function saveDoc() {
  if (!viewingDoc.value) return
  try {
    await api.put(`/api/documents/${viewingDoc.value.id}`, { title: docEditTitle.value, content: docEditContent.value })
    viewingDoc.value.title = docEditTitle.value
    viewingDoc.value.content = docEditContent.value
    showDocEditor.value = false
    toast('已保存')
  } catch (_) { toast('保存失败') }
}

async function deleteDoc(id: string) {
  const ok = await confirm('确定删除此文档？')
  if (!ok) return
  try {
    await api.del(`/api/documents/${id}`)
    documents.value = documents.value.filter((d: any) => d.id !== id)
    if (viewingDoc.value?.id === id) viewingDoc.value = null
    toast('已删除')
  } catch (_) { toast('删除失败') }
}

// ── Archives ──
async function loadArchives() {
  try { const data = await api.listArchives(); archives.value = data.archives } catch (_) {}
}

async function deleteArchive(id: string) {
  const ok = await confirm('确定删除此归档？')
  if (!ok) return
  try { await api.deleteArchive(id); archives.value = archives.value.filter((a: any) => a.id !== id); toast('已删除') }
  catch (_) { toast('删除失败') }
}

// ── Storage event listener (cross-tab note sync) ──
function onStorage(e: StorageEvent) {
  if (e.key?.startsWith('topo_notes')) { loadPendingDrafts(); if (tab.value === 'notes') loadNotes() }
}

// ── Tabs ──
function switchTab(t: 'chat' | 'notes' | 'docs' | 'archives') {
  tab.value = t as any
  if (t === 'notes') loadNotes()
  if (t === 'docs') loadDocs()
  if (t === 'archives') loadArchives()
}

const tabKeys = ['chat', 'notes', 'docs'] as const

// ── Autocomplete ──
function onInputChange() {
  const val = input.value
  const cursorPos = (document.querySelector('.input-row textarea') as HTMLTextAreaElement)?.selectionStart || val.length
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
        autoCompleteVisible.value = false // Real impl would fetch
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
      const ta = document.querySelector('.input-row textarea') as HTMLTextAreaElement
      if (ta) {
        const val = ta.value
        const pos = ta.selectionStart
        const before = val.slice(0, pos)
        const match = before.match(/(\/\w*)$|(@\w*:?\w*)$/)
        if (match) {
          const start = pos - match[1].length
          ta.value = val.slice(0, start) + item.trigger + val.slice(pos)
          ta.selectionStart = ta.selectionEnd = start + item.trigger.length
          ta.focus()
        }
      }
      autoCompleteVisible.value = false
    }
  } else if (e.key === 'Escape') { autoCompleteVisible.value = false }
}

onMounted(async () => {
  applyFontSize(fontSize.value)
  try {
    const data = await api.listModels()
    models.value = data.models
    if (data.webChatDefaultModelId) currentModel.value = data.webChatDefaultModelId
    else if (data.models.length > 0) currentModel.value = data.models[0].id
  } catch (_) {}
  await loadSessions()
  checkStorage()
  window.addEventListener('storage', onStorage)
})

onUnmounted(() => { bc.close(); window.removeEventListener('storage', onStorage) })
</script>

<template>
  <div class="app">
    <AppDialog :dialog="dialog" @ok="(v) => dialog.onOk?.(v)" @cancel="dialog.onCancel?.()" />

    <aside class="sidebar">
      <div class="sidebar-header">
        <div class="logo">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="5" r="2.5"/><circle cx="5" cy="19" r="2.5"/><circle cx="19" cy="19" r="2.5"/><line x1="11" y1="7" x2="6" y2="17"/><line x1="13" y1="7" x2="18" y2="17"/><line x1="7" y1="19" x2="17" y2="19"/></svg>
          <span>TopoCode</span>
        </div>
      </div>
      <div class="sidebar-tabs">
        <div v-for="tk in tabKeys" :key="tk" class="sidebar-tab" :class="{ active: tab === tk }" @click="switchTab(tk)">
          {{ { chat: '对话', notes: '便签', docs: '文档', archives: '归档' }[tk] }}
        </div>
      </div>

      <div v-if="tab === 'chat'" class="sidebar-content">
        <button class="btn-new" @click="createSession">新对话</button>
        <div v-for="s in sessions" :key="s.id" class="session-item" :class="{ active: s.id === currentId }" @click="switchSession(s.id)">
          <span class="title">{{ s.title }}</span>
          <button class="del-btn" @click.stop="deleteSession(s.id)">×</button>
          <button class="rename-btn" @click.stop="openRename(s)">✏️</button>
        </div>
        <div v-if="!sessions.length" class="note-empty">暂无对话</div>
      </div>

      <div v-else-if="tab === 'notes'" class="sidebar-content">
        <div v-for="n in notes" :key="n.id" class="note-item" @click="viewNote(n)">
          <span class="status-dot" :class="n.status"></span>
          <span class="title">{{ n.title || '无标题' }}</span>
        </div>
        <div v-if="!notes.length" class="note-empty">暂无便签</div>
        <div v-if="pendingDrafts.length" class="pending-section">
          <div class="pending-title">待处理草稿</div>
          <div v-for="d in pendingDrafts" :key="d.id" class="pending-item">
            <span class="title">{{ d.userText?.slice(0, 20) || `#${d.seq}` }}</span>
            <button class="send-btn" @click="execPendingDraft(d)">执行</button>
          </div>
        </div>
      </div>

      <div v-else-if="tab === 'archives'" class="sidebar-content">
        <div v-for="a in archives" :key="a.id" class="note-item">
          <span class="title">{{ a.title || a.id.slice(0,16) }}</span>
          <span class="ref-count">{{ a.category }}</span>
          <button class="del-btn" @click.stop="deleteArchive(a.id)">×</button>
        </div>
        <div v-if="!archives.length" class="note-empty">暂无归档</div>
      </div>

      <div v-else class="sidebar-content">
        <input v-model="docSearch" class="sidebar-search" placeholder="搜索文档..." @input="loadDocs" />
        <div v-for="d in documents" :key="d.id" class="note-item" :class="{ active: viewingDoc?.id === d.id }" @click="viewDoc(d)">
          <span class="title">{{ d.title || d.id }}</span>
          <button class="del-btn" @click.stop="deleteDoc(d.id)">×</button>
        </div>
        <div v-if="!documents.length" class="note-empty">暂无文档</div>
      </div>
    </aside>

    <main class="main">
      <!-- Rename Dialog -->
      <div v-if="renameDialog" class="dialog-overlay" @click.self="renameDialog = null">
        <div class="dialog-box" style="width:360px">
          <h3>重命名会话</h3>
          <input v-model="renameText" class="dialog-input" placeholder="输入新标题" @keydown.enter="submitRename" ref="renameInput" />
          <div class="dialog-actions">
            <button class="dialog-btn" @click="renameDialog = null">取消</button>
            <button class="dialog-btn" :disabled="renameGenerating" @click="aiRename">{{ renameGenerating ? '生成中...' : 'AI 生成' }}</button>
            <button class="dialog-btn primary" @click="submitRename">确认</button>
          </div>
        </div>
      </div>

      <!-- Note Detail Dialog -->
      <div v-if="viewNoteData" class="dialog-overlay" @click.self="viewNoteData = null">
        <div class="dialog-box" style="width:500px">
          <h3>{{ viewNoteData.title || '便签详情' }}</h3>
          <div class="note-detail-content">{{ viewNoteData.content || '无内容' }}</div>
          <div v-if="viewNoteData.refs?.length" class="note-detail-refs">
            <div class="ref-section-title">引用 ({{ viewNoteData.refs.length }})</div>
            <div v-for="(r, i) in viewNoteData.refs" :key="i" class="ref-item">{{ r.label || r.text?.slice(0, 50) || `引用 ${i+1}` }}</div>
          </div>
          <div class="dialog-actions">
            <button class="dialog-btn" style="color:#ef4444" @click="deleteNote(viewNoteData.id)">删除</button>
            <button class="dialog-btn" @click="viewNoteData = null">关闭</button>
          </div>
        </div>
      </div>

      <!-- Doc Editor Dialog -->
      <div v-if="showDocEditor" class="dialog-overlay" @click.self="showDocEditor = false">
        <div class="dialog-box" style="width:700px;max-width:95vw">
          <h3><input v-model="docEditTitle" class="dialog-input" style="margin-bottom:8px" placeholder="文档标题" /></h3>
          <div style="display:flex;gap:8px;margin-bottom:8px">
            <label class="toggle-switch">
              <input type="checkbox" v-model="docPreview" /><span class="toggle-slider"></span>
            </label>
            <span style="font-size:12px;color:var(--text-muted)">{{ docPreview ? '预览' : '编辑' }}</span>
          </div>
          <textarea v-if="!docPreview" v-model="docEditContent" style="width:100%;min-height:400px;font-family:var(--font-mono);font-size:13px;padding:12px;border:1px solid var(--border);border-radius:8px;resize:vertical;background:var(--bg-code);color:var(--code-text,#d4d4d4);outline:none" spellcheck="false"></textarea>
          <div v-else class="doc-render" style="min-height:400px;padding:12px;border:1px solid var(--border);border-radius:8px;overflow:auto;font-size:var(--content-font-size)" v-html="renderMarkdown(docEditContent)"></div>
          <div class="dialog-actions" style="margin-top:8px">
            <button class="dialog-btn" @click="showDocEditor = false">取消</button>
            <button class="dialog-btn primary" @click="saveDoc">保存</button>
          </div>
        </div>
      </div>

      <header class="topbar">
        <div class="topbar-left"><span class="chat-title">{{ currentTitle }}</span></div>
        <div class="topbar-right">
          <select v-model="currentModel"><option value="">选择模型</option><option v-for="m in models" :key="m.id" :value="m.id">{{ m.name }}<template v-if="m.isDefault"> ★</template></option></select>
          <select v-model.number="contextLimit"><option :value="16000">16K</option><option :value="32000">32K</option><option :value="64000">64K</option><option :value="128000">128K</option></select>
          <select v-model.number="fontSize"><option :value="13">13px</option><option :value="15">15px</option><option :value="18">18px</option><option :value="22">22px</option><option :value="26">26px</option></select>
          <button class="header-action-btn" @click="toggleDeleteMode">{{ deleteMode ? '取消' : '删除' }}</button>
          <button class="header-action-btn" @click="clearChat">清空</button>
        </div>
      </header>

      <!-- Document view -->
      <div v-if="viewingDoc" class="doc-view">
        <div class="doc-view-body">
          <div class="doc-render" v-html="renderMarkdown(viewingDoc.content || '')"></div>
        </div>
      </div>

      <!-- Messages -->
      <div v-else class="messages" ref="msgArea" :class="{ 'delete-mode': deleteMode }">
        <template v-for="(m, i) in messages" :key="m.id || i">
          <div class="message" :class="m.role" @click.stop>
            <div v-if="deleteMode && m.id" class="cbox-wrap"><input type="checkbox" :checked="selectedIds.has(m.id)" @change="toggleSelect(m.id)" /></div>
            <div v-if="m.role !== 'user'" class="message-avatar ai">AI</div>
            <div class="msg-content">
              <div v-if="m.role === 'assistant'" class="sender">TopoCode</div>
              <div v-if="m.role === 'assistant' && !m.content && m.isStreaming" class="loading-dots"><span></span><span></span><span></span></div>
              <div v-if="m.qualityLow" class="quality-low-banner">⚠️ 本次分析未能生成有效回答</div>
              <div v-if="m.reasoning" class="reasoning-toggle" @click="m.showReasoning = !m.showReasoning">
                <span class="arrow" :class="{ open: m.showReasoning }">▶</span>
                <span>{{ m.showReasoning ? '收起思考过程' : '查看思考过程' }}<span v-if="m.reasoning.length > 10" class="reasoning-tokens">({{ Math.round(m.reasoning.length / 2) }} tokens)</span></span>
              </div>
              <div v-if="m.reasoning && m.showReasoning" class="reasoning-content">{{ m.reasoning }}</div>
              <div v-if="m.toolCalls?.length" class="tool-toggle" @click="m.showToolCalls = !m.showToolCalls">
                <span class="arrow" :class="{ open: m.showToolCalls }">▶</span>
                <span>调用 {{ m.toolCalls.length }} 个工具</span>
              </div>
              <div v-if="m.toolCalls?.length && m.showToolCalls" class="tool-detail">
                <div v-for="tc in m.toolCalls" :key="tc.id" class="tool-call-item">
                  <div class="tool-call-name">🔧 {{ tc.name }}</div>
                  <div class="tool-label">参数</div>
                  <pre>{{ JSON.stringify(tc.arguments, null, 2) }}</pre>
                  <div v-if="tc.result" class="tool-label">执行结果</div>
                  <pre v-if="tc.result">{{ tc.result }}</pre>
                </div>
              </div>
              <div v-else class="bubble" v-html="renderMarkdown(m.content)"></div>
              <div v-if="m.id && !deleteMode" class="message-actions">
                <button class="msg-act-btn" @click="copyMessage(m)" title="复制">📋</button>
                <button class="msg-act-btn" @click="quoteMessage(m)" title="引用">💬</button>
                <button class="msg-act-btn" @click="continueAssistant(m)" title="继续">⟳</button>
                <button class="msg-act-btn" @click="saveMsgAsDoc(m)" title="保存为文档">📄</button>
                <button class="msg-act-btn del-msg" @click="deleteSingle(m.id)" title="删除">🗑️</button>
              </div>
            </div>
          </div>
        </template>
      </div>

      <div v-if="!currentId && !viewingDoc" class="empty-state">
        <p>选择或创建一个对话开始</p><button class="start-btn" @click="createSession">新对话</button>
      </div>

      <div v-if="deleteMode && selectedIds.size > 0" class="delete-bar">
        <span>已选 {{ selectedIds.size }} 条</span>
        <button class="tb-btn" @click="selectAll">{{ allSelected ? '取消全选' : '全选' }}</button>
        <button class="tb-btn" style="background:#ef4444;color:#fff;border-color:#ef4444" @click="deleteSelected">删除 {{ selectedIds.size }}</button>
        <button class="tb-btn" @click="toggleDeleteMode">取消</button>
      </div>

      <div class="input-area" v-if="!viewingDoc">
        <div class="input-wrapper">
          <div class="input-row" style="position:relative">
            <div class="autocomplete-wrap">
              <textarea v-model="input" @keydown.enter.exact="send" @keydown="onInputKeydown" @input="onInputChange" :placeholder="streaming ? 'AI 正在回复...' : '输入消息...'" rows="3" :disabled="streaming" />
              <div v-if="autoCompleteVisible" class="autocomplete-panel open">
                <div v-for="(item, idx) in autoCompleteItems" :key="idx" class="ac-item" :class="{ active: idx === autoCompleteIdx }" @mousedown.prevent="">
                  <span class="ac-trigger">{{ item.trigger }}</span>
                  <span class="ac-hint">{{ item.hint }}</span>
                </div>
              </div>
            </div>
            <button class="btn-send" :class="{ 'stop-btn': streaming }" :disabled="!streaming && !input.trim()" @click="streaming ? abortStream() : send()">
              <svg v-if="!streaming" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>
              <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
            </button>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<style>
:root{--bg:#ffffff;--bg-side:#f7f7f8;--bg-hover:#f0f0f2;--bubble-ai:#ffffff;--bubble-user:#e8e8ea;--border:#e4e4e7;--text:#1a1a1a;--text-secondary:#6b6b76;--text-muted:#8e8e98;--accent:#4d6bfe;--accent-hover:#3a56d4;--accent-light:rgba(77,107,254,0.08);--shadow-sm:0 1px 2px rgba(0,0,0,0.04);--shadow-md:0 4px 16px rgba(0,0,0,0.06);--radius-sm:8px;--radius-md:12px;--radius-lg:16px;--radius-full:9999px;--content-font-size:18px;--ui-font-size:14px;--font:'Inter',-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;--font-mono:"JetBrains Mono","Fira Code",monospace;--transition:0.2s ease}
@media(prefers-color-scheme:dark){
  :root{--bg:#212121;--bg-side:#2d2d2d;--bg-hover:#3d3d3d;--bubble-ai:#2d2d2d;--bubble-user:#3d3d3d;--border:#3d3d3d;--text:#e8e8e8;--text-secondary:#a0a0a0;--text-muted:#6b6b6b;--accent:#60a5fa;--accent-hover:#3b82f6;--accent-light:rgba(96,165,250,0.12)}
}
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;font-family:var(--font);background:var(--bg);color:var(--text);-webkit-font-smoothing:antialiased}
.app{display:flex;height:100vh;overflow:hidden}
.sidebar{width:260px;background:var(--bg-side);border-right:1px solid var(--border);display:flex;flex-direction:column;flex-shrink:0}
.sidebar-header{display:flex;align-items:center;gap:8px;padding:14px 14px 10px}
.sidebar-header .logo{display:flex;align-items:center;gap:8px;font-weight:600;font-size:var(--ui-font-size);color:var(--text);flex:1}
.sidebar-header .logo svg{width:18px;height:18px}
.sidebar-tabs{display:flex;padding:0 12px 10px;gap:4px}
.sidebar-tab{padding:5px 12px;border-radius:var(--radius-md);font-size:var(--ui-font-size);color:var(--text-secondary);cursor:pointer;font-weight:500}
.sidebar-tab:hover{background:var(--bg-hover)}
.sidebar-tab.active{background:var(--accent);color:#fff}
.sidebar-content{flex:1;overflow-y:auto;padding:0 8px 8px}
.sidebar-content,.doc-view-body::-webkit-scrollbar{width:4px}
.sidebar-content::-webkit-scrollbar-track,.doc-view-body::-webkit-scrollbar-track{background:transparent}
.sidebar-content::-webkit-scrollbar-thumb,.doc-view-body::-webkit-scrollbar-thumb{background:var(--border);border-radius:8px}
.sidebar-search{width:100%;padding:6px 10px;font-size:var(--ui-font-size);border:1px solid var(--border);border-radius:var(--radius-md);background:var(--bg);color:var(--text);outline:none;box-sizing:border-box}
.sidebar-search:focus{border-color:var(--accent)}
.btn-new{background:var(--accent-light);color:var(--accent);border:1px solid var(--accent-light);border-radius:var(--radius-md);padding:8px 10px;font-size:var(--ui-font-size);font-weight:500;cursor:pointer;display:block;width:100%;text-align:center;margin-bottom:6px}
.btn-new:hover{background:var(--accent);color:#fff}
.session-item,.note-item{display:flex;align-items:center;padding:8px 10px;border-radius:var(--radius-md);font-size:var(--ui-font-size);color:var(--text-secondary);cursor:pointer;gap:6px;margin-bottom:1px}
.session-item:hover,.note-item:hover{background:var(--bg-hover)}
.session-item.active{background:var(--accent-light);color:var(--text);font-weight:500}
.session-item .title,.note-item .title{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.del-btn,.rename-btn{opacity:0;background:none;border:none;cursor:pointer;padding:2px 6px;border-radius:4px;font-size:var(--ui-font-size);line-height:1;color:var(--text-muted)}
.rename-btn{font-size:12px;padding:2px 4px}
.session-item:hover .del-btn,.session-item:hover .rename-btn,.note-item:hover .del-btn{opacity:1}
.del-btn:hover{background:var(--bg-hover);color:#ef4444}.rename-btn:hover{opacity:1;background:var(--bg-hover)}
.note-item .status-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.note-item .status-dot.draft{background:#f59e0b}
.note-item .status-dot.sent{background:#10b981}
.note-empty{padding:24px;text-align:center;color:var(--text-muted);font-size:var(--ui-font-size)}
.pending-section{border-top:1px solid var(--border);margin:8px 10px 0;padding-top:8px}
.pending-title{font-size:var(--ui-font-size);font-weight:500;color:var(--text-muted);margin-bottom:6px}
.pending-item{display:flex;align-items:center;gap:6px;padding:6px 8px;border-radius:var(--radius-md);border-left:3px solid #f59e0b;margin-bottom:4px}
.pending-item .title{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text);font-size:var(--ui-font-size)}
.send-btn{background:var(--accent);color:#fff;border:none;border-radius:var(--radius-full);padding:2px 10px;font-size:var(--ui-font-size);font-weight:500;cursor:pointer;white-space:nowrap}
.send-btn:hover{background:var(--accent-hover)}
.main{flex:1;display:flex;flex-direction:column;min-width:0}
.topbar{display:flex;align-items:center;justify-content:space-between;padding:12px 24px;border-bottom:1px solid var(--border);flex-shrink:0;background:var(--bg)}
.topbar-left{display:flex;align-items:center;gap:12px}
.chat-title{font-size:var(--ui-font-size);font-weight:500;color:var(--text)}
.topbar-right{display:flex;gap:8px;align-items:center}
.topbar-right select,.header-action-btn{font-size:var(--ui-font-size);padding:5px 10px;border-radius:var(--radius-md);border:1px solid var(--border);background:var(--bg);color:var(--text);cursor:pointer;outline:none}
.header-action-btn{padding:4px 10px}
.topbar-right select:focus,.header-action-btn:hover{border-color:var(--accent)}.header-action-btn:hover{background:var(--bg-hover)}
.doc-view{flex:1;overflow-y:auto;padding:24px 32px}
.doc-view-body{max-width:820px;margin:0 auto;font-size:var(--content-font-size)}
.doc-render{line-height:1.7}
.doc-render h1,.doc-render h2,.doc-render h3{margin:16px 0 8px}
.doc-render p{margin:8px 0}
.doc-render code{padding:1px 4px;background:var(--bg-hover);border-radius:3px;font-size:0.9em}
.doc-render pre{background:var(--bg-code);padding:12px;border-radius:8px;overflow:auto}
.doc-render pre code{background:none;padding:0}
.doc-render ul,.doc-render ol{padding-left:20px;margin:8px 0}
.messages{flex:1;overflow-y:auto;padding:24px 32px 16px;display:flex;flex-direction:column}
.message{display:flex;gap:14px;max-width:820px;margin:0 auto;width:100%;margin-bottom:24px;position:relative;animation:fadeUp .3s ease}
@keyframes fadeUp{0%{opacity:0;transform:translateY(8px)}100%{opacity:1;transform:translateY(0)}}
.message-avatar{width:32px;height:32px;border-radius:var(--radius-full);flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:var(--ui-font-size);font-weight:500;color:#fff}
.message-avatar.ai{background:var(--accent)}
.msg-content{flex:1;display:flex;flex-direction:column;gap:4px;min-width:0;max-width:75%}
.sender{font-weight:500;color:var(--text-secondary);font-size:var(--ui-font-size)}
.bubble{padding:16px 20px;border-radius:var(--radius-lg);font-size:var(--content-font-size,15px);line-height:1.65;word-break:break-word;background:var(--bubble-ai);border:1px solid var(--border);box-shadow:var(--shadow-sm)}
.bubble h1{font-size:1.13em;font-weight:600;margin:16px 0 8px}.bubble h2{font-size:1.07em;font-weight:600;margin:14px 0 6px}.bubble h3{font-size:1em;font-weight:600;margin:12px 0 4px}
.bubble p{margin:6px 8px}.bubble ul,.bubble ol{padding-left:22px;margin:6px 0}
.bubble pre{background:var(--bg-code);padding:12px 14px;border-radius:8px;overflow-x:auto;margin:8px 0;line-height:1.5}
.bubble pre code{font-family:var(--font-mono);background:none;padding:0}
.bubble p>code{background:var(--bg-code);padding:2px 6px;border-radius:4px;font-family:var(--font-mono)}
.bubble a{color:var(--accent);text-decoration:none}
.bubble a:hover{text-decoration:underline}
.bubble blockquote{border-left:3px solid var(--accent);padding:4px 12px;color:var(--text-secondary);margin:8px 0;background:var(--accent-light);border-radius:0 4px 4px 0}
.bubble table{border-collapse:collapse;margin:8px 0;width:100%}
.bubble th,.bubble td{border:1px solid var(--border);padding:6px 10px;text-align:left}
.bubble th{background:var(--bg-hover);font-weight:600}
.message.user .bubble{background:var(--accent-light);border-color:transparent;border-radius:var(--radius-lg)}
.message.user .msg-content{align-items:flex-end}
.message.assistant .msg-content{margin-left:4px}
.message.user .msg-content{margin-right:4px}
.message-actions{display:flex;align-items:center;gap:4px;margin-top:4px;opacity:0;transition:opacity .15s}
.message:hover .message-actions{opacity:1}
.msg-act-btn,.del-msg{background:none;border:none;color:var(--text-muted);font-size:var(--ui-font-size);cursor:pointer;padding:2px 6px;border-radius:4px;line-height:1}
.msg-act-btn:hover,.del-msg:hover{background:var(--bg-hover);color:var(--text-secondary)}
.cbox-wrap{position:absolute;left:-28px;top:8px;display:none}
.delete-mode .cbox-wrap{display:block}
.delete-mode .message-actions{opacity:1!important}
.delete-bar{background:var(--bg);border-top:1px solid var(--border);padding:10px 24px;display:flex;align-items:center;gap:8px;flex-shrink:0}
.quality-low-banner{padding:10px 14px;color:var(--warning,#f59e0b);font-weight:600;font-size:var(--ui-font-size);margin-bottom:4px}
.reasoning-toggle,.tool-toggle{color:var(--text-muted);cursor:pointer;display:inline-flex;align-items:center;gap:4px;user-select:none;padding:2px 0;margin-bottom:4px;font-size:var(--ui-font-size)}
.reasoning-toggle:hover,.tool-toggle:hover{color:var(--accent)}
.reasoning-toggle .arrow,.tool-toggle .arrow{font-size:var(--ui-font-size);transition:transform .2s}
.reasoning-toggle .arrow.open,.tool-toggle .arrow.open{transform:rotate(90deg)}
.reasoning-tokens{font-size:var(--ui-font-size);opacity:0.7;margin-left:2px}
.reasoning-content{color:var(--text-secondary);padding:10px 14px;background:var(--bg-hover);border-radius:8px;margin:4px 0 10px;white-space:pre-wrap;line-height:1.5;max-height:300px;overflow-y:auto;border-left:3px solid var(--accent);font-size:var(--ui-font-size)}
.tool-detail{padding:10px 14px;background:var(--bg-hover);border-radius:8px;margin:4px 0 10px;border-left:3px solid #f59e0b;font-size:var(--ui-font-size)}
.tool-call-item{margin-bottom:8px;font-size:var(--ui-font-size)}
.tool-call-item:last-child{margin-bottom:0}
.tool-call-name{font-weight:500;color:var(--text);margin-bottom:4px}
.tool-label{font-size:var(--ui-font-size);color:var(--text-muted);margin-bottom:2px}
.tool-detail pre{color:var(--text-secondary);margin:2px 0 6px;white-space:pre-wrap;word-break:break-all;max-height:200px;overflow-y:auto;font-family:var(--font-mono);font-size:12px;background:var(--bg-code);padding:6px;border-radius:4px}
.loading-dots{display:inline-flex;gap:4px;align-items:center;padding:8px 0}
.loading-dots span{width:6px;height:6px;border-radius:50%;background:var(--text-muted);animation:pulse 1.2s ease-in-out infinite}
.loading-dots span:nth-child(2){animation-delay:0.2s}
.loading-dots span:nth-child(3){animation-delay:0.4s}
@keyframes pulse{0%,100%{opacity:0.3}50%{opacity:1}}
.input-area{padding:0 24px 24px;flex-shrink:0;display:flex;flex-direction:column;align-items:center}
.input-wrapper{max-width:820px;width:100%;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-lg);box-shadow:var(--shadow-sm);padding:6px 8px 6px 16px}
.input-wrapper:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-light)}
.input-row{display:flex;align-items:flex-end;gap:8px}
.autocomplete-wrap{flex:1;position:relative}
.input-row textarea{flex:1;border:none;outline:none;resize:none;font-family:var(--font);line-height:1.5;padding:8px 0;min-height:52px;max-height:200px;color:var(--text);background:transparent;font-size:var(--content-font-size);width:100%}
.input-row textarea::placeholder{color:var(--text-muted)}
.autocomplete-panel{position:absolute;bottom:100%;left:0;right:0;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-md);box-shadow:0 -4px 16px rgba(0,0,0,0.1);max-height:200px;overflow-y:auto;z-index:100;display:none;margin-bottom:4px}
.autocomplete-panel.open{display:block}
.ac-item{padding:8px 14px;cursor:pointer;color:var(--text);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px}
.ac-item:last-child{border-bottom:none}
.ac-item:hover,.ac-item.active{background:var(--accent);color:#fff}
.ac-trigger{font-weight:600;font-family:var(--font-mono);font-size:var(--ui-font-size);opacity:0.7;min-width:80px}
.ac-hint{font-size:var(--ui-font-size);opacity:0.7}
.ac-item:hover .ac-trigger,.ac-item.active .ac-trigger,.ac-item:hover .ac-hint,.ac-item.active .ac-hint{opacity:1}
.btn-send{background:var(--accent);color:#fff;border:none;width:34px;height:34px;border-radius:var(--radius-full);display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0}
.btn-send:hover{background:var(--accent-hover)}
.btn-send:disabled{opacity:0.4;cursor:not-allowed}
.btn-send.stop-btn{background:#ef4444}.btn-send.stop-btn:hover{background:#dc2626}
.empty-state{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;color:var(--text-muted)}
.start-btn{background:var(--accent);color:#fff;border:none;border-radius:var(--radius-full);padding:8px 20px;font-size:0.93em;font-weight:500;cursor:pointer;margin-top:4px}
.start-btn:hover{background:var(--accent-hover)}
.dialog-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:9999;animation:fadeIn .15s ease}
.dialog-box{background:var(--bg);border:1px solid var(--border);border-radius:12px;padding:24px;max-width:90vw;box-shadow:0 8px 32px rgba(0,0,0,0.25)}
.dialog-box h3{font-size:15px;font-weight:600;color:var(--text);margin-bottom:12px}
.dialog-box p{font-size:14px;color:var(--text-secondary);margin-bottom:16px;line-height:1.5}
.dialog-input{width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:14px;background:var(--bg);color:var(--text);outline:none;margin-bottom:8px;box-sizing:border-box}
.dialog-input:focus{border-color:var(--accent)}
.dialog-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:12px}
.dialog-btn{padding:7px 16px;border-radius:8px;font-size:13px;cursor:pointer;border:1px solid var(--border);background:var(--bg);color:var(--text)}
.dialog-btn:hover{border-color:var(--accent)}
.dialog-btn.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.dialog-btn.primary:hover{background:var(--accent-hover)}
.dialog-btn:disabled{opacity:0.5;cursor:not-allowed}
.note-detail-content{padding:8px 0;font-size:var(--ui-font-size);color:var(--text);line-height:1.6;white-space:pre-wrap;max-height:200px;overflow-y:auto}
.note-detail-refs{margin-top:12px;border-top:1px solid var(--border);padding-top:8px}
.ref-section-title{font-size:var(--ui-font-size);font-weight:500;color:var(--text-muted);margin-bottom:6px}
.ref-item{padding:4px 8px;background:var(--bg-hover);border-radius:4px;margin-bottom:4px;font-size:var(--ui-font-size);color:var(--text)}
.toggle-switch{position:relative;display:inline-flex;width:36px;height:20px;cursor:pointer}
.toggle-switch input{opacity:0;width:0;height:0}
.toggle-slider{position:absolute;inset:0;background:var(--border);border-radius:10px;transition:background .2s}
.toggle-slider::before{content:'';position:absolute;left:2px;top:2px;width:16px;height:16px;background:#fff;border-radius:50%;transition:transform .2s}
.toggle-switch input:checked+.toggle-slider{background:var(--accent)}
.toggle-switch input:checked+.toggle-slider::before{transform:translateX(16px)}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
</style>
