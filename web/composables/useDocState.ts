import { ref, nextTick } from 'vue'
import * as api from '@web/services/api'
import type { CommunityChild } from '@web/types'

export function useDocState(taskId: ReturnType<typeof ref<string>>) {
  console.log('[useDocState] init')

  const docId = ref(new URLSearchParams(location.search).get('docId') || '')
  const originalDocId = docId.value
  const urlCid = new URLSearchParams(location.search).get('communityId') || new URLSearchParams(location.search).get('cid') || ''
  const urlEt = new URLSearchParams(location.search).get('edgeType') || 'INCLUDE'

  const docCommId = ref(urlCid)
  const docEdgeType = ref(urlEt)
  const docBreadcrumb = ref<{ label: string; cid: string; et: string }[]>([])
  const doc = ref<{ title: string; content: string; projectId?: string; projectName?: string } | null>(null)
  const loading = ref(true)
  const children = ref<CommunityChild[]>([])
  const docContentRef = ref<HTMLDivElement>()

  // TOC state
  const tocVisible = ref(false)
  const tocCallChildren = ref<CommunityChild[]>([])
  const tocIncludeChildren = ref<CommunityChild[]>([])
  const tocLoading = ref(false)

  // File list state
  const files = ref<any[]>([])
  const filePage = ref(1)
  const fileSearch = ref('')
  const filePreview = ref<any>(null)
  const fileSummary = ref<any>(null)
  const pageMode = ref<'doc' | 'file-summary'>('doc')
  const filteredFiles = ref<any[]>([])

  function pushDocBc(item: { label: string; cid: string; et: string }) {
    const last = docBreadcrumb.value[docBreadcrumb.value.length - 1]
    if (last?.cid === item.cid) return
    docBreadcrumb.value.push(item)
  }

  async function loadDoc(afterRender?: () => void) {
    if (!taskId.value) return; loading.value = true
    try {
      if (docCommId.value) {
        const d = await api.getCommunityDoc(taskId.value, docCommId.value, docEdgeType.value)
        console.log('[useDocState] community doc loaded:', d?.title, 'content length:', d?.content?.length)
        doc.value = { title: d.title, content: d.content, projectId: d.projectId, projectName: d.projectName }
        if (docBreadcrumb.value.length) {
          const last = docBreadcrumb.value[docBreadcrumb.value.length - 1]
          last.label = d.title
        }
      } else if (docId.value) {
        const d: any = await api.get('/api/docs/' + docId.value)
        doc.value = { title: d.title || '文档', content: d.content || '', projectId: d.projectId, projectName: d.projectName }
      } else {
        doc.value = { title: taskId.value, content: '选择左侧子组件查看详细文档' }
        docBreadcrumb.value = []
      }
      await loadChildren()
    } catch (e: any) {
      console.error('[useDocState] loadDoc error:', e?.message || e)
    } finally {
      loading.value = false
      nextTick(() => { if (afterRender) afterRender() })
    }
  }

  async function loadChildren() {
    try {
      const kids = await api.getCommunityChildren(taskId.value, docCommId.value || undefined, docEdgeType.value)
      children.value = kids
    } catch (_) { children.value = [] }
  }

  function navigateTo(cid: string, et?: string) {
    docId.value = ''
    docCommId.value = cid; if (et) docEdgeType.value = et
    pushDocBc({ label: cid.slice(0, 16), cid, et: et || docEdgeType.value })
    loadDoc()
  }

  function navBack(idx: number) {
    if (idx < 0 || !docBreadcrumb.value[idx]) {
      docId.value = originalDocId; docCommId.value = ''; docEdgeType.value = 'INCLUDE'; docBreadcrumb.value = []; loadDoc(); return
    }
    const target = docBreadcrumb.value[idx]
    if (target?.cid) { docCommId.value = target.cid; docEdgeType.value = target.et || 'INCLUDE'; docBreadcrumb.value = docBreadcrumb.value.slice(0, idx + 1); loadDoc() }
  }

  // ── File list ──
  async function loadFiles() {
    if (!docCommId.value) return
    try {
      const data = await api.get('/api/community-files', { task_id: taskId.value, community_id: docCommId.value, edge_type: docEdgeType.value })
      files.value = data.files || []
      filteredFiles.value = data.files || []
    } catch (_) { files.value = []; filteredFiles.value = [] }
  }

  function filterFiles() {
    const q = fileSearch.value.toLowerCase()
    filteredFiles.value = files.value.filter((f: any) => f.path.toLowerCase().includes(q))
  }

  function openFilePreview(fp: string) {
    filePreview.value = fp; pageMode.value = 'file-summary'
    if (taskId.value) {
      api.get('/api/file-summary', { task_id: taskId.value, file_path: fp }).then(d => { fileSummary.value = d }).catch(() => { fileSummary.value = null })
    }
  }

  // ── TOC ──
  async function toggleToc() {
    tocVisible.value = !tocVisible.value
    if (tocVisible.value) await loadTocData()
  }

  async function loadTocData() {
    tocLoading.value = true
    tocCallChildren.value = []
    tocIncludeChildren.value = []
    try {
      const isRoot = !docCommId.value
      if (isRoot) {
        const [callKids, includeKids] = await Promise.all([
          api.getCommunityChildren(taskId.value, undefined, 'CALL'),
          api.getCommunityChildren(taskId.value, undefined, 'INCLUDE'),
        ])
        tocCallChildren.value = callKids || []
        tocIncludeChildren.value = includeKids || []
      } else {
        const kids = await api.getCommunityChildren(taskId.value, docCommId.value, docEdgeType.value)
        if (docEdgeType.value === 'CALL') tocCallChildren.value = kids || []
        else tocIncludeChildren.value = kids || []
      }
    } catch (_) {
      tocCallChildren.value = []
      tocIncludeChildren.value = []
    } finally { tocLoading.value = false }
  }

  function tocNavigate(c: CommunityChild) {
    tocVisible.value = false
    docId.value = ''
    docCommId.value = c.commId
    docEdgeType.value = c.edgeType || docEdgeType.value
    pushDocBc({ label: c.name || c.commId, cid: c.commId, et: c.edgeType || docEdgeType.value })
    loadDoc()
  }

  return {
    docId, originalDocId,
    docCommId, docEdgeType, docBreadcrumb, doc, loading, children,
    docContentRef,
    tocVisible, tocCallChildren, tocIncludeChildren, tocLoading,
    files, filePage, fileSearch, filePreview, fileSummary, pageMode, filteredFiles,
    pushDocBc, loadDoc, loadChildren, navigateTo, navBack,
    loadFiles, filterFiles, openFilePreview,
    toggleToc, loadTocData, tocNavigate,
  }
}
