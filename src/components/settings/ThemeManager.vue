<script setup lang="ts">
/** 主题管理器 - 主题列表/切换/导入导出/预览 */

import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useThemeStore } from '@/stores/theme'
import type { CustomTheme, ThemeColors, ThemeFonts } from '@/types'
import ThemeEditor from './ThemeEditor.vue'
import {
  PlusIcon,
  PencilIcon,
  TrashIcon,
  ArrowDownTrayIcon,
  ArrowUpTrayIcon,
  ClipboardDocumentIcon,
  CheckCircleIcon,
  PaintBrushIcon,
} from '@heroicons/vue/24/outline'
import {
  CheckCircleIcon as CheckCircleSolid,
} from '@heroicons/vue/24/solid'
import { useComponentId } from '@/composables/useComponentId'
const { showId, componentId } = useComponentId('ST-005')


const { t } = useI18n()
const themeStore = useThemeStore()

// 状态
const showEditor = ref(false)
const editorMode = ref<'create' | 'edit'>('create')
const editingTheme = ref<CustomTheme | null>(null)
const previewTheme = ref<CustomTheme | null>(null)
const showPreview = ref(false)
const importJson = ref('')
const showImportDialog = ref(false)

// 所有主题
const allThemes = computed(() => themeStore.getAllThemes())

// 内置主题
const builtInThemes = computed(() => allThemes.value.filter(t => t.isBuiltIn))

// 自定义主题
const customThemes = computed(() => allThemes.value.filter(t => !t.isBuiltIn))

// 操作
function handleCreate() {
  editorMode.value = 'create'
  editingTheme.value = null
  showEditor.value = true
}

function handleEdit(theme: CustomTheme) {
  editorMode.value = 'edit'
  editingTheme.value = theme
  showEditor.value = true
}

function handleSave(data: Omit<CustomTheme, 'id' | 'createdAt' | 'updatedAt'>) {
  if (editorMode.value === 'create') {
    const newTheme = themeStore.createTheme(data)
    // 自动切换到新创建的主题
    themeStore.switchTheme(newTheme.id)
  } else if (editingTheme.value) {
    themeStore.updateTheme(editingTheme.value.id, data)
  }
  showEditor.value = false
}

function handleDelete(theme: CustomTheme) {
  if (!confirm(`${t('theme.confirmDeleteTheme')} "${theme.name}"？`)) return
  themeStore.deleteTheme(theme.id)
}

function handleDuplicate(theme: CustomTheme) {
  const newTheme = themeStore.duplicateTheme(theme.id)
  if (newTheme) {
    themeStore.switchTheme(newTheme.id)
  }
}

function handleExport(theme: CustomTheme) {
  const json = themeStore.exportTheme(theme.id)
  if (!json) return

  // 复制到剪贴板
  navigator.clipboard.writeText(json).then(() => {
    alert(t('theme.copiedToClipboard'))
  }).catch(() => {
    // 降级：显示对话框
    prompt(t('theme.copyJsonPrompt'), json)
  })
}

function handleImport() {
  if (!importJson.value.trim()) return
  const result = themeStore.importTheme(importJson.value)
  if (result) {
    showImportDialog.value = false
    importJson.value = ''
    alert(`${t('theme.importSuccess')} "${result.name}"`)
  } else {
    alert(t('theme.importFailed'))
  }
}

function handleSwitch(theme: CustomTheme) {
  themeStore.switchTheme(theme.id)
}

function handlePreview(theme: CustomTheme) {
  previewTheme.value = theme
  showPreview.value = true
}

function handlePreviewApply() {
  if (previewTheme.value) {
    themeStore.switchTheme(previewTheme.value.id)
    showPreview.value = false
  }
}

function handlePreviewCancel() {
  showPreview.value = false
  previewTheme.value = null
}

function handleEditorCancel() {
  showEditor.value = false
}

// 生成主题预览色块
function getThemeSwatches(theme: CustomTheme): string[] {
  return [
    theme.colors.bgPrimary,
    theme.colors.accent,
    theme.colors.success,
    theme.colors.warning,
    theme.colors.error,
  ]
}

onMounted(() => {
  themeStore.init()
})
</script>

