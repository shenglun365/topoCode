<template>
  <div class="star-logo-wrapper">
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 660 155"
      class="star-logo-svg"
    >
      <defs>
        <linearGradient
          id="bgGrad"
          x1="0%"
          y1="0%"
          x2="100%"
          y2="100%"
        >
          <stop
            offset="0%"
            stop-color="#0A0E1A"
          />
          <stop
            offset="100%"
            stop-color="#141C2B"
          />
        </linearGradient>
        <linearGradient
          id="textGrad"
          x1="0%"
          y1="0%"
          x2="100%"
          y2="0%"
        >
          <stop
            offset="0%"
            stop-color="#00D4FF"
          />
          <stop
            offset="100%"
            stop-color="#7B61FF"
          />
        </linearGradient>
        <filter
          id="glowS"
          x="-50%"
          y="-50%"
          width="200%"
          height="200%"
        >
          <feGaussianBlur stdDeviation="2.2" />
          <feMerge><feMergeNode /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
        <filter
          id="glowB"
          x="-80%"
          y="-80%"
          width="260%"
          height="260%"
        >
          <feGaussianBlur stdDeviation="5.5" />
          <feMerge><feMergeNode /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
        <pattern
          id="dots"
          width="12"
          height="12"
          patternUnits="userSpaceOnUse"
        >
          <circle
            cx="6"
            cy="6"
            r="0.35"
            fill="#4FACFE"
            opacity="0.05"
          />
        </pattern>
      </defs>

      <rect
        width="660"
        height="155"
        rx="14"
        fill="url(#bgGrad)"
      />
      <rect
        width="660"
        height="155"
        fill="url(#dots)"
      />

      <text
        x="16"
        y="22"
        font-family="Inter,Segoe UI,sans-serif"
        font-weight="500"
        font-size="12"
        fill="#5D6A85"
        letter-spacing="0.5"
      >v{{ version }}</text>

      <g class="particles">
        <circle
          v-for="p in particles"
          :key="p.id"
          :cx="p.x"
          :cy="p.y"
          :r="p.r"
          fill="#4FACFE"
          :opacity="p.op"
        >
          <animate
            attributeName="opacity"
            :values="`${p.op};${p.op*0.2};${p.op}`"
            :dur="`${p.dur}s`"
            :begin="`${p.delay}s`"
            repeatCount="indefinite"
          />
        </circle>
      </g>

      <g class="polaris-group">
        <circle
          cx="120"
          cy="60"
          r="16"
          fill="none"
          stroke="#7B61FF"
          stroke-width="2.5"
          opacity="0.18"
        >
          <animate
            attributeName="r"
            values="14;22;14"
            dur="3s"
            repeatCount="indefinite"
          />
          <animate
            attributeName="opacity"
            values="0.18;0.06;0.18"
            dur="3s"
            repeatCount="indefinite"
          />
        </circle>
        <circle
          cx="120"
          cy="60"
          r="10"
          fill="none"
          stroke="#7B61FF"
          stroke-width="4"
          opacity="0.1"
        >
          <animate
            attributeName="r"
            values="8;15;8"
            dur="2.6s"
            repeatCount="indefinite"
          />
        </circle>
        <circle
          cx="120"
          cy="60"
          r="5.5"
          fill="#7B61FF"
          filter="url(#glowB)"
        />
        <circle
          cx="120"
          cy="60"
          r="2.6"
          fill="#FFFFFF"
        />
      </g>

      <g
        ref="dipperGroup"
        class="dipper-group"
        :transform="`rotate(${angle}, 120, 60)`"
      >
        <line
          x1="120"
          y1="104"
          x2="120"
          y2="60"
          stroke="#7B61FF"
          stroke-width="0.9"
          opacity="0.3"
          stroke-dasharray="5,7"
        />
        <line
          x1="120"
          y1="88"
          x2="120"
          y2="104"
          stroke="#4FACFE"
          stroke-width="1.3"
          opacity="0.45"
        />
        <line
          x1="120"
          y1="104"
          x2="136"
          y2="110"
          stroke="#4FACFE"
          stroke-width="1.3"
          opacity="0.45"
        />
        <line
          x1="136"
          y1="110"
          x2="133"
          y2="89"
          stroke="#4FACFE"
          stroke-width="1.3"
          opacity="0.45"
        />
        <line
          x1="133"
          y1="89"
          x2="120"
          y2="88"
          stroke="#4FACFE"
          stroke-width="1.3"
          opacity="0.45"
        />
        <line
          x1="133"
          y1="89"
          x2="144"
          y2="86"
          stroke="#4FACFE"
          stroke-width="1.3"
          opacity="0.45"
        />
        <line
          x1="144"
          y1="86"
          x2="158"
          y2="76"
          stroke="#4FACFE"
          stroke-width="1.3"
          opacity="0.45"
        />
        <line
          x1="158"
          y1="76"
          x2="172"
          y2="64"
          stroke="#4FACFE"
          stroke-width="1.3"
          opacity="0.45"
        />

        <g><circle
          cx="120"
          cy="88"
          r="8"
          fill="none"
          stroke="#00D4FF"
          stroke-width="1.4"
          opacity="0.18"
        ><animate
          attributeName="r"
          values="7;12;7"
          dur="2.4s"
          repeatCount="indefinite"
        /></circle><circle
          cx="120"
          cy="88"
          r="3.8"
          fill="#00D4FF"
          filter="url(#glowS)"
        /><circle
          cx="120"
          cy="88"
          r="1.7"
          fill="#FFF"
        /></g>
        <g><circle
          cx="120"
          cy="104"
          r="8"
          fill="none"
          stroke="#00D4FF"
          stroke-width="1.4"
          opacity="0.18"
        ><animate
          attributeName="r"
          values="7;12;7"
          dur="2.8s"
          repeatCount="indefinite"
        /></circle><circle
          cx="120"
          cy="104"
          r="3.6"
          fill="#00D4FF"
          filter="url(#glowS)"
        /><circle
          cx="120"
          cy="104"
          r="1.6"
          fill="#FFF"
        /></g>
        <g><circle
          cx="136"
          cy="110"
          r="7"
          fill="none"
          stroke="#00D4FF"
          stroke-width="1.3"
          opacity="0.16"
        ><animate
          attributeName="r"
          values="6;11;6"
          dur="2.6s"
          repeatCount="indefinite"
        /></circle><circle
          cx="136"
          cy="110"
          r="3.2"
          fill="#00D4FF"
          filter="url(#glowS)"
        /><circle
          cx="136"
          cy="110"
          r="1.4"
          fill="#FFF"
        /></g>
        <g><circle
          cx="133"
          cy="89"
          r="6"
          fill="none"
          stroke="#00D4FF"
          stroke-width="1.1"
          opacity="0.13"
        ><animate
          attributeName="r"
          values="5;9;5"
          dur="3s"
          repeatCount="indefinite"
        /></circle><circle
          cx="133"
          cy="89"
          r="2.6"
          fill="#4FACFE"
        /><circle
          cx="133"
          cy="89"
          r="1.1"
          fill="#E8E8F0"
        /></g>
        <g><circle
          cx="144"
          cy="86"
          r="7.5"
          fill="none"
          stroke="#00D4FF"
          stroke-width="1.4"
          opacity="0.17"
        ><animate
          attributeName="r"
          values="6.5;11;6.5"
          dur="2.5s"
          repeatCount="indefinite"
        /></circle><circle
          cx="144"
          cy="86"
          r="3.5"
          fill="#00D4FF"
          filter="url(#glowS)"
        /><circle
          cx="144"
          cy="86"
          r="1.5"
          fill="#FFF"
        /></g>
        <g><circle
          cx="158"
          cy="76"
          r="8"
          fill="none"
          stroke="#00D4FF"
          stroke-width="1.4"
          opacity="0.18"
        ><animate
          attributeName="r"
          values="7;12;7"
          dur="2.7s"
          repeatCount="indefinite"
        /></circle><circle
          cx="158"
          cy="76"
          r="3.7"
          fill="#00D4FF"
          filter="url(#glowS)"
        /><circle
          cx="158"
          cy="76"
          r="1.6"
          fill="#FFF"
        /></g>
        <g><circle
          cx="172"
          cy="64"
          r="7"
          fill="none"
          stroke="#00D4FF"
          stroke-width="1.3"
          opacity="0.16"
        ><animate
          attributeName="r"
          values="6;10;6"
          dur="2.9s"
          repeatCount="indefinite"
        /></circle><circle
          cx="172"
          cy="64"
          r="3.1"
          fill="#00D4FF"
          filter="url(#glowS)"
        /><circle
          cx="172"
          cy="64"
          r="1.3"
          fill="#FFF"
        /></g>
      </g>

      <g
        :transform="`translate(${textX}, 48)`"
        text-anchor="middle"
      >
        <text
          x="0"
          y="30"
          font-family="Inter,Segoe UI,PingFang SC,sans-serif"
          font-weight="700"
          font-size="36"
          fill="url(#textGrad)"
          letter-spacing="1.2"
        >TopoCode</text>
        <text
          x="0"
          y="60"
          font-family="Inter,PingFang SC,sans-serif"
          font-weight="400"
          font-size="16"
          fill="#8892B0"
          letter-spacing="0.5"
        >{{ subtitle || t('settings.aboutSubtitle') }}</text>
      </g>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'

