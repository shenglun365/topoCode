import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useProjectStore } from '@/stores/project'

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
    path: '/user',
    name: 'User',
    component: () => import('@/pages/UserPage.vue'),
    meta: { title: '用户中心' },
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/pages/SettingsPage.vue'),
    meta: { title: '设置' },
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/pages/LoginPage.vue'),
    meta: { title: '登录', hideShell: true },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/pages/RegisterPage.vue'),
    meta: { title: '注册', hideShell: true },
  },
  {
    path: '/reset-password',
    name: 'ResetPassword',
    component: () => import('@/pages/ResetPasswordPage.vue'),
    meta: { title: '重置密码', hideShell: true },
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// 路由守卫
router.beforeEach((to, _from, next) => {
  const projectStore = useProjectStore()
  if (projectStore.importing) {
    next(false)
    return
  }
  const title = to.meta.title as string
  if (title) {
    document.title = `${title} - TopoCode`
  }
  next()
})

export default router
