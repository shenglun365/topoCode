// dev 便利：vite proxy 自动注入网关鉴权头（token 读 ~/.topocode/token）。
// 生产态由页面 #token= 流程自带；dev 下前端无 token，代理层补齐。
// 客户端已带 Authorization 时不覆盖；token 文件缺失则放行（由网关返回 401）。
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

function readDevToken(): string {
  try {
    return fs.readFileSync(path.join(os.homedir(), '.topocode', 'token'), 'utf8').trim()
  } catch {
    return ''
  }
}

export function devAuthProxyHooks() {
  return {
    configure: (proxy: any) => {
      proxy.on('proxyReq', (proxyReq: any) => {
        if (proxyReq.getHeader('authorization')) return
        const token = readDevToken()
        if (token) proxyReq.setHeader('Authorization', `Bearer ${token}`)
      })
      proxy.on('proxyReqWs', (proxyReq: any) => {
        if (proxyReq.getHeader('authorization')) return
        const token = readDevToken()
        if (token) proxyReq.setHeader('Authorization', `Bearer ${token}`)
      })
    },
  }
}