<template>
  <div class="theme-manager">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 头部 -->
    <div class="manager-header">
      <div class="header-left">
        <h3 class="manager-title">
          <PaintBrushIcon class="w-5 h-5" />
          <span>{{ t('theme.themeManagement') }}</span>
        </h3>
        <p class="manager-desc">
          {{ t('theme.themeDesc') }}
        </p>
      </div>
      <div class="header-right">
        <button
          class="btn btn-ghost btn-sm"
          :title="t('theme.importTheme')"
          @click="showImportDialog = true"
        >
          <ArrowUpTrayIcon class="w-4 h-4" />
          <span>{{ t('common.import') }}</span>
        </button>
        <button
          class="btn btn-primary btn-sm"
          @click="handleCreate"
        >
          <PlusIcon class="w-4 h-4" />
          <span>{{ t('theme.newTheme') }}</span>
        </button>
      </div>
    </div>

    <!-- 内置主题 -->
    <div class="theme-section">
      <h4 class="section-title">
        {{ t('theme.builtInThemes') }}
      </h4>
      <div class="theme-grid">
        <div
          v-for="theme in builtInThemes"
          :key="theme.id"
          class="theme-card"
          :class="{ active: themeStore.activeThemeId === theme.id }"
          @click="handleSwitch(theme)"
        >
          <!-- 激活指示器 -->
          <div
            v-if="themeStore.activeThemeId === theme.id"
            class="active-indicator"
          >
            <CheckCircleSolid class="w-4 h-4 text-white" />
          </div>

          <!-- 色块预览 -->
          <div class="theme-swatches">
            <span
              v-for="(color, i) in getThemeSwatches(theme)"
              :key="i"
              class="swatch"
              :style="{ background: color }"
            />
          </div>

          <!-- 主题信息 -->
          <div class="theme-info">
            <div class="theme-name">
              {{ theme.name }}
            </div>
            <div class="theme-desc">
              {{ theme.description || t('theme.builtInTheme') }}
            </div>
          </div>

          <!-- 操作按钮 -->
          <div class="theme-actions">
            <button
              class="action-btn"
              :title="t('theme.preview')"
              @click.stop="handlePreview(theme)"
            >
              <PaintBrushIcon class="w-4 h-4" />
            </button>
            <button
              class="action-btn"
              :title="t('common.export')"
              @click.stop="handleExport(theme)"
            >
              <ArrowDownTrayIcon class="w-4 h-4" />
            </button>
            <button
              class="action-btn"
              :title="t('common.duplicate')"
              @click.stop="handleDuplicate(theme)"
            >
              <ClipboardDocumentIcon class="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 自定义主题 -->
    <div class="theme-section">
      <div class="section-header">
        <h4 class="section-title">
          {{ t('theme.customThemes') }} ({{ customThemes.length }})
        </h4>
      </div>

      <div
        v-if="customThemes.length === 0"
        class="empty-state"
      >
        <div class="empty-icon">
          🎨
        </div>
        <div class="empty-text">
          {{ t('theme.noCustomThemes') }}
        </div>
        <div class="empty-hint">
          {{ t('theme.noCustomThemesHint') }}
        </div>
      </div>

      <div
        v-else
        class="theme-grid"
      >
        <div
          v-for="theme in customThemes"
          :key="theme.id"
          class="theme-card"
          :class="{ active: themeStore.activeThemeId === theme.id }"
          @click="handleSwitch(theme)"
        >
          <!-- 激活指示器 -->
          <div
            v-if="themeStore.activeThemeId === theme.id"
            class="active-indicator"
          >
            <CheckCircleSolid class="w-4 h-4 text-white" />
          </div>

          <!-- 色块预览 -->
          <div class="theme-swatches">
            <span
              v-for="(color, i) in getThemeSwatches(theme)"
              :key="i"
              class="swatch"
              :style="{ background: color }"
            />
          </div>

          <!-- 主题信息 -->
          <div class="theme-info">
            <div class="theme-name">
              {{ theme.name }}
            </div>
            <div class="theme-desc">
              {{ theme.description || t('theme.customTheme') }}
            </div>
            <div class="theme-time">
              {{ new Date(theme.updatedAt).toLocaleDateString() }}
            </div>
          </div>

          <!-- 操作按钮 -->
          <div class="theme-actions">
            <button
              class="action-btn"
              :title="t('theme.preview')"
              @click.stop="handlePreview(theme)"
            >
              <PaintBrushIcon class="w-4 h-4" />
            </button>
            <button
              class="action-btn"
              :title="t('common.edit')"
              @click.stop="handleEdit(theme)"
            >
              <PencilIcon class="w-4 h-4" />
            </button>
            <button
              class="action-btn"
              :title="t('common.export')"
              @click.stop="handleExport(theme)"
            >
              <ArrowDownTrayIcon class="w-4 h-4" />
            </button>
            <button
              class="action-btn"
              :title="t('common.duplicate')"
              @click.stop="handleDuplicate(theme)"
            >
              <ClipboardDocumentIcon class="w-4 h-4" />
            </button>
            <button
              class="action-btn danger"
              :title="t('common.delete')"
              @click.stop="handleDelete(theme)"
            >
              <TrashIcon class="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 主题编辑器弹窗 -->
    <div
      v-if="showEditor"
      class="modal-overlay"
      @click="handleEditorCancel"
    >
      <div
        class="modal-content editor-modal"
        @click.stop
      >
        <ThemeEditor
          :theme="editingTheme"
          :mode="editorMode"
          @save="handleSave"
          @cancel="handleEditorCancel"
        />
      </div>
    </div>

    <!-- 预览弹窗 -->
    <div
      v-if="showPreview && previewTheme"
      class="modal-overlay"
      @click="handlePreviewCancel"
    >
      <div
        class="modal-content preview-modal"
        @click.stop
      >
        <div class="preview-header">
          <h3>{{ t('theme.previewTheme') }}: {{ previewTheme.name }}</h3>
          <div class="preview-actions">
            <button
              class="btn btn-secondary btn-sm"
              @click="handlePreviewCancel"
            >
              {{ t('common.cancel') }}
            </button>
            <button
              class="btn btn-primary btn-sm"
              @click="handlePreviewApply"
            >
              <CheckCircleIcon class="w-4 h-4" />
              <span>{{ t('theme.applyThisTheme') }}</span>
            </button>
          </div>
        </div>

        <!-- 预览内容 -->
        <div
          class="preview-content"
          :style="getPreviewStyle(previewTheme)"
        >
          <div class="preview-card">
            <h4>{{ t('theme.themePreview') }}</h4>
            <p>{{ t('theme.previewContent') }}</p>
            <div class="preview-buttons">
              <button class="preview-btn primary">
                {{ t('theme.primaryButton') }}
              </button>
              <button class="preview-btn secondary">
                {{ t('theme.secondaryButton') }}
              </button>
              <button class="preview-btn ghost">
                {{ t('theme.ghostButton') }}
              </button>
            </div>
            <div class="preview-tags">
              <span class="preview-tag success">{{ t('common.success') }}</span>
              <span class="preview-tag warning">{{ t('common.warning') }}</span>
              <span class="preview-tag error">{{ t('common.error') }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 导入对话框 -->
    <div
      v-if="showImportDialog"
      class="modal-overlay"
      @click="showImportDialog = false"
    >
      <div
        class="modal-content import-modal"
        @click.stop
      >
        <div class="import-header">
          <h3>{{ t('theme.importTheme') }}</h3>
          <button
            class="btn btn-ghost btn-sm"
            @click="showImportDialog = false"
          >
            ✕
          </button>
        </div>
        <div class="import-body">
          <p class="import-hint">
            {{ t('theme.pasteThemeJson') }}
          </p>
          <textarea
            v-model="importJson"
            class="import-textarea"
            :placeholder="t('theme.themeJsonPlaceholder')"
            rows="8"
          />
          <div class="import-actions">
            <button
              class="btn btn-secondary"
              @click="showImportDialog = false"
            >
              {{ t('common.cancel') }}
            </button>
            <button
              class="btn btn-primary"
              @click="handleImport"
            >
              <ArrowUpTrayIcon class="w-4 h-4" />
              <span>{{ t('common.import') }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
// 预览样式辅助函数
function getPreviewStyle(theme: CustomTheme): Record<string, string> {
  return {
    '--preview-bg': theme.colors.bgPrimary,
    '--preview-bg-secondary': theme.colors.bgSecondary,
    '--preview-text': theme.colors.textPrimary,
    '--preview-text-muted': theme.colors.textMuted,
    '--preview-accent': theme.colors.accent,
    '--preview-success': theme.colors.success,
    '--preview-warning': theme.colors.warning,
    '--preview-error': theme.colors.error,
    '--preview-border': theme.colors.border,
    '--preview-font-sans': theme.fonts.fontSans,
    '--preview-font-mono': theme.fonts.fontMono,
  }
}

// 暴露给父组件
import { defineExpose } from 'vue'
defineExpose({ getPreviewStyle })
</script>

<style scoped>
.theme-manager {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.manager-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
}

.manager-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.manager-title svg {
  color: var(--accent);
}

.manager-desc {
  font-size: 12px;
  color: var(--text-muted);
  margin: 4px 0 0;
}

.header-right {
  display: flex;
  gap: 8px;
}

.theme-section {
  padding: 16px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 12px;
}

.theme-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.theme-card {
  position: relative;
  background: var(--bg-tertiary);
  border: 2px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.theme-card:hover {
  border-color: var(--accent);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.theme-card.active {
  border-color: var(--accent);
  background: var(--bg-hover);
}

.active-indicator {
  position: absolute;
  top: 8px;
  right: 8px;
  color: var(--accent);
}

.theme-swatches {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
}

.swatch {
  flex: 1;
  height: 32px;
  border-radius: var(--radius-sm);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.theme-info {
  margin-bottom: 8px;
}

.theme-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 2px;
}

.theme-desc {
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 2px;
}

.theme-time {
  font-size: 10px;
  color: var(--text-muted);
}

.theme-actions {
  display: flex;
  gap: 4px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}

.action-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 6px;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}

.action-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.action-btn.danger:hover {
  background: var(--error);
  color: white;
}

.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--text-muted);
}

.empty-icon {
  font-size: 32px;
  margin-bottom: 8px;
}

.empty-text {
  font-size: 14px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.empty-hint {
  font-size: 12px;
}

/* 模态框 */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.modal-content {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.editor-modal {
  width: 700px;
  max-width: 100%;
  max-height: 85vh;
}

.preview-modal {
  width: 500px;
  max-width: 100%;
}

.import-modal {
  width: 500px;
  max-width: 100%;
}

.preview-header, .import-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}

.preview-header h3, .import-header h3 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.preview-actions, .import-actions {
  display: flex;
  gap: 8px;
}

.preview-content {
  padding: 20px;
  background: var(--preview-bg);
  font-family: var(--preview-font-sans);
  min-height: 200px;
}

.preview-card {
  background: var(--preview-bg-secondary);
  border: 1px solid var(--preview-border);
  border-radius: var(--radius-md);
  padding: 16px;
  color: var(--preview-text);
}

.preview-card h4 {
  margin: 0 0 8px;
  font-size: 14px;
}

.preview-card p {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--preview-text-muted);
  line-height: 1.5;
}

.preview-buttons {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.preview-btn {
  padding: 6px 12px;
  font-size: 12px;
  border-radius: var(--radius-sm);
  border: none;
  cursor: pointer;
}

.preview-btn.primary {
  background: var(--preview-accent);
  color: white;
}

.preview-btn.secondary {
  background: var(--preview-border);
  color: var(--preview-text);
}

.preview-btn.ghost {
  background: transparent;
  border: 1px solid var(--preview-border);
  color: var(--preview-text);
}

.preview-tags {
  display: flex;
  gap: 8px;
}

.preview-tag {
  padding: 4px 8px;
  font-size: 11px;
  border-radius: var(--radius-sm);
  color: white;
}

.preview-tag.success { background: var(--preview-success); }
.preview-tag.warning { background: var(--preview-warning); }
.preview-tag.error { background: var(--preview-error); }

.import-body {
  padding: 16px;
}

.import-hint {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 0 0 8px;
}

.import-textarea {
  width: 100%;
  padding: 10px;
  font-size: 12px;
  font-family: var(--font-mono);
  color: var(--text-primary);
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  resize: vertical;
  outline: none;
  margin-bottom: 12px;
}

.import-textarea:focus {
  border-color: var(--accent);
}
</style>
