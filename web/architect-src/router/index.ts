import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/overview' },
  {
    path: '/overview',
    name: 'Overview',
    component: () => import('@/pages/OverviewPage.vue'),
    meta: { workbench: false, title: '项目概览' },
  },
  {
    path: '/workbench',
    component: () => import('@/pages/WorkbenchLayout.vue'),
    meta: { workbench: true, title: '工作台' },
    children: [
      { path: '', redirect: '/workbench/requirements' },
      {
        path: 'requirements',
        name: 'Requirements',
        component: () => import('@/pages/RequirementsPage.vue'),
        meta: { workbench: true, stepper: true, title: '需求分析' },
      },
      {
        path: 'requirements/analysis',
        name: 'RequirementAnalysis',
        component: () => import('@/pages/RequirementWorkspace.vue'),
        meta: { workbench: true, stepper: true, title: '需求管理' },
      },
      {
        path: 'assets',
        name: 'Assets',
        component: () => import('@/pages/AssetsPage.vue'),
        meta: { workbench: true, title: '项目资产' },
      },
      {
        path: 'architecture',
        redirect: '/workbench/assets',
      },
      {
        path: 'execute',
        name: 'Execute',
        component: () => import('@/pages/ExecutePage.vue'),
        meta: { workbench: true, stepper: true, title: '任务执行' },
      },
      {
        path: 'coding',
        redirect: '/workbench/execute',
      },
      {
        path: 'archmap',
        name: 'ArchMap',
        component: () => import('@/pages/ArchMapPage.vue'),
        meta: { workbench: true, title: '架构变更视图' },
      },
      {
        path: 'config',
        name: 'Config',
        component: () => import('@/pages/ConfigPage.vue'),
        meta: { workbench: true, title: '配置管理' },
      },
      {
        path: 'mcp',
        name: 'Mcp',
        component: () => import('@/pages/McpPage.vue'),
        meta: { workbench: true, title: '外部调用' },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/overview' },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

export default router
