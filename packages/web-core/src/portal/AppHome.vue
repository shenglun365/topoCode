<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import StarLogoMark from '../components/StarLogoMark.vue'
import ThemeToggle from '../components/ThemeToggle.vue'
import { FontSizeSelect, LocaleToggle, HelpButton, readFontSize, setFontSize } from '../shell'

const { t } = useI18n()

const FONT_TARGETS: ('--content-font-size')[] = ['--content-font-size']
const fontSize = ref(readFontSize())

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
    href: `${gatewayBase}/chat`,
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
        <ThemeToggle app-key="portal" :size="30" />
        <FontSizeSelect :model-value="fontSize" :targets="FONT_TARGETS" @update:model-value="onFontSize" />
        <LocaleToggle />
        <HelpButton />
        <a
          href="#/settings"
          class="toolbar-btn"
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          ><line x1="4" y1="21" x2="4" y2="14" /><line x1="4" y1="10" x2="4" y2="3" /><line x1="12" y1="21" x2="12" y2="12" /><line x1="12" y1="8" x2="12" y2="3" /><line x1="20" y1="21" x2="20" y2="16" /><line x1="20" y1="12" x2="20" y2="3" /><line x1="1" y1="14" x2="7" y2="14" /><line x1="9" y1="8" x2="15" y2="8" /><line x1="17" y1="16" x2="23" y2="16" /></svg>
          {{ t('home.settings') }}
        </a>
        <a
          href="#/user"
          class="toolbar-btn"
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          ><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
          {{ t('home.userCenter') }}
        </a>
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
  justify-content: center;
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
  flex-wrap: wrap;
  justify-content: flex-end;
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