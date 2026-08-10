import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'
import App from './architect-src/App.vue'
import router from './architect-src/router'
import { i18n } from './architect-src/i18n'
import { useArchSettingsStore } from './architect-src/stores/settings-store'
import './architect-src/styles/global.css'

const app = createApp(App)

const pinia = createPinia()
pinia.use(piniaPluginPersistedstate)
app.use(pinia)

app.use(router)
app.use(i18n)

const settings = useArchSettingsStore()
settings.initLocale()
settings.initFontScale()

app.mount('#app')
