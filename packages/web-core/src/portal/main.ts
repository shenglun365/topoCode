import { createApp } from 'vue'
import AppHome from './AppHome.vue'
import { initTheme } from '../composables/useTheme'
import '../styles/variables.scss'

initTheme('portal')

createApp(AppHome).mount('#app')