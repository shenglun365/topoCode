import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'
import App from './App.vue'
import router from './router'
import i18n from './i18n'
import { useSettingsStore } from './stores/settings-store'
import '@topo/web-core/styles/global.scss'

// 注入 window.api（HTTP /api/rpc + /ws/events）；已存在则跳过（防御）
import { installBrowserAPI } from '@/services/browser-api'
installBrowserAPI()

// 旧 hash 路由书签一次性迁移（history 切换后兼容）：/app#/xxx → /app/xxx。
// #token= 鉴权片段不匹配 ^#/ 前缀，不受影响（token.ts 自行消费）。
if (/^#\//.test(window.location.hash)) {
  window.history.replaceState(null, '', window.location.pathname + window.location.hash.slice(1))
}

// hash 锚点链接劫持（history 路由兼容）：AppHome/SettingsPage 等 web-core 组件
// 产出 href="#/xxx" 锚点——hash 路由时代浏览器改 hash 即触发路由，history 模式下
// hash 被路由无视（点击停留在原页）。统一翻译为 router.push。
// （web-core portal 自构建仍为 hash 迷你路由，此劫持仅在 workbench 宿主注册。）
document.addEventListener('click', (e) => {
  const el = e.target as HTMLElement | null
  const a = el?.closest?.('a[href^="#/"]') as HTMLAnchorElement | null
  if (!a) return
  e.preventDefault()
  router.push(a.getAttribute('href')!.slice(1))
}, true)

const app = createApp(App)

// Pinia
const pinia = createPinia()
pinia.use(piniaPluginPersistedstate)
app.use(pinia)

// Router
app.use(router)

// i18n
app.use(i18n)

// Initialize locale in settings store
const settingsStore = useSettingsStore()
settingsStore.initLocale()
settingsStore.initFontSize()

// Mount
app.mount('#app')
