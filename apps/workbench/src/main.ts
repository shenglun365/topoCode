import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'
import App from './App.vue'
import router from './router'
import i18n from './i18n'
import { useSettingsStore } from './stores/settings-store'
import '@topo/web-core/styles/global.scss'

// 注入 window.api（HTTP /api/rpc + /ws/events）；已存在则跳过（防御）
import { installBrowserAPI } from '@topo/web-core/services/browser-api'
installBrowserAPI()

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
