<script setup lang="ts">
const VERSION = '0.1.0'
</script>

<template>
  <div class="panel">
    <h3>关于</h3>
    <div class="about-body">
      <div class="about-logo">◆</div>
      <h4>TopoCode</h4>
      <p class="muted">源码架构分析 · 知识库管理 · AI 驱动的智能开发工作台</p>
      <p>版本 v{{ VERSION }}</p>
      <p class="muted">
        各子模块：工作台 /app · 文档 /doc · AI CHAT /chat · Architect /architect · 门户 /
      </p>
    </div>
  </div>
</template>
