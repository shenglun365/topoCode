import { ref, computed } from 'vue'
import * as api from '@web/services/api'
import { useToast } from '@web/composables/useToast'

export function useNotes(taskId: ReturnType<typeof ref<string>>) {
  console.log('[useNotes] init')
  const { toast } = useToast()

  const notesModalVisible = ref(false)
  const notesList = ref<any[]>([])
  const notesFilterStatus = ref('all')
  const notesSortOrder = ref('seq')
  const notesProjectFilter = ref('')
  const notesProjectOptions = ref<string[]>([])
  const notesUserText = ref('')
  const notesSelectedSessions = ref<any[]>([])
  const notesSessions = ref<any[]>([])
  const notesExecStep = ref<'none' | 'confirm' | 'sessions'>('none')
  const notesAutoDelete = ref(true)
  const notesDotVisible = ref(false)
  let notesBc: BroadcastChannel | null = null
  let notesPollTimer: any = null
  let _pendingExecRefs: { noteId: string; refId: string }[] = []

  const notesKey = computed(() => `topo_notes_${taskId.value}`)
  const chatDraftsKey = computed(() => `topo_chat_drafts_${taskId.value}`)

  const filteredNotes = computed(() => {
    let list = notesList.value
    if (notesFilterStatus.value !== 'all') list = list.filter((n: any) => n.status === 'draft')
    if (notesProjectFilter.value) list = list.filter((n: any) => n.refs?.some((r: any) => r.projectId === notesProjectFilter.value))
    if (notesSortOrder.value === 'time') list = [...list].sort((a, b) => (b.createdAt || '').localeCompare(a.createdAt || ''))
    else list = [...list].sort((a, b) => (a.seq || 0) - (b.seq || 0))
    return list
  })

  function _notesMakeRefId(): string { return 'ref_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 6) }

  function _chatDraftsLoad(): any[] {
    try {
      const raw = localStorage.getItem(chatDraftsKey.value)
      return raw ? JSON.parse(raw) : []
    } catch (_) { return [] }
  }

  function _chatDraftsSave(list: any[]) {
    try {
      localStorage.setItem(chatDraftsKey.value, JSON.stringify(list))
    } catch (_) {}
  }

  function updateNotesDot() {
    notesDotVisible.value = notesList.value.some((n: any) => n.status === 'draft')
  }

  function _notesSave() {
    try {
      localStorage.setItem(notesKey.value, JSON.stringify(notesList.value))
      updateNotesDot()
      try { notesBc?.postMessage({ type: 'notes' }) } catch (_) {}
    } catch (_) {}
  }

  function _notesLoad() {
    try {
      const raw = localStorage.getItem(notesKey.value)
      notesList.value = raw ? JSON.parse(raw) : []
      // 迁移：旧数据中的 pending/done 转移到 chat drafts key
      const nonDraft = notesList.value.filter((n: any) => n.status !== 'draft')
      if (nonDraft.length) {
        console.log(`[notes] migrate ${nonDraft.length} pending/done to ${chatDraftsKey.value}`)
        const existing = _chatDraftsLoad()
        _chatDraftsSave([...existing, ...nonDraft])
        notesList.value = notesList.value.filter((n: any) => n.status === 'draft')
        _notesSave()
      }
      const projs = new Set<string>()
      for (const n of notesList.value)
        for (const r of (n.refs || []))
          if (r.projectId) projs.add(r.projectId)
      notesProjectOptions.value = Array.from(projs).sort()
      updateNotesDot()
      loadNotesSessions()
    } catch (_) { notesList.value = [] }
  }

  function loadNotesSessions() {
    if (taskId.value) {
      api.listSessions().then(d => { notesSessions.value = d.sessions || [] }).catch(() => {})
    }
  }

  function openNotesModal() {
    notesModalVisible.value = !notesModalVisible.value
    if (notesModalVisible.value) {
      _notesLoad()
      notesExecStep.value = 'none'
      notesUserText.value = ''
    }
  }

  function deleteRefFromNote(noteId: string, refId: string) {
    const n = notesList.value.find((x: any) => x.id === noteId)
    if (!n) return
    n.refs = (n.refs || []).filter((r: any) => r._id !== refId)
    if (!n.refs.length) {
      notesList.value = notesList.value.filter((x: any) => x.id !== noteId)
    }
    _notesSave()
  }

  function deleteNoteById(id: string) {
    notesList.value = notesList.value.filter((x: any) => x.id !== id)
    _notesSave()
  }

  function deleteSelectedRefs() {
    const checked = document.querySelectorAll<HTMLInputElement>('.cbox:checked')
    const ids = new Map<string, string[]>()
    checked.forEach(cb => { const [nid, rid] = cb.value.split('|'); if (!ids.has(nid)) ids.set(nid, []); ids.get(nid)!.push(rid) })
    for (const [nid, rids] of ids) {
      const n = notesList.value.find((x: any) => x.id === nid)
      if (!n) continue
      n.refs = (n.refs || []).filter((r: any) => !rids.includes(r._id))
      if (!n.refs.length) notesList.value = notesList.value.filter((x: any) => x.id !== nid)
    }
    _notesSave()
  }

  function _getOrCreateDraft(): any {
    let draft = notesList.value.find((n: any) => n.status === 'draft')
    if (!draft) {
      const maxSeq = Math.max(0, ...notesList.value.map((n: any) => n.seq || 0))
      draft = { id: 'draft_' + Date.now().toString(36), seq: maxSeq + 1, status: 'draft', createdAt: new Date().toISOString(), refs: [], userText: '' }
      notesList.value.unshift(draft)
    }
    return draft
  }

  function _addRefToDraft(ref: any) {
    const draft = _getOrCreateDraft()
    draft.refs.push({ ...ref, _id: _notesMakeRefId(), seq: draft.refs.length + 1 })
    _notesSave()
    if (notesModalVisible.value) _notesLoad()
  }

  function manualDrafts() {
    const checked = document.querySelectorAll<HTMLInputElement>('.cbox:checked')
    if (!checked.length) { toast('请选择要处理的引用'); return }
    const keepRefs = new Map<string, Set<string>>()
    checked.forEach(cb => {
      const [nid, rid] = cb.value.split('|')
      if (!keepRefs.has(nid)) keepRefs.set(nid, new Set())
      keepRefs.get(nid)!.add(rid)
    })
    const pendingList: any[] = []
    for (const [noteId, refIds] of keepRefs) {
      const n = notesList.value.find((x: any) => x.id === noteId)
      if (!n) continue
      const checkedRefs = (n.refs || []).filter((r: any) => refIds.has(r._id))
      if (!checkedRefs.length) continue
      const existing = _chatDraftsLoad()
      const maxSeq = Math.max(0, ...existing.map((x: any) => x.seq || 0))
      pendingList.push({
        id: 'pending_' + Date.now().toString(36),
        seq: maxSeq + 1,
        status: 'pending',
        refs: checkedRefs,
        userText: notesUserText.value || n.userText || '',
        createdAt: new Date().toISOString(),
      })
      if (notesAutoDelete.value) {
        n.refs = (n.refs || []).filter((r: any) => !refIds.has(r._id))
      }
    }
    _chatDraftsSave([..._chatDraftsLoad(), ...pendingList])
    console.log(`[notes] manualDrafts checked=${checked.length} sourceNoteIds=[${Array.from(keepRefs.keys()).join(',')}] newPending=${pendingList.length} autoDelete=${notesAutoDelete.value}`)
    _notesSave()
    notesModalVisible.value = false
    toast('已标记为待处理')
  }

  async function executeNotes() {
    const checked = document.querySelectorAll<HTMLInputElement>('.cbox:checked')
    if (!checked.length && !notesUserText.value.trim()) { toast('请选择便签或输入内容'); return }

    if (notesExecStep.value === 'none') {
      // 第一歩：保存选中的引用到缓存，避免后续 DOM 重渲染丢失状态
      _pendingExecRefs = []
      checked.forEach(cb => {
        const [nid, rid] = cb.value.split('|')
        _pendingExecRefs.push({ noteId: nid, refId: rid })
      })
      console.log(`[notes] executeNotes step1 checked=${checked.length} cached=${_pendingExecRefs.length} items=${JSON.stringify(_pendingExecRefs)}`)
      notesExecStep.value = 'sessions'
      await loadNotesSessions()
      return
    }

    if (notesExecStep.value === 'sessions') {
      const selSession = document.querySelector<HTMLSelectElement>('#noteSessionSelect')
      let sessionId = selSession?.value
      if (!sessionId) { toast('请选择会话'); return }
      if (sessionId === '__new__') {
        try {
          const s = await api.createSession('新对话')
          sessionId = s.id
          notesSessions.value.unshift(s)
        } catch (_) { toast('创建会话失败'); return }
      }
      const refs: any[] = []
      for (const { noteId, refId } of _pendingExecRefs) {
        const n = notesList.value.find((x: any) => x.id === noteId)
        if (!n) continue
        const r = (n.refs || []).find((x: any) => x._id === refId)
        if (r) refs.push(r)
      }
      console.log(`[notes] executeNotes step2 sessionId=${sessionId} refsCount=${refs.length} autoDelete=${notesAutoDelete.value}`)
      const execData = { taskId: taskId.value, sessionId, refs, userText: notesUserText.value || '' }
      try {
        localStorage.setItem('topo_exec_pending_' + taskId.value, JSON.stringify(execData))
        window.open(`/chat?taskId=${taskId.value}&sessionId=${sessionId}`, '_blank')
        if (notesAutoDelete.value) {
          for (const { noteId, refId } of _pendingExecRefs) {
            const n = notesList.value.find((x: any) => x.id === noteId)
            if (!n) continue
            n.refs = (n.refs || []).filter((r: any) => r._id !== refId)
            if (!n.refs.length) notesList.value = notesList.value.filter((x: any) => x.id !== noteId)
          }
          console.log(`[notes] executeNotes autoDelete removed ${_pendingExecRefs.length} refs`)
          _notesSave()
        }
      } catch (_) { toast('执行失败') }
      _pendingExecRefs = []
      notesModalVisible.value = false
      notesExecStep.value = 'none'
    }
  }

  function initNotesChannel() {
    try {
      notesBc = new BroadcastChannel('topo_notes_' + taskId.value)
      notesBc.onmessage = () => { if (notesModalVisible.value) _notesLoad() }
    } catch (_) {}
    notesPollTimer = setInterval(() => {
      if (!notesModalVisible.value) { _notesLoad() }
    }, 30000)
  }

  return {
    notesModalVisible, notesList, notesFilterStatus, notesSortOrder,
    notesProjectFilter, notesProjectOptions, notesUserText,
    notesSelectedSessions, notesSessions, notesExecStep, notesAutoDelete,
    notesDotVisible, filteredNotes,
    openNotesModal, deleteRefFromNote, deleteNoteById, deleteSelectedRefs,
    manualDrafts, executeNotes, _addRefToDraft,
    _notesLoad, initNotesChannel,
  }
}
