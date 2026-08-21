import { createApp } from 'vue'
import AppChat from './AppChat.vue'
import { initTheme } from '@topo/web-core/composables/useTheme'
import '@topo/web-core/styles/variables.scss'

initTheme('chat')

createApp(AppChat).mount('#app')
