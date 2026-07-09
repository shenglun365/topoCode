<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth-store'
import { authService } from '@/services/auth-service'
import QRCode from 'qrcode'

const { t } = useI18n()
const router = useRouter()
const auth = useAuthStore()

const qrDataUrl = ref('')
const showQr = ref(false)
const toast = ref('')

const refreshing = ref(false)
const editingUsername = ref(false)
const editUsername = ref('')

const binding = ref<'email' | 'phone' | null>(null)
const bindStep = ref<'verify' | 'new'>('verify')
const bindVerifyTarget = ref<'email' | 'phone'>('email')
const bindAccount = ref('')
const bindCode = ref('')
const bindVerifyCode = ref('')
const bindSending = ref(false)
const bindSent = ref(false)
const bindCountdown = ref(0)
const bindVerifySending = ref(false)
const bindVerifySent = ref(false)
const bindVerifyCountdown = ref(0)
const bindLoading = ref(false)
const bindVerifying = ref(false)
let bindTimer: ReturnType<typeof setInterval> | null = null
let bindVerifyTimer: ReturnType<typeof setInterval> | null = null

const isRebind = computed(() =>
  binding.value === 'email' ? !!auth.user?.email : !!auth.user?.phone,
)

const currentEmail = computed(() => auth.user?.email || '')
const currentPhone = computed(() => auth.user?.phone || '')

async function refreshProfile() {
  refreshing.value = true
  try {
    await auth.fetchProfile()
    await auth.loadReferralInfo()
    await auth.loadReferralStats()
    const link = auth.shareLink || `https://topocode.cn/register?ref=${auth.referralCode}`
    if (link) {
      qrDataUrl.value = await QRCode.toDataURL(link, { width: 160, margin: 1 })
    }
  } finally {
    refreshing.value = false
  }
}

onMounted(async () => {
  if (auth.isAuthenticated) {
    await auth.loadReferralInfo()
    await auth.loadReferralStats()
    const link = auth.shareLink || `https://topocode.cn/register?ref=${auth.referralCode}`
    if (link) {
      qrDataUrl.value = await QRCode.toDataURL(link, { width: 160, margin: 1 })
    }
  }
})

function startCountdown(
  ref: { value: number },
  sent: { value: boolean },
  timerRef: { value: ReturnType<typeof setInterval> | null },
) {
  ref.value = 60
  sent.value = true
  if (timerRef.value) clearInterval(timerRef.value)
  timerRef.value = setInterval(() => {
    ref.value--
    if (ref.value <= 0) {
      if (timerRef.value) clearInterval(timerRef.value)
      sent.value = false
    }
  }, 1000)
}

async function sendVerifyCode() {
  const target = bindVerifyTarget.value === 'email' ? currentEmail.value : currentPhone.value
  if (!target) return
  bindVerifySending.value = true
  try {
    await authService.sendChangeCode(target)
    startCountdown(bindVerifyCountdown, bindVerifySent, { value: bindVerifyTimer })
  } catch (e: any) {
    toast.value = e.message || '发送失败'
    setTimeout(() => { toast.value = '' }, 2000)
  } finally {
    bindVerifySending.value = false
  }
}

async function verifyIdentity() {
  if (!bindVerifyCode.value) return
  bindVerifying.value = true
  try {
    await authService.verifyChangeCode(bindVerifyCode.value)
    toast.value = '身份验证成功'
    bindStep.value = 'new'
  } catch (e: any) {
    toast.value = e.message || '验证失败'
  } finally {
    bindVerifying.value = false
    setTimeout(() => { toast.value = '' }, 2000)
  }
}

async function sendNewCode() {
  if (!bindAccount.value) return
  bindSending.value = true
  try {
    await authService.sendCode(bindAccount.value)
    startCountdown(bindCountdown, bindSent, { value: bindTimer })
  } catch (e: any) {
    toast.value = e.message || '发送失败'
    setTimeout(() => { toast.value = '' }, 2000)
  } finally {
    bindSending.value = false
  }
}

