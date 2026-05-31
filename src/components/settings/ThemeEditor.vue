<script setup lang="ts">
/** 主题编辑器 - 颜色/字体配置 */

import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CustomTheme, ThemeColors, ThemeFonts } from '@/types'
import { useThemeStore } from '@/stores/theme'
import {
  PencilIcon,
  XMarkIcon,
  ArrowPathIcon,
  EyeIcon,
} from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'
const { showId, componentId } = useComponentId('ST-006')


const { t } = useI18n()
const themeStore = useThemeStore()

const props = defineProps<{
  theme?: CustomTheme | null
  mode?: 'create' | 'edit' | 'preview'
}>()

const emit = defineEmits<{
  save: [theme: Omit<CustomTheme, 'id' | 'createdAt' | 'updatedAt'>]
  cancel: []
  preview: [colors: ThemeColors, fonts: ThemeFonts]
}>()

// 表单状态
const name = ref(props.theme?.name || '')
const description = ref(props.theme?.description || '')
const colors = ref<ThemeColors>({ ...getPresetColors() })
const fonts = ref<ThemeFonts>({
  fontSans: "'Segoe UI', 'Microsoft YaHei', 'PingFang SC', system-ui, sans-serif",
  fontMono: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace",
})

// 预览模式
const previewMode = ref(false)

function getPresetColors(): ThemeColors {
  if (props.theme) return { ...props.theme.colors }
  return {
    bgPrimary: '#1e1e2e',
    bgSecondary: '#181825',
    bgTertiary: '#313244',
    bgHover: '#45475a',
    bgActive: '#585b70',
    textPrimary: '#cdd6f4',
    textSecondary: '#a6adc8',
    textMuted: '#6c7086',
    accent: '#89b4fa',
    accentHover: '#74c7ec',
    success: '#a6e3a1',
    warning: '#f9e2af',
    error: '#f38ba8',
    border: '#45475a',
    borderLight: '#585b70',
  }
}

// 颜色分组
const colorGroups = [
  {
    label: () => t('theme.backgroundColors'),
    fields: [
      { key: 'bgPrimary' as const, label: () => t('theme.primaryBackground') },
      { key: 'bgSecondary' as const, label: () => t('theme.secondaryBackground') },
      { key: 'bgTertiary' as const, label: () => t('theme.tertiaryBackground') },
      { key: 'bgHover' as const, label: () => t('theme.hoverBackground') },
      { key: 'bgActive' as const, label: () => t('theme.activeBackground') },
    ],
  },
  {
    label: () => t('theme.textColors'),
    fields: [
      { key: 'textPrimary' as const, label: () => t('theme.primaryText') },
      { key: 'textSecondary' as const, label: () => t('theme.secondaryText') },
      { key: 'textMuted' as const, label: () => t('theme.mutedText') },
    ],
  },
  {
    label: () => t('theme.semanticColors'),
    fields: [
      { key: 'accent' as const, label: () => t('theme.accentColor') },
      { key: 'accentHover' as const, label: () => t('theme.accentHover') },
      { key: 'success' as const, label: () => t('common.success') },
      { key: 'warning' as const, label: () => t('common.warning') },
      { key: 'error' as const, label: () => t('common.error') },
    ],
  },
  {
    label: () => t('theme.borderColor'),
    fields: [
      { key: 'border' as const, label: () => t('theme.border') },
      { key: 'borderLight' as const, label: () => t('theme.lightBorder') },
    ],
  },
]

// 实时预览
watch([colors, fonts], () => {
  if (previewMode.value) {
    emit('preview', colors.value, fonts.value)
  }
}, { deep: true })

function handleSave() {
  if (!name.value.trim()) {
    alert(t('theme.enterThemeName'))
    return
  }
  emit('save', {
    name: name.value.trim(),
    description: description.value.trim(),
    colors: { ...colors.value },
    fonts: { ...fonts.value },
  })
}

function handleReset() {
  colors.value = getPresetColors()
  fonts.value = {
    fontSans: "'Segoe UI', 'Microsoft YaHei', 'PingFang SC', system-ui, sans-serif",
    fontMono: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace",
  }
}

function handleCancel() {
  emit('cancel')
}

