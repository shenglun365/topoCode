<script setup lang="ts">
import { ref, onMounted } from 'vue'

interface CustomTheme {
  id: string
  name: string
  colors: Record<string, string>
  fonts: Record<string, string>
}

const CSS_VAR_MAP: Record<string, string> = {
  bgPrimary: '--bg-primary', bgSecondary: '--bg-secondary', bgTertiary: '--bg-tertiary',
  bgHover: '--bg-hover', bgActive: '--bg-active', textPrimary: '--text-primary',
  textSecondary: '--text-secondary', textMuted: '--text-muted', accent: '--accent',
  accentHover: '--accent-hover', success: '--success', warning: '--warning',
  error: '--error', border: '--border', borderLight: '--border-light',
}
const FONT_VAR_MAP: Record<string, string> = { fontSans: '--font-sans', fontMono: '--font-mono' }

const APPS = [
  { key: 'app', label: '工作台 /app' },
  { key: 'chat', label: 'AI CHAT' },
  { key: 'docs', label: '文档 /doc' },
  { key: 'architect', label: 'Architect' },
  { key: 'portal', label: '门户 /' },
]

const customThemes = ref<CustomTheme[]>([])

function loadCustom() {
  try {
    const raw = localStorage.getItem('topoone-custom-themes')
    customThemes.value = raw ? JSON.parse(raw) : []
  } catch {
    customThemes.value = []
  }
}

function readTheme(app: string): 'dark' | 'light' {
  return localStorage.getItem(`topoone-theme-${app}`) === 'light' ? 'light' : 'dark'
}

function toggleTheme(app: string) {
  const next = readTheme(app) === 'dark' ? 'light' : 'dark'
  localStorage.setItem(`topoone-theme-${app}`, next)
  if (app === 'portal') document.documentElement.setAttribute('data-theme', next)
}

function resetCssVars() {
  const root = document.documentElement
  for (const v of Object.values(CSS_VAR_MAP)) root.style.removeProperty(v)
  for (const v of Object.values(FONT_VAR_MAP)) root.style.removeProperty(v)
}

function applyCustom(theme: CustomTheme) {
  const root = document.documentElement
  root.removeAttribute('data-theme')
  resetCssVars()
  for (const [k, cssVar] of Object.entries(CSS_VAR_MAP)) {
    const v = (theme.colors as Record<string, string | undefined>)[k]
    if (v) root.style.setProperty(cssVar, v)
  }
  for (const [k, cssVar] of Object.entries(FONT_VAR_MAP)) {
    const v = (theme.fonts as Record<string, string | undefined>)[k]
    if (v) root.style.setProperty(cssVar, v)
  }
  localStorage.setItem('topoone-theme-app', theme.id)
}

onMounted(loadCustom)
</script>

<template>
  <div class="panel">
    <h3>主题管理</h3>
    <p class="panel-hint">各子模块独立记忆主题（topoone-theme-{app}）；自定义主题可应用到 /app。</p>

    <div class="section">
      <h4>按子模块切换明暗</h4>
      <div class="theme-apps">
        <div v-for="a in APPS" :key="a.key" class="theme-app-row">
          <span>{{ a.label }}</span>
          <button class="btn btn-ghost btn-xs" @click="toggleTheme(a.key)">
            {{ readTheme(a.key) === 'dark' ? '暗色 → 亮色' : '亮色 → 暗色' }}
          </button>
        </div>
      </div>
    </div>

    <div class="section">
      <h4>自定义主题（应用到 /app）</h4>
      <div v-if="customThemes.length === 0" class="muted">暂无自定义主题（在 /app 设置中创建）。</div>
      <div v-for="t in customThemes" :key="t.id" class="theme-app-row">
        <span>{{ t.name }}</span>
        <button class="btn btn-ghost btn-xs" @click="applyCustom(t)">应用</button>
      </div>
    </div>
  </div>
</template>
