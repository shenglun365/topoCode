import { defineAsyncComponent } from 'vue'

export const RIGHT_PANEL_COMPONENTS: Record<string, ReturnType<typeof defineAsyncComponent>> = {
  debug: defineAsyncComponent(() => import('@/components/debug/DebugPanel.vue')),
  codeIndex: defineAsyncComponent(() => import('@/components/report/CodeIndexPanel.vue')),
  ai: defineAsyncComponent(() => import('@/components/ai/AIAssistantPanel.vue')),
  taskList: defineAsyncComponent(() => import('@/components/report/ReportTaskListPanel.vue')),
  agentTaskList: defineAsyncComponent(() => import('@/components/report/AgentTaskList.vue')),
}