// 预设主题
const presets = [
  { name: 'Catppuccin Mocha', colors: BUILTIN_DARK_COLORS },
  { name: 'Catppuccin Latte', colors: BUILTIN_LIGHT_COLORS },
  { name: 'Nord', colors: NORD_COLORS },
  { name: 'Gruvbox Dark', colors: GRUVBOX_COLORS },
]

const BUILTIN_DARK_COLORS: ThemeColors = {
  bgPrimary: '#1e1e2e', bgSecondary: '#181825', bgTertiary: '#313244',
  bgHover: '#45475a', bgActive: '#585b70',
  textPrimary: '#cdd6f4', textSecondary: '#a6adc8', textMuted: '#6c7086',
  accent: '#89b4fa', accentHover: '#74c7ec',
  success: '#a6e3a1', warning: '#f9e2af', error: '#f38ba8',
  border: '#45475a', borderLight: '#585b70',
}

const BUILTIN_LIGHT_COLORS: ThemeColors = {
  bgPrimary: '#eff1f5', bgSecondary: '#e6e9ef', bgTertiary: '#ccd0da',
  bgHover: '#bcc0cc', bgActive: '#acb0be',
  textPrimary: '#4c4f69', textSecondary: '#5c5f77', textMuted: '#8c8fa1',
  accent: '#1e66f5', accentHover: '#2a6ef5',
  success: '#40a02b', warning: '#df8e1d', error: '#d20f39',
  border: '#acb0be', borderLight: '#9ca0b0',
}

const NORD_COLORS: ThemeColors = {
  bgPrimary: '#2e3440', bgSecondary: '#3b4252', bgTertiary: '#434c5e',
  bgHover: '#4c566a', bgActive: '#d8dee9',
  textPrimary: '#eceff4', textSecondary: '#e5e9f0', textMuted: '#4c566a',
  accent: '#88c0d0', accentHover: '#8fbcbb',
  success: '#a3be8c', warning: '#ebcb8b', error: '#bf616a',
  border: '#4c566a', borderLight: '#434c5e',
}

const GRUVBOX_COLORS: ThemeColors = {
  bgPrimary: '#282828', bgSecondary: '#1d2021', bgTertiary: '#3c3836',
  bgHover: '#504945', bgActive: '#665c54',
  textPrimary: '#ebdbb2', textSecondary: '#d5c4a1', textMuted: '#7c6f64',
  accent: '#83a598', accentHover: '#8ec07c',
  success: '#b8bb26', warning: '#fabd2f', error: '#fb4934',
  border: '#504945', borderLight: '#3c3836',
}

function applyPreset(presetColors: ThemeColors) {
  colors.value = { ...presetColors }
}
</script>

