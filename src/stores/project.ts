/** Project Store - 项目管理 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Project, FileTreeNode, AnalysisTask } from '@/types/ipc'
import { ipc } from '@/services/ipc'
import { useAnalysisStore } from '@/stores/analysis'
import i18n from '@/i18n'

export type TabKind = 'file' | 'taskList' | 'taskCreate'

export interface HomeTab {
  id: string
  kind: TabKind
  title: string
  // file 类型
  filePath?: string
  node?: FileTreeNode
  // taskCreate 类型
  taskId?: string  // 编辑已有任务时传入
}

export const useProjectStore = defineStore('project', () => {
  // State
  const projects = ref<Project[]>([])
  const selectedProjectId = ref<string | null>(null)
  const viewMode = ref<'default' | 'project'>('default')
  const tabs = ref<HomeTab[]>([])
  const activeTabId = ref<string | null>(null)
  const loading = ref(false)
  const selectedFile = ref<FileTreeNode | null>(null)

  // Getters
  const selectedProject = computed(() =>
    projects.value.find(p => p.id === selectedProjectId.value)
  )
  const activeTab = computed(() =>
    tabs.value.find(t => t.id === activeTabId.value)
  )
  const projectCount = computed(() => projects.value.length)

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

  async function importProject(path: string) {
    loading.value = true
    try {
      // ipc.project.import() 已通过 adaptProject 完成 snake→camel 转换
      const project = await ipc.project.import(path)
      if (!project) return null
      projects.value.push(project)
      return project
    } finally {
      loading.value = false
    }
  }

  async function selectProject(id: string) {
    selectedProjectId.value = id
    viewMode.value = 'project'
    // 将项目根目录加入 Electron 白名单
    const project = projects.value.find(p => p.id === id)
    if (project && project.path) {
      try {
        await window.api.fs.addAllowedDir(project.path)
      } catch (e) {
        console.warn('Failed to add allowed dir:', e)
      }
    }
    // 清空 tabs，不初始化默认 tab
    tabs.value = []
    activeTabId.value = null
    selectedFile.value = null
  }

  function deselectProject() {
    selectedProjectId.value = null
    viewMode.value = 'default'
    tabs.value = []
    activeTabId.value = null
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
      const debugStore = (await import('@/stores/debug')).useDebugStore()
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
    // 按 filePath 去重，已打开则切换焦点
    const existing = tabs.value.find(t => t.filePath === node.path)
    if (existing) {
      activeTabId.value = existing.id
      return
    }
    // 新开 tab
    const tab: HomeTab = {
      id: `tab-file-${node.path || node.name}`,
      kind: 'file',
      title: node.name,
      filePath: node.path || node.name,
      node,
    }
    tabs.value.push(tab)
    activeTabId.value = tab.id
  }

  function closeTab(tabId: string) {
    const idx = tabs.value.findIndex(t => t.id === tabId)
    if (idx === -1) return

    tabs.value.splice(idx, 1)

    if (activeTabId.value === tabId) {
      if (tabs.value.length > 0) {
        const newIdx = Math.min(idx, tabs.value.length - 1)
        activeTabId.value = tabs.value[newIdx].id
      } else {
        activeTabId.value = null
      }
    }
  }

  function closeAllTabs() {
    tabs.value = []
    activeTabId.value = null
  }

  function setActiveTab(tabId: string) {
    activeTabId.value = tabId
  }

  function openTaskListTab() {
    // 若已存在 taskList tab，直接激活
    const existing = tabs.value.find(tab => tab.kind === 'taskList')
    if (existing) {
      activeTabId.value = existing.id
      return
    }
    const tab: HomeTab = {
      id: `tab-taskList-${Date.now()}`,
      kind: 'taskList',
      title: i18n.global.t('analysis.taskList'),
    }
    tabs.value.push(tab)
    activeTabId.value = tab.id

    // 加载任务数据
    if (selectedProjectId.value) {
      const analysisStore = useAnalysisStore()
      analysisStore.loadTasks(selectedProjectId.value)
    }
  }

  async function openTaskCreateForm(taskId?: string) {
    if (taskId) {
      // 编辑模式 - 使用通用标题，详细数据由 TaskCreateForm 自行加载
      const tab: HomeTab = {
        id: `tab-taskCreate-${Date.now()}`,
        kind: 'taskCreate',
        title: i18n.global.t('analysis.editTask'),
        taskId,
      }
      tabs.value.push(tab)
      activeTabId.value = tab.id
    } else {
      // 新建模式
      const tab: HomeTab = {
        id: `tab-taskCreate-${Date.now()}`,
        kind: 'taskCreate',
        title: i18n.global.t('analysis.newTask'),
      }
      tabs.value.push(tab)
      activeTabId.value = tab.id
    }
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
    loadProjects,
    importProject,
    selectProject,
    deselectProject,
    removeProject,
    syncProject,
    getFileTree,
    updatePath,
    checkFileChanges,
    initSampleData,
    clearSampleData,
    openFileTab,
    closeTab,
    closeAllTabs,
    setActiveTab,
    setSelectedFile,
    openTaskListTab,
    openTaskCreateForm,
  }
})
