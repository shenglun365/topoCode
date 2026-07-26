import { ref, computed } from 'vue'
import * as api from '@web/services/api'
import { useToast } from '@web/composables/useToast'

export function useNotes(taskId: ReturnType<typeof ref<string>>) {
  console.log('[useNotes] init')
  const { toast } = useToast()

  const notesModalVisible = ref(false)
  const notesList = ref<any[]>([])
  const notesFilterStatus = ref('draft')
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

  const notesKey = computed(() => `topo_notes_${taskId.value}`)

  const filteredNotes = computed(() => {
    let list = notesList.value
    if (notesFilterStatus.value !== 'all') list = list.filter((n: any) => n.status === notesFilterStatus.value)
    if (notesProjectFilter.value) list = list.filter((n: any) => n.refs?.some((r: any) => r.projectId === notesProjectFilter.value))
    if (notesSortOrder.value === 'time') list = [...list].sort((a, b) => (b.createdAt || '').localeCompare(a.createdAt || ''))
    else list = [...list].sort((a, b) => (a.seq || 0) - (b.seq || 0))
    return list
  })

  function _notesMakeRefId(): string { return 'ref_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 6) }

  function updateNotesDot() {
    notesDotVisible.value = notesList.value.some((n: any) => n.status === 'draft' || n.status === 'pending')
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
    const checked = document.querySelectorAll<HTMLInputElement>('.note-ref-cbox:checked')
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
    const pending = notesList.value.filter((n: any) => n.status === 'draft')
    pending.forEach((n: any) => { n.status = 'pending'; n.userText = notesUserText.value || n.userText || '' })
    _notesSave()
    notesModalVisible.value = false
    toast('已标记为待处理')
  }

  async function executeNotes() {
    const checked = document.querySelectorAll<HTMLInputElement>('.note-ref-cbox:checked')
    if (!checked.length && !notesUserText.value.trim()) { toast('请选择便签或输入内容'); return }

    if (notesExecStep.value === 'none') {
      notesExecStep.value = 'sessions'
      await loadNotesSessions()
      return
    }

    if (notesExecStep.value === 'sessions') {
      const selSession = document.querySelector<HTMLSelectElement>('#noteSessionSelect')
      const sessionId = selSession?.value
      if (!sessionId) { toast('请选择会话'); return }
      const refs: any[] = []
      const checked2 = document.querySelectorAll<HTMLInputElement>('.note-ref-cbox:checked')
      checked2.forEach(cb => {
        const [nid, rid] = cb.value.split('|')
        const n = notesList.value.find((x: any) => x.id === nid)
        if (!n) return
        const r = (n.refs || []).find((x: any) => x._id === rid)
        if (r) refs.push(r)
      })
      const execData = { taskId: taskId.value, sessionId, refs, userText: notesUserText.value || '' }
      try {
        localStorage.setItem('topo_exec_pending_' + taskId.value, JSON.stringify(execData))
        window.open(`/chat?taskId=${taskId.value}&sessionId=${sessionId}`, '_blank')
        if (notesAutoDelete.value) {
          checked2.forEach(cb => {
            const [nid, rid] = cb.value.split('|')
            const n = notesList.value.find((x: any) => x.id === nid)
            if (!n) return
            n.refs = (n.refs || []).filter((r: any) => r._id !== rid)
            if (!n.refs.length) notesList.value = notesList.value.filter((x: any) => x.id !== nid)
          })
          _notesSave()
        }
      } catch (_) { toast('执行失败') }
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
