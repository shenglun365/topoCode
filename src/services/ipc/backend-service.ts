import type {
  BackendActionResult, PingResult, PortTestResult,
  BackendStatusEvent, HttpConfigDTO, SuccessResponse,
} from '@/types/ipc'

export interface BackendService {
  start(): Promise<BackendActionResult>
  stop(): Promise<BackendActionResult>
  restart(): Promise<BackendActionResult>
  getStatus(): Promise<BackendActionResult>
  ping(): Promise<PingResult>
  testPort(port: number): Promise<PortTestResult>
  onStatusChange(cb: (data: BackendStatusEvent) => void): void
  getMemoryLimit(): Promise<number>
  setMemoryLimit(limit: number): Promise<void>
  getHttpConfig(): Promise<HttpConfigDTO>
  setHttpConfig(config: { host: string; port: number }): Promise<SuccessResponse>
  saveHttpConfig(config: { host?: string; port?: number }): Promise<SuccessResponse>
}

export function createBackendService(api: any): BackendService {
  return {
    start: async () => {
      return await api.backend.start() as BackendActionResult
    },
    stop: async () => {
      return await api.backend.stop() as BackendActionResult
    },
    restart: async () => {
      return await api.backend.restart() as BackendActionResult
    },
    getStatus: async () => {
      return await api.backend.getStatus() as BackendActionResult
    },
    ping: async () => {
      return await api.backend.ping() as PingResult
    },
    testPort: async (port: number) => {
      return await api.backend.testPort(port) as PortTestResult
    },
    onStatusChange: (cb: (data: BackendStatusEvent) => void) => {
      api.backend.onStatusChange(cb)
    },
    getHttpConfig: async () => {
      return await api.backend.getHttpConfig() as HttpConfigDTO
    },
    getMemoryLimit: async () => {
      return await api.backend.getMemoryLimit() as number
    },
    setMemoryLimit: async (limit: number) => {
      return await api.backend.setMemoryLimit(limit) as void
    },
    setHttpConfig: async (config: { host: string; port: number }) => {
      return await api.backend.setHttpConfig(config) as SuccessResponse
    },
    saveHttpConfig: async (config: { host?: string; port?: number }) => {
      return await api.backend.saveHttpConfig(config) as SuccessResponse
    },
  }
}
