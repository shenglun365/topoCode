import { createApp } from 'vue'
import AppViewer from './AppViewer.vue'
import { initTheme } from '@topo/web-core/composables/useTheme'
import '@topo/web-core/styles/variables.scss'

initTheme('docs')

createApp(AppViewer).mount('#app')
