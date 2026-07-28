<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as api from '@web/services/api'
import { renderMarkdown, renderDocMarkdown, codeFullscreen } from '@web/services/render'
import { diagramStateStore } from '@web/services/diagramStateStore'
import { parseDocContent } from '@web/services/parseContent'
import ChatInput from '@web/components/ChatInput.vue'
import ChatToolbar from '@web/components/ChatToolbar.vue'
import ChatSidebar from '@web/components/ChatSidebar.vue'
import ChatMessage from '@web/components/ChatMessage.vue'
import MermaidViewer from '@web/components/MermaidViewer.vue'
import PlantUmlViewer from '@web/components/PlantUmlViewer.vue'
import RenameDialog from '@web/components/RenameDialog.vue'
import SaveAsDocDialog from '@web/components/SaveAsDocDialog.vue'
import NoteDetailDialog from '@web/components/NoteDetailDialog.vue'
import { useToast } from '@web/composables/useToast'
import { useDialog } from '@web/composables/useDialog'
import AppDialog from '@web/components/shared/AppDialog.vue'
import type { ChatSession, ChatMessage as ChatMsg, ModelConfig, Note } from '@web/types'

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
const MODEL_LS_KEY = 'topoone_last_model'

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

// Batch delete
const deleteMode = ref(false)
const selectedIds = ref(new Set<string>())

const allSelected = computed(() => {
  const ids = displayMessages.value.filter(m => m.id).map(m => m.id)
  return selectedIds.value.size === ids.length && ids.length > 0
})

const currentTitle = computed(() => {
  const s = sessions.value.find(x => x.id === currentId.value)
  return s ? s.title : 'TopoCode AI'
})

const docBlocks = computed(() => parseDocContent(viewingDoc.value?.content || '', viewingDoc.value?.id))

// 合并连续的工具调用助手消息（用于展示）
const displayMessages = computed(() => {
  const enriched: ChatMessage[] = []
  // Phase 1: 从 tool 消息回填结果到同组 assistant 的 toolCalls
  for (const m of messages.value) {
    if (m.role === 'tool' && m.content) {
      for (let i = enriched.length - 1; i >= 0; i--) {
        const prev = enriched[i]
        if (prev.role === 'assistant' && prev.toolCalls?.length) {
          const tc = prev.toolCalls.find(t => !t.result)
          if (tc) { tc.result = m.content.slice(0, 500); break }
        }
      }
      continue
    }
    enriched.push({ ...m })
  }
  // Phase 2: 合并连续的工具调用组
  const merged: ChatMessage[] = []
  for (const m of enriched) {
    if (m.role === 'assistant' && m.toolCalls?.length) {
      const prev = merged[merged.length - 1]
      if (prev?.role === 'assistant' && prev.toolCalls?.length) {
        prev.toolCalls!.push(...m.toolCalls)
        if (m.content) prev.content = (prev.content || '') + (prev.content ? '\n\n' : '') + m.content
        if (m.reasoning) prev.reasoning = (prev.reasoning || '') + '\n\n' + m.reasoning
        if (m.id) prev._mergedIds!.push(m.id)
        continue
      }
    }
    const entry = { ...m, _mergedIds: m.role === 'assistant' && m.id ? [m.id] : undefined }
    merged.push(entry)
  }
  return merged
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
watch(currentModel, (val) => { if (val) try { localStorage.setItem(MODEL_LS_KEY, val) } catch (_) {} })

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
  viewingDoc.value = null
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
      messages.value.forEach(m => { if (m.id) diagramStateStore.removeAll(m.id) })
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
    const resp = await fetch(`/api/chat/sessions/${s.id}/auto-title`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ modelId: currentModel.value }) })
    const data = await resp.json()
    if (data.generated && data.title) {
      renameText.value = data.title
      s.title = data.title
      renameDialog.value = null
      await loadSessions()
    } else {
      toast(data.title ? '标题未变化，请检查模型配置' : 'AI 生成失败')
    }
  } catch (_) { toast('AI 生成失败') }
  finally { renameGenerating.value = false }
}

