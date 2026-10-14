import { createApp } from 'vue'
import AppPortal from './AppPortal.vue'
import { initTheme } from '../composables/useTheme'
import { createPortalI18n } from './i18n'
import { readFontSize, setFontSize } from '../shell'
import '../styles/variables.scss'
import './portal-kit.css'

initTheme('portal')

// 启动时应用已保存字号（--content-font-size → --ui-scale 等比缩放全部门户控件）
setFontSize(readFontSize(), ['--content-font-size'])

const app = createApp(AppPortal)
app.use(createPortalI18n())
app.mount('#app')
