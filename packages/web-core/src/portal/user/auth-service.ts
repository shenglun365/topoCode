/** 用户中心（基础服务）认证服务 —— 自 workbench 迁入，走统一网关 /topoapi */
import type { TransactionRecord } from './types'
import { request } from '../../utils/http'

export const authService = {
  async sendCode(account: string): Promise<void> {
    await request('/topoapi/auth/send-code', {
      method: 'POST',
      body: JSON.stringify({ account }),
    })
  },

  async login(account: string, password: string): Promise<{ token: string; user: any }> {
    return request('/topoapi/auth/login', {
      method: 'POST',
      body: JSON.stringify({ account, password }),
    })
  },

  async loginWithCode(account: string, code: string): Promise<{ token: string; user: any }> {
    return request('/topoapi/auth/login-with-code', {
      method: 'POST',
      body: JSON.stringify({ account, code }),
    })
  },

  async register(username: string, email: string, password: string, emailCode: string, phone?: string, smsCode?: string, referralCode?: string): Promise<{ token: string; user: any }> {
    return request('/topoapi/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, email, password, email_code: emailCode, phone, sms_code: smsCode, referral_code: referralCode }),
    })
  },

  async forgotPassword(email: string): Promise<void> {
    await request('/topoapi/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email }),
    })
  },

  async resetPassword(email: string, code: string, newPassword: string): Promise<void> {
    await request('/topoapi/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ email, code, new_password: newPassword }),
    })
  },

  async fetchProfile(): Promise<any> {
    return request('/topoapi/user/profile')
  },

  async getReferralInfo(): Promise<{ referral_code: string; points_balance: number; random_share_link: string }> {
    return request('/topoapi/user/referral-info')
  },

  async getReferralStats(): Promise<{ total_referred: number; total_earned: number }> {
    return request('/topoapi/user/referral-stats')
  },

  async getAccountInfo(): Promise<{ balance: number; points: number; total_recharged: number; total_consumed: number; total_points_rewarded: number }> {
    return request('/topoapi/user/account-info')
  },

  async getTransactions(params?: { page?: number; page_size?: number; type?: string; currency?: string }): Promise<{ total: number; page: number; page_size: number; items: TransactionRecord[] }> {
    const q = new URLSearchParams()
    if (params?.page) q.set('page', String(params.page))
    if (params?.page_size) q.set('page_size', String(params.page_size))
    if (params?.type) q.set('type', params.type)
    if (params?.currency) q.set('currency', params.currency)
    return request(`/topoapi/user/transactions?${q}`)
  },

  async updateProfile(data: { username?: string }): Promise<any> {
    return request('/topoapi/user/profile', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  async setPassword(newPassword: string): Promise<void> {
    await request('/topoapi/user/set-password', {
      method: 'POST',
      body: JSON.stringify({ new_password: newPassword }),
    })
  },

  async sendChangeCode(target?: string): Promise<{ message: string }> {
    return request('/topoapi/user/send-change-code', {
      method: 'POST',
      body: target ? JSON.stringify({ target }) : undefined,
    })
  },

  async verifyChangeCode(code: string): Promise<void> {
    await request('/topoapi/user/verify-change-code', {
      method: 'POST',
      body: JSON.stringify({ code }),
    })
  },

  async bindEmail(email: string, code: string): Promise<void> {
    await request('/topoapi/user/bind-email', {
      method: 'POST',
      body: JSON.stringify({ email, code }),
    })
  },

  async bindPhone(phone: string, code: string): Promise<void> {
    await request('/topoapi/user/bind-phone', {
      method: 'POST',
      body: JSON.stringify({ phone, code }),
    })
  },

  async logout(): Promise<void> {
    await request('/topoapi/auth/logout', {
      method: 'POST',
    })
  },
}