// ── Messages ──
let _loadMsgCount = 0
async function loadMessages() {
  _loadMsgCount++
  const caller = new Error().stack?.split('\n')[2]?.trim() || '?'
  console.log(`[loadMessages] #${_loadMsgCount} caller=${caller} currentId=${currentId.value}`)
  if (!currentId.value) return
  try {
    const data = await api.getMessages(currentId.value)
    messages.value = data.messages.filter(m => m.role !== 'system')
    data.messages.forEach((m: any, i: number) => {
      if (m.role === 'assistant') console.log(`[loadMessages] #${i} role=${m.role} contentLen=${(m.content||'').length} reasoningLen=${(m.reasoning||'').length} toolCalls=${(m.toolCalls||[]).length} contentStart=${(m.content||'').slice(0,80)}`)
    })
    loadPendingDrafts()
  } catch (_) {}
}

// 代码编辑：子组件触发的 "重新渲染" → 更新 msg.content
async function onCodeChange(msgId: string, diagId: string, newCode: string) {
  const msg = messages.value.find(m => m.id === msgId)
  if (!msg) return
  // 从 diagId 末尾提取图块索引: "diag_msg_{msgId}_{index}"
  const idxMatch = diagId.match(/_(\d+)$/)
  const targetIndex = idxMatch ? parseInt(idxMatch[1]) : 0
  const parts = msg.content.split(/(```(?:mermaid|plantuml)[\s\S]*?```)/)
  let diagIndex = 0
  for (let i = 0; i < parts.length; i++) {
    if (/^```(?:mermaid|plantuml)/.test(parts[i])) {
      if (diagIndex === targetIndex) {
        const match = parts[i].match(/^```(?:mermaid|plantuml)\n?/)
        if (match) {
          parts[i] = match[0] + newCode + '\n```'
        }
        break
      }
      diagIndex++
    }
  }
  msg.content = parts.join('')
  try {
    await api.put(`/api/chat/sessions/${currentId.value}/messages/${msgId}`, { content: msg.content } as any)
  } catch (_) {}
}

async function onSend(text: string) {
  input.value = text
  await send()
}

async function send() {
  const text = input.value.trim()
  if (!text || streaming.value) return
  if (!currentId.value) { await createSession(); if (!currentId.value) return }

  const userMsg: ChatMessage = { id: `tmp-${Date.now()}`, role: 'user', content: text, createdAt: new Date().toISOString() }
  messages.value.push(userMsg)
  input.value = ''
  streaming.value = true
  scrollToBottom()

  const asstMsg: ChatMessage = { id: `tmp-${Date.now()}-asst`, role: 'assistant', content: '', createdAt: new Date().toISOString(), isStreaming: true }
  asstMsg.toolCalls = []
  asstMsg.reasoning = ''
  messages.value.push(asstMsg)
  const msg = messages.value[messages.value.length - 1]
  const tcById: Record<string, any> = {}
  let contentChunks = 0

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
    let chatFinished = false
    while (true) {
      if (chatFinished) break
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
              if (data.reasoning) msg.reasoning = (msg.reasoning || '') + data.reasoning
              console.log(`[sse done] contentLen=${(msg.content||'').length} reasoningLen=${(msg.reasoning||'').length} toolCalls=${(msg.toolCalls||[]).length}`)
              scrollToBottom()
              streaming.value = false
              chatFinished = true
              break
            }
            else if (data.type === 'error') { msg.isStreaming = false; msg.role = 'error'; msg.content = data.message || '请求失败'; scrollToBottom(); streaming.value = false; chatFinished = true; break }
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
  else selectedIds.value = new Set(displayMessages.value.map(m => m.id).filter(Boolean))
}

async function deleteSingle(id: string) {
  if (!currentId.value) return
  const dm = displayMessages.value.find(m => m._mergedIds?.includes(id))
  const ids = dm?._mergedIds ? dm._mergedIds.join(',') : id
  try { await api.deleteMessages(currentId.value, ids); (dm?._mergedIds || [id]).forEach(mid => diagramStateStore.removeAll(mid)); await loadMessages() } catch (_) { toast('删除失败') }
}

