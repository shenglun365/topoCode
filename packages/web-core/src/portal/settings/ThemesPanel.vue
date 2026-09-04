<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

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
  { key: 'app', labelKey: 'settings.appNames.workbench' },
  { key: 'chat', labelKey: 'settings.appNames.chat' },
  { key: 'docs', labelKey: 'settings.appNames.docs' },
  { key: 'architect', labelKey: 'settings.appNames.architect' },
  { key: 'portal', labelKey: 'settings.appNames.portal' },
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
    <h3>{{ t('settings.tabs.theme') }}</h3>
    <p class="panel-hint">{{ t('settings.themes.hint', { app: 'app' }) }}</p>

    <div class="section">
      <h4>{{ t('settings.themes.toggleSection') }}</h4>
      <div class="theme-apps">
        <div v-for="a in APPS" :key="a.key" class="theme-app-row">
          <span>{{ t(a.labelKey) }}</span>
          <button class="btn btn-ghost btn-xs" @click="toggleTheme(a.key)">
            {{ readTheme(a.key) === 'dark' ? t('settings.themes.toLight') : t('settings.themes.toDark') }}
          </button>
        </div>
      </div>
    </div>

    <div class="section">
      <h4>{{ t('settings.themes.customSection') }}</h4>
      <div v-if="customThemes.length === 0" class="muted">{{ t('settings.themes.customEmpty') }}</div>
      <div v-for="theme in customThemes" :key="theme.id" class="theme-app-row">
        <span>{{ theme.name }}</span>
        <button class="btn btn-ghost btn-xs" @click="applyCustom(theme)">{{ t('common.apply') }}</button>
      </div>
    </div>
  </div>
</template>
