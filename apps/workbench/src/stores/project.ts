/** Project Store - 项目管理

职责划分：
- 项目数据管理（projects, loading, selectedFile）保留在此 store
- Tab 管理 + 功能组上下文已迁移至 funcGroup store
- 保留向后兼容的 computed/函数，内部委托给 funcGroup store
*/
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useAnalysisStore } from '@/stores/analysis'
import { useFuncGroupStore } from '@/stores/funcGroup'
import { useReportStore } from '@/stores/report-store'
import { useDebugStore } from '@/stores/debug'
import { useCommunityStore } from '@/stores/community-store'
import { ipc } from '@/services/ipc'
import type { FileTreeNode, Project } from '@/types/ipc'
import i18n from '@/i18n'

export type TabKind = 'file' | 'taskList' | 'taskCreate' | 'report' | 'reportHome' | 'subdoc' | 'groupManager' | 'preSummaryFiles'

export interface HomeTab {
  id: string
  kind: TabKind
  title: string
  projectId?: string  // 归属项目 ID，用于跨项目 tab 隔离
  // file 类型
  filePath?: string
  node?: FileTreeNode
  // taskCreate 类型
  taskId?: string  // 编辑已有任务时传入
  // report 类型
  reportType?: string  // dependency | callChain
  alias?: string  // 用户自定义别名
  // subdoc 类型
  subDocId?: string  // 子文档 ID
  content?: string  // 内联内容（AI 分析结果等，无 subDocId 时使用）
  parentReportId?: string  // 父报告 tab ID
  hasUnsavedChanges?: boolean  // 未保存标记
  // subdoc parent context
  parentLevel?: string
  parentCommId?: string
  parentEdgeType?: string
}

