/** Project Store - 项目管理 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Project, FileTreeNode } from '@/types/ipc'
import { ipc } from '@/services/ipc'

export interface HomeTab {
  id: string
  type: 'file'
  title: string
  filePath: string
  node: FileTreeNode
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
      const list = await ipc.project.list()
      // 适配后端字段：snake_case → camelCase，过滤 null 条目
      projects.value = (list || []).filter(Boolean).map(p => ({
        ...p,
        rootPath: p.root_path || p.rootPath || p.path || '',
        path: p.root_path || p.path || '',
        needsResync: p.needs_resync ?? p.needsResync ?? 0,
        hasFileChanges: p.has_file_changes ?? p.hasFileChanges ?? 0,
        isSample: p.is_sample ?? p.isSample ?? 0,
      }))
    } finally {
      loading.value = false
    }
  }

  async function importProject(path: string) {
    loading.value = true
    try {
      const project = await ipc.project.import(path)
      if (!project) return null
      // 适配后端字段：root_path → rootPath
      project.rootPath = project.root_path || project.rootPath || project.path || ''
      project.path = project.root_path || project.path || ''
      project.needsResync = project.needs_resync ?? project.needsResync ?? 0
      project.hasFileChanges = project.has_file_changes ?? project.hasFileChanges ?? 0
      project.isSample = project.is_sample ?? project.isSample ?? 0
      // 兼容旧字段
      if (!project.path && project.rootPath) {
        project.path = project.rootPath
      }
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
      type: 'file',
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
  }
})