async function confirmBind() {
  if (!bindAccount.value || !bindCode.value) return
  bindLoading.value = true
  try {
    if (binding.value === 'email') {
      await authService.bindEmail(bindAccount.value, bindCode.value)
    } else {
      await authService.bindPhone(bindAccount.value, bindCode.value)
    }
    toast.value = '绑定成功'
    resetBind()
    await auth.fetchProfile()
  } catch (e: any) {
    toast.value = e.message || '绑定失败'
  } finally {
    bindLoading.value = false
    setTimeout(() => { toast.value = '' }, 2000)
  }
}

function startBind(type: 'email' | 'phone') {
  binding.value = type
  bindStep.value = isRebind.value ? 'verify' : 'new'
  bindVerifyTarget.value = currentEmail.value ? 'email' : 'phone'
  bindAccount.value = ''
  bindCode.value = ''
  bindVerifyCode.value = ''
  bindSent.value = false
  bindVerifySent.value = false
  clearTimers()
}

function resetBind() {
  binding.value = null
  bindAccount.value = ''
  bindCode.value = ''
  bindVerifyCode.value = ''
  bindSent.value = false
  bindVerifySent.value = false
  clearTimers()
}

function clearTimers() {
  if (bindTimer) clearInterval(bindTimer)
  if (bindVerifyTimer) clearInterval(bindVerifyTimer)
}

function startEditUsername() {
  editUsername.value = auth.user?.username || ''
  editingUsername.value = true
}

async function saveUsername() {
  const name = editUsername.value.trim()
  if (!name || name.length < 2 || name.length > 20) {
    toast.value = '用户名长度需 2-20 个字符'
    setTimeout(() => { toast.value = '' }, 2000)
    return
  }
  try {
    await authService.updateProfile({ username: name })
    await auth.fetchProfile()
    editingUsername.value = false
    toast.value = '用户名已更新'
  } catch (e: any) {
    toast.value = e.message || '修改失败'
  }
  setTimeout(() => { toast.value = '' }, 2000)
}

function cancelEditUsername() {
  editingUsername.value = false
  editUsername.value = ''
}

async function copyLink() {
  const link = auth.shareLink || `https://topocode.cn/register?ref=${auth.referralCode}`
  try {
    await navigator.clipboard.writeText(link)
    toast.value = t('auth.copied', '已复制分享链接')
  } catch {
    toast.value = t('auth.copyFailed', '复制失败')
  }
  setTimeout(() => { toast.value = '' }, 2000)
}

function shareWeibo() {
  const link = encodeURIComponent(auth.shareLink || `https://topocode.cn/register?ref=${auth.referralCode}`)
  const title = encodeURIComponent('推荐 TopoCode - 源码架构分析工具')
  window.open(`https://service.weibo.com/share/share.php?url=${link}&title=${title}`, '_blank')
}

function shareWechat() {
  showQr.value = true
}

function shareXiaohongshu() {
  const link = auth.shareLink || `https://topocode.cn/register?ref=${auth.referralCode}`
  navigator.clipboard.writeText(link)
  toast.value = t('auth.copiedXhs', '已复制，请打开小红书粘贴分享')
  setTimeout(() => { toast.value = '' }, 2000)
}

function avatarColor(name: string): string {
  const colors = [
    '#6366f1', '#8b5cf6', '#ec4899', '#f43f5e', '#f97316',
    '#eab308', '#22c55e', '#14b8a6', '#06b6d4', '#3b82f6',
  ]
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  return colors[Math.abs(hash) % colors.length]
}

function avatarInitials(name: string): string {
  const parts = name.trim().split(/[\s_-]+/).filter(Boolean)
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase()
  }
  const clean = name.replace(/[^a-zA-Z0-9\u4e00-\u9fa5]/g, '')
  return clean.slice(0, 2).toUpperCase() || '?'
}

function handleLogout() {
  auth.logout()
  router.push('/')
}

