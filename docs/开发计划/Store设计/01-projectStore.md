# stores/project.ts

> Phase 2: 项目导入与代码分析的状态管理

```typescript
import { defineStore } from 'pinia';

interface ProjectMeta {
  id: string;
  name: string;
  path: string;
  language: string;
  fileCount: number;
  lastModified: number;
  syncStatus: 'synced' | 'changed' | 'error';
  analysisProgress: number;  // 0-100
}

interface HomeTabCard {
  id: string;
  type: 'file' | 'task-private' | 'task-shared' | 'report';
  title: string;
  icon: string;
  data: any;
  closable: boolean;
}

export const useProjectStore = defineStore('project', () => {
  // ---- State ----
  const projects = ref<ProjectMeta[]>([]);
  const selectedProject = ref<ProjectMeta | null>(null);
  const viewMode = ref<'files' | 'tasks'>('files');
  const homeTabs = ref<HomeTabCard[]>([]);
  const activeHomeTabId = ref<string | null>(null);

  // ---- Getters ----
  const selectedProjectId = computed(() => selectedProject.value?.id ?? null);
  const hasProject = computed(() => selectedProject.value !== null);
  const activeHomeTab = computed(() =>
    homeTabs.value.find(t => t.id === activeHomeTabId.value) ?? null
  );

  // ---- Actions ----
  function setProjects(list: ProjectMeta[]) {
    projects.value = list;
  }

  function selectProject(project: ProjectMeta) {
    selectedProject.value = project;
    homeTabs.value = [];
    activeHomeTabId.value = null;
  }

  function deselectProject() {
    selectedProject.value = null;
  }

  function setViewMode(mode: 'files' | 'tasks') {
    viewMode.value = mode;
  }

  function openTab(tab: HomeTabCard) {
    // 最大 10 个 Tab，超出时移除最早的
    if (homeTabs.value.length >= 10) {
      homeTabs.value.shift();
    }
    // 去重
    const existing = homeTabs.value.find(t => t.id === tab.id);
    if (!existing) {
      homeTabs.value.push(tab);
    }
    activeHomeTabId.value = tab.id;
  }

  function closeTab(tabId: string) {
    const idx = homeTabs.value.findIndex(t => t.id === tabId);
    if (idx === -1) return;
    homeTabs.value.splice(idx, 1);
    // 如果关闭的是激活 Tab，自动激活相邻 Tab
    if (activeHomeTabId.value === tabId) {
      const newIdx = Math.min(idx, homeTabs.value.length - 1);
      activeHomeTabId.value = homeTabs.value[newIdx]?.id ?? null;
    }
  }

  function switchTab(tabId: string) {
    activeHomeTabId.value = tabId;
  }

  return {
    // State
    projects, selectedProject, viewMode,
    homeTabs, activeHomeTabId,
    // Getters
    selectedProjectId, hasProject, activeHomeTab,
    // Actions
    setProjects, selectProject, deselectProject, setViewMode,
    openTab, closeTab, switchTab,
  };
});
```
