import type { TransactionRecord } from '@/types'
import { request } from '@/utils/http'

function delay(ms = 400): Promise<void> {
  return new Promise(r => setTimeout(r, ms))
}

const USE_MOCK = (import.meta.env.DEV || !window.navigator.onLine) && !import.meta.env.VITE_DISABLE_MOCK

export const authService = {
  async sendCode(account: string): Promise<void> {
    if (USE_MOCK) {
      await delay()
      return
    }
    await request('/topoapi/auth/send-code', {
      method: 'POST',
      body: JSON.stringify({ account }),
    })
  },

  async login(account: string, password: string): Promise<{ token: string; user: any }> {
    if (USE_MOCK) {
      await delay()
      return {
        token: 'mock-jwt-token-for-development',
        user: {
          id: 1,
          username: account.split('@')[0],
          email: account.includes('@') ? account : `${account}@phone.mock`,
          phone: account.includes('@') ? '' : account,
          avatar: '',
          referral_code: 'ABC12345',
          points: 150,
          has_password: true,
          created_at: new Date().toISOString(),
        },
      }
    }
    return request('/topoapi/auth/login', {
      method: 'POST',
      body: JSON.stringify({ account, password }),
    })
  },

  async loginWithCode(account: string, code: string): Promise<{ token: string; user: any }> {
    if (USE_MOCK) {
      await delay()
      return {
        token: 'mock-jwt-token-for-development',
        user: {
          id: 1,
          username: account.split('@')[0],
          email: account.includes('@') ? account : `${account}@phone.mock`,
          phone: account.includes('@') ? '' : account,
          avatar: '',
          referral_code: 'ABC12345',
          points: 150,
          has_password: true,
          created_at: new Date().toISOString(),
        },
      }
    }
    return request('/topoapi/auth/login-with-code', {
      method: 'POST',
      body: JSON.stringify({ account, code }),
    })
  },

  async register(username: string, email: string, password: string, emailCode: string, phone?: string, smsCode?: string, referralCode?: string): Promise<{ token: string; user: any }> {
    if (USE_MOCK) {
      await delay()
      return {
        token: 'mock-jwt-token-for-development',
        user: {
          id: 1,
          username,
          email,
          phone: phone || '',
          avatar: '',
          referral_code: 'ABC12345',
          points: 0,
          balance: 0,
          has_password: false,
          created_at: new Date().toISOString(),
        },
      }
    }
    return request('/topoapi/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, email, password, email_code: emailCode, phone, sms_code: smsCode, referral_code: referralCode }),
    })
  },

  async forgotPassword(email: string): Promise<void> {
    if (USE_MOCK) {
      await delay()
      return
    }
    await request('/topoapi/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email }),
    })
  },

  async resetPassword(email: string, code: string, newPassword: string): Promise<void> {
    if (USE_MOCK) {
      await delay()
      return
    }
    await request('/topoapi/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ email, code, new_password: newPassword }),
    })
  },

  async fetchProfile(): Promise<any> {
    if (USE_MOCK) {
      await delay()
      return {
        id: 1,
        username: 'mock_user',
        email: 'mock@example.com',
        phone: '',
        avatar: '',
        referral_code: 'ABC12345',
        points: 150,
        has_password: true,
        created_at: '2026-06-15T00:00:00',
      }
    }
    return request('/topoapi/user/profile')
  },

  async getReferralInfo(): Promise<{ referral_code: string; points_balance: number; random_share_link: string }> {
    if (USE_MOCK) {
      await delay()
      const paths = ['/share/a', '/share/b', '/share/c']
      const randomPath = paths[Math.floor(Math.random() * paths.length)]
      return { referral_code: 'ABC12345', points_balance: 150, random_share_link: `https://topocode.cn${randomPath}` }
    }
    return request('/topoapi/user/referral-info')
  },

  async getReferralStats(): Promise<{ total_referred: number; total_earned: number }> {
    if (USE_MOCK) {
      await delay()
      return { total_referred: 3, total_earned: 150 }
    }
    return request('/topoapi/user/referral-stats')
  },

  async getAccountInfo(): Promise<{ balance: number; points: number; total_recharged: number; total_consumed: number; total_points_rewarded: number }> {
    if (USE_MOCK) {
      await delay()
      return { balance: 120, points: 150, total_recharged: 170, total_consumed: 49, total_points_rewarded: 185 }
    }
    return request('/topoapi/user/account-info')
  },

  async getTransactions(params?: { page?: number; page_size?: number; type?: string; currency?: string }): Promise<{ total: number; page: number; page_size: number; items: TransactionRecord[] }> {
    if (USE_MOCK) {
      await delay()
      const items: TransactionRecord[] = [
        { id: 1, type: 'recharge', currency: 'balance', amount: 100, balance_after: 100, description: '余额充值', created_at: '2026-06-28T10:30:00' },
        { id: 2, type: 'consume', currency: 'points', amount: -30, balance_after: 120, description: '兑换资源：Spring Boot 电商微服务架构分析', created_at: '2026-06-25T14:20:00' },
        { id: 3, type: 'consume', currency: 'balance', amount: -49, balance_after: 51, description: '购买资源：Unity 游戏客户端架构分析', created_at: '2026-06-22T09:15:00' },
        { id: 4, type: 'reward', currency: 'points', amount: 50, balance_after: 150, description: '邀请奖励：好友完成注册', created_at: '2026-06-20T16:00:00' },
        { id: 5, type: 'recharge', currency: 'balance', amount: 50, balance_after: 100, description: '余额充值', created_at: '2026-06-18T11:00:00' },
        { id: 6, type: 'consume', currency: 'points', amount: -20, balance_after: 100, description: '兑换资源：React 18 大型前端项目依赖分析', created_at: '2026-06-15T08:30:00' },
        { id: 7, type: 'reward', currency: 'points', amount: 100, balance_after: 120, description: '邀请奖励：好友首次登录', created_at: '2026-06-10T20:00:00' },
        { id: 8, type: 'consume', currency: 'points', amount: -15, balance_after: 20, description: '兑换资源：Vue 3 组件库架构分析', created_at: '2026-06-05T13:45:00' },
        { id: 9, type: 'reward', currency: 'points', amount: 35, balance_after: 35, description: '新手任务奖励', created_at: '2026-06-01T09:00:00' },
      ]
      let filtered = items
      if (params?.type) {
        filtered = filtered.filter(t => t.type === params.type)
      }
      if (params?.currency) {
        filtered = filtered.filter(t => t.currency === params.currency)
      }
      const p = params?.page || 1
      const ps = params?.page_size || 20
      const start = (p - 1) * ps
      return { total: filtered.length, page: p, page_size: ps, items: filtered.slice(start, start + ps) }
    }
    const q = new URLSearchParams()
    if (params?.page) q.set('page', String(params.page))
    if (params?.page_size) q.set('page_size', String(params.page_size))
    if (params?.type) q.set('type', params.type)
    if (params?.currency) q.set('currency', params.currency)
    return request(`/topoapi/user/transactions?${q}`)
  },

  async updateProfile(data: { username?: string }): Promise<any> {
    if (USE_MOCK) {
      await delay()
      return { id: 1, username: data.username || 'mock_user', email: 'mock@example.com', phone: '' }
    }
    return request('/topoapi/user/profile', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  async setPassword(newPassword: string): Promise<void> {
    if (USE_MOCK) {
      await delay()
      return
    }
    await request('/topoapi/user/set-password', {
      method: 'POST',
      body: JSON.stringify({ new_password: newPassword }),
    })
  },

  async sendChangeCode(target?: string): Promise<{ message: string }> {
    if (USE_MOCK) {
      await delay()
      return { message: '验证码已发送' }
    }
    return request('/topoapi/user/send-change-code', {
      method: 'POST',
      body: target ? JSON.stringify({ target }) : undefined,
    })
  },

  async verifyChangeCode(code: string): Promise<void> {
    if (USE_MOCK) {
      await delay()
      return
    }
    await request('/topoapi/user/verify-change-code', {
      method: 'POST',
      body: JSON.stringify({ code }),
    })
  },

  async bindEmail(email: string, code: string): Promise<void> {
    if (USE_MOCK) {
      await delay()
      return
    }
    await request('/topoapi/user/bind-email', {
      method: 'POST',
      body: JSON.stringify({ email, code }),
    })
  },

  async bindPhone(phone: string, code: string): Promise<void> {
    if (USE_MOCK) {
      await delay()
      return
    }
    await request('/topoapi/user/bind-phone', {
      method: 'POST',
      body: JSON.stringify({ phone, code }),
    })
  },

  async logout(): Promise<void> {
    if (USE_MOCK) {
      await delay()
      return
    }
    await request('/topoapi/auth/logout', {
      method: 'POST',
    })
  },
}
