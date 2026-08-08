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
    path: '/docs/:docId',
    name: 'DocView',
    component: () => import('@/pages/DocViewPage.vue'),
    meta: { workbench: false, title: '文档预览' },
  },
  {
    path: '/workbench',
    component: () => import('@/pages/WorkbenchLayout.vue'),
    meta: { workbench: true, title: '工作台' },
    children: [
      {
        path: '',
        name: 'ProjectOverview',
        component: () => import('@/pages/ProjectOverviewPage.vue'),
        meta: { workbench: true, title: '项目概览' },
      },
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
        path: 'unit-test',
        name: 'UnitTest',
        component: () => import('@/pages/UnitTestPage.vue'),
        meta: { workbench: true, stepper: true, title: '单元测试' },
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

/**
 * 项目选择持久化在 URL 内(?project=<arch行id> / ?root=<path>，多页签各处理不同项目)。
 * 各菜单/跳转组件 push 时往往不带 query，导致项目绑定丢失。
 * 这里用统一的全局守卫：同一标签内导航时自动继承来源的项目/工作目录参数，
 * 避免「点了菜单就丢项目 → 后续项目级请求无参 → 400」。
 *
 * 规则：
 *  - 目标已带 ?project= / ?root= → 显式覆盖优先，不动；
 *  - 目标为首页 /overview(全局项目选择器) → 不继承(进入即重置到选择态)；
 *  - 其余在站内导航 → 从来源 URL 继承缺失的 project/root。
 */
const PROJECT_QUERY_KEYS = ['project', 'root'] as const

router.beforeEach((to, from) => {
  if (to.path === '/overview' && !to.query.project && !to.query.root) {
    return true
  }
  const inherited: Record<string, string> = {}
  for (const k of PROJECT_QUERY_KEYS) {
    const src = typeof from.query[k] === 'string' ? (from.query[k] as string) : ''
    if (src && typeof to.query[k] !== 'string') inherited[k] = src
  }
  if (Object.keys(inherited).length === 0) return true
  return { path: to.path, query: { ...(to.query as Record<string, string>), ...inherited } }
})

export default router
