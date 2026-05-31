<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('ST-008')
const { t } = useI18n()
</script>

<template>
  <div class="about-page">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <h2 style="font-size:16px; font-weight:600; margin-bottom:16px;">
      {{ t('settings.aboutTopoCode') }}
    </h2>

    <div
      class="card"
      style="padding:16px; margin-bottom:12px;"
    >
      <div style="font-size:16px; font-weight:700; margin-bottom:2px;">
        TopoCode
      </div>
      <div
        class="text-muted"
        style="font-size:12px; margin-bottom:8px;"
      >
        {{ t('settings.aboutTagline') }}
      </div>
      <span class="badge badge-blue">v0.1.0 beta</span>
      <div style="margin-top:10px; font-size:12px; color:var(--text-muted);">
        <div>topocode@163.com</div>
        <div><a href="https://github.com/shenglun365/topoCode" target="_blank" style="color:var(--accent);">github.com/shenglun365/topoCode</a></div>
      </div>
    </div>

    <div
      class="card"
      style="padding:14px; margin-bottom:12px;"
    >
      <div style="font-size:13px; font-weight:500; margin-bottom:8px;">
        {{ t('settings.techStack') }}
      </div>
      <div style="display:flex; flex-wrap:wrap; gap:6px;">
        <span class="badge badge-blue">Electron 33</span>
        <span class="badge badge-blue">Vue 3.5</span>
        <span class="badge badge-blue">TypeScript</span>
        <span class="badge badge-blue">Vite 5.4</span>
        <span class="badge badge-blue">Pinia 3</span>
        <span class="badge badge-blue">Tailwind CSS 3.4</span>
        <span class="badge badge-green">D3.js</span>
        <span class="badge badge-green">Mermaid</span>
        <span class="badge" style="background:rgba(139,92,246,0.15);color:#8b5cf6;">Python 3.10+</span>
        <span class="badge" style="background:rgba(139,92,246,0.15);color:#8b5cf6;">FastAPI</span>
        <span class="badge" style="background:rgba(139,92,246,0.15);color:#8b5cf6;">ZeroMQ</span>
        <span class="badge" style="background:rgba(139,92,246,0.15);color:#8b5cf6;">NetworkX</span>
        <span class="badge" style="background:rgba(139,92,246,0.15);color:#8b5cf6;">Tree-sitter</span>
      </div>
    </div>

    <div
      class="card"
      style="padding:14px; margin-bottom:12px;"
    >
      <div style="font-size:13px; font-weight:500; margin-bottom:8px;">
        {{ t('settings.systemInfo') }}
      </div>
      <div style="font-size:12px; color:var(--text-secondary); line-height:1.8;">
        <div>{{ t('settings.os') }}: Linux</div>
        <div>Node.js: v22.17.0</div>
        <div>npm: 11.13.0</div>
        <div>{{ t('settings.pythonEnv') }}: Python 3.10+</div>
      </div>
    </div>

    <div
      class="card"
      style="padding:14px; margin-bottom:12px;"
    >
      <div style="font-size:13px; font-weight:500; margin-bottom:8px;">
        {{ t('settings.license') }}
      </div>
      <div style="font-size:12px; color:var(--text-secondary); line-height:1.7;">
        <div>Apache-2.0 License — {{ t('settings.licenseText') }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.about-page {
  max-width: 600px;
}
</style>
