<!-- SYNC-WITH: packages/web-core/src/shell/AppToolbar.vue（MS3-U1 独立化拷贝——改一方须 diff 另一方） -->
<script setup lang="ts">
import './toolbar.css'
import ThemeToggle from './ThemeToggle.vue'
import StarLogoMark from '@/components/common/StarLogoMark.vue'
import FontSizeSelect from './FontSizeSelect.vue'
import LocaleToggle from './LocaleToggle.vue'
import HelpButton from './HelpButton.vue'
import type { FontSizeTarget } from './prefs'

/**
 * 统一工具栏（P2）—— 各子模块共用外壳。
 * 左：品牌（slot `brand`）· 子模块名/标题（slot `title` 或 prop `title`）·
 *    项目徽标（slot `project`）· 模块专属工具（slot `tools`）
 * 右：主题 · 字号 · 语言 · 帮助。
 * 主题按钮默认用共享 `ThemeToggle`（per-app 独立记忆键）；workbench/architect
 * 用各自 theme store，经 slot `theme` 覆盖。
 */
const props = withDefaults(defineProps<{
  title?: string
  appKey?: string
  fontTargets?: FontSizeTarget[]
  fontSize?: number
  helpHref?: string
}>(), {
  appKey: 'default',
  fontTargets: () => ['--content-font-size'] as FontSizeTarget[],
  fontSize: 16,
  helpHref: '/',
})

const emit = defineEmits<{
  (e: 'update:fontSize', v: number): void
  (e: 'update:locale', l: string): void
}>()

function onFontSize(v: number) {
  emit('update:fontSize', v)
}
function onLocale(l: string) {
  emit('update:locale', l)
}
</script>

<template>
  <header class="app-toolbar">
    <div class="toolbar-left">
      <slot name="brand">
        <StarLogoMark :size="18" />
      </slot>
      <slot name="title">
        <span class="toolbar-title">{{ title }}</span>
      </slot>
      <slot name="project" />
      <slot name="tools" />
    </div>
    <div class="toolbar-right">
      <slot name="theme">
        <ThemeToggle :app-key="appKey" :size="30" />
      </slot>
      <FontSizeSelect :model-value="fontSize" :targets="fontTargets" @update:model-value="onFontSize" />
      <LocaleToggle @update:locale="onLocale" />
      <HelpButton :href="helpHref" />
    </div>
  </header>
</template>

<style>
/* 共享工具栏控件样式（非 scoped，供各 shell 组件复用） */
.app-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: calc(8px * var(--ui-scale, 1));
  height: calc(48px * var(--ui-scale, 1));
  padding: 0 calc(12px * var(--ui-scale, 1));
  background: var(--bg-secondary, #181825);
  border-bottom: 1px solid var(--border, #45475a);
  flex-shrink: 0;
}
.toolbar-left {
  display: flex;
  align-items: center;
  gap: calc(8px * var(--ui-scale, 1));
  min-width: 0;
}
.toolbar-right {
  display: flex;
  align-items: center;
  gap: calc(6px * var(--ui-scale, 1));
  flex-shrink: 0;
}
.toolbar-title {
  font-weight: 600;
  color: var(--text, var(--text-primary));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
