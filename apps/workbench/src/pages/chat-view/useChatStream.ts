/**
 * useChat · stream 域（MS6-W3 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { ref } from 'vue'
import { consumeChatSse } from '@topo/web-core/services/chat-stream'
import * as api from '@topo/web-core/services/api'
import type { ChatMessage } from '@topo/web-core/types/domain'
import { useI18n } from 'vue-i18n'

import type { ChatDeps } from './chatTypes'

export function useChatStream(D: ChatDeps) {
  const { t } = useI18n()
  const {
    createSession,
    currentId,
    currentModel,
    contextLimit,
    diagramEnabled,
    DIAGRAM_LS_KEY,
    displayMessages,
    hasMore,
    input,
    messages,
    messagesOffset,
    pendingRefs,
    scrollToBottom,
  } = D as any

const streaming = ref(false)
async function onCodeChange(msgId: string, diagId: string, newCode: string) {
  const dm = displayMessages.value.find(m => m.id === msgId)
  if (!dm?.content) return

  const idxMatch = diagId.match(/_(\d+)$/)
  const targetIndex = idxMatch ? parseInt(idxMatch[1]) : 0

  const mergedIds = (dm as any)._mergedIds
  let ownerMid = msgId
  let localIdx = targetIndex

  if (mergedIds?.length > 1) {
    let fenceOffset = 0
    for (const mid of mergedIds) {
      const orig = messages.value.find(m => m.id === mid)
      const origFences = (orig?.content || '').match(/```(?:mermaid|plantuml)[\s\S]*?```/g) || []
      if (targetIndex < fenceOffset + origFences.length) {
        ownerMid = mid
        localIdx = targetIndex - fenceOffset
        break
      }
      fenceOffset += origFences.length
    }
  }

  const owner = messages.value.find(m => m.id === ownerMid)
  if (!owner) return
  const ownerParts = (owner.content || '').split(/(```(?:mermaid|plantuml)[\s\S]*?```)/)
  let diagIndex = 0
  let replaced = false
  for (let i = 0; i < ownerParts.length; i++) {
    if (/^```(?:mermaid|plantuml)/.test(ownerParts[i])) {
      if (diagIndex === localIdx) {
        const m = ownerParts[i].match(/^```(?:mermaid|plantuml)\n?/)
        if (m) {
          ownerParts[i] = m[0] + newCode + '\n```'
          replaced = true
        }
        break
      }
      diagIndex++
    }
  }
  if (!replaced) return

  const newContent = ownerParts.join('')
  owner.content = newContent
  try {
    await api.put(`/api/chat/sessions/${currentId.value}/messages/${ownerMid}`, { content: newContent } as any)
  } catch (e) { console.error('[diagram-save] PUT failed', e) }
}

async function onSend(text: string) {
  input.value = text
  await send()
}

async function send() {
  const text = input.value.trim()
  if (!text || streaming.value) return
  if (!currentId.value) { await createSession(); if (!currentId.value) return }
  // Reset pagination on new message
  messagesOffset.value = 0
  hasMore.value = false

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
      method: 'POST', headers: { 'Content-Type': 'application/json', ...api.authHeaders() }, body: JSON.stringify(body),
    })
    if (!resp.ok) { const errBody = await resp.text().catch(() => ''); throw new Error(errBody || `API ${resp.status}`) }

    // SSE 循环已抽为 web-core 共享助手（R2 修正，原此处内联 ReadableStream 循环）
    await consumeChatSse(resp, {
      onChunk: (text) => { msg.content += text; contentChunks++; scrollToBottom() },
      onReasoning: (text) => { msg.reasoning = (msg.reasoning || '') + text },
      onToolCall: (call) => {
        if (!msg.toolCalls) msg.toolCalls = []
        msg.toolCalls.push({ id: call.id, name: call.name, arguments: call.arguments })
      },
      onToolResult: (id, result) => {
        const tc = msg.toolCalls?.find(x => x.id === id)
        if (tc) tc.result = result
      },
      onDone: (data) => {
        msg.isStreaming = false
        if (data.quality === 'low') msg.qualityLow = true
        if (data.content) msg.content = data.content
        if (data.reasoning) msg.reasoning = (msg.reasoning || '') + data.reasoning
        scrollToBottom()
        streaming.value = false
      },
      onError: (message) => {
        msg.isStreaming = false; msg.role = 'error'; msg.content = message || t('error.request')
        scrollToBottom(); streaming.value = false
      },
    })
  } catch (e: any) {
    asstMsg.isStreaming = false; asstMsg.role = 'error'; asstMsg.content = e.message || t('error.request')
  } finally {
    streaming.value = false; scrollToBottom()
  }
}

async function onToggleDiagram(enabled: boolean) {
  diagramEnabled.value = enabled
  try { localStorage.setItem(DIAGRAM_LS_KEY, enabled ? '1' : '0') } catch (_) {}
  if (!currentId.value) return
  try {
    const resp = await fetch(`/api/chat/sessions/${currentId.value}`, { headers: api.authHeaders() })
    const session = await resp.json()
    const meta = (session as any).metadata || {}
    const current: string[] = meta.active_skills || []
    const next = enabled
      ? [...new Set([...current, 'diagram_editor'])]
      : current.filter((s: string) => s !== 'diagram_editor')
    await api.put(`/api/chat/sessions/${currentId.value}`, { skills: next } as any)
  } catch (_) {}
}

function abortStream() {
  if (currentId.value) fetch(`/api/chat/sessions/${currentId.value}/stream/abort`, { method: 'POST', headers: api.authHeaders() }).catch(() => {})
  streaming.value = false
}

  return {
    abortStream,
    onCodeChange,
    onSend,
    onToggleDiagram,
    send,
    streaming,
  }
}