function formatDate(dateStr: string): string {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const h = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${y}-${m}-${day} ${h}:${min}`
}
</script>

<template>
  <div class="profile-tab" v-if="auth.isAuthenticated">
    <div style="display:flex; justify-content:flex-end; margin-bottom:8px;">
      <button class="btn btn-ghost btn-icon btn-xs" @click="refreshProfile" :disabled="refreshing" title="刷新">
        <svg class="icon-refresh" :class="{ spinning: refreshing }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>
      </button>
    </div>
    <div class="avatar-section">
      <div class="avatar-placeholder" :style="{ background: avatarColor(auth.user?.username || '') }">
        {{ avatarInitials(auth.user?.username || '') }}
      </div>
    </div>
    <div class="info-list">
      <div class="info-row">
        <span class="info-label">{{ t('auth.username', '用户名') }}</span>
        <span class="info-value" v-if="!editingUsername">
          {{ auth.user?.username }}
          <button class="btn-link" @click="startEditUsername">修改</button>
        </span>
        <div v-else class="username-edit">
          <input v-model="editUsername" class="input" placeholder="用户名" maxlength="20" @keyup.enter="saveUsername" @keyup.escape="cancelEditUsername">
          <button class="btn btn-sm btn-primary" @click="saveUsername" :disabled="!editUsername.trim()">保存</button>
          <button class="btn btn-sm btn-ghost" @click="cancelEditUsername">取消</button>
        </div>
      </div>
      <div class="info-row">
        <span class="info-label">{{ t('auth.email', '邮箱') }}</span>
        <span class="info-value" v-if="auth.user?.email">
          {{ auth.user.email }}
          <span class="badge badge-bound">已绑定</span>
          <button class="btn-link" @click="startBind('email')">换绑</button>
        </span>
        <span class="info-value" v-else>
          <span class="text-unbound">未绑定</span>
          <button class="btn-link" @click="startBind('email')">绑定</button>
        </span>
        <div v-if="binding === 'email'" class="bind-form">
          <template v-if="isRebind && bindStep === 'verify'">
            <div class="verify-hint">验证身份 — 选择接收验证码的方式：</div>
            <div class="verify-options">
              <label v-if="currentEmail" class="verify-option" :class="{ active: bindVerifyTarget === 'email' }">
                <input type="radio" v-model="bindVerifyTarget" value="email"> {{ currentEmail }}
              </label>
              <label v-if="currentPhone" class="verify-option" :class="{ active: bindVerifyTarget === 'phone' }">
                <input type="radio" v-model="bindVerifyTarget" value="phone"> {{ currentPhone }}
              </label>
            </div>
            <div class="code-row" style="margin-top:6px;">
              <input v-model="bindVerifyCode" class="input bind-input" placeholder="身份验证码" maxlength="6">
              <button class="btn btn-sm btn-ghost code-btn" :disabled="bindVerifySending || bindVerifySent" @click="sendVerifyCode">
                {{ bindVerifySending ? '...' : bindVerifySent ? `${bindVerifyCountdown}s` : '发送验证码' }}
              </button>
            </div>
            <div class="code-row" style="margin-top:6px;">
              <button class="btn btn-sm btn-primary code-btn" :disabled="!bindVerifyCode || bindVerifying" @click="verifyIdentity">
                {{ bindVerifying ? '验证中...' : '验证身份' }}
              </button>
              <button class="btn btn-sm btn-ghost code-btn" @click="resetBind">取消</button>
            </div>
          </template>
          <template v-else-if="bindStep === 'new'">
            <div class="code-row">
              <input v-model="bindAccount" class="input bind-input" placeholder="新邮箱" type="email">
              <button class="btn btn-sm btn-ghost code-btn" :disabled="bindSending || bindSent" @click="sendNewCode">
                {{ bindSending ? '...' : bindSent ? `${bindCountdown}s` : '发送验证码' }}
              </button>
            </div>
            <div class="code-row" style="margin-top:6px;">
              <input v-model="bindCode" class="input bind-input" placeholder="验证码" maxlength="6">
            </div>
            <div class="code-row" style="margin-top:8px;">
              <button class="btn btn-sm btn-primary code-btn" :disabled="bindLoading || !bindAccount || !bindCode" @click="confirmBind">
                {{ bindLoading ? '...' : '确认绑定' }}
              </button>
              <button class="btn btn-sm btn-ghost code-btn" @click="resetBind">取消</button>
            </div>
          </template>
        </div>
      </div>
      <div class="info-row">
        <span class="info-label">{{ t('auth.phone', '手机号') }}</span>
        <span class="info-value" v-if="auth.user?.phone">
          {{ auth.user.phone }}
          <span class="badge badge-bound">已绑定</span>
          <button class="btn-link" @click="startBind('phone')">换绑</button>
        </span>
        <span class="info-value" v-else>
          <span class="text-unbound">未绑定</span>
          <button class="btn-link" @click="startBind('phone')">绑定</button>
        </span>
        <div v-if="binding === 'phone'" class="bind-form">
          <template v-if="isRebind && bindStep === 'verify'">
            <div class="verify-hint">验证身份 — 选择接收验证码的方式：</div>
            <div class="verify-options">
              <label v-if="currentEmail" class="verify-option" :class="{ active: bindVerifyTarget === 'email' }">
                <input type="radio" v-model="bindVerifyTarget" value="email"> {{ currentEmail }}
              </label>
              <label v-if="currentPhone" class="verify-option" :class="{ active: bindVerifyTarget === 'phone' }">
                <input type="radio" v-model="bindVerifyTarget" value="phone"> {{ currentPhone }}
              </label>
            </div>
            <div class="code-row" style="margin-top:6px;">
              <input v-model="bindVerifyCode" class="input bind-input" placeholder="身份验证码" maxlength="6">
              <button class="btn btn-sm btn-ghost code-btn" :disabled="bindVerifySending || bindVerifySent" @click="sendVerifyCode">
                {{ bindVerifySending ? '...' : bindVerifySent ? `${bindVerifyCountdown}s` : '发送验证码' }}
              </button>
            </div>
            <div class="code-row" style="margin-top:6px;">
              <button class="btn btn-sm btn-primary code-btn" :disabled="!bindVerifyCode || bindVerifying" @click="verifyIdentity">
                {{ bindVerifying ? '验证中...' : '验证身份' }}
              </button>
              <button class="btn btn-sm btn-ghost code-btn" @click="resetBind">取消</button>
            </div>
          </template>
          <template v-else-if="bindStep === 'new'">
            <div class="code-row">
              <input v-model="bindAccount" class="input bind-input" placeholder="新手机号">
              <button class="btn btn-sm btn-ghost code-btn" :disabled="bindSending || bindSent" @click="sendNewCode">
                {{ bindSending ? '...' : bindSent ? `${bindCountdown}s` : '发送验证码' }}
              </button>
            </div>
            <div class="code-row" style="margin-top:6px;">
              <input v-model="bindCode" class="input bind-input" placeholder="验证码" maxlength="6">
            </div>
            <div class="code-row" style="margin-top:8px;">
              <button class="btn btn-sm btn-primary code-btn" :disabled="bindLoading || !bindAccount || !bindCode" @click="confirmBind">
                {{ bindLoading ? '...' : '确认绑定' }}
              </button>
              <button class="btn btn-sm btn-ghost code-btn" @click="resetBind">取消</button>
            </div>
          </template>
        </div>
      </div>
      <div class="info-row">
        <span class="info-label">{{ t('auth.password', '密码') }}</span>
        <span class="info-value" v-if="auth.user?.has_password">
          ********
          <router-link to="/reset-password" class="btn-link">修改密码</router-link>
        </span>
        <span class="info-value" v-else>
          <span class="text-unbound">未设置（仅验证码登录）</span>
          <router-link to="/reset-password?set=1" class="btn-link">设置密码</router-link>
        </span>
      </div>
      <div class="info-row">
        <span class="info-label">{{ t('auth.registerTime', '注册时间') }}</span>
        <span class="info-value">{{ formatDate(auth.user?.created_at || '') }}</span>
      </div>
      <div class="info-row">
        <span class="info-label">{{ t('auth.points', '积分') }}</span>
        <span class="info-value points">{{ auth.points }}</span>
      </div>
    </div>

    <div class="referral-section">
      <div class="section-title">{{ t('auth.referralTitle', '邀请好友') }}</div>
      <div class="referral-code">
        <span class="code-label">{{ t('auth.referralCode', '邀请码') }}</span>
        <span class="code-value">{{ auth.referralCode }}</span>
      </div>
      <div class="qr-area" v-if="qrDataUrl">
        <img :src="qrDataUrl" class="qr-img" @click="showQr = true">
        <span class="qr-hint">{{ t('auth.qrHint', '扫码打开分享链接') }}</span>
      </div>
      <div class="share-buttons">
        <button class="share-btn" @click="copyLink" title="复制链接">
          <svg class="share-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
          </svg>
          <span>{{ t('auth.copyLink', '复制链接') }}</span>
        </button>
        <button class="share-btn" @click="shareWeibo" title="分享到微博">
          <svg class="share-icon" viewBox="0 0 50.5 40.65" fill="currentColor">
            <path d="M50.448 12.132c.217 2.814-.259 6.186-2.117 6.351-3.033.271-1.451-3.07-1.411-5.081.111-5.829-4.865-9.879-9.739-9.879-1.381 0-4.588.936-4.094-1.976.222-1.284 1.31-1.266 2.399-1.411 8.197-1.093 14.386 4.546 14.962 11.996z"/>
            <path d="M37.04 18.907c3.524 1.928 7.758 2.888 7.056 8.61-.168 1.371-.998 3.203-1.834 4.373-5.957 8.339-23.924 11.844-35.144 5.506C3.355 35.269-.539 32.159.062 25.962c.517-5.333 4.103-9.464 7.622-12.983 3.357-3.359 6.897-5.987 11.714-7.198 5.226-1.314 6.771 3.043 5.363 7.339 3.027-.203 9.442-3.582 12.279-.282 1.25 1.454.771 4.058 0 6.069zm-3.811 13.548c1.129-1.28 2.264-3.231 2.257-5.503-.015-7.014-8.851-9.605-15.806-9.033-3.804.312-6.363 1.115-9.033 2.682-2.179 1.279-4.729 3.36-5.363 6.491-1.427 7.041 6.231 10.35 11.855 10.726 6.498.437 13.002-1.857 16.09-5.363z"/>
            <path d="M43.531 12.132c.296 2.149-.319 4.011-1.552 4.093-2.056.137-1.287-1.408-1.412-3.246-.078-1.132-1.016-2.439-1.835-2.823-1.606-.752-4.093.548-4.093-1.693 0-1.664 1.443-1.491 2.259-1.553 3.574-.272 6.216 2.191 6.633 5.222z"/>
            <path d="M27.019 26.246c3.007 9.088-12.66 13.314-15.525 5.504-1.917-5.223 2.686-9.377 7.48-9.879 4.093-.429 7.144 1.658 8.045 4.375zm-7.198 1.553c.638 1.104 2.105.311 1.976-.564-.154-1.013-1.989-.863-1.976.564zm-2.541 4.799c2.634-.627 2.988-5.588-.988-4.658-3.34.78-2.694 5.533.988 4.658z"/>
          </svg>
          <span>{{ t('auth.weibo', '微博') }}</span>
        </button>
        <button class="share-btn" @click="shareWechat" title="分享到微信">
          <svg class="share-icon" viewBox="0 0 2500 2025" fill="currentColor">
            <path d="m2499.7 1313.8c0-347.3-335.9-630.6-749.5-630.6s-747.2 283.3-747.2 630.6 335.9 630.6 749.5 630.6c80 0 155.4-9.1 226.2-29.7 20.6-4.6 43.4-2.3 64 6.9l185.1 100.5c11.4 6.9 27.4-4.6 22.8-18.3l-36.6-148.5c-4.6-22.8 2.3-45.7 22.8-59.4 160.1-116.5 262.9-287.9 262.9-482.1zm-1016.8-82.2c-57.1 0-102.8-45.7-102.8-102.8s45.7-102.8 102.8-102.8 102.8 45.7 102.8 102.8-45.7 102.8-102.8 102.8zm505 0c-57.1 0-102.8-45.7-102.8-102.8s45.7-102.8 102.8-102.8 102.8 45.7 102.8 102.8-48 102.8-102.8 102.8z"/>
            <path d="m941.4 1316.1c0-386.1 365.6-699.2 818-699.2h34.3c-73.2-349.6-443.3-616.9-888.9-616.9-500.4 0-904.8 333.6-904.8 747.2 0 228.5 125.7 434.1 322.2 571.2 13.7 9.1 18.3 25.1 16 41.1l-68.5 242.2c-4.6 16 13.7 32 29.7 22.8l267.3-159.9c18.3-11.4 38.8-13.7 59.4-6.9 89.1 22.8 182.8 36.6 278.8 36.6 20.6 0 41.1 0 64-2.3-18.4-57.1-27.5-116.5-27.5-175.9z"/>
          </svg>
          <span>{{ t('auth.wechat', '微信') }}</span>
        </button>

      </div>
      <div class="referral-stats">
        <div class="stat-item">
          <span class="stat-value">{{ auth.referralStats.total_referred }}</span>
          <span class="stat-label">{{ t('auth.referredCount', '邀请人数') }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-value">+{{ auth.referralStats.total_earned }}</span>
          <span class="stat-label">{{ t('auth.rewardPoints', '奖励积分') }}</span>
        </div>
      </div>
    </div>

    <div class="actions">
      <button class="btn btn-ghost btn-sm" @click="handleLogout">{{ t('auth.logout', '退出登录') }}</button>
    </div>

    <Teleport to="body">
      <div v-if="showQr" class="qr-overlay" @click.self="showQr = false">
        <div class="qr-modal">
          <img :src="qrDataUrl" class="qr-big">
          <p>{{ t('auth.qrScanWechat', '请用微信扫码分享') }}</p>
          <button class="btn btn-sm btn-ghost" @click="showQr = false">{{ t('common.close', '关闭') }}</button>
        </div>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="toast" class="toast">{{ toast }}</div>
    </Teleport>
  </div>
  <div class="profile-tab unauthenticated" v-else>
    <p class="login-hint">{{ t('auth.loginHint', '登录后可查看个人资料和下载资源') }}</p>
    <div class="actions">
      <router-link to="/login" class="btn btn-primary btn-sm">{{ t('auth.login', '登录') }}</router-link>
      <router-link to="/register" class="btn btn-ghost btn-sm">{{ t('auth.register', '注册') }}</router-link>
    </div>
  </div>
</template>

<style scoped>
.profile-tab {
  max-width: 480px;
}
.avatar-section {
  display: flex;
  justify-content: center;
  margin-bottom: 24px;
}
.avatar-placeholder {
  width: 72px; height: 72px; border-radius: 50%;
  background: var(--accent); color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-size: 28px; font-weight: 600;
}
.info-list {
  display: flex; flex-direction: column; gap: 12px;
}
.info-row {
  display: flex; justify-content: space-between;
  padding: 8px 0; border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.info-label { font-size: 12px; color: var(--text-muted); }
.info-value {
  font-size: 13px; color: var(--text-primary); font-weight: 500;
  display: flex; align-items: center; gap: 6px;
}
.info-value.points { color: var(--accent); font-weight: 700; }
.text-unbound { color: var(--text-muted); font-size: 12px; }
.btn-link {
  font-size: 11px; color: var(--accent); text-decoration: none;
  background: none; border: none; cursor: pointer; padding: 0;
  white-space: nowrap;
}
.btn-link:hover { text-decoration: underline; }
.badge-bound {
  font-size: 10px; padding: 1px 6px; border-radius: 3px;
  background: rgba(34,197,94,0.12); color: #22c55e; font-weight: 500;
}
.username-edit {
  display: flex; gap: 6px; align-items: center; width: 100%;
}
.username-edit .input {
  flex: 1; min-width: 0;
}
.username-edit .btn {
  flex-shrink: 0;
}
.bind-form {
  width: 100%; margin-top: 6px;
}
.bind-input {
  flex: 1; min-width: 0;
}
.verify-hint {
  font-size: 11px; color: var(--text-muted); margin: 6px 0 4px;
}
.verify-options {
  display: flex; gap: 8px; margin-bottom: 6px; flex-wrap: wrap;
}
.verify-option {
  display: flex; align-items: center; gap: 4px;
  font-size: 12px; padding: 4px 8px; border: 1px solid var(--border);
  border-radius: 4px; cursor: pointer; color: var(--text-primary);
}
.verify-option.active {
  border-color: var(--accent); color: var(--accent);
}
.verify-option input { display: none; }
.code-btn {
  white-space: nowrap; flex-shrink: 0; font-size: 11px;
}
.code-row {
  display: flex; gap: 6px; align-items: center;
}
.input {
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

.referral-section {
  margin-top: 24px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-secondary);
}
.section-title {
  font-size: 14px; font-weight: 600; color: var(--text-primary);
  margin-bottom: 12px;
}
.referral-code {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 12px;
}
.code-label { font-size: 12px; color: var(--text-muted); }
.code-value {
  font-size: 18px; font-weight: 700; color: var(--accent);
  letter-spacing: 2px; font-family: monospace;
}
.qr-area {
  display: flex; flex-direction: column; align-items: center;
  margin-bottom: 12px;
}
.qr-img { width: 80px; height: 80px; cursor: pointer; border-radius: 4px; }
.qr-hint { font-size: 10px; color: var(--text-muted); margin-top: 4px; }
.share-buttons {
  display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px;
}
.share-btn {
  display: flex; align-items: center; gap: 4px;
  padding: 5px 10px; border: 1px solid var(--border);
  border-radius: 4px; background: var(--bg-primary);
  color: var(--text-primary); font-size: 11px; cursor: pointer;
  transition: all .15s;
}
.share-btn:hover { border-color: var(--accent); color: var(--accent); }
.share-icon { width: 16px; height: 16px; display: block; }
.referral-stats {
  display: flex; gap: 16px; justify-content: center;
  padding-top: 12px; border-top: 1px solid var(--border);
}
.stat-item { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.stat-value { font-size: 18px; font-weight: 700; color: var(--accent); }
.stat-label { font-size: 10px; color: var(--text-muted); }

.actions { margin-top: 24px; display: flex; gap: 8px; }
.login-hint { font-size: 13px; color: var(--text-muted); margin-bottom: 16px; }
.unauthenticated .actions { justify-content: center; }

.qr-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.6);
  display: flex; align-items: center; justify-content: center; z-index: 10000;
}
.qr-modal {
  text-align: center; background: #fff; padding: 24px;
  border-radius: 12px;
}
.qr-big { width: 200px; height: 200px; margin-bottom: 12px; }
.qr-modal p { font-size: 13px; color: #333; margin-bottom: 12px; }

.toast {
  position: fixed; bottom: 40px; left: 50%; transform: translateX(-50%);
  padding: 8px 20px; background: var(--accent); color: #fff;
  border-radius: 6px; font-size: 12px; z-index: 99999;
  box-shadow: 0 2px 8px rgba(0,0,0,0.2);
}
.icon-refresh { width: 16px; height: 16px; }
.icon-refresh.spinning { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
