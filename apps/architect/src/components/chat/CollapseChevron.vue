<script setup lang="ts">
/**
 * 卡片收起/展开 chevron 按钮 —— 信息卡头部统一交互入口。
 * 视觉单源 ChevronSvg(收起=灰▶ / 展开=蓝▼旋转); 点击上抛 toggle。
 * 头部整体是按钮的卡(问询卡/digest/需求卡)改内联 ChevronSvg, 禁按钮嵌套。
 */
import { useI18n } from 'vue-i18n'
import { computed } from 'vue'
import ChevronSvg from './ChevronSvg.vue'

const props = defineProps<{ collapsed: boolean }>()
const emit = defineEmits<{ (e: 'toggle'): void }>()
const { t } = useI18n()

const title = computed(() => props.collapsed ? t('requirement.chat.expandCard') : t('requirement.chat.collapseCard'))
</script>

<template>
  <button
    class="flex items-center shrink-0"
    :title="title"
    @click.stop="emit('toggle')"
  >
    <ChevronSvg :collapsed="props.collapsed" />
  </button>
</template>
