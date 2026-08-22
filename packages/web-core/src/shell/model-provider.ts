export interface ModelInfo {
  id: string
  name: string
}

/**
 * 模型/上下文设置后端接口（P2）—— 各子模块注入自己的 provider：
 * - chat      : `api.listModels()`（共享 model_configs）+ PUT /api/models/{id}
 * - workbench : `ipc.settings.getModels()`（共享 model_configs，偏好存 localStorage）
 * - architect : `/api/architect/llm/models`（独立模型库）+ PUT /llm/model、/llm/max-tokens
 * save* 可选：不提供则仅持久化 localStorage 偏好。
 */
export interface ModelSettingsProvider {
  listModels(): Promise<ModelInfo[]>
  saveModel?(modelId: string): Promise<void>
  saveContext?(context: number): Promise<void>
}
