import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/home',
  },
  {
    path: '/home',
    name: 'Home',
    component: () => import('@/pages/HomePage.vue'),
    meta: { title: '项目导入' },
  },
  {
    path: '/code',
    name: 'Code',
    component: () => import('@/pages/CodePage.vue'),
    meta: { title: '代码解析' },
  },
  {
    path: '/analysis',
    name: 'Analysis',
    component: () => import('@/pages/AnalysisPage.vue'),
    meta: { title: '代码分析' },
  },
  {
    path: '/knowledge',
    name: 'Knowledge',
    component: () => import('@/pages/KnowledgePage.vue'),
    meta: { title: '知识库' },
  },
  {
    path: '/coder',
    name: 'Coder',
    component: () => import('@/pages/CoderPage.vue'),
    meta: { title: 'AI 助手' },
  },
  {
    path: '/user',
    name: 'User',
    component: () => import('@/pages/UserPage.vue'),
    meta: { title: '设置' },
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// 路由守卫
router.beforeEach((to, _from, next) => {
  const title = to.meta.title as string
  if (title) {
    document.title = `${title} - TopoCode`
  }
  next()
})

export default router
