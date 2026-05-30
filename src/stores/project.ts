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
import { useReportStore } from '@/stores/report'
import { useDebugStore } from '@/stores/debug'
import { useSettingsStore } from '@/stores/settings'
import { ipc } from '@/services/ipc'

import { useAnalysisStore } from '@/stores/analysis'
import { useFuncGroupStore } from '@/stores/funcGroup'
import i18n from '@/i18n'

export type TabKind = 'file' | 'taskList' | 'taskCreate' | 'report' | 'reportHome' | 'subdoc' | 'groupManager' | 'componentAnalysis'

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
  // child-analysis / subdoc parent context
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
    importProgressCleanup = window.api.on('event:project.import.progress', (data: any) => {
      importProgress.value = data.progress
      importStatus.value = data.phase || ''
      if (data.progress >= 100) {
        importing.value = false
        importProgress.value = null
        importStatus.value = ''
      }
    })
  }

  async function importProject(path: string) {
    initImportListener()
    importing.value = true
    importProgress.value = 0
    importStatus.value = 'scan'
    try {
      // ipc.project.import() 已通过 adaptProject 完成 snake→camel 转换
      const project = await ipc.project.import(path)
      if (!project) return null
      projects.value.push(project)
      return project
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

  async function selectProject(id: string) {
    // 委托给 funcGroup store（首页+代码解析+分析功能组）
    funcGroup.selectProject('home', id)
    funcGroup.selectProject('code', id)
    funcGroup.selectProject('analysis', id)
    if (selectedProjectId.value !== id) {
      selectedFile.value = null
    }
    // 将项目根目录加入 Electron 白名单
    const project = projects.value.find(p => p.id === id)
    if (project && project.path) {
      try {
        await window.api.fs.addAllowedDir(project.path)
      } catch (e) {
        console.warn('Failed to add allowed dir:', e)
      }
    }
    // 默认打开任务列表 tab
    openTaskListTab()
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
    await ipc.project.remove(id)
    const idx = projects.value.findIndex(p => p.id === id)
    if (idx >= 0) projects.value.splice(idx, 1)
    if (selectedProjectId.value === id) deselectProject()
  }

  async function clearProjectCache(id: string) {
    const result = await ipc.analysis.clearProjectCache(id)
    // 清除前端缓存的旧任务数据，避免打开已删除任务的报告
    const analysisStore = useAnalysisStore()
    analysisStore.tasks = []
    const reportStore = useReportStore()
    reportStore.tasks = {}
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

  async function getFileTree(id: string, fromPath: string = null) {
    console.log('[ProjectStore] getFileTree id:', id, 'fromPath:', fromPath)
    const result = await ipc.project.getFileTree(id, fromPath)
    console.log('[ProjectStore] getFileTree result:', JSON.stringify(result).substring(0, 200))
    // 记录到 debug store
    try {
      const debugStore = useDebugStore()
      debugStore.log('projectStore', `[getFileTree] id=${id} fromPath="${fromPath}" → ${result.length} nodes`)
      if (result.length > 0) {
        debugStore.log('projectStore', `  → nodes: ${result.map((n: any) => `${n.type}:${n.name}`).join(', ')}`)
      }
    } catch (e) {
      // ignore
    }
    return result
  }

  async function updatePath(id: string, newRootPath: string) {
    const result = await ipc.project.updatePath(id, newRootPath)
    if (!result?.project) return result
    const idx = projects.value.findIndex(p => p.id === id)
    if (idx >= 0) {
      projects.value[idx] = {
        ...result.project,
        rootPath: result.project.root_path || result.project.rootPath || '',
        needsResync: result.project.needs_resync ?? result.project.needsResync ?? 0,
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
      rootPath: result.project.root_path || result.project.rootPath || '',
      isSample: result.project.is_sample ?? result.project.isSample ?? 0,
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

  function openFileTab(node: FileTreeNode) {
    const pid = funcGroup.currentProjectId;
    // 按 filePath 去重，已打开则切换焦点
    const existing = funcGroup.currentTabs.find(t => t.filePath === node.path)
    if (existing) {
      funcGroup.setActiveTab('home', existing.id)
      return
    }
    // 新开 tab
    const tab: HomeTab = {
      id: `tab-file-${node.path || node.name}`,
      kind: 'file',
      title: node.name,
      projectId: pid,
      filePath: node.path || node.name,
      node,
    }
    funcGroup.openTab('home', tab)
  }

  function closeTab(tabId: string): boolean {
    const tab = funcGroup.currentTabs.find(t => t.id === tabId)
    if (!tab) return false

    // 检查未保存更改
    if (tab.hasUnsavedChanges) {
      const confirmed = confirm(i18n.global.t('report.confirmCloseUnsaved'))
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

  function openTaskListTab() {
    const pid = funcGroup.currentProjectId;
    // 若已存在 taskList tab，直接激活（在 home 功能组中查找）
    const existing = funcGroup.context.home.tabs.find(tab => tab.kind === 'taskList')
    if (existing) {
      funcGroup.setActiveTab('home', existing.id)
      return
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
      analysisStore.loadTasks(pid)
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
  }) {
    const pid = funcGroup.currentProjectId;
    const existing = funcGroup.context.analysis.tabs.find(
      t => t.kind === 'reportHome' && t.taskId === params.taskId
    )
    if (existing) {
      funcGroup.setActiveTab('analysis', existing.id)
      return existing.id
    }
    const title = `${i18n.global.t('analysis.analysisReport')} · ${params.taskName}`
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
    selectProject,
    deselectProject,
    removeProject,
    clearProjectCache,
    syncProject,
    getFileTree,
    updatePath,
    checkFileChanges,
    updateProjectMeta,
    initSampleData,
    clearSampleData,
    openFileTab,
    closeTab,
    closeAllTabs,
    setActiveTab,
    setSelectedFile,
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
