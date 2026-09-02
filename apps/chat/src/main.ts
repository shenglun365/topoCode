import { createApp } from 'vue'
import AppChat from './AppChat.vue'
import { initTheme } from '@topo/web-core/composables/useTheme'
import { readLocale } from '@topo/web-core/shell'
import { i18n } from './i18n'
import '@topo/web-core/styles/variables.scss'

initTheme('chat')
document.documentElement.lang = readLocale()

createApp(AppChat).use(i18n).mount('#app')
