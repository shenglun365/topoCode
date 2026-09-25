<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import StarLogoMark from '../components/StarLogoMark.vue'
import ThemeToggle from '../components/ThemeToggle.vue'
import { FontSizeSelect, LocaleToggle, HelpButton, readFontSize, setFontSize } from '../shell'

const { t } = useI18n()

const FONT_TARGETS: ('--content-font-size')[] = ['--content-font-size']
const fontSize = ref(readFontSize())

const settingsOpen = ref(false)
const settingsWrap = ref<HTMLElement | null>(null)
let settingsCloseTimer: number | null = null

function cancelSettingsClose() {
  if (settingsCloseTimer !== null) {
    window.clearTimeout(settingsCloseTimer)
    settingsCloseTimer = null
  }
}
function scheduleSettingsClose() {
  cancelSettingsClose()
  settingsCloseTimer = window.setTimeout(() => {
    settingsOpen.value = false
    settingsCloseTimer = null
  }, 500)
}

function onDocClick(e: MouseEvent) {
  if (settingsWrap.value && !settingsWrap.value.contains(e.target as Node)) {
    cancelSettingsClose()
    settingsOpen.value = false
  }
}
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    cancelSettingsClose()
    settingsOpen.value = false
  }
}
onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  cancelSettingsClose()
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKeydown)
})

function onFontSize(v: number) {
  fontSize.value = v
  setFontSize(v, FONT_TARGETS)
}

interface ModuleCard {
  key: string
  href: string
  icon: string
  accent: string
}

// 环境感知：统一网关在 3456（prod 同源）；dev 下各 SPA 分散在不同端口。
// - 5173 = 主工作台 dev（内嵌首页时工作台链接用 hash #/home）
// - 5174 = docs SPA dev（viewer/web-root/portal）
// - 5175 = chat dev
// - 5176 = architect dev
const host = window.location.hostname
const port = window.location.port
const isDevSrc = port === '5173'
const isDev = ['5173', '5174', '5175', '5176'].includes(port)
const gatewayBase = isDev ? `//${host}:3456` : ''
const workbenchHref = isDevSrc ? '#/home' : `${gatewayBase}/app`

const modules: ModuleCard[] = [
  {
    key: 'kb',
    href: workbenchHref,
    icon: 'M12 21v-8.25M15.75 21v-8.25M8.25 21v-8.25M3 9l9-6 9 6m-1.5 12V10.332A48.36 48.36 0 0 0 12 9.75c-2.551 0-5.056.2-7.5.582V21M3 21h18M12 6.75h.008v.008H12V6.75Z',
    accent: '#4d6bfe',
  },
  {
    key: 'projects',
    href: `${gatewayBase}/projects`,
    icon: 'M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25',
    accent: '#10b981',
  },
  {
    key: 'chat',
    // chat FE 并入 workbench（MS7-W3）：规范直达 /app/chat（gateway /chat 会 301 到这里）
    href: `${gatewayBase}/app/chat`,
    icon: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2zM8 9h8M8 13h5',
    accent: '#f59e0b',
  },
  {
    key: 'architect',
    href: `${gatewayBase}/architect`,
    icon: 'M9 17.25v1.007a3 3 0 0 1-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0 1 15 18.257V17.25m6-12V15a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 15V5.25m18 0A2.25 2.25 0 0 0 18.75 3H5.25A2.25 2.25 0 0 0 3 5.25m18 0V12a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 12V5.25',
    accent: '#a855f7',
  },
]

function modText(key: string, field: 'title' | 'desc'): string {
  return t(`home.modules.${key}.${field}`)
}
function modChips(key: string): string[] {
  return t(`home.modules.${key}.chips`) as unknown as string[]
}
</script>

