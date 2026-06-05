import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockOnProgress = vi.fn()
const mockOnComplete = vi.fn()
const mockOnError = vi.fn()

const mockApi = {
  analysis: {
    listTasks: vi.fn(),
    runTask: vi.fn(),
    getTask: vi.fn(),
    stopTask: vi.fn(),
    onProgress: mockOnProgress,
    onComplete: mockOnComplete,
    onError: mockOnError,
  },
}

vi.stubGlobal('window', { api: mockApi })

describe('analysis-service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('createAnalysisService creates service object', async () => {
    const { createAnalysisService } = await import('@/services/ipc/analysis-service')
    const svc = createAnalysisService(mockApi)
    expect(svc).toBeDefined()
    expect(typeof svc.listTasks).toBe('function')
    expect(typeof svc.runTask).toBe('function')
    expect(typeof svc.onProgress).toBe('function')
  })

  it('runTask delegates to api.analysis.runTask', async () => {
    mockApi.analysis.runTask.mockResolvedValue({ taskId: 'task-1' })
    const { createAnalysisService } = await import('@/services/ipc/analysis-service')
    const svc = createAnalysisService(mockApi)
    const result = await svc.runTask('task-1')
    expect(mockApi.analysis.runTask).toHaveBeenCalledWith('task-1')
    expect(result).toEqual({ taskId: 'task-1' })
  })

  it('getTask delegates to api.analysis.getTask', async () => {
    mockApi.analysis.getTask.mockResolvedValue({ id: 'task-1', status: 'done' })
    const { createAnalysisService } = await import('@/services/ipc/analysis-service')
    const svc = createAnalysisService(mockApi)
    const result = await svc.getTask('task-1')
    expect(mockApi.analysis.getTask).toHaveBeenCalledWith('task-1')
    expect(result).toBeDefined()
  })

  it('listTasks delegates to api.analysis.listTasks', async () => {
    mockApi.analysis.listTasks.mockResolvedValue([])
    const { createAnalysisService } = await import('@/services/ipc/analysis-service')
    const svc = createAnalysisService(mockApi)
    const result = await svc.listTasks('proj-1')
    expect(mockApi.analysis.listTasks).toHaveBeenCalledWith('proj-1')
    expect(result).toEqual([])
  })

  it('onProgress registers callback via api', async () => {
    const cb = vi.fn()
    const { createAnalysisService } = await import('@/services/ipc/analysis-service')
    const svc = createAnalysisService(mockApi)
    svc.onProgress(cb)
    expect(mockOnProgress).toHaveBeenCalledWith(cb)
  })

})
