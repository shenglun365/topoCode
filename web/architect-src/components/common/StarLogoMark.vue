<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import starLogoMarkDark from '../../assets/star-logo-mark-v8.svg'
import starLogoMarkLight from '../../assets/star-logo-mark-v8-light.svg'

const props = defineProps<{
  size?: number
  clickable?: boolean
}>()

const LOGO_THEME_KEY = 'topo_logo_theme'
const savedTheme = localStorage.getItem(LOGO_THEME_KEY)
const isDark = ref(savedTheme ? savedTheme === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches)
const starLogoMark = computed(() => (isDark.value ? starLogoMarkDark : starLogoMarkLight))

function toggleLogoTheme() {
  if (props.clickable === false) return
  isDark.value = !isDark.value
  localStorage.setItem(LOGO_THEME_KEY, isDark.value ? 'dark' : 'light')
  updateFavicon()
}

function updateFavicon() {
  let link = document.querySelector<HTMLLinkElement>("link[rel='icon'][type='image/svg+xml']")
  if (!link) {
    link = document.createElement('link')
    link.rel = 'icon'
    link.type = 'image/svg+xml'
    document.head.appendChild(link)
  }
  link.href = isDark.value ? '/star-logo-mark-v8.svg' : '/star-logo-mark-v8-light.svg'
}

let mq: MediaQueryList
function onThemeChange(e: MediaQueryListEvent) {
  if (!localStorage.getItem(LOGO_THEME_KEY)) isDark.value = e.matches
}

onMounted(() => {
  updateFavicon()
  mq = window.matchMedia('(prefers-color-scheme: dark)')
  mq.addEventListener('change', onThemeChange)
})

onUnmounted(() => {
  mq?.removeEventListener('change', onThemeChange)
})
</script>

<template>
  <img
    :src="starLogoMark"
    alt="TopoCode"
    class="star-logo-mark"
    :class="{ clickable: clickable !== false }"
    :style="{ width: size + 'px', height: size + 'px' }"
    title="点击切换 logo 配色"
    @click="toggleLogoTheme"
  />
</template>

<style scoped>
.star-logo-mark {
  display: block;
  flex-shrink: 0;
  user-select: none;
  -webkit-user-drag: none;
}
.star-logo-mark.clickable {
  cursor: pointer;
}
</style>
