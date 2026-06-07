import type {
  SubDocCreateResponse, SubDocDTO, SubDocUpdateResponse, SubDocDeleteResponse,
  SaveOverallDocResponse, PipelineStateResponse, PipelineStateData,
  ReadmeContentResponse, DependencyFilesResult, ProjectSummaryResponse,
  ProjectSummaryData, LevelCommunityDetailResult, SaveFileSummariesResponse,
  FileSummariesResult,
} from '@/types/ipc'

export interface ReportService {
  createSubDoc(params: {
    taskId: string; edgeType?: string; commId?: string;
    title: string; content: string; templateId?: string;
  }): Promise<SubDocCreateResponse>
  listSubDocs(params: { taskId: string; commId?: string }): Promise<SubDocDTO[]>
  getSubDoc(subDocId: string): Promise<SubDocDTO>
  updateSubDoc(params: { subDocId: string; title?: string; content?: string }): Promise<SubDocUpdateResponse>
  deleteSubDoc(subDocId: string): Promise<SubDocDeleteResponse>
  saveOverallDoc(params: { taskId: string; title: string; content: string }): Promise<SaveOverallDocResponse>
  savePipelineState(params: { taskId: string; stateJson: string }): Promise<PipelineStateResponse>
  loadPipelineState(params: { taskId: string }): Promise<PipelineStateData>
  getReadmeContent(params: { projectId: string }): Promise<ReadmeContentResponse>
  extractDependencyFiles(params: { projectId: string }): Promise<DependencyFilesResult>
  generateProjectSummary(params: { projectId: string }): Promise<ProjectSummaryResponse>
  getProjectSummary(params: { projectId: string }): Promise<ProjectSummaryData>
  saveProjectSummary(params: { projectId: string; summary: string }): Promise<ProjectSummaryResponse>
  getLevelCommunityDetail(params: {
    projectId: string; taskId: string; level?: string; edgeType?: string
  }): Promise<LevelCommunityDetailResult>
  saveFileSummaries(params: { projectId: string; taskId: string; summaries: any[] }): Promise<SaveFileSummariesResponse>
  getFileSummaries(params: { projectId: string; taskId?: string; source?: string }): Promise<FileSummariesResult>
}

export function createReportService(api: any): ReportService {
  return {
    createSubDoc: async (params) => {
      return await api.report.createSubDoc(params) as SubDocCreateResponse
    },
    listSubDocs: async (params) => {
      return await api.report.listSubDocs(params) as SubDocDTO[]
    },
    getSubDoc: async (subDocId: string) => {
      return await api.report.getSubDoc(subDocId) as SubDocDTO
    },
    updateSubDoc: async (params) => {
      return await api.report.updateSubDoc(params) as SubDocUpdateResponse
    },
    deleteSubDoc: async (subDocId: string) => {
      return await api.report.deleteSubDoc(subDocId) as SubDocDeleteResponse
    },
    saveOverallDoc: async (params) => {
      return await api.report.saveOverallDoc(params) as SaveOverallDocResponse
    },
    savePipelineState: async (params) => {
      return await api.report.savePipelineState(params) as PipelineStateResponse
    },
    loadPipelineState: async (params) => {
      return await api.report.loadPipelineState(params) as PipelineStateData
    },
    getReadmeContent: async (params) => {
      return await api.report.getReadmeContent(params) as ReadmeContentResponse
    },
    extractDependencyFiles: async (params) => {
      return await api.report.extractDependencyFiles(params) as DependencyFilesResult
    },
    generateProjectSummary: async (params) => {
      return await api.report.generateProjectSummary(params) as ProjectSummaryResponse
    },
    getProjectSummary: async (params) => {
      return await api.report.getProjectSummary(params) as ProjectSummaryData
    },
    saveProjectSummary: async (params) => {
      return await api.report.saveProjectSummary(params) as ProjectSummaryResponse
    },
    getLevelCommunityDetail: async (params) => {
      return await api.report.getLevelCommunityDetail(params) as LevelCommunityDetailResult
    },
    saveFileSummaries: async (params) => {
      return await api.report.saveFileSummaries(params) as SaveFileSummariesResponse
    },
    getFileSummaries: async (params) => {
      return await api.report.getFileSummaries(params) as FileSummariesResult
    },
  }
}
