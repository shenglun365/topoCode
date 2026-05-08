# stores/analysis.ts

> Phase 2: 代码分析任务的状态管理

```typescript
import { defineStore } from 'pinia';

type TaskType = 'full-parse' | 'ast-gen' | 'call-chain' | 'dataflow' | 'dep-analysis';
type TaskStatus = 'pending' | 'running' | 'done' | 'failed';

interface AnalysisTask {
  id: string;
  projectId: string;
  type: TaskType;
  status: TaskStatus;
  title: string;
  targetFiles: string[];
  progress: number;        // 0-100
  tags: string[];
  favorite: boolean;
  pinned: boolean;
  createdAt: number;
  finishedAt: number | null;
}

interface TaskReportData {
  taskId: string;
  ast?: any;
  callChain?: any;
  dependencies?: any;
  dataFlow?: any;
  logs?: string[];
}

interface TaskFilter {
  status?: TaskStatus[];
  tags?: string[];
  category?: string;
  projectId?: string;
}

export const useAnalysisStore = defineStore('analysis', () => {
  // ---- State ----
  const tasks = ref<AnalysisTask[]>([]);
  const selectedTask = ref<AnalysisTask | null>(null);
  const currentReport = ref<TaskReportData | null>(null);
  const activeReportTab = ref<string>('ast');
  const filter = ref<TaskFilter>({});
  const viewLayout = ref<'card' | 'list'>('card');

  // ---- Getters ----
  const filteredTasks = computed(() => {
    let result = tasks.value;
    if (filter.value.status?.length) {
      result = result.filter(t => filter.value.status!.includes(t.status));
    }
    if (filter.value.tags?.length) {
      result = result.filter(t =>
        t.tags.some(tag => filter.value.tags!.includes(tag))
      );
    }
    if (filter.value.projectId) {
      result = result.filter(t => t.projectId === filter.value.projectId);
    }
    return result;
  });

  const favoritedTasks = computed(() =>
    tasks.value.filter(t => t.favorite)
  );

  const pinnedTasks = computed(() =>
    tasks.value.filter(t => t.pinned)
  );

  // ---- Actions ----
  function setTasks(list: AnalysisTask[]) {
    tasks.value = list;
  }

  function selectTask(task: AnalysisTask) {
    selectedTask.value = task;
    currentReport.value = null;
  }

  function toggleFavorite(taskId: string) {
    const task = tasks.value.find(t => t.id === taskId);
    if (task) task.favorite = !task.favorite;
  }

  function togglePin(taskId: string) {
    const task = tasks.value.find(t => t.id === taskId);
    if (task) task.pinned = !task.pinned;
  }

  function updateTaskProgress(taskId: string, progress: number) {
    const task = tasks.value.find(t => t.id === taskId);
    if (task) task.progress = progress;
  }

  function setReport(report: TaskReportData) {
    currentReport.value = report;
  }

  function setActiveReportTab(tab: string) {
    activeReportTab.value = tab;
  }

  function setFilter(newFilter: Partial<TaskFilter>) {
    filter.value = { ...filter.value, ...newFilter };
  }

  function clearFilter() {
    filter.value = {};
  }

  return {
    tasks, selectedTask, currentReport, activeReportTab,
    filter, viewLayout,
    filteredTasks, favoritedTasks, pinnedTasks,
    setTasks, selectTask, toggleFavorite, togglePin,
    updateTaskProgress, setReport, setActiveReportTab,
    setFilter, clearFilter,
  };
});
```