<template>
  <div class="home">
    <header class="hero">
      <div class="hero-inner">
        <StarLogoMark :size="56" />
        <div class="hero-text">
          <h1>TopoCode</h1>
          <p class="hero-sub">{{ t('home.sub') }}</p>
        </div>
      </div>
      <div class="hero-controls">
        <a
          href="#/user"
          class="icon-btn"
          :title="t('home.userCenter')"
          :aria-label="t('home.userCenter')"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          ><path d="M17.982 18.725A7.488 7.488 0 0 0 12 15.75a7.488 7.488 0 0 0-5.982 2.975m11.963 0a9 9 0 1 0-11.963 0m11.963 0A8.966 8.966 0 0 1 12 21a8.966 8.966 0 0 1-5.982-2.275M15 9.75a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" /></svg>
        </a>
        <div
          ref="settingsWrap"
          class="settings-pop"
          @mouseenter="cancelSettingsClose"
          @mouseleave="scheduleSettingsClose"
        >
          <button
            type="button"
            class="icon-btn"
            :class="{ open: settingsOpen }"
            :title="t('home.settings')"
            :aria-label="t('home.settings')"
            :aria-expanded="settingsOpen"
            @click.stop="settingsOpen = !settingsOpen"
            @mouseenter="settingsOpen = true"
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.5"
              stroke-linecap="round"
              stroke-linejoin="round"
            ><path d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" /><path d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" /></svg>
          </button>
          <div v-if="settingsOpen" class="settings-panel">
            <div class="controls-row">
              <ThemeToggle app-key="portal" :size="30" />
              <FontSizeSelect :model-value="fontSize" :targets="FONT_TARGETS" @update:model-value="onFontSize" />
              <LocaleToggle />
              <HelpButton />
            </div>
            <a
              href="#/settings"
              class="all-settings"
              @click.stop="settingsOpen = false"
            >{{ t('home.allSettings') }} →</a>
          </div>
        </div>
      </div>
    </header>

    <main class="grid">
      <a
        v-for="m in modules"
        :key="m.key"
        class="card"
        :href="m.href"
        target="_blank"
        rel="noopener"
      >
        <div class="card-icon" :style="{ background: m.accent + '1a', color: m.accent }">
          <svg
            width="26"
            height="26"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path :d="m.icon" />
          </svg>
        </div>
        <div class="card-body">
          <h2>{{ modText(m.key, 'title') }}</h2>
          <p class="card-desc">{{ modText(m.key, 'desc') }}</p>
          <div class="chips">
            <span
              v-for="c in modChips(m.key)"
              :key="c"
              class="chip"
            >{{ c }}</span>
          </div>
        </div>
        <div class="card-arrow" :style="{ color: m.accent }">
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </div>
      </a>
    </main>

    <footer class="foot">
      <span>{{ t('home.footer') }}</span>
    </footer>
  </div>
</template>

