<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth-store'
import QRCode from 'qrcode'

const { t } = useI18n()
const router = useRouter()
const auth = useAuthStore()

const qrDataUrl = ref('')
const showQr = ref(false)
const toast = ref('')

onMounted(async () => {
  if (auth.isAuthenticated) {
    await auth.loadReferralInfo()
    await auth.loadReferralStats()
    if (auth.shareLink) {
      qrDataUrl.value = await QRCode.toDataURL(auth.shareLink, { width: 160, margin: 1 })
    }
  }
})

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
</script>

<template>
  <div class="profile-tab" v-if="auth.isAuthenticated">
    <div class="avatar-section">
      <div class="avatar-placeholder" :style="{ background: avatarColor(auth.user?.username || '') }">
        {{ avatarInitials(auth.user?.username || '') }}
      </div>
    </div>
    <div class="info-list">
      <div class="info-row">
        <span class="info-label">{{ t('auth.username', '用户名') }}</span>
        <span class="info-value">{{ auth.user?.username }}</span>
      </div>
      <div class="info-row">
        <span class="info-label">{{ t('auth.email', '邮箱') }}</span>
        <span class="info-value">{{ auth.user?.email }}</span>
      </div>
      <div class="info-row">
        <span class="info-label">{{ t('auth.phone', '手机号') }}</span>
        <span class="info-value">{{ auth.user?.phone || '-' }}</span>
      </div>
      <div class="info-row">
        <span class="info-label">{{ t('auth.registerTime', '注册时间') }}</span>
        <span class="info-value">{{ auth.user?.created_at || '-' }}</span>
      </div>
      <div class="info-row">
        <span class="info-label">{{ t('auth.points', '积分') }}</span>
        <span class="info-value points">{{ auth.points }}</span>
      </div>
    </div>

    <!-- 推广分享区 -->
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
          <span class="share-icon">🔗</span>
          <span>{{ t('auth.copyLink', '复制链接') }}</span>
        </button>
        <button class="share-btn" @click="shareWeibo" title="分享到微博">
          <span class="share-icon">🔴</span>
          <span>{{ t('auth.weibo', '微博') }}</span>
        </button>
        <button class="share-btn" @click="shareWechat" title="分享到微信">
          <span class="share-icon">💬</span>
          <span>{{ t('auth.wechat', '微信') }}</span>
        </button>
        <button class="share-btn" @click="shareXiaohongshu" title="分享到小红书">
          <span class="share-icon">📕</span>
          <span>{{ t('auth.xiaohongshu', '小红书') }}</span>
        </button>
      </div>
      <div class="referral-stats">
        <div class="stat-item">
          <span class="stat-value">{{ auth.referralStats.referred_count }}</span>
          <span class="stat-label">{{ t('auth.referredCount', '邀请人数') }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-value">{{ auth.referralStats.active_count }}</span>
          <span class="stat-label">{{ t('auth.activeCount', '活跃人数') }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-value">+{{ auth.referralStats.total_points_awarded }}</span>
          <span class="stat-label">{{ t('auth.rewardPoints', '奖励积分') }}</span>
        </div>
      </div>
    </div>

    <div class="actions">
      <button class="btn btn-ghost btn-sm" @click="handleLogout">{{ t('auth.logout', '退出登录') }}</button>
    </div>

    <!-- QR 放大弹窗 -->
    <Teleport to="body">
      <div v-if="showQr" class="qr-overlay" @click.self="showQr = false">
        <div class="qr-modal">
          <img :src="qrDataUrl" class="qr-big">
          <p>{{ t('auth.qrScanWechat', '请用微信扫码分享') }}</p>
          <button class="btn btn-sm btn-ghost" @click="showQr = false">{{ t('common.close', '关闭') }}</button>
        </div>
      </div>
    </Teleport>

    <!-- Toast -->
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
}
.info-label { font-size: 12px; color: var(--text-muted); }
.info-value { font-size: 13px; color: var(--text-primary); font-weight: 500; }
.info-value.points { color: var(--accent); font-weight: 700; }

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
.share-icon { font-size: 14px; }
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
</style>