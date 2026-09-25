/**
 * useChat · msgactions 域（MS6-W3 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { ref } from 'vue'
import { diagramStateStore } from '@topo/web-core/services/diagramStateStore'
import * as api from '@topo/web-core/services/api'
import { useToast } from '@topo/web-core/composables/useToast'
import { useI18n } from 'vue-i18n'
import type { ChatMessage } from '@topo/web-core/types/domain'

import type { ChatDeps } from './chatTypes'

export function useChatMsgactions(D: ChatDeps) {
  const { toast } = useToast()
  const {
    allSelected,
    createSession,
    currentId,
    displayMessages,
    input,
    loadMessages,
    loadNotes,
    messages,
    msgShowReasoning,
    msgShowToolCalls,
    tab,
    viewingNote,
  } = D as any
  const { t } = useI18n()

const deleteMode = ref(false)
const selectedIds = ref(new Set<string>())
function toggleSelect(id: string) {
  const s = selectedIds.value
  if (s.has(id)) s.delete(id); else s.add(id)
  selectedIds.value = new Set(s)
}

function toggleReasoning(msgId?: string) {
  if (msgId) msgShowReasoning[msgId] = !msgShowReasoning[msgId]
}
function toggleToolCalls(msgId?: string) {
  if (msgId) msgShowToolCalls[msgId] = !msgShowToolCalls[msgId]
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
  try { await api.deleteMessages(currentId.value, ids); (dm?._mergedIds || [id]).forEach(mid => diagramStateStore.removeAll(mid)); await loadMessages() } catch (_) { toast(t('error.delete')) }
}

async function deleteSelected() {
  if (!currentId.value || !selectedIds.value.size) return
  const allIds = new Set(selectedIds.value)
  displayMessages.value.forEach(dm => {
    if (dm._mergedIds && dm._mergedIds.some(mid => selectedIds.value.has(mid)))
      dm._mergedIds.forEach(id => allIds.add(id))
  })
  const ids = Array.from(allIds).join(',')
  try { await api.deleteMessages(currentId.value, ids); allIds.forEach(id => diagramStateStore.removeAll(id)); selectedIds.value = new Set(); await loadMessages() } catch (_) { toast(t('error.delete')) }
}

function copyMessage(m: ChatMessage) {
  const prefix = m.role === 'user' ? t('msg.copyPrefixUser') : t('msg.copyPrefixAI')
  copyToClipboard(prefix + m.content.slice(0, 4000))
}

function copyToClipboard(text: string) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(() => toast(t('common.copied'))).catch(() => fallbackCopy(text))
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
  try { document.execCommand('copy'); toast(t('common.copied')) } catch (_) {}
  document.body.removeChild(ta)
}

function quoteMessage(m: ChatMessage) {
  const prefix = m.role === 'user' ? t('msg.quoteUser') : t('msg.quoteAI')
  input.value = `> ${prefix}:\n> ${m.content.slice(0, 200)}\n\n` + input.value
}

async function continueAssistant(m: ChatMessage) {
  if (D.stream.streaming.value) return
  input.value = t('msg.continue')
  if (!currentId.value) { await createSession() }
  await D.stream.send()
}

// ── Save message as note ──
const saveAsNoteMsg = ref<ChatMessage | null>(null)

function saveMsgAsNote(m: ChatMessage) {
  saveAsNoteMsg.value = m
}

async function handleSaveAsNote(opts: { mode: 'single' | 'session'; target: 'new' | 'existing'; title: string; noteId?: string }) {
  const msg = saveAsNoteMsg.value
  if (!msg) return
  saveAsNoteMsg.value = null

  let content = ''
  if (opts.mode === 'single') {
    content = msg.content
  } else {
    // 完整对话：拼接所有非 system/tool 消息的 content，略过 reasoning/toolCalls
    content = messages.value
      .filter(m => m.role === 'user' || m.role === 'assistant')
      .map(m => `**${m.role === 'user' ? t('common.roleUser') : t('common.roleAI')}**:\n${m.content}`)
      .join('\n\n---\n\n')
  }
  // 保护代码围栏：替换 fence 内容为占位符，避免 ann:slot 注入到代码块中
  const fences: string[] = []
  const protectedContent = content.replace(
    /```(\w*)\n([\s\S]*?)```/g,
    (match) => { fences.push(match); return `<!-- CODE_FENCE_${fences.length - 1} -->` }
  )
  content = protectedContent.replace(/\n\n/g, '\n\n<!-- ann:slot -->\n\n') + '\n\n<!-- ann:slot -->'
  content = content.replace(/<!-- CODE_FENCE_(\d+) -->/g, (_, i) => fences[parseInt(i)])

  try {
    let noteId = ''
    if (opts.target === 'new') {
      const created: any = await api.post('/api/notes', { title: opts.title, content })
      noteId = created.id || created.noteId || ''
    } else if (opts.noteId) {
      noteId = opts.noteId
      const existing: any = await api.get(`/api/notes/${opts.noteId}`)
      const appended = (existing.content || '') + '\n\n---\n\n' + content
      await api.put(`/api/notes/${opts.noteId}`, { content: appended })
    }
    toast(t('saveAs.saved'))
    await loadNotes()
    if (noteId) {
      try {
        const data = await api.get(`/api/notes/${noteId}`)
        viewingNote.value = data
        tab.value = 'notes'
      } catch (_) {}
    }
  } catch (_) { toast(t('error.save')) }
}

  return {
    continueAssistant,
    copyMessage,
    copyToClipboard,
    deleteMode,
    deleteSelected,
    deleteSingle,
    fallbackCopy,
    handleSaveAsNote,
    quoteMessage,
    saveAsNoteMsg,
    saveMsgAsNote,
    selectAll,
    selectedIds,
    toggleDeleteMode,
    toggleReasoning,
    toggleSelect,
    toggleToolCalls,
  }
}