export const useProjectStore = defineStore('project', () => {
  // State
  const projects = ref<Project[]>([])
  const loading = ref(false)
  const selectedFile = ref<FileTreeNode | null>(null)
  const importProgress = ref<number | null>(null)
  const importing = ref(false)
  const importStatus = ref<'scan' | 'write' | 'done' | ''>('')
  /** 项目删除进度（后台删除轮询态；id + phase + progress） */
  const deleteProgress = ref<{ id: string; phase: string; progress: number } | null>(null)

  // 委托给 funcGroup store（首页功能组）
  const funcGroup = useFuncGroupStore()

  // 向后兼容 — 首页功能组的上下文
  const selectedProjectId = computed(() => funcGroup.currentProjectId)
  const viewMode = computed(() => funcGroup.currentProjectId ? 'project' as const : 'default' as const)
  const tabs = computed(() => funcGroup.currentTabs)
  const activeTabId = computed(() => funcGroup.currentActiveTabId)

  // Getters
  const selectedProject = computed(() =>
    projects.value.find(p => p.id === funcGroup.currentProjectId)
  )
  const activeTab = computed(() => funcGroup.currentActiveTab)
  const projectCount = computed(() => projects.value.length)
  // 当前项目的 tabs（跨项目隔离）— 按 projectId 过滤
  const currentProjectTabs = computed(() => {
    const pid = funcGroup.currentProjectId;
    return pid ? funcGroup.currentTabs.filter(t => t.projectId === pid) : funcGroup.currentTabs;
  })

  // Actions
  async function loadProjects() {
    loading.value = true
    try {
      // ipc.project.list() 已通过 adaptProject 完成 snake→camel 转换
      projects.value = await ipc.project.list()
    } finally {
      loading.value = false
    }
  }

  // 导入进度监听器
  let importProgressCleanup: (() => void) | null = null

  function initImportListener() {
    if (importProgressCleanup) return
    importProgressCleanup = window.api!.on('event:project.import.progress', (data: any) => {
      importProgress.value = data.progress
      importStatus.value = data.phase || ''
      if (data.progress >= 100) {
        importing.value = false
        importProgress.value = null
        importStatus.value = ''
        // 超时/异常后导入仍可能完成，重新拉取项目列表
        ipc.project.list().then(list => {
          projects.value = list
        }).catch(() => {})
      }
    })
  }

  async function importProject(path: string, opts?: { mode?: string; branch?: string; head?: string; repoUrl?: string; localRepoPath?: string }) {
    // 检查重复导入
    const existing = projects.value.find(
      p => p.path === path || p.rootPath === path
    )
    if (existing) return null

    // 前置校验：检查是否有正在执行的分析任务
    const { useDialog } = await import('@topo/web-core/composables/useDialog')
    const { confirmChoice } = useDialog()
    const running = await ipc.analysis.listRunningTasks()
    if (running && running.length > 0) {
      const names = running.map((r: any) => r.name).join('、')
      const choice = await confirmChoice(
        i18n.global.t('project.importRunningConfirm', { count: running.length, names }),
        [
          { label: i18n.global.t('project.importChoiceStop'), value: 'stop', variant: 'danger' },
          { label: i18n.global.t('project.importChoiceWait'), value: 'wait', variant: 'warning' },
          { label: i18n.global.t('project.importChoiceCancel'), value: 'cancel', variant: 'ghost' },
        ]
      )
      if (choice === 'cancel') return null
      if (choice === 'stop') {
        for (const r of running) {
          if (!r.id) continue
          try {
            if (r.name && r.name.startsWith('[Agent]')) {
              await ipc.analysis.cancelAgentTask({ agentTaskId: r.id })
            } else {
              const store = useAnalysisStore()
              await store.stopTask(r.id)
            }
          } catch { /* skip */ }
        }
      }
      if (choice === 'wait') {
        while (true) {
          const still = await ipc.analysis.listRunningTasks()
          if (!still || still.length === 0) break
          await new Promise(r => setTimeout(r, 3000))
        }
      }
    }

    initImportListener()
    importing.value = true
    importProgress.value = 0
    importStatus.value = 'scan'
    try {
      // ipc.project.import() 已通过 adaptProject 完成 snake→camel 转换；
      // 后台化后立即返回 {requestId}，此处轮询等待导入完成并取回项目行
      const result: any = await ipc.project.import(path, opts)
      if (result && result.requestId && !result.id) {
        const project = await pollImportCompletion(result.requestId)
        if (!project) return null
        return project
      }
      if (!result) return null
      projects.value.push(result)
      return result
    } catch (e) {
      console.warn('[importProject] import IPC failed, backend may still be processing:', e)
      return null
    } finally {
      // 等待 backend 发布 100% 事件后再重置
      setTimeout(() => {
        if (importProgress.value !== 100) {
          importing.value = false
          importProgress.value = null
          importStatus.value = ''
        }
      }, 3000)
    }
  }

  async function pollImportCompletion(requestId: string, timeoutMs = 15 * 60 * 1000) {
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline) {
      try {
        const st = await ipc.project.importStatus(requestId)
        if (st?.status === 'done') {
          const list = await ipc.project.list()
          const found = (list || []).find(p => p.id === (st.projectId || ''))
          if (found) return found
          return (list && list.length) ? list[list.length - 1] : null
        }
        if (st?.status === 'error') {
          importStatus.value = ''
          return null
        }
      } catch {
        // 轮询失败继续重试
      }
      await new Promise(r => setTimeout(r, 1000))
    }
    return null
  }

  /** 最近选中项目：刷新后无 ?project= 查询时由 AppShell 回退恢复 */
  const LAST_PROJECT_KEY = 'topoone-last-project'

  async function selectProject(id: string) {
    // 刷新直达 /analysis 等页面时项目列表可能尚未加载，selectedProject 依赖它查找，
    // 不加载则 TopBar 项目徽章永远为空
    if (projects.value.length === 0 && !loading.value) {
      await loadProjects().catch(() => {})
    }
    // 统一在此记录最近项目（覆盖所有选择入口，避免回退键过期）
    try { localStorage.setItem(LAST_PROJECT_KEY, id) } catch { /* ignore */ }
    // 委托给 funcGroup store（首页+代码解析+分析功能组）
    funcGroup.selectProject('home', id)
    funcGroup.selectProject('code', id)
    funcGroup.selectProject('analysis', id)
    if (selectedProjectId.value !== id) {
      selectedFile.value = null
    }
    // 将项目根目录加入服务端目录白名单
    const project = projects.value.find(p => p.id === id)
    if (project && project.path) {
      try {
        await window.api!.fs.addAllowedDir(project.path)
      } catch (e) {
        console.warn('Failed to add allowed dir:', e)
      }
    }
    // 默认打开任务列表 tab
    await openTaskListTab()
  }

  function deselectProject() {
    funcGroup.deselectProject('home')
    funcGroup.deselectProject('code')
    funcGroup.deselectProject('analysis')
    selectedFile.value = null
  }

  function setSelectedFile(node: FileTreeNode | null) {
    selectedFile.value = node
  }

  async function removeProject(id: string) {
    const res: any = await ipc.project.remove(id)
    // 同步模式（wait=true / 旧后端）：立即返回
    if (!res || !res.requestId) {
      const idx = projects.value.findIndex(p => p.id === id)
      if (idx >= 0) projects.value.splice(idx, 1)
      if (selectedProjectId.value === id) deselectProject()
      return
    }
    // 后台模式：轮询删除进度（大项目删除耗时较长，UI 需要反馈）
    deleteProgress.value = { id, phase: 'prepare', progress: 0 }
    try {
      for (;;) {
        await new Promise(r => setTimeout(r, 500))
        let st: any
        try {
          st = await ipc.project.removeStatus(res.requestId)
        } catch {
          continue
        }
        if (!st || st.status === 'unknown') {
          // 状态丢失（如后端重启）：视为完成，刷新列表兜底
          break
        }
        deleteProgress.value = { id, phase: st.phase || '', progress: st.progress ?? 0 }
        if (st.status === 'done') break
        if (st.status === 'error') throw new Error(st.error || 'delete failed')
      }
    } finally {
      deleteProgress.value = null
      const idx = projects.value.findIndex(p => p.id === id)
      if (idx >= 0) projects.value.splice(idx, 1)
      if (selectedProjectId.value === id) deselectProject()
    }
  }

  async function clearProjectCache(id: string) {
    let result: any
    try {
      result = await ipc.analysis.clearProjectCache(id)
    } catch (err) {
      console.warn('[ProjectStore] clearProjectCache backend call failed, cleaning local cache anyway:', err)
    }
    // 清除前端缓存的旧任务数据，避免打开已删除任务的报告
    const analysisStore = useAnalysisStore()
    analysisStore.tasks = []
    const communityStore = useCommunityStore()
    communityStore.clearTask(id)
    // 关闭该项目的所有分析 tab，清理已删除任务的引用
    const funcGroup = useFuncGroupStore()
    const ctx = funcGroup.context.analysis
    const tabsToClose = ctx.tabs.filter(t => t.projectId === id)
    for (const tab of tabsToClose) {
      funcGroup.closeTab('analysis', tab.id)
    }
    console.log('[ProjectStore] clearProjectCache result:', result)
    return result
  }

  async function syncProject(id: string) {
    loading.value = true
    try {
      const project = await ipc.project.sync(id)
      const idx = projects.value.findIndex(p => p.id === id)
      if (idx >= 0) projects.value[idx] = project
      return project
    } finally {
      loading.value = false
    }
  }

  async function updatePath(id: string, newRootPath: string) {
    const result = await ipc.project.updatePath(id, newRootPath)
    if (!result?.project) return result
    const idx = projects.value.findIndex(p => p.id === id)
    if (idx >= 0) {
      projects.value[idx] = {
        ...result.project,
        rootPath: (result.project as any).root_path || result.project.rootPath || '',
        needsResync: (result.project as any).needs_resync ?? result.project.needsResync ?? 0,
      }
    }
    return result
  }

  async function checkFileChanges(id: string) {
    return await ipc.project.checkFileChanges(id)
  }

  async function updateProjectMeta(id: string, meta: Record<string, any>) {
    const updated = await ipc.project.updateMeta(id, meta)
    if (updated) {
      // 重新加载列表以获取正确的排序（pinned DESC, sort_order ASC, updated_at DESC）
      await loadProjects()
      return updated
    }
  }

  async function initSampleData() {
    const result = await ipc.project.initSampleData()
    if (!result?.project) return null
    const project = {
      ...result.project,
      rootPath: (result.project as any).root_path || result.project.rootPath || '',
      isSample: result.project.isSample ?? 0,
    }
    projects.value.push(project)
    return project
  }

  async function clearSampleData(id: string) {
    await ipc.project.clearSampleData(id)
    const idx = projects.value.findIndex(p => p.id === id)
    if (idx >= 0) {
      projects.value.splice(idx, 1)
    }
  }

  async function closeTab(tabId: string): Promise<boolean> {
    const tab = funcGroup.currentTabs.find(t => t.id === tabId)
    if (!tab) return false

    if (tab.hasUnsavedChanges) {
      const { useDialog } = await import('@topo/web-core/composables/useDialog')
      const confirmed = await useDialog().confirm(i18n.global.t('report.confirmCloseUnsaved'), '确认', {
        okLabel: i18n.global.t('common.confirm'),
        cancelLabel: i18n.global.t('common.cancel'),
      })
      if (!confirmed) return false
    }

    return funcGroup.closeTab('home', tabId)
  }

  /** 打开子文档 tab */
  function openSubDocTab(params: {
    subDocId?: string
    title: string
    taskId: string
    content?: string
    parentReportId?: string
  }) {
    const pid = funcGroup.currentProjectId;
    if (params.subDocId) {
      const existing = funcGroup.currentTabs.find(
        t => t.kind === 'subdoc' && t.subDocId === params.subDocId
      )
      if (existing) {
        funcGroup.setActiveTab('home', existing.id)
        return existing.id
      }
    }

    const tabId = params.subDocId
      ? `tab-subdoc-${params.subDocId}`
      : `tab-subdoc-inline-${Date.now()}`
    const tab: HomeTab = {
      id: tabId,
      kind: 'subdoc',
      title: params.title,
      projectId: pid,
      subDocId: params.subDocId,
      content: params.content,
      taskId: params.taskId,
      parentReportId: params.parentReportId,
      hasUnsavedChanges: false,
    }
    funcGroup.openTab('home', tab)
    return tab.id
  }

  function closeAllTabs() {
    funcGroup.closeAllTabs('home')
  }

  function setActiveTab(tabId: string) {
    funcGroup.setActiveTab('home', tabId)
  }

  async function openTaskListTab() {
    const pid = funcGroup.currentProjectId;
    // 已有 taskList tab 但属于旧项目 → 先关闭再新建
    const existing = funcGroup.context.home.tabs.find(tab => tab.kind === 'taskList')
    if (existing) {
      if (existing.projectId === pid) {
        funcGroup.setActiveTab('home', existing.id)
        return
      }
      funcGroup.closeTab('home', existing.id)
    }
    const tab: HomeTab = {
      id: `tab-taskList-${Date.now()}`,
      kind: 'taskList',
      title: i18n.global.t('analysis.taskList'),
      projectId: pid,
    }
    funcGroup.openTab('home', tab)

    // 加载任务数据
    if (pid) {
      const analysisStore = useAnalysisStore()
      await analysisStore.loadTasks(pid)
    }
  }

 async function openTaskCreateForm(taskId?: string) {
    const pid = funcGroup.currentProjectId;
    if (taskId) {
      // 编辑模式 - 使用通用标题，详细数据由 TaskCreateForm 自行加载
      const tab: HomeTab = {
        id: `tab-taskCreate-${Date.now()}`,
        kind: 'taskCreate',
        title: i18n.global.t('analysis.editTask'),
        taskId,
        projectId: pid,
      }
      funcGroup.openTab('home', tab)
    } else {
      // 新建模式
      const tab: HomeTab = {
        id: `tab-taskCreate-${Date.now()}`,
        kind: 'taskCreate',
        title: i18n.global.t('analysis.newTask'),
        projectId: pid,
      }
      funcGroup.openTab('home', tab)
    }
  }

  /** 打开分组管理 tab — 全局单例 */
  function openGroupManagerTab() {
    // 确保在 home 功能组
    funcGroup.switchFuncGroup('home')
    // 若已存在 groupManager tab，直接激活
    const existing = funcGroup.context.home.tabs.find(tab => tab.kind === 'groupManager')
    if (existing) {
      funcGroup.setActiveTab('home', existing.id)
      return
    }
    const tab: HomeTab = {
      id: `tab-groupManager`,
      kind: 'groupManager',
      title: i18n.global.t('group.manager'),
      projectId: funcGroup.currentProjectId, // 关联当前项目，避免被 TabBar 过滤
    }
    funcGroup.openTab('home', tab)
  }

  /** 关闭分组管理 tab */
  function closeGroupManagerTab() {
    const tab = funcGroup.context.home.tabs.find(t => t.kind === 'groupManager')
    if (tab) {
      funcGroup.closeTab('home', tab.id)
    }
  }

  /** 打开报告首页 tab — 分析报告生成入口 */
  function openReportHomeTab(params: {
    taskId: string
    taskName: string
    projectName?: string
    projectId?: string
  }) {
    const pid = params.projectId ?? funcGroup.currentProjectId;
    const existing = funcGroup.context.analysis.tabs.find(
      t => t.kind === 'reportHome' && t.taskId === params.taskId
    )
    if (existing) {
      existing.projectId = pid
      funcGroup.setActiveTab('analysis', existing.id)
      return existing.id
    }
    const title = params.taskName
    const tab: HomeTab = {
      id: `tab-reportHome-${params.taskId}-${Date.now()}`,
      kind: 'reportHome',
      title,
      projectId: pid,
      taskId: params.taskId,
    }
    funcGroup.openTab('analysis', tab)
    return tab.id
  }

  return {
    projects,
    selectedProjectId,
    viewMode,
    tabs,
    activeTabId,
    loading,
    selectedFile,
    selectedProject,
    activeTab,
    projectCount,
    currentProjectTabs,
    loadProjects,
    importProject,
    importProgress,
    importing,
    importStatus,
    deleteProgress,
    selectProject,
    deselectProject,
    removeProject,
    clearProjectCache,
    syncProject,
    updatePath,
    checkFileChanges,
    updateProjectMeta,
    initSampleData,
    clearSampleData,
    closeTab,
    closeAllTabs,
    setActiveTab,
    openTaskListTab,
    openTaskCreateForm,
    openGroupManagerTab,
    closeGroupManagerTab,
    openReportHomeTab,
    openSubDocTab,
    // 暴露 funcGroup 供其他功能组使用
    funcGroup,
  }
})