<style scoped>
.home {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg, #f7f7f8);
  color: var(--text, #1a1a1a);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.hero {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: calc(24px * var(--ui-scale));
  padding: calc(40px * var(--ui-scale)) calc(24px * var(--ui-scale));
  width: 100%;
  max-width: 1080px;
  margin: 0 auto;
}

.hero-controls {
  display: flex;
  align-items: center;
  gap: calc(8px * var(--ui-scale));
}

.icon-btn {
  width: calc(30px * var(--ui-scale));
  height: calc(30px * var(--ui-scale));
  border-radius: var(--radius-sm, 4px);
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border, #e4e4e7);
  background: var(--bg-card, #ffffff);
  color: var(--text-secondary, #6b6b76);
  cursor: pointer;
  text-decoration: none;
  transition: border-color 0.18s ease, color 0.18s ease;
}
.icon-btn:hover,
.icon-btn.open {
  border-color: var(--accent, #4d6bfe);
  color: var(--accent, #4d6bfe);
}
.icon-btn svg {
  width: calc(16px * var(--ui-scale));
  height: calc(16px * var(--ui-scale));
  flex-shrink: 0;
}

.settings-pop {
  position: relative;
}

.settings-panel {
  position: absolute;
  top: calc(100% + 10px * var(--ui-scale));
  right: 0;
  display: flex;
  flex-direction: column;
  gap: calc(8px * var(--ui-scale));
  padding: calc(12px * var(--ui-scale));
  background: var(--bg-card, #ffffff);
  border: 1px solid var(--border, #e4e4e7);
  border-radius: 14px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.12);
  z-index: 50;
  animation: settings-pop-in 0.14s ease;
}
.settings-panel::before {
  content: '';
  position: absolute;
  top: calc(-10px * var(--ui-scale));
  left: 0;
  right: 0;
  height: calc(10px * var(--ui-scale));
}
.settings-panel .controls-row {
  display: flex;
  align-items: center;
  gap: calc(8px * var(--ui-scale));
}
.all-settings {
  align-self: flex-start;
  padding-top: calc(8px * var(--ui-scale));
  border-top: 1px solid var(--border, #e4e4e7);
  margin-top: calc(2px * var(--ui-scale));
  width: 100%;
  box-sizing: border-box;
  font-size: calc(13px * var(--ui-scale));
  color: var(--text-secondary, #6b6b76);
  text-decoration: none;
}
.all-settings:hover {
  color: var(--accent, #4d6bfe);
}
@keyframes settings-pop-in {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.hero-inner {
  display: flex;
  align-items: center;
  gap: calc(16px * var(--ui-scale));
}

.hero-text h1 {
  font-size: calc(30px * var(--ui-scale));
  font-weight: 700;
  margin: 0;
  letter-spacing: 0.5px;
}

.hero-sub {
  margin: calc(6px * var(--ui-scale)) 0 0;
  font-size: calc(14px * var(--ui-scale));
  color: var(--text-secondary, #6b6b76);
}

.grid {
  flex: 1;
  width: 100%;
  max-width: 1080px;
  margin: 0 auto;
  padding: calc(8px * var(--ui-scale)) calc(24px * var(--ui-scale)) calc(40px * var(--ui-scale));
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(480px, 1fr));
  gap: calc(20px * var(--ui-scale));
}

.card {
  display: flex;
  align-items: flex-start;
  gap: calc(18px * var(--ui-scale));
  padding: calc(24px * var(--ui-scale));
  background: var(--bg-card, #ffffff);
  border: 1px solid var(--border, #e4e4e7);
  border-radius: 16px;
  text-decoration: none;
  color: inherit;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
  position: relative;
}

.card:hover {
  transform: translateY(-3px);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.08);
  border-color: var(--accent, #4d6bfe);
}

.card-icon {
  flex-shrink: 0;
  width: calc(52px * var(--ui-scale));
  height: calc(52px * var(--ui-scale));
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.card-icon svg {
  width: calc(26px * var(--ui-scale));
  height: calc(26px * var(--ui-scale));
}

.card-body {
  flex: 1;
}

.card-body h2 {
  font-size: calc(17px * var(--ui-scale));
  font-weight: 600;
  margin: 0 0 calc(6px * var(--ui-scale));
}

.card-desc {
  font-size: calc(13px * var(--ui-scale));
  line-height: 1.6;
  color: var(--text-secondary, #6b6b76);
  margin: 0 0 calc(12px * var(--ui-scale));
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: calc(6px * var(--ui-scale));
}

.chip {
  font-size: calc(11px * var(--ui-scale));
  padding: calc(3px * var(--ui-scale)) calc(10px * var(--ui-scale));
  border-radius: 999px;
  background: var(--bg-chip, #f0f0f2);
  color: var(--text-secondary, #6b6b76);
}

.card-arrow {
  flex-shrink: 0;
  margin-top: 16px;
  opacity: 0.5;
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.card-arrow svg {
  width: calc(18px * var(--ui-scale));
  height: calc(18px * var(--ui-scale));
}

.card:hover .card-arrow {
  opacity: 1;
  transform: translateX(3px);
}

.foot {
  padding: calc(20px * var(--ui-scale));
  text-align: center;
  font-size: calc(12px * var(--ui-scale));
  color: var(--text-muted, #8e8e98);
}

@media (max-width: 720px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>