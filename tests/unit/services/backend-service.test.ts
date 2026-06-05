import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockOnStatusChange = vi.fn()

const mockApi = {
  backend: {
    getStatus: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
    restart: vi.fn(),
    ping: vi.fn(),
    testPort: vi.fn(),
    onStatusChange: mockOnStatusChange,
    getHttpConfig: vi.fn(),
    setHttpConfig: vi.fn(),
  },
}

vi.stubGlobal('window', { api: mockApi })

describe('backend-service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('createBackendService creates service object', async () => {
    const { createBackendService } = await import('@/services/ipc/backend-service')
    const svc = createBackendService(mockApi)
    expect(svc).toBeDefined()
    expect(typeof svc.getStatus).toBe('function')
    expect(typeof svc.start).toBe('function')
    expect(typeof svc.stop).toBe('function')
    expect(typeof svc.onStatusChange).toBe('function')
  })

  it('getStatus delegates to api', async () => {
    mockApi.backend.getStatus.mockResolvedValue({ status: 'running', pid: 12345 })
    const { createBackendService } = await import('@/services/ipc/backend-service')
    const svc = createBackendService(mockApi)
    const result = await svc.getStatus()
    expect(mockApi.backend.getStatus).toHaveBeenCalled()
    expect(result).toEqual({ status: 'running', pid: 12345 })
  })

  it('start delegates to api', async () => {
    mockApi.backend.start.mockResolvedValue({ status: 'running' })
    const { createBackendService } = await import('@/services/ipc/backend-service')
    const svc = createBackendService(mockApi)
    const result = await svc.start()
    expect(mockApi.backend.start).toHaveBeenCalled()
    expect(result).toEqual({ status: 'running' })
  })

  it('stop delegates to api', async () => {
    mockApi.backend.stop.mockResolvedValue({ status: 'stopped' })
    const { createBackendService } = await import('@/services/ipc/backend-service')
    const svc = createBackendService(mockApi)
    const result = await svc.stop()
    expect(mockApi.backend.stop).toHaveBeenCalled()
    expect(result).toEqual({ status: 'stopped' })
  })

  it('onStatusChange registers callback via api', async () => {
    const cb = vi.fn()
    const { createBackendService } = await import('@/services/ipc/backend-service')
    const svc = createBackendService(mockApi)
    svc.onStatusChange(cb)
    expect(mockOnStatusChange).toHaveBeenCalledWith(cb)
  })

  it('onStatusChange calls the api method', async () => {
    const cb = vi.fn()
    const { createBackendService } = await import('@/services/ipc/backend-service')
    const svc = createBackendService(mockApi)
    svc.onStatusChange(cb)
    expect(mockOnStatusChange).toHaveBeenCalledWith(cb)
  })
})