async function deleteSelected() {
  if (!currentId.value || !selectedIds.value.size) return
  const allIds = new Set(selectedIds.value)
  displayMessages.value.forEach(dm => {
    if (dm._mergedIds && dm._mergedIds.some(mid => selectedIds.value.has(mid)))
      dm._mergedIds.forEach(id => allIds.add(id))
  })
  const ids = Array.from(allIds).join(',')
  try { await api.deleteMessages(currentId.value, ids); allIds.forEach(id => diagramStateStore.removeAll(id)); selectedIds.value = new Set(); await loadMessages() } catch (_) { toast('删除失败') }
}

function copyMessage(m: ChatMessage) {
  const prefix = m.role === 'user' ? '用户: ' : 'AI: '
  copyToClipboard(prefix + m.content.slice(0, 4000))
}

function copyToClipboard(text: string) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(() => toast('已复制')).catch(() => fallbackCopy(text))
  } else {
    fallbackCopy(text)
  }
}

function fallbackCopy(text: string) {
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'; ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  try { document.execCommand('copy'); toast('已复制') } catch (_) {}
  document.body.removeChild(ta)
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

// ── Save message as document ──
const saveAsDocMsg = ref<ChatMessage | null>(null)

function saveMsgAsDoc(m: ChatMessage) {
  saveAsDocMsg.value = m
}

async function handleSaveAsDoc(opts: { mode: 'single' | 'session'; target: 'new' | 'existing'; title: string; docId?: string }) {
  const msg = saveAsDocMsg.value
  if (!msg) return
  saveAsDocMsg.value = null

  let content = ''
  if (opts.mode === 'single') {
    content = msg.content
  } else {
    // 完整对话：拼接所有非 system/tool 消息的 content，略过 reasoning/toolCalls
    content = messages.value
      .filter(m => m.role === 'user' || m.role === 'assistant')
      .map(m => `**${m.role === 'user' ? '用户' : 'AI'}**:\n${m.content}`)
      .join('\n\n---\n\n')
  }
  content = content.replace(/\n\n/g, '\n\n<!-- ann:slot -->\n\n') + '\n\n<!-- ann:slot -->'

  try {
    if (opts.target === 'new') {
      await api.post('/api/documents', { title: opts.title, content })
    } else if (opts.docId) {
      const existing = await api.get(`/api/documents/${opts.docId}`)
      const appended = (existing.content || '') + '\n\n---\n\n' + content
      await api.put(`/api/documents/${opts.docId}`, { content: appended })
    }
    toast('已保存为文档')
    await loadDocs()
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
    diagramStateStore.removeAll(id)
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

function copyId(id: string) {
  copyToClipboard(id)
}

// ── Annotations ──
const showAnnotations = ref(true)
const editAnnoData = ref<{ id: string; text: string; isNew: boolean; isSlot?: boolean } | null>(null)

function getAnnotationBlocks(html: string): string {
  if (!html) return html
  if (!showAnnotations.value) return html.replace(/<!--\s*annotation:[^\s]+\s*-->[\s\S]*?<!--\s*\/annotation\s*-->/g, '').replace(/<!--\s*ann:slot\s*-->/g, '')
  let r = html.replace(/<!--\s*annotation:([^\s]+)\s*-->([\s\S]*?)<!--\s*\/annotation\s*-->/g,
    (_, id, text) => `<div class="doc-annotation" data-anno-id="${id}"><div class="doc-anno-marker"></div><div class="doc-anno-body">${renderMarkdown(text.trim())}</div></div>`)
  r = r.replace(/<!--\s*ann:slot\s*-->/g,
    () => '<div class="doc-annotation doc-annotation-slot" data-anno-slot><div class="doc-anno-marker" style="opacity:.3"></div><div class="doc-anno-body" style="color:var(--text-muted);font-style:italic;font-size:12px">+ 添加批注</div></div>')
  return r
}
function onDocAnnoClick(e: MouseEvent) {
  const fsBtn = (e.target as HTMLElement).closest('.code-fs-btn') as HTMLElement
  if (fsBtn) {
    const wrap = fsBtn.closest('.code-block-wrap')
    const codeEl = wrap?.querySelector('code')
    const text = codeEl?.textContent || ''
    if (text) { codeFullscreen(text); return }
  }
  const anno = (e.target as HTMLElement).closest('.doc-annotation') as HTMLElement
  if (!anno) return
  const isSlot = anno.dataset?.annoSlot !== undefined
  if (isSlot) {
    editAnnoData.value = { id: '', text: '', isNew: true, isSlot: true }
  } else {
    editAnnoData.value = { id: anno.dataset.annoId || '', text: anno.querySelector('.doc-anno-body')?.textContent?.trim() || '', isNew: false }
  }
}
function addNewAnnotation() { editAnnoData.value = { id: '', text: '', isNew: true } }
function saveAnnotation() {
  if (!editAnnoData.value || !viewingDoc.value) { editAnnoData.value = null; return }
  const { id, text, isNew, isSlot } = editAnnoData.value
  if (!text?.trim()) { editAnnoData.value = null; return }
  const tag = `\n<!-- annotation:${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)} -->\n${text.trim()}\n<!-- /annotation -->\n`
  if (isNew && isSlot) {
    viewingDoc.value.content = viewingDoc.value.content.replace('<!-- ann:slot -->', tag)
  } else if (isNew) {
    viewingDoc.value.content += `\n\n<!-- annotation:${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)} -->${text.trim()}<!-- /annotation -->`
  } else {
    viewingDoc.value.content = viewingDoc.value.content.replace(new RegExp(`<!--\\s*annotation:${id}\\s*-->[\\s\\S]*?<!--\\s*/annotation\\s*-->`, 'g'), `<!-- annotation:${id} -->${text.trim()}<!-- /annotation -->`)
  }
  editAnnoData.value = null; toast('批注已保存')
}
function deleteAnnotation() {
  if (!editAnnoData.value?.id || !viewingDoc.value) return
  viewingDoc.value.content = viewingDoc.value.content.replace(new RegExp(`<!--\\s*annotation:${editAnnoData.value.id}\\s*-->[\\s\\S]*?<!--\\s*/annotation\\s*-->\\n?`, 'g'), '')
  editAnnoData.value = null; toast('批注已删除')
}

// ── Tabs ──
function switchTab(t: 'chat' | 'notes' | 'docs' | 'archives') {
  tab.value = t as any
  if (t === 'chat' || t === 'notes') viewingDoc.value = null
  if (t === 'notes') loadNotes()
  if (t === 'docs') loadDocs()
  if (t === 'archives') loadArchives()
}

// ── State persistence ──
function saveState() {
  try {
    localStorage.setItem('chat_view_state', JSON.stringify({
      tab: tab.value,
      sessionId: currentId.value,
      docId: viewingDoc.value ? viewingDoc.value.id : null,
    }))
  } catch (_) {}
}
watch(tab, saveState)
watch(currentId, saveState)
watch(viewingDoc, saveState)

async function restoreState() {
  try {
    const saved = JSON.parse(localStorage.getItem('chat_view_state') || '')
    if (!saved) { console.log('[restoreState] no saved state'); return }
    console.log(`[restoreState] saved.sessionId=${saved.sessionId} saved.tab=${saved.tab} saved.docId=${saved.docId} currentId=${currentId.value}`)
    if (saved.docId) {
      api.get(`/api/documents/${saved.docId}`).then((data) => {
        viewingDoc.value = data
        tab.value = 'docs'
      }).catch(() => {})
    } else if (saved.sessionId) {
      if (saved.sessionId !== currentId.value) {
        console.log(`[restoreState] switching to saved session ${saved.sessionId} (was ${currentId.value})`)
        currentId.value = saved.sessionId
        tab.value = saved.tab || 'chat'
        await loadMessages()
      } else {
        console.log(`[restoreState] already on session ${saved.sessionId}, skip loadMessages`)
        tab.value = saved.tab || 'chat'
      }
    } else {
      console.log(`[restoreState] restore tab only: ${saved.tab}`)
    }
  } catch (_) {}
}

// ── Diagram view state ──
async function saveDiagState() {
  const id = currentId.value
  if (!id) return
  const toSave: { id: string; content: string }[] = []
  for (const msg of messages.value) {
    if (!msg.id) continue
    const states = diagramStateStore.loadAll(msg.id)
    if (!Object.keys(states).length) continue
    msg.content = diagramStateStore.embedInContent(msg.content, msg.id)
    toSave.push({ id: msg.id, content: msg.content })
  }
  if (!toSave.length) return
  try {
    await api.post(`/api/chat/sessions/${id}/messages/batch`, { messages: toSave })
    for (const { id: mid } of toSave) diagramStateStore.removeAll(mid)
    document.dispatchEvent(new CustomEvent('diagram-state-changed'))
    toast('图状态已保存')
  } catch (_) { toast('保存失败') }
}

/** 保存当前查看文档的图状态 */
async function saveViewingDocDiagState() {
  const doc = viewingDoc.value
  if (!doc) return
  const states = diagramStateStore.loadAll(doc.id)
  if (!Object.keys(states).length) return
  doc.content = diagramStateStore.embedInContent(doc.content, doc.id)
  try {
    await api.put(`/api/documents/${doc.id}`, { content: doc.content } as any)
    diagramStateStore.removeAll(doc.id)
    document.dispatchEvent(new CustomEvent('diagram-state-changed'))
    toast('文档图状态已保存')
  } catch (_) { toast('保存失败') }
}

onMounted(async () => {
  applyFontSize(fontSize.value)

  try {
    const data = await api.listModels()
    models.value = data.models
    const lastModel = localStorage.getItem(MODEL_LS_KEY)
    if (lastModel && data.models.some((m: any) => m.id === lastModel)) {
      currentModel.value = lastModel
    } else if (data.webChatDefaultModelId) {
      currentModel.value = data.webChatDefaultModelId
    } else if (data.models.length > 0) {
      currentModel.value = data.models[0].id
    }
  } catch (_) {}
  await loadSessions()
  await restoreState()
  checkStorage()
  window.addEventListener('storage', onStorage)
})

onUnmounted(() => { bc.close(); window.removeEventListener('storage', onStorage) })
</script>

<template>
  <div class="app">
    <AppDialog :dialog="dialog" @ok="(v) => dialog.onOk?.(v)" @cancel="dialog.onCancel?.()" />

    <ChatSidebar
      :tab="tab"
      :sessions="sessions"
      :currentId="currentId"
      :notes="notes"
      :pendingDrafts="pendingDrafts"
      :archives="archives"
      :documents="documents"
      :docSearch="docSearch"
      :viewingDoc="viewingDoc"
      @update:tab="switchTab"
      @create-session="createSession"
      @switch-session="switchSession"
      @delete-session="deleteSession"
      @open-rename="openRename"
      @view-note="viewNote"
      @delete-note="deleteNote"
      @exec-pending-draft="execPendingDraft"
      @delete-archive="deleteArchive"
      @load-docs="loadDocs"
      @view-doc="viewDoc"
      @delete-doc="deleteDoc"
      @copy-id="copyId"
      @update:docSearch="docSearch = $event"
    />

    <main class="main">
      <RenameDialog
        :visible="!!renameDialog"
        :title="renameText"
        :generating="renameGenerating"
        @update:title="renameText = $event"
        @close="renameDialog = null"
        @submit="submitRename"
        @ai-rename="aiRename"
      />

      <NoteDetailDialog
        :note="viewNoteData"
        @close="viewNoteData = null"
        @delete="deleteNote"
      />

      <SaveAsDocDialog
        :visible="!!saveAsDocMsg"
        :msg-content="saveAsDocMsg?.content || ''"
        :session-messages="messages"
        @close="saveAsDocMsg = null"
        @save="handleSaveAsDoc"
      />

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
          <div v-else class="doc-render" style="min-height:400px;padding:12px;border:1px solid var(--border);border-radius:8px;overflow:auto;font-size:var(--content-font-size)" v-html="renderDocMarkdown(docEditContent)"></div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:4px">使用 &lt;!-- annotation:id --&gt;批注文字&lt;!-- /annotation --&gt; 添加批注</div>
          <div class="dialog-actions" style="margin-top:8px">
            <button class="dialog-btn" @click="showDocEditor = false">取消</button>
            <button class="dialog-btn primary" @click="saveDoc">保存</button>
          </div>
        </div>
      </div>

      <ChatToolbar
        :currentTitle="currentTitle"
        :currentModel="currentModel"
        :models="models"
        :contextLimit="contextLimit"
        :fontSize="fontSize"
        :viewingDoc="!!viewingDoc"
        :viewingDocTitle="viewingDoc?.title || ''"
        :showAnnotations="showAnnotations"
        @update:currentModel="currentModel = $event"
        @update:contextLimit="contextLimit = $event"
        @update:fontSize="fontSize = $event"
        @edit-doc="openDocEditor"
        @toggle-annotations="showAnnotations = !showAnnotations"
        @add-annotation="addNewAnnotation"
      />

      <!-- Document view -->
      <div v-if="viewingDoc" class="doc-view">
        <div class="doc-view-body" @click="onDocAnnoClick">
          <template v-for="(b, i) in docBlocks" :key="i">
            <span v-if="b.type === 'text'" class="doc-render" v-html="getAnnotationBlocks(b.html || '')"></span>
            <MermaidViewer
              v-else-if="b.type === 'mermaid'"
              :code="b.code!"
              :diag-id="b.diagId!"
              :msg-id="viewingDoc?.id"
              :initial-state="b.initialState"
              @save-state="saveViewingDocDiagState"
            />
            <PlantUmlViewer
              v-else-if="b.type === 'plantuml'"
              :code="b.code!"
              :diag-id="b.diagId!"
              :msg-id="viewingDoc?.id"
              :initial-state="b.initialState"
              @save-state="saveViewingDocDiagState"
            />
          </template>
        </div>
      </div>

      <!-- Annotation Editor Dialog -->
      <div v-if="editAnnoData" class="dialog-overlay" @click.self="editAnnoData = null">
        <div class="dialog-box" style="width:500px">
          <h3>{{ editAnnoData.isNew ? '添加批注' : '编辑批注' }}</h3>
          <textarea v-model="editAnnoData.text" class="dialog-input" style="min-height:100px;resize:vertical" placeholder="批注内容..."></textarea>
          <div class="dialog-actions">
            <button v-if="!editAnnoData.isNew" class="dialog-btn" style="color:#ef4444" @click="deleteAnnotation">删除</button>
            <button class="dialog-btn" @click="editAnnoData = null">取消</button>
            <button class="dialog-btn primary" @click="saveAnnotation">保存</button>
          </div>
        </div>
      </div>

      <!-- Messages -->
      <div v-if="!viewingDoc" class="messages" ref="msgArea" :class="{ 'delete-mode': deleteMode }">
        <ChatMessage
          v-for="(m, i) in displayMessages"
          :key="m.id || i"
          :message="m"
          :deleteMode="deleteMode"
          :isSelected="selectedIds.has(m.id || '')"
          @toggle-select="toggleSelect"
          @copy-message="copyMessage"
          @quote-message="quoteMessage"
          @continue-assistant="continueAssistant"
          @save-msg-as-doc="saveMsgAsDoc"
          @delete-single="deleteSingle"
          @code-change="onCodeChange"
          @save-state="saveDiagState"
        />
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

      <ChatInput v-if="!viewingDoc" :streaming="streaming" v-model="input" @send="onSend" @abort-stream="abortStream" />
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
.sidebar-content::-webkit-scrollbar,.doc-view-body::-webkit-scrollbar{width:4px}
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
.del-btn,.rename-btn,.copy-id-btn{opacity:0;background:none;border:none;cursor:pointer;padding:2px 6px;border-radius:4px;font-size:var(--ui-font-size);line-height:1;color:var(--text-muted)}
.copy-id-btn{padding:2px 4px;vertical-align:middle}
.rename-btn{font-size:12px;padding:2px 4px}
.session-item:hover .del-btn,.session-item:hover .rename-btn,.session-item:hover .copy-id-btn,.note-item:hover .del-btn,.note-item:hover .copy-id-btn{opacity:1}
.del-btn:hover{background:var(--bg-hover);color:#ef4444}.rename-btn:hover,.copy-id-btn:hover{opacity:1;background:var(--bg-hover)}
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
.topbar-badge{display:inline-block;font-size:10px;font-weight:600;padding:1px 6px;border-radius:4px;margin-right:6px;vertical-align:middle;line-height:1.6}
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
.badge-doc{background:#dbeafe;color:#2563eb;padding:2px 8px;border-radius:var(--radius-sm);font-weight:500;font-size:12px}
.doc-title-clickable{cursor:pointer;padding:2px 20px 2px 6px;border-radius:var(--radius-md);border:1px solid transparent;position:relative;font-size:15px;color:var(--text);font-weight:600}
.doc-title-clickable:hover{border-color:var(--border);background:var(--bg-hover)}
.doc-title-clickable .edit-icon{display:none;position:absolute;right:4px;top:50%;transform:translateY(-50%);width:14px;height:14px;color:var(--text-muted);pointer-events:none}
.doc-title-clickable:hover .edit-icon{display:inline}
.doc-topbar-btn{background:none;border:1px solid var(--border);border-radius:var(--radius-sm);padding:4px 8px;cursor:pointer;color:var(--text-muted);display:flex;align-items:center}
.doc-topbar-btn:hover{background:var(--bg-hover);color:var(--text)}
.doc-topbar-btn.active{background:var(--accent-light);color:var(--accent);border-color:var(--accent)}
.doc-annotation{display:flex;gap:8px;margin:12px 0;padding:10px 12px;background:var(--bg-hover);border-radius:var(--radius-md);cursor:pointer}
.doc-annotation:hover{outline:1px solid var(--accent)}
.doc-anno-marker{width:3px;flex-shrink:0;background:var(--accent);border-radius:2px;opacity:.6}
.doc-anno-body{flex:1;font-size:13px;color:var(--text-secondary);line-height:1.6}
.doc-anno-body p{margin:4px 0}
.messages{flex:1;overflow-y:auto;padding:24px 32px 16px;display:flex;flex-direction:column}
.message{display:flex;gap:14px;max-width:min(85%,960px);margin:0 auto;width:100%;margin-bottom:24px;position:relative;animation:fadeUp .3s ease}
@keyframes fadeUp{0%{opacity:0;transform:translateY(8px)}100%{opacity:1;transform:translateY(0)}}
.message-avatar{width:32px;height:32px;border-radius:var(--radius-full);flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:var(--ui-font-size);font-weight:500;color:#fff}
.message-avatar.ai{background:var(--accent)}
.msg-content{flex:1;display:flex;flex-direction:column;gap:4px;min-width:0}
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
.reasoning-toggle .arrow,.tool-toggle .arrow{display:inline-flex;transition:transform .2s}
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
.code-block-wrap{position:relative}
.code-block-wrap .code-fs-btn{position:absolute;top:4px;right:4px;width:28px;height:28px;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.4);border:none;border-radius:4px;color:#fff;cursor:pointer;opacity:0;transition:opacity .15s;z-index:1}
.code-block-wrap:hover .code-fs-btn{opacity:1}
.code-block-wrap .code-fs-btn:hover{background:rgba(0,0,0,.6)}
.code-fs-content{max-width:92%;max-height:88vh;overflow:auto;transform-origin:0 0;background:#1e1e1e;border-radius:8px;padding:24px;box-shadow:0 8px 40px rgba(0,0,0,.4)}
.code-fs-content pre{margin:0;white-space:pre;font-family:var(--font-mono,monospace);font-size:14px;line-height:1.6;color:#d4d4d4}
.code-fs-content code{background:transparent!important;padding:0!important;font-family:inherit;color:inherit}
</style>
