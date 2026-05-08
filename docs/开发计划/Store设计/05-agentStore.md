# stores/agent.ts

> Phase 4: Agent 任务调度状态管理 (WebSocket 实时推送)

```typescript
import { defineStore } from 'pinia';

type AgentTaskStatus = 'pending' | 'running' | 'done' | 'failed';

interface AgentTask {
  id: string;
  agentId: string;
  agentName: string;
  status: AgentTaskStatus;
  progress: number;              // 0-100
  currentStep: number;
  totalSteps: number;
  description: string;
  generatedFiles: string[];
  validationResults: {
    compile: boolean;
    tests: { passed: number; total: number };
    fileMatch: boolean;
    signatureMatch: boolean;
  } | null;
  logs: string[];
  estimatedRemaining: number;    // 秒
  createdAt: number;
  finishedAt: number | null;
}

export const useAgentStore = defineStore('agent', () => {
  // ---- State ----
  const tasks = ref<Map<string, AgentTask>>(new Map());
  const selectedTaskId = ref<string | null>(null);

  // ---- Getters ----
  const selectedTask = computed(() =>
    selectedTaskId.value ? tasks.value.get(selectedTaskId.value) ?? null : null
  );

  const runningTasks = computed(() =>
    [...tasks.value.values()].filter(t => t.status === 'running')
  );

  const recentTasks = computed(() =>
    [...tasks.value.values()]
      .sort((a, b) => b.createdAt - a.createdAt)
      .slice(0, 20)
  );

  // ---- Actions ----
  function upsertTask(task: AgentTask) {
    tasks.value.set(task.id, { ...tasks.value.get(task.id), ...task } as AgentTask);
  }

  function updateTaskStatus(taskId: string, status: AgentTaskStatus) {
    const task = tasks.value.get(taskId);
    if (task) {
      task.status = status;
      if (status === 'done' || status === 'failed') {
        task.finishedAt = Date.now();
      }
    }
  }

  function updateTaskProgress(taskId: string, progress: number, currentStep: number) {
    const task = tasks.value.get(taskId);
    if (task) {
      task.progress = progress;
      task.currentStep = currentStep;
    }
  }

  function appendLog(taskId: string, log: string) {
    const task = tasks.value.get(taskId);
    if (task) task.logs.push(log);
  }

  function setValidationResults(taskId: string, results: AgentTask['validationResults']) {
    const task = tasks.value.get(taskId);
    if (task) task.validationResults = results;
  }

  function selectTask(taskId: string | null) {
    selectedTaskId.value = taskId;
  }

  return {
    tasks, selectedTaskId,
    selectedTask, runningTasks, recentTasks,
    upsertTask, updateTaskStatus, updateTaskProgress,
    appendLog, setValidationResults, selectTask,
  };
});
```
