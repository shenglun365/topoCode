<script setup lang="ts">
/**
 * ChangeWatch（批5，需求 5 / 2-F）：代码变更实时感知。
 * 轻量轮询(60s) git-info → dirty/head 边沿检测 → 顶部提示条(不打扰：同一 head
 * 只提示一次，用户忽略后不重复)；「去更新」跳资产工作区触发手动同步(2-G 用户手动)。
 */
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { projectService } from '@/services/project-service'
import { currentProjectParams } from '@/services/project-service'

const router = useRouter()
const CHANGED_KEY = 'arch.changewatch.lastHead'

const show = ref(false)
const dirtyCount = ref(0)
let timer: ReturnType<typeof setInterval> | null = null
let checking = false

async function check(): Promise<void> {
  if (checking) return
  const { root, project } = currentProjectParams()
  if (!root && !project) return
  checking = true
  try {
    const info = await projectService.gitInfo()
    const head = info?.head || ''
    const dirty = !!info?.dirty
    const last = localStorage.getItem(CHANGED_KEY) || ''
    // 边沿：head 变化且工作区脏 → 提示一次；用户点击「知道了」记录当前 head
    if (dirty && head && head !== last) {
      show.value = true
    }
  } catch { /* 探测失败静默 */ } finally {
    checking = false
  }
}

function dismiss(): void {
  show.value = false
  const { root } = currentProjectParams()
  void projectService.gitInfo().then((info) => {
    if (info?.head) {
      // 记录到 per-root 键，避免多项目串扰
      localStorage.setItem(`${CHANGED_KEY}:${root || 'default'}`, info.head)
      localStorage.setItem(CHANGED_KEY, info.head)
    }
  })
}

function goSync(): void {
  dismiss()
  void router.push({ path: '/workbench/asset-mgmt', query: { ...router.currentRoute.value.query } })
}

onMounted(() => {
  timer = setInterval(check, 60_000)
  setTimeout(check, 4_000)   // 挂载后首查延后(避开首屏请求峰)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <transition name="cw-slide">
    <div
      v-if="show"
      class="cw-bar"
      role="status"
    >
      <span class="cw-dot" />
      <span class="cw-text">检测到工作区代码变更——语义资产可能已过期</span>
      <button class="cw-btn cw-primary" @click="goSync">去更新资产</button>
      <button class="cw-btn" @click="dismiss">知道了</button>
    </div>
  </transition>
</template>

<style scoped>
.cw-bar {
  position: fixed;
  top: 18vh;              /* 页面中心中上位置(用户裁决 2026-10-03, 原 top:12px 顶部贴边) */
  left: 50%;
  transform: translateX(-50%);
  z-index: 2100;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 14px;
  border-radius: 8px;
  background: var(--ctp-base, #1e1e2e);
  border: 1px solid var(--ctp-yellow, #f9e2af);
  box-shadow: 0 4px 18px rgb(0 0 0 / 40%);
  font-size: 12px;
  color: var(--ctp-text, #cdd6f4);
}
.cw-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ctp-yellow, #f9e2af);
  animation: cw-pulse 1.6s ease-in-out infinite;
}
@keyframes cw-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}
.cw-text { color: var(--ctp-subtext0, #a6adc8); }
.cw-btn {
  border: none;
  border-radius: 6px;
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
  background: var(--ctp-surface1, #45475a);
  color: var(--ctp-text, #cdd6f4);
}
.cw-primary {
  background: var(--ctp-blue, #89b4fa);
  color: var(--ctp-base, #1e1e2e);
  font-weight: 600;
}
.cw-slide-enter-active, .cw-slide-leave-active { transition: all 0.3s ease; }
.cw-slide-enter-from, .cw-slide-leave-to { opacity: 0; transform: translateX(-50%) translateY(-12px); }
</style>