const { t, locale } = useI18n()

const textX = computed(() => locale.value.startsWith('zh') ? 350 : 380)

const POLARIS_X = 120
const POLARIS_Y = 60

defineProps<{
  subtitle?: string
  version?: string
}>()

const angle = ref(0)
const dipperGroup = ref<SVGGElement | null>(null)

let animationId: number | null = null
let lastTime: number | null = null

const particles = Array.from({ length: 36 }, (_, i) => ({
  id: i,
  x: Math.random() * 660,
  y: Math.random() * 155,
  r: Math.random() * 1 + 0.3,
  op: Math.random() * 0.3 + 0.05,
  dur: Math.random() * 4 + 3,
  delay: Math.random() * 5,
}))

onMounted(() => {
  const loop = (time: number) => {
    if (lastTime === null) lastTime = time
    const delta = (time - lastTime) / 1000
    lastTime = time
    angle.value = (angle.value + 6 * delta) % 360
    animationId = requestAnimationFrame(loop)
  }
  animationId = requestAnimationFrame(loop)
})

onUnmounted(() => {
  if (animationId !== null) cancelAnimationFrame(animationId)
})
</script>

<style scoped>
.star-logo-wrapper {
  width: 100%;
  margin: 0 auto;
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), filter 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.star-logo-wrapper:hover {
  transform: translateY(-1px);
  filter: drop-shadow(0 8px 24px rgba(0, 180, 220, 0.12));
}
.star-logo-svg {
  display: block;
  width: 100%;
  height: auto;
  border-radius: 10px;
}
</style>
