import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useProjectStore } from '@/stores/project'
import { useNavigationStore } from '@/stores/navigation'
import type { PageType } from '@/types'

const routes: RouteRecordRaw[] = [
  // dev 模式：5173/ 显示统一首页（四模块入口）；生产构建（/app 主工作台）仍 redirect 到 /home
  ...(import.meta.env.DEV
    ? [
        {
          path: '/',
          name: 'HomePortal',
          component: () => import('@/pages/HomePortal.vue'),
          meta: { title: '首页', hideShell: true },
        },
      ]
    : [
        {
          path: '/',
          redirect: '/home',
        },
      ]),
  {
    path: '/home',
    name: 'Home',
    component: () => import('@/pages/HomePage.vue'),
    meta: { title: '知识库解析和管理' },
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
    document.title = `TopoCode · ${title}`
  }
  next()
})

const routePageMap: Record<string, PageType> = {
  '/home': 'home',
  '/code': 'code',
  '/analysis': 'analysis',
  '/knowledge': 'knowledge',
}

// 从路由同步左侧导航选中态与面包屑（刷新 / 直达 URL 时保证高亮正确）
router.afterEach((to) => {
  const page = routePageMap[to.path]
  if (!page) return
  useNavigationStore().navigateTo(page)
})

export default router
