import { createApp } from 'vue'
import AppWebRoot from './AppWebRoot.vue'
import { initTheme } from '@topo/web-core/composables/useTheme'
import { i18n } from './i18n'
import '@topo/web-core/styles/variables.scss'

initTheme('docs')

createApp(AppWebRoot).use(i18n).mount('#app')
