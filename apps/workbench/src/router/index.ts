import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import i18n from '@/i18n'
import { useProjectStore } from '@/stores/project'
import { useNavigationStore } from '@/stores/navigation'
import type { PageType } from '@/types'

const routes: RouteRecordRaw[] = [
  // dev 模式：5173/ 显示统一首页（四模块入口）；生产构建（/app 主工作台）仍 redirect 到 /home
  // 门户微路由：AppHome 顶部「全部设置/用户中心」链接指向 #/settings、#/user，宿主路由需等价承接
  ...(import.meta.env.DEV
    ? [
        {
          path: '/',
          name: 'HomePortal',
          component: () => import('@/pages/HomePortal.vue'),
          meta: { title: 'nav.home', hideShell: true },
        },
        {
          path: '/settings',
          name: 'PortalSettings',
          component: () => import('@topo/web-core/portal/settings/SettingsPage.vue'),
          meta: { title: 'nav.settings', hideShell: true },
        },
        {
          path: '/user',
          name: 'PortalUser',
          component: () => import('@topo/web-core/portal/user/UserCenterPage.vue'),
          meta: { title: 'nav.userCenter', hideShell: true },
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
    meta: { title: 'pageTitle.home' },
  },
  {
    path: '/code',
    name: 'Code',
    component: () => import('@/pages/CodePage.vue'),
    meta: { title: 'nav.code' },
  },
  {
    path: '/analysis',
    name: 'Analysis',
    component: () => import('@/pages/AnalysisPage.vue'),
    meta: { title: 'pageTitle.analysis' },
  },
  {
    path: '/knowledge',
    name: 'Knowledge',
    component: () => import('@/pages/KnowledgePage.vue'),
    meta: { title: 'nav.knowledge' },
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/pages/LoginPage.vue'),
    meta: { title: 'pageTitle.login', hideShell: true },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/pages/RegisterPage.vue'),
    meta: { title: 'pageTitle.register', hideShell: true },
  },
  {
    path: '/reset-password',
    name: 'ResetPassword',
    component: () => import('@/pages/ResetPasswordPage.vue'),
    meta: { title: 'pageTitle.resetPassword', hideShell: true },
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
    document.title = `TopoCode · ${i18n.global.t(title)}`
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
