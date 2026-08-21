<script setup lang="ts">
import StarLogoMark from '../components/StarLogoMark.vue'

interface ModuleCard {
  key: string
  title: string
  desc: string
  href: string
  icon: string
  accent: string
  chips: string[]
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
    title: '知识库解析和管理',
    desc: '项目导入 · 代码解析 · 任务分析 · 知识库管理，一站式管理你的代码知识资产。',
    href: workbenchHref,
    icon: 'M12 21v-8.25M15.75 21v-8.25M8.25 21v-8.25M3 9l9-6 9 6m-1.5 12V10.332A48.36 48.36 0 0 0 12 9.75c-2.551 0-5.056.2-7.5.582V21M3 21h18M12 6.75h.008v.008H12V6.75Z',
    accent: '#4d6bfe',
    chips: ['项目导入', '代码解析', '任务分析'],
  },
  {
    key: 'projects',
    title: '知识库文档浏览',
    desc: '浏览项目列表、任务文档与社区文档，快速定位知识库内容与文件摘要。',
    href: `${gatewayBase}/projects`,
    icon: 'M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25',
    accent: '#10b981',
    chips: ['项目列表', '任务文档', '社区文档'],
  },
  {
    key: 'chat',
    title: 'AI CHAT',
    desc: '与 AI 助手对话，查询代码、生成文档、执行分析，智能赋能研发全流程。',
    href: `${gatewayBase}/chat`,
    icon: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2zM8 9h8M8 13h5',
    accent: '#f59e0b',
    chips: ['智能问答', '文档生成', 'Agent 执行'],
  },
  {
    key: 'architect',
    title: 'Architect 工作台',
    desc: '需求驱动 · 架构驱动 Coding Agent：语义资产提取、需求分析与智能编码协作。',
    href: `${gatewayBase}/architect`,
    icon: 'M9 17.25v1.007a3 3 0 0 1-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0 1 15 18.257V17.25m6-12V15a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 15V5.25m18 0A2.25 2.25 0 0 0 18.75 3H5.25A2.25 2.25 0 0 0 3 5.25m18 0V12a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 12V5.25',
    accent: '#a855f7',
    chips: ['语义资产', '需求驱动', 'Coding Agent'],
  },
]
</script>

<template>
  <div class="home">
    <header class="hero">
      <div class="hero-inner">
        <StarLogoMark :size="56" />
        <div class="hero-text">
          <h1>TopoCode</h1>
          <p class="hero-sub">源码架构分析 · 知识库管理 · AI 驱动的智能开发工作台</p>
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
          <h2>{{ m.title }}</h2>
          <p class="card-desc">{{ m.desc }}</p>
          <div class="chips">
            <span
              v-for="c in m.chips"
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
      <span>TopoCode · 统一 Web 工作台</span>
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
  padding: 56px 24px 32px;
  display: flex;
  justify-content: center;
}

.hero-inner {
  display: flex;
  align-items: center;
  gap: 16px;
}

.hero-text h1 {
  font-size: 30px;
  font-weight: 700;
  margin: 0;
  letter-spacing: 0.5px;
}

.hero-sub {
  margin: 6px 0 0;
  font-size: 14px;
  color: var(--text-secondary, #6b6b76);
}

.grid {
  flex: 1;
  width: 100%;
  max-width: 1080px;
  margin: 0 auto;
  padding: 8px 24px 40px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(480px, 1fr));
  gap: 20px;
}

.card {
  display: flex;
  align-items: flex-start;
  gap: 18px;
  padding: 24px;
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
  width: 52px;
  height: 52px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.card-body {
  flex: 1;
}

.card-body h2 {
  font-size: 17px;
  font-weight: 600;
  margin: 0 0 6px;
}

.card-desc {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary, #6b6b76);
  margin: 0 0 12px;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chip {
  font-size: 11px;
  padding: 3px 10px;
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
  padding: 20px;
  text-align: center;
  font-size: 12px;
  color: var(--text-muted, #8e8e98);
}

@media (prefers-color-scheme: dark) {
  .home {
    --bg: #212121;
    --bg-card: #2d2d2d;
    --bg-chip: #3d3d3d;
    --text: #e8e8e8;
    --text-secondary: #a0a0a0;
    --text-muted: #6b6b6b;
    --border: #3d3d3d;
  }
  .card:hover {
    box-shadow: 0 12px 28px rgba(0, 0, 0, 0.45);
  }
}

@media (max-width: 720px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>