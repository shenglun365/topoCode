import type { KbConfig } from '@/types'
import { apiGet, apiPut, apiPost } from './api-client'

/** 知识库连接配置与连通性测试。 */
export const kbService = {
  async getConfig(): Promise<KbConfig> {
    return apiGet<KbConfig>('/kb/config')
  },
  async saveConfig(opts: { dataApiUrl?: string; mcpUrl?: string }): Promise<KbConfig> {
    return apiPut<KbConfig>('/kb/config', opts)
  },
  async test(): Promise<KbConfig> {
    return apiPost<KbConfig>('/kb/config/test')
  },
}
