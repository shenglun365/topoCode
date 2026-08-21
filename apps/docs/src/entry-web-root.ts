import { createApp } from 'vue'
import AppWebRoot from './AppWebRoot.vue'
import { initTheme } from '@topo/web-core/composables/useTheme'
import '@topo/web-core/styles/variables.scss'

initTheme('docs')

createApp(AppWebRoot).mount('#app')