<template>
  <div class="theme-editor">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 头部操作 -->
    <div class="editor-header">
      <div class="header-left">
        <h3 class="editor-title">
          {{ mode === 'create' ? t('theme.createNewTheme') : t('theme.editTheme') }}
        </h3>
      </div>
      <div class="header-right">
        <button
          class="btn btn-ghost btn-sm"
          :title="previewMode ? t('theme.closePreview') : t('theme.livePreview')"
          @click="previewMode = !previewMode"
        >
          <EyeIcon class="w-4 h-4" />
          <span>{{ previewMode ? t('theme.closePreview') : t('theme.preview') }}</span>
        </button>
        <button
          class="btn btn-ghost btn-sm"
          :title="t('common.reset')"
          @click="handleReset"
        >
          <ArrowPathIcon class="w-4 h-4" />
        </button>
        <button
          class="btn btn-ghost btn-sm"
          :title="t('common.cancel')"
          @click="handleCancel"
        >
          <XMarkIcon class="w-4 h-4" />
        </button>
      </div>
    </div>

    <div class="editor-body">
      <!-- 基本信息 -->
      <div class="editor-section">
        <h4 class="section-title">
          {{ t('theme.basicInfo') }}
        </h4>
        <div class="form-grid">
          <div class="form-item">
            <label class="form-label">{{ t('theme.themeName') }}</label>
            <input
              v-model="name"
              class="form-input"
              :placeholder="t('theme.myTheme')"
            >
          </div>
          <div class="form-item">
            <label class="form-label">{{ t('common.description') }}</label>
            <input
              v-model="description"
              class="form-input"
              :placeholder="t('theme.optionalDesc')"
            >
          </div>
        </div>
      </div>

      <!-- 预设主题 -->
      <div class="editor-section">
        <h4 class="section-title">
          {{ t('theme.presetThemes') }}
        </h4>
        <div class="preset-grid">
          <button
            v-for="preset in presets"
            :key="preset.name"
            class="preset-btn"
            @click="applyPreset(preset.colors)"
          >
            <div class="preset-colors">
              <span
                v-for="(color, i) in [preset.colors.bgPrimary, preset.colors.accent, preset.colors.success, preset.colors.error]"
                :key="i"
                class="preset-swatch"
                :style="{ background: color }"
              />
            </div>
            <span class="preset-name">{{ preset.name }}</span>
          </button>
        </div>
      </div>

      <!-- 颜色配置 -->
      <div class="editor-section">
        <h4 class="section-title">
          {{ t('theme.colorConfig') }}
        </h4>
        <div
          v-for="group in colorGroups"
          :key="group.label"
          class="color-group"
        >
          <h5 class="group-label">
            {{ typeof group.label === 'function' ? group.label() : group.label }}
          </h5>
          <div class="color-grid">
            <div
              v-for="field in group.fields"
              :key="field.key"
              class="color-item"
            >
              <label class="color-label">{{ typeof field.label === 'function' ? field.label() : field.label }}</label>
              <div class="color-input-wrap">
                <input
                  type="color"
                  :value="colors[field.key]"
                  class="color-picker"
                  @input="colors[field.key] = ($event.target as HTMLInputElement).value"
                >
                <input
                  v-model="colors[field.key]"
                  class="color-text"
                  :placeholder="colors[field.key]"
                  spellcheck="false"
                >
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 字体配置 -->
      <div class="editor-section">
        <h4 class="section-title">
          {{ t('theme.fontConfig') }}
        </h4>
        <div class="form-grid">
          <div class="form-item">
            <label class="form-label">{{ t('theme.sansFont') }}</label>
            <input
              v-model="fonts.fontSans"
              class="form-input"
              placeholder="'Segoe UI', sans-serif"
            >
          </div>
          <div class="form-item">
            <label class="form-label">{{ t('theme.monoFont') }}</label>
            <input
              v-model="fonts.fontMono"
              class="form-input"
              placeholder="'Fira Code', monospace"
            >
          </div>
        </div>
      </div>

      <!-- 底部操作 -->
      <div class="editor-footer">
        <button
          class="btn btn-secondary"
          @click="handleCancel"
        >
          {{ t('common.cancel') }}
        </button>
        <button
          class="btn btn-primary"
          @click="handleSave"
        >
          <PencilIcon class="w-4 h-4" />
          <span>{{ mode === 'create' ? t('theme.createTheme') : t('theme.saveChanges') }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.theme-editor {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
}

.editor-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.header-right {
  display: flex;
  gap: 4px;
}

.editor-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.editor-section {
  margin-bottom: 24px;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 12px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.form-input {
  padding: 8px 10px;
  font-size: 13px;
  color: var(--text-primary);
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  outline: none;
  transition: border-color 0.15s;
}

.form-input:focus {
  border-color: var(--accent);
}

/* 预设主题 */
.preset-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 8px;
}

.preset-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.15s;
}

.preset-btn:hover {
  border-color: var(--accent);
  background: var(--bg-hover);
}

.preset-colors {
  display: flex;
  gap: 4px;
}

.preset-swatch {
  width: 20px;
  height: 20px;
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.preset-name {
  font-size: 11px;
  color: var(--text-secondary);
}

/* 颜色配置 */
.color-group {
  margin-bottom: 16px;
}

.group-label {
  font-size: 11px;
  color: var(--text-muted);
  margin: 0 0 8px;
}

.color-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 8px;
}

.color-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.color-label {
  font-size: 11px;
  color: var(--text-secondary);
}

.color-input-wrap {
  display: flex;
  gap: 4px;
  align-items: center;
}

.color-picker {
  width: 32px;
  height: 32px;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  background: transparent;
}

.color-text {
  flex: 1;
  padding: 6px 8px;
  font-size: 12px;
  font-family: var(--font-mono);
  color: var(--text-primary);
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  outline: none;
}

.color-text:focus {
  border-color: var(--accent);
}

/* 底部 */
.editor-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border);
  background: var(--bg-secondary);
}
</style>
