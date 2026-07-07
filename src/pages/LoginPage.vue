<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth-store'
import { authService } from '@/services/auth-service'

const { t } = useI18n()
const router = useRouter()
const auth = useAuthStore()

const loginMode = ref<'password' | 'code'>('password')
const email = ref('')
const phone = ref('')
const password = ref('')
const code = ref('')
const loading = ref(false)
const errorMsg = ref('')
const codeSending = ref(false)
const codeSent = ref(false)
const codeCountdown = ref(0)
let countdownTimer: ReturnType<typeof setInterval> | null = null

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
  if (codeSending.value || codeSent.value) return
  codeSending.value = true
  errorMsg.value = ''
  try {
    if (email.value) {
      await authService.sendEmailCode(email.value)
    } else if (phone.value) {
      await authService.sendSmsCode(phone.value)
    } else {
      errorMsg.value = '请填写邮箱或手机号'
      codeSending.value = false
      return
    }
    startCountdown()
  } catch (e: any) {
    errorMsg.value = e.message || '发送失败'
  } finally {
    codeSending.value = false
  }
}

function toggleMode() {
  loginMode.value = loginMode.value === 'password' ? 'code' : 'password'
  errorMsg.value = ''
  code.value = ''
  codeSent.value = false
  if (countdownTimer) clearInterval(countdownTimer)
}

async function handleLogin() {
  errorMsg.value = ''

  if (loginMode.value === 'password') {
    if (!email.value || !password.value) {
      errorMsg.value = '请填写邮箱和密码'
      return
    }
    loading.value = true
    const ok = await auth.login(email.value, password.value)
    loading.value = false
    if (ok) {
      router.push('/')
    } else {
      errorMsg.value = auth.error || '邮箱或密码错误'
    }
  } else {
    if (!email.value && !phone.value) {
      errorMsg.value = '请填写邮箱或手机号'
      return
    }
    if (!code.value) {
      errorMsg.value = '请填写验证码'
      return
    }
    loading.value = true
    const ok = await auth.loginWithCode({
      email: email.value || undefined,
      phone: phone.value || undefined,
      code: code.value,
    })
    loading.value = false
    if (ok) {
      router.push('/')
    } else {
      errorMsg.value = auth.error || '验证码错误或已过期'
    }
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="auth-logo">◆</div>
      <h1 class="auth-title">{{ t('auth.login', 'TopoCode 登录') }}</h1>
      <form @submit.prevent="handleLogin">
        <div class="field">
          <input v-model="email" type="email" class="input" :placeholder="t('auth.email', '邮箱')" autocomplete="email">
        </div>
        <div v-if="loginMode === 'code'" class="field">
          <p class="field-hint">{{ t('auth.orUsePhone', '或使用手机号') }}</p>
          <input v-model="phone" class="input" :placeholder="t('auth.phoneHint', '手机号')" autocomplete="tel">
        </div>
        <div v-if="loginMode === 'password'" class="field">
          <input v-model="password" type="password" class="input" :placeholder="t('auth.password', '密码')" autocomplete="current-password">
        </div>
        <div v-if="loginMode === 'code'" class="field">
          <div class="code-row">
            <input v-model="code" class="input flex-1" :placeholder="t('auth.verificationCode', '验证码')" maxlength="6" autocomplete="one-time-code">
            <button type="button" class="btn btn-sm btn-ghost code-btn" :disabled="codeSending || codeSent" @click="sendCode">
              {{ codeSending ? '...' : codeSent ? `${codeCountdown}s` : t('auth.sendCode', '发送验证码') }}
            </button>
          </div>
        </div>
        <div v-if="errorMsg" class="error">{{ errorMsg }}</div>
        <button type="submit" class="btn btn-primary btn-full" :disabled="loading">
          {{ loading ? t('common.loading', '登录中...') : t('auth.loginBtn', '登录') }}
        </button>
      </form>
      <div class="toggle-mode" @click="toggleMode">
        {{ loginMode === 'password' ? t('auth.useCodeLogin', '使用验证码登录') : t('auth.usePasswordLogin', '使用密码登录') }}
      </div>
      <div class="auth-links">
        <router-link to="/register">{{ t('auth.noAccount', '没有账号？立即注册') }}</router-link>
        <span class="sep">|</span>
        <router-link to="/reset-password" class="link-muted">{{ t('auth.forgotPassword', '忘记密码') }}</router-link>
      </div>
      <div class="auth-back">
        <router-link to="/">{{ t('auth.backHome', '← 返回首页') }}</router-link>
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
  width: 400px;
  padding: 40px 32px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  text-align: center;
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
  margin-bottom: 24px;
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
.field-hint {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 6px;
  text-align: left;
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
.toggle-mode {
  margin-top: 10px;
  font-size: 12px;
  color: var(--accent);
  cursor: pointer;
  opacity: 0.8;
}
.toggle-mode:hover {
  opacity: 1;
  text-decoration: underline;
}
.auth-links {
  margin-top: 14px;
  font-size: 12px;
}
.auth-links a {
  color: var(--accent);
  text-decoration: none;
}
.auth-links .sep {
  color: var(--border);
  margin: 0 6px;
}
.auth-links .link-muted {
  color: var(--text-muted);
}
.auth-back {
  margin-top: 12px;
  font-size: 12px;
}
.auth-back a {
  color: var(--text-muted);
  text-decoration: none;
}
</style>
