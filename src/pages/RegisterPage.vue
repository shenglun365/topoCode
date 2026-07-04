<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth-store'
import { authService } from '@/services/auth-service'

const { t } = useI18n()
const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const email = ref('')
const phone = ref('')
const emailCode = ref('')
const smsCode = ref('')
const password = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const errorMsg = ref('')
const usePhone = ref(false)
const referralCode = ref('')

const emailCodeSending = ref(false)
const emailCodeSent = ref(false)
const emailCodeCountdown = ref(0)
const smsCodeSending = ref(false)
const smsCodeSent = ref(false)
const smsCodeCountdown = ref(0)

let countdownTimer: ReturnType<typeof setInterval> | null = null

function startCountdown(which: 'email' | 'sms') {
  const countdown = which === 'email' ? emailCodeCountdown : smsCodeCountdown
  const sent = which === 'email' ? emailCodeSent : smsCodeSent
  countdown.value = 60
  sent.value = true
  if (countdownTimer) clearInterval(countdownTimer)
  countdownTimer = setInterval(() => {
    countdown.value--
    if (countdown.value <= 0) {
      if (countdownTimer) clearInterval(countdownTimer)
      sent.value = false
    }
  }, 1000)
}

async function sendEmailCode() {
  if (!email.value) { errorMsg.value = '请先填写邮箱'; return }
  emailCodeSending.value = true
  errorMsg.value = ''
  try {
    await authService.sendEmailCode(email.value)
    startCountdown('email')
  } catch (e: any) {
    errorMsg.value = e.message || '发送失败'
  } finally {
    emailCodeSending.value = false
  }
}

async function sendSmsCode() {
  if (!phone.value) { errorMsg.value = '请先填写手机号'; return }
  smsCodeSending.value = true
  errorMsg.value = ''
  try {
    await authService.sendSmsCode(phone.value)
    startCountdown('sms')
  } catch (e: any) {
    errorMsg.value = e.message || '发送失败'
  } finally {
    smsCodeSending.value = false
  }
}

const canSubmit = computed(() => {
  if (!username.value || !password.value || password.value !== confirmPassword.value) return false
  if (!email.value || !emailCode.value) return false
  if (usePhone.value && (!phone.value || !smsCode.value)) return false
  return true
})

onMounted(() => {
  const params = new URLSearchParams(window.location.hash.split('?')[1] || window.location.search)
  const ref = params.get('ref')
  if (ref) referralCode.value = ref.toUpperCase()
})

async function handleRegister() {
  if (!canSubmit.value) return
  loading.value = true
  errorMsg.value = ''
  const ok = await auth.register(
    username.value, email.value, password.value, emailCode.value,
    usePhone.value ? phone.value : undefined,
    usePhone.value ? smsCode.value : undefined,
    referralCode.value || undefined,
  )
  loading.value = false
  if (ok) {
    router.push('/login')
  } else {
    errorMsg.value = auth.error || '注册失败'
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="auth-logo">◆</div>
      <h1 class="auth-title">{{ t('auth.register', '创建 TopoCode 账号') }}</h1>
      <form @submit.prevent="handleRegister">
        <div class="field">
          <input v-model="username" class="input" :placeholder="t('auth.username', '用户名')" autocomplete="username">
        </div>
        <div class="field">
          <input v-model="referralCode" class="input" :placeholder="t('auth.referralCode', '邀请码（可选）')" maxlength="8" style="text-transform:uppercase;">
        </div>
        <div class="field">
          <div class="code-row">
            <input v-model="email" type="email" class="input flex-1" :placeholder="t('auth.email', '邮箱')" autocomplete="email">
            <button type="button" class="btn btn-sm btn-ghost code-btn" :disabled="emailCodeSending || emailCodeSent" @click="sendEmailCode">
              {{ emailCodeSending ? '...' : emailCodeSent ? `${emailCodeCountdown}s` : t('auth.sendCode', '发送验证码') }}
            </button>
          </div>
        </div>
        <div class="field">
          <input v-model="emailCode" class="input" :placeholder="t('auth.emailCode', '邮箱验证码')" maxlength="6">
        </div>

        <div class="or-divider">
          <span>{{ t('auth.or', '或') }}</span>
        </div>

        <div class="field">
          <div class="code-row">
            <input v-model="phone" class="input flex-1" :placeholder="t('auth.phoneHint', '手机号（仅支持中国大陆）')" autocomplete="tel">
            <button type="button" class="btn btn-sm btn-ghost code-btn" :disabled="smsCodeSending || smsCodeSent" @click="sendSmsCode">
              {{ smsCodeSending ? '...' : smsCodeSent ? `${smsCodeCountdown}s` : t('auth.sendCode', '发送验证码') }}
            </button>
          </div>
        </div>
        <div class="field">
          <input v-model="smsCode" class="input" :placeholder="t('auth.smsCode', '手机验证码')" maxlength="6">
        </div>

        <div class="field">
          <input v-model="password" type="password" class="input" :placeholder="t('auth.password', '密码')" autocomplete="new-password">
        </div>
        <div class="field">
          <input v-model="confirmPassword" type="password" class="input" :placeholder="t('auth.confirmPassword', '确认密码')" autocomplete="new-password">
        </div>
        <div v-if="errorMsg" class="error">{{ errorMsg }}</div>
        <button type="submit" class="btn btn-primary btn-full" :disabled="loading || !canSubmit">
          {{ loading ? t('common.loading', '注册中...') : t('auth.registerBtn', '注册') }}
        </button>
      </form>
      <div class="auth-links">
        <router-link to="/login">{{ t('auth.hasAccount', '已有账号？去登录') }}</router-link>
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
.or-divider {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 8px 0;
  color: var(--text-muted);
  font-size: 11px;
}
.or-divider::before,
.or-divider::after {
  content: '';
  flex: 1;
  border-top: 1px solid var(--border);
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