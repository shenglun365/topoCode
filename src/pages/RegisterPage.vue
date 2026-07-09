<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth-store'
import { authService } from '@/services/auth-service'

const { t } = useI18n()
const router = useRouter()
const auth = useAuthStore()

const account = ref('')
const code = ref('')
const loading = ref(false)
const errorMsg = ref('')
const codeSending = ref(false)
const codeSent = ref(false)
const codeCountdown = ref(0)

let countdownTimer: ReturnType<typeof setInterval> | null = null

const isEmail = computed(() => /@/.test(account.value))

function startCountdown() {
  codeCountdown.value = 60
  codeSent.value = true
  if (countdownTimer) clearInterval(countdownTimer)
  countdownTimer = setInterval(() => {
    codeCountdown.value--
    if (codeCountdown.value <= 0) {
      if (countdownTimer) clearInterval(countdownTimer)
      codeSent.value = false
    }
  }, 1000)
}

async function sendCode() {
  if (!account.value) { errorMsg.value = '请填写邮箱或手机号'; return }
  codeSending.value = true
  errorMsg.value = ''
  try {
    await authService.sendCode(account.value)
    startCountdown()
  } catch (e: any) {
    errorMsg.value = e.message || '发送失败'
  } finally {
    codeSending.value = false
  }
}

const canSubmit = computed(() => {
  return !!account.value && !!code.value
})

async function handleRegister() {
  if (!canSubmit.value) return
  loading.value = true
  errorMsg.value = ''
  const username = account.value.split('@')[0] || `user_${Date.now()}`
  const tempPassword = Math.random().toString(36).slice(2, 10)
  const ok = await auth.register(
    username,
    isEmail.value ? account.value : '',
    tempPassword,
    isEmail.value ? code.value : '',
    isEmail.value ? undefined : account.value,
    isEmail.value ? undefined : code.value,
    undefined,
  )
  loading.value = false
  if (ok) {
    router.push('/user')
  } else {
    errorMsg.value = auth.error || '注册失败'
  }
}

function close() {
  router.push('/login')
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <button class="close-btn" @click="close">✕</button>
      <div class="auth-logo">◆</div>
      <h1 class="auth-title">{{ t('auth.register', '创建账号') }}</h1>

      <form @submit.prevent="handleRegister">
        <div class="field">
          <div class="code-row">
            <input v-model="account" class="input flex-1" placeholder="邮箱 / 手机号" autocomplete="username">
            <button type="button" class="btn btn-sm btn-ghost code-btn" :disabled="codeSending || codeSent" @click="sendCode">
              {{ codeSending ? '...' : codeSent ? `${codeCountdown}s` : '发送验证码' }}
            </button>
          </div>
        </div>

        <div class="field">
          <input v-model="code" class="input" placeholder="验证码" maxlength="6" autocomplete="one-time-code">
        </div>

        <div v-if="errorMsg" class="error">{{ errorMsg }}</div>
        <button type="submit" class="btn btn-primary btn-full" :disabled="loading || !canSubmit">
          {{ loading ? '注册中...' : '注册' }}
        </button>
      </form>

      <div class="auth-links">
        <router-link to="/login">已有账号？去登录</router-link>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
}
.auth-card {
  position: relative;
  width: 400px;
  padding: 40px 32px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  text-align: center;
}
.close-btn {
  position: absolute;
  top: 12px;
  right: 16px;
  background: none;
  border: none;
  font-size: 18px;
  color: var(--text-muted);
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  line-height: 1;
}
.close-btn:hover {
  color: var(--text-primary);
  background: var(--bg-primary);
}
.auth-logo {
  font-size: 32px;
  color: var(--accent);
  margin-bottom: 8px;
}
.auth-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 20px;
}
.field {
  margin-bottom: 10px;
}
.input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
  box-sizing: border-box;
}
.input:focus {
  border-color: var(--accent);
}
.flex-1 {
  flex: 1;
}
.code-row {
  display: flex;
  gap: 6px;
  align-items: center;
}
.code-btn {
  white-space: nowrap;
  flex-shrink: 0;
  font-size: 11px;
}
.error {
  color: var(--error);
  font-size: 12px;
  margin-bottom: 12px;
}
.btn-full {
  width: 100%;
  padding: 10px;
  font-size: 14px;
}
.auth-links {
  margin-top: 16px;
  font-size: 12px;
}
.auth-links a {
  color: var(--accent);
  text-decoration: none;
}
</style>
