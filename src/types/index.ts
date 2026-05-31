/* ========================================
   全局类型定义
   ======================================== */

/** 页面类型 */
export type PageType = 'home' | 'code' | 'analysis' | 'knowledge' | 'coder' | 'user';

/** 内置主题类型 */
export type ThemeType = 'dark' | 'light';

/** CSS 变量键名 */
export type CssVarKey =
  | 'bgPrimary' | 'bgSecondary' | 'bgTertiary' | 'bgHover' | 'bgActive'
  | 'textPrimary' | 'textSecondary' | 'textMuted'
  | 'accent' | 'accentHover' | 'success' | 'warning' | 'error'
  | 'border' | 'borderLight'
  | 'fontSans' | 'fontMono';

/** 自定义主题颜色变量 */
export interface ThemeColors {
  bgPrimary: string;
  bgSecondary: string;
  bgTertiary: string;
  bgHover: string;
  bgActive: string;
  textPrimary: string;
  textSecondary: string;
  textMuted: string;
  accent: string;
  accentHover: string;
  success: string;
  warning: string;
  error: string;
  border: string;
  borderLight: string;
}

/** 自定义主题字体配置 */
export interface ThemeFonts {
  fontSans: string;
  fontMono: string;
}

/** 自定义主题 */
export interface CustomTheme {
  id: string;
  name: string;
  description?: string;
  colors: ThemeColors;
  fonts: ThemeFonts;
  isBuiltIn?: boolean;
  createdAt: string;
  updatedAt: string;
}

/** 后端状态 */
export interface BackendStatus {
  status: 'running' | 'stopped' | 'error';
  pid?: number;
  port?: number;
  error?: string;
  httpPort?: number;
  httpHost?: string;
}

/** 项目信息 */
export interface Project {
  id: string;
  name: string;
  path: string;
  language: string;
  fileCount: number;
  status: 'synced' | 'syncing' | 'error';
  lastSync: string;
  createdAt: string;
}

/** 分析任务 */
export interface AnalysisTask {
  id: string;
  projectId: string;
  type: 'full-parse' | 'ast-gen' | 'call-chain' | 'dataflow' | 'dep-analysis';
  name: string;
  status: 'done' | 'running' | 'pending' | 'error';
  progress?: number;
  total?: number;
  current?: number;
  error?: string;
  createdAt: string;
  updatedAt: string;
  favorite?: boolean;
  pinned?: boolean;
  tags?: string[];
}

/** 知识文档 */
export interface KnowledgeDoc {
  id: string;
  title: string;
  content: string;
  type: 'project' | 'document';
  dimensions: {
    lifecycle?: string[];
    techstack?: string[];
    abstraction?: string[];
    attribute?: string[];
  };
  status: 'draft' | 'pending' | 'approved';
  favorite?: boolean;
  pinned?: boolean;
  createdAt: string;
  updatedAt: string;
}

/** AI Session */
export interface CoderSession {
  id: string;
  title: string;
  type: 'chat' | 'design';
  group: 'current' | 'general' | 'history' | 'temp';
  messages: ChatMessage[];
  createdAt: string;
  updatedAt: string;
}

/** 聊天消息 */
export interface ChatMessage {
  id: string;
  sessionId: string;
  role: 'user' | 'assistant';
  type: 'text' | 'context' | 'spec' | 'task' | 'error';
  content: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
}

/** Agent 任务 */
export interface AgentTask {
  id: string;
  sessionId: string;
  agentId: string;
  status: 'running' | 'done' | 'error';
  progress: number;
  logs: string[];
  result?: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

/** 模型配置 */
export interface ModelConfig {
  id: string;
  name: string;
  type: 'ollama' | 'openai' | 'custom';
  url: string;
  model: string;
  temperature?: number;
  maxTokens?: number;
  isDefault?: boolean;
  status: 'online' | 'offline' | 'error';
  latency?: number;
}

/** Agent 配置 */
export interface AgentConfig {
  id: string;
  name: string;
  path: string;
  args?: string[];
  isDefault?: boolean;
  status: 'online' | 'offline' | 'error';
  version?: string;
}

/** SKILL 配置 */
export interface SkillConfig {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
}

/** 设置 */
export interface AppSettings {
  theme: ThemeType;
  language: string;
  fontSize: number;
  autoSave: number;
  kbHttpServer: {
    enabled: boolean;
    port: number;
  };
}

/** 导航状态 */
export interface NavigationState {
  currentPage: PageType;
  breadcrumbs: Breadcrumb[];
}

/** 面包屑 */
export interface Breadcrumb {
  label: string;
  page?: PageType;
  onClick?: () => void;
}

/** 面板状态 */
export interface PanelState {
  leftCollapsed: boolean;
  rightCollapsed: boolean;
  leftWidth: number;
  rightWidth: number;
}

/** 状态栏信息 */
export interface StatusBarState {
  backend: BackendStatus;
  astStatus: string;
  gitBranch: string;
  aiModel: string;
  encoding: string;
  zoom: number;
}

/** API 响应 */
export interface APIResponse<T = unknown> {
  code: number;
  message: string;
  data: T;
}

/** 错误类型 */
export class AppError extends Error {
  constructor(
    public code: number,
    message: string,
    public details?: unknown
  ) {
    super(message);
    this.name = 'AppError';
  }
}
