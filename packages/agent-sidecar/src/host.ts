/**
 * ClineCoreHost — ClineCore 会话宿主（v2 sidecar 核心）。
 *
 * 单进程单 ClineCore 实例，按 sessionId 多路复用多作业会话：
 *   - startSession   完整 ClineCoreStartConfig（模型/策略/压缩/检查点/teams）
 *   - sendTurn       真多回合（上下文由 ClineCore 会话持久化保持）
 *   - abort          中止当前回合（工具级，会话保留）
 *   - stop           优雅终止会话
 *   - respondApproval  审批桥（capabilities.requestToolApproval ↔ approval/respond）
 *   - dispose        遍历 stop + cline.dispose()（防孤儿进程/文件锁）
 *
 * 事件面：CoreSessionEvent → 归一化通知（chunk/tool/iteration/notice/usage/
 * status/ended/team/pending_prompts/approval_request），全部携带 sessionId。
 *
 * 存储隔离：configureStorage() 须在 ClineCore.create 之前调用（CLINE_DATA_DIR
 * 运行时读取），把会话/设置/machine-id 全部重定向到 ~/.topocode/cline/<id>/。
 */
import { ClineCore, createTool } from "@cline/sdk";
import type { ToolApprovalResult } from "@cline/sdk";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

export interface ModelConfig {
  providerId: string;
  modelId: string;
  apiKey?: string;
  baseUrl?: string;
  headers?: Record<string, string>;
  thinking?: boolean;
  reasoningEffort?: string;
  thinkingBudgetTokens?: number;
  maxTokensPerTurn?: number;
  temperature?: number;
}

export interface SessionStartParams {
  sessionId?: string;
  cwd: string;
  workspaceRoot?: string;
  model: ModelConfig;
  maxIterations?: number;
  systemPrompt?: string;
  mode?: string;                       // "act" | "plan"
  toolPolicies?: Record<string, { enabled?: boolean; autoApprove?: boolean }>;
  enableTools?: boolean;
  enableAgentTeams?: boolean;
  enableSpawnAgent?: boolean;
  yolo?: boolean;
  disableMcpSettingsTools?: boolean;   // 默认 true：MCP 仅经注册表注入，禁会话内自改
  checkpointEnabled?: boolean;         // 默认 true（git 按 run 快照）
  compaction?: { enabled?: boolean; strategy?: string; preserveRecentTokens?: number };
  skills?: string[];
  teamName?: string;
  workspaceMetadata?: string;
  sessionMetadata?: Record<string, unknown>;
  archUrl?: string;                    // architect 资产工具注入
  archToken?: string;
  projectId?: string;
  protocolTools?: boolean;             // 默认 true：注入 report_turn_outcome 完成协议工具
  mcpServers?: McpServerSpec[];        // P5: MCP server 注入（单失败降级跳过）
  teams?: { enabled?: boolean; teamName?: string };
  approvalTimeoutMs?: number;
}

export interface TurnSendParams {
  sessionId: string;
  prompt: string;
  mode?: string;
  delivery?: "queue" | "steer";
  timeoutMs?: number;
}

export interface SessionInfo {
  sessionId: string;
  cwd: string;
  providerId: string;
  modelId: string;
  createdAt: number;
  lastActivityTs: number;
  status: string;                      // running | idle | ended | stopped | failed
  inflight: boolean;                   // 回合进行中
}

export interface TurnResult {
  ok: boolean;
  status: string;                      // completed | aborted | failed | ...
  outputText: string;
  iterations: number;
  usage: unknown;
  error: string;
  turnOutcome?: TurnOutcome | null;    // 协作协议工具回报（T2）
}

/** 回合结局（结构化替代 [[IMPLEMENT_DONE]]/[[NEED_INPUT]] 文本标记） */
export interface TurnOutcome {
  status: "done" | "need_input";
  summary: string;
  changedFiles?: string[];
  notes?: string;
}

/** MCP server 注入规格（P5）：streamableHttp 优先（SSE 不转发 Authorization 的坑）。 */
export interface McpServerSpec {
  name: string;
  transport?: "streamableHttp" | "sse" | "stdio";
  url?: string;
  headers?: Record<string, string>;
  command?: string;
  args?: string[];
  cwd?: string;
  env?: Record<string, string>;
  timeoutSeconds?: number;
}

export type HostEvent = Record<string, unknown> & { type: string; sessionId?: string };

export interface HostOptions {
  fetch?: typeof fetch;                // 测试注入 fake LLM（ClineCoreOptions.fetch 透传）
  dataDir?: string;                    // 存储重定向（默认 ~/.topocode/cline/default）
  clientName?: string;
  onEvent?: (event: HostEvent) => void;
}

const DEFAULT_APPROVAL_TIMEOUT_MS = 600_000;

export function configureStorage(dataDir?: string): string {
  const root = dataDir
    || process.env.TOPOCODE_CLINE_DATA_DIR || "";
  const abs = path.resolve(root
    || path.join(os.homedir(), ".topocode", "cline", "default"));
  const data = path.join(abs, "data");
  fs.mkdirSync(data, { recursive: true });
  process.env.CLINE_DATA_DIR = data;
  return abs;
}

export class ClineCoreHost {
  private _cline: ClineCore | null = null;
  private _createPromise: Promise<ClineCore> | null = null;
  private readonly _options: HostOptions;
  private readonly _sessions = new Map<string, SessionInfo>();
  private readonly _approvals = new Map<string, (r: ToolApprovalResult) => void>();
  private _approvalSeq = 0;
  private _unsubscribe: (() => void) | null = null;
  private _approvalTimeoutMs = DEFAULT_APPROVAL_TIMEOUT_MS;
  private readonly _turnOutcomes = new Map<string, TurnOutcome>();
  private readonly _mcpManagers: Array<{ dispose: () => Promise<void> }> = [];

  constructor(options: HostOptions = {}) {
    this._options = options;
  }

  get sessions(): Map<string, SessionInfo> {
    return this._sessions;
  }

  private _emit(event: HostEvent): void {
    try {
      this._options.onEvent?.(event);
    } catch {
      /* 事件回调容错 */
    }
  }

  private async _core(): Promise<ClineCore> {
    if (this._cline) return this._cline;
    if (this._createPromise) return this._createPromise;
    this._createPromise = (async () => {
      configureStorage(this._options.dataDir);
      const core = await ClineCore.create({
        clientName: this._options.clientName || "topoone-sidecar",
        backendMode: "local",
        fetch: this._options.fetch,
        capabilities: {
          requestToolApproval: async (request: {
            sessionId: string;
            toolCallId: string;
            toolName: string;
            input: unknown;
            policy?: unknown;
          }) => this._requestApproval(request),
        },
      } as never) as ClineCore;
      this._cline = core;
      this._unsubscribe = core.subscribe((event: never) => this._onSessionEvent(event));
      return core;
    })();
    try {
      return await this._createPromise;
    } catch (e) {
      this._createPromise = null;
      throw e;
    }
  }

  // ── 会话生命周期 ──

  async startSession(params: SessionStartParams): Promise<{ sessionId: string }> {
    const core = await this._core();
    this._approvalTimeoutMs = params.approvalTimeoutMs || DEFAULT_APPROVAL_TIMEOUT_MS;
    const m = params.model || ({} as ModelConfig);
    const config: Record<string, unknown> = {
      sessionId: params.sessionId || undefined,
      providerId: m.providerId,
      modelId: m.modelId,
      ...(m.apiKey ? { apiKey: m.apiKey } : {}),
      ...(m.baseUrl ? { baseUrl: m.baseUrl } : {}),
      ...(m.headers ? { headers: m.headers } : {}),
      ...(m.thinking !== undefined ? { thinking: m.thinking } : {}),
      ...(m.reasoningEffort ? { reasoningEffort: m.reasoningEffort } : {}),
      ...(m.thinkingBudgetTokens ? { thinkingBudgetTokens: m.thinkingBudgetTokens } : {}),
      ...(m.maxTokensPerTurn ? { maxTokensPerTurn: m.maxTokensPerTurn } : {}),
      ...(m.temperature !== undefined ? { temperature: m.temperature } : {}),
      ...(params.maxIterations ? { maxIterations: params.maxIterations } : {}),
      cwd: params.cwd,
      ...(params.workspaceRoot ? { workspaceRoot: params.workspaceRoot } : {}),
      systemPrompt: params.systemPrompt
        || "You are a senior software engineer working inside a managed coding-agent runner. Work carefully, verify your changes, and report results concisely.",
      mode: params.mode || "act",
      enableTools: params.enableTools !== false,
      enableAgentTeams: params.enableAgentTeams === true,
      enableSpawnAgent: params.enableSpawnAgent === true,
      disableMcpSettingsTools: params.disableMcpSettingsTools !== false,
      yolo: params.yolo === true,
      ...(params.toolPolicies ? { toolPolicies: params.toolPolicies } : {}),
      checkpoint: { enabled: params.checkpointEnabled !== false },
      ...(params.compaction ? { compaction: params.compaction } : {}),
      ...(params.skills ? { skills: params.skills } : {}),
      ...(params.teamName ? { teamName: params.teamName } : {}),
      ...(params.workspaceMetadata ? { workspaceMetadata: params.workspaceMetadata } : {}),
    };
    // 协议工具在 start 前构建；SDK 分配的最终 sessionId 经 getSid 闭包回填
    // （未显式指定 sessionId 的场景）。extraTools 必须随 config 传入——
    // LocalOnly 键由 SDK 侧 splitCoreSessionConfig 拆到 localRuntime。
    let boundSessionId = params.sessionId || "";
    const extraTools = [
      ...this._buildExtraTools(params, () => boundSessionId),
      ...(await this._buildMcpTools(params, boundSessionId)),
    ];
    if (extraTools.length) {
      (config as Record<string, unknown>).extraTools = extraTools;
    }
    if (params.teams?.enabled) {
      config.enableAgentTeams = true;
      if (params.teams.teamName) config.teamName = params.teams.teamName;
    }
    const startInput: Record<string, unknown> = {
      source: "cli",
      interactive: true, // 常驻会话：回合完成后不 finalize，可续多回合
      config,
      ...(params.sessionMetadata ? { sessionMetadata: params.sessionMetadata } : {}),
    };
    const result = await (core as unknown as {
      start: (input: unknown) => Promise<{ sessionId: string }>;
    }).start(startInput);
    const sessionId = result.sessionId;
    boundSessionId = sessionId;
    this._sessions.set(sessionId, {
      sessionId,
      cwd: params.cwd,
      providerId: m.providerId || "",
      modelId: m.modelId || "",
      createdAt: Date.now(),
      lastActivityTs: Date.now(),
      status: "idle",
      inflight: false,
    });
    return { sessionId };
  }

  private _buildSendInput(params: TurnSendParams): Record<string, unknown> {
    return {
      sessionId: params.sessionId,
      prompt: params.prompt,
      ...(params.mode ? { mode: params.mode } : {}),
      ...(params.delivery ? { delivery: params.delivery } : {}),
      ...(params.timeoutMs ? { timeoutMs: params.timeoutMs } : {}),
    };
  }

  private _mapResult(
    info: SessionInfo | undefined,
    result: Record<string, unknown> | undefined,
  ): TurnResult {
    const status = String((result?.finishReason as string) || (result ? "completed" : "failed"));
    if (info) {
      info.inflight = false;
      info.status = status === "completed" ? "idle" : status;
      info.lastActivityTs = Date.now();
    }
    return {
      ok: status === "completed",
      status,
      outputText: String((result?.text as string) || ""),
      iterations: Number((result?.iterations as number) || 0),
      usage: (result?.usage as unknown) ?? null,
      error: String((result as { error?: unknown })?.error || ""),
      turnOutcome: info ? (this._turnOutcomes.get(info.sessionId) ?? null) : null,
    };
  }

  async sendTurn(params: TurnSendParams): Promise<TurnResult> {
    const core = await this._core();
    const info = this._sessions.get(params.sessionId);
    if (info) {
      info.inflight = true;
      info.status = "running";
      info.lastActivityTs = Date.now();
    }
    const send = (core as unknown as {
      send: (input: unknown) => Promise<Record<string, unknown> | undefined>;
    }).send.bind(core);
    try {
      const result = await send(this._buildSendInput(params));
      return this._mapResult(info, result);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      // 回合间隙竞态：上一回合 bookkeeping 未落定 → session_run_in_progress，退避重试
      if (/in_progress|in progress|unusable/i.test(msg)) {
        for (let i = 0; i < 10; i++) {
          await new Promise((r) => setTimeout(r, 500));
          try {
            const retry = await send(this._buildSendInput(params));
            return this._mapResult(info, retry);
          } catch (retryErr) {
            const rm = retryErr instanceof Error ? retryErr.message : String(retryErr);
            if (!/in_progress|in progress|unusable/i.test(rm)) {
              break;
            }
          }
        }
      }
      if (info) {
        info.inflight = false;
        info.status = "failed";
      }
      return {
        ok: false,
        status: "failed",
        outputText: "",
        iterations: 0,
        usage: null,
        error: msg,
      };
    }
  }

  async abort(sessionId: string, reason?: string): Promise<boolean> {
    if (!this._cline) return false;
    try {
      await this._cline.abort(sessionId, reason || "aborted by runner");
      const info = this._sessions.get(sessionId);
      if (info) {
        info.inflight = false;
        info.lastActivityTs = Date.now();
      }
      return true;
    } catch {
      return false;
    }
  }

  async stop(sessionId: string): Promise<boolean> {
    if (!this._cline) return false;
    try {
      await this._cline.stop(sessionId);
      const info = this._sessions.get(sessionId);
      if (info) info.status = "stopped";
      return true;
    } catch {
      return false;
    }
  }

  getStatus(sessionId: string): SessionInfo | undefined {
    return this._sessions.get(sessionId);
  }

  // ── 内省面（T3）──

  /** 会话转写（display=true 为 UI 投影，含工具块；false 为模型重放口径）。 */
  async readMessages(sessionId: string, display = true): Promise<unknown> {
    const core = await this._core();
    if (display) {
      return await (core as unknown as {
        readDisplayMessages: (sid: string) => Promise<unknown>;
      }).readDisplayMessages(sessionId);
    }
    return await (core as unknown as {
      readMessages: (sid: string) => Promise<unknown>;
    }).readMessages(sessionId);
  }

  /** 会话累计用量（usage=主代理；aggregateUsage=含 teammates/subagents）。 */
  async getUsage(sessionId: string): Promise<unknown> {
    const core = await this._core();
    return await (core as unknown as {
      getAccumulatedUsage: (sid: string) => Promise<unknown>;
    }).getAccumulatedUsage(sessionId);
  }

  /** 会话内换模（仅 modelId）；换 provider/密钥/推理配置走 updateConnection。 */
  async updateModel(sessionId: string, modelId: string): Promise<boolean> {
    const core = await this._core();
    try {
      await (core as unknown as {
        updateSessionModel: (sid: string, mid: string) => Promise<void>;
      }).updateSessionModel(sessionId, modelId);
      const info = this._sessions.get(sessionId);
      if (info) info.modelId = modelId;
      return true;
    } catch {
      return false;
    }
  }

  /** 会话内换连接（provider/apiKey/baseUrl/headers/推理配置），下一回合生效。 */
  async updateConnection(sessionId: string, updates: {
    providerId?: string;
    modelId?: string;
    apiKey?: string;
    baseUrl?: string;
    headers?: Record<string, string>;
    thinking?: boolean;
    reasoningEffort?: string;
    thinkingBudgetTokens?: number;
  }): Promise<boolean> {
    const core = await this._core();
    try {
      await (core as unknown as {
        updateSessionConnection: (sid: string, u: unknown) => Promise<void>;
      }).updateSessionConnection(sessionId, updates);
      const info = this._sessions.get(sessionId);
      if (info) {
        if (updates.modelId) info.modelId = updates.modelId;
        if (updates.providerId) info.providerId = updates.providerId;
      }
      return true;
    } catch {
      return false;
    }
  }

  /** 会话历史清单（跨作业 sessionRef 复活的发现面）。 */
  async listHistory(limit = 50): Promise<unknown> {
    const core = await this._core();
    return await (core as unknown as {
      list: (n?: number) => Promise<unknown>;
    }).list(limit);
  }

  /** 检查点与工作区比对（验收素材：run N 之后的变更 diff）。 */
  async compareCheckpoint(sessionId: string, runCount: number): Promise<unknown> {
    const core = await this._core();
    return await (core as unknown as {
      compareCheckpoint: (input: unknown) => Promise<unknown>;
    }).compareCheckpoint({ sessionId, checkpointRunCount: runCount });
  }

  /** 回滚到检查点（messages+工作区可独立开关）。 */
  async restoreCheckpoint(sessionId: string, runCount: number, options?: {
    messages?: boolean;
    workspace?: boolean;
  }): Promise<unknown> {
    const core = await this._core();
    return await (core as unknown as {
      restore: (input: unknown) => Promise<unknown>;
    }).restore({
      sessionId,
      checkpointRunCount: runCount,
      ...(options ? { restore: options } : {}),
    });
  }

  /** 挂起提示清单（queue/steer 排队面）。 */
  async listPendingPrompts(sessionId: string): Promise<unknown> {
    const core = await this._core();
    return await (core as unknown as {
      pendingPrompts: { list: (i: unknown) => Promise<unknown> };
    }).pendingPrompts.list({ sessionId });
  }

  /** 长命令放行（run_commands 执行中：后台继续并采集输出，解终端阻塞坑）。 */
  async proceedWhileRunning(sessionId: string, toolCallId?: string): Promise<number | null> {
    const core = await this._core();
    try {
      return await (core as unknown as {
        proceedWhileRunning?: (sid: string, tid?: string) => Promise<number>;
      }).proceedWhileRunning?.(sessionId, toolCallId) ?? null;
    } catch {
      return null;
    }
  }

  /** steer：运行中/空闲会话注入转向提示（delivery=steer，SDK 入队优先投递）。 */
  async steerTurn(sessionId: string, prompt: string): Promise<{
    ok: boolean;
    steered: boolean;
    error?: string;
  }> {
    const core = await this._core();
    const info = this._sessions.get(sessionId);
    if (info) info.lastActivityTs = Date.now();
    try {
      await (core as unknown as {
        send: (input: unknown) => Promise<Record<string, unknown> | undefined>;
      }).send({ sessionId, prompt, delivery: "steer" });
      // SDK 语义：busy → 入队 pending 立即返回；空闲 → 入队后 drain 立即执行
      return { ok: true, steered: true };
    } catch (e) {
      return {
        ok: false,
        steered: false,
        error: e instanceof Error ? e.message : String(e),
      };
    }
  }

  // ── 审批桥 ──
  private _requestApproval(request: {
    sessionId: string;
    toolCallId: string;
    toolName: string;
    input: unknown;
    policy?: unknown;
  }): Promise<ToolApprovalResult> {
    return new Promise((resolve) => {
      const requestId = `apr-${++this._approvalSeq}`;
      const timer = setTimeout(() => {
        this._approvals.delete(requestId);
        resolve({ approved: false, reason: "approval timeout (auto-denied)" });
      }, this._approvalTimeoutMs);
      this._approvals.set(requestId, (r) => {
        clearTimeout(timer);
        resolve(r);
      });
      this._emit({
        type: "approval_request",
        requestId,
        sessionId: request.sessionId,
        toolCallId: request.toolCallId,
        toolName: request.toolName,
        input: request.input,
        policy: request.policy ?? null,
      });
    });
  }

  respondApproval(requestId: string, approved: boolean, reason?: string): boolean {
    const resolve = this._approvals.get(requestId);
    if (!resolve) return false;
    this._approvals.delete(requestId);
    resolve({ approved, ...(reason ? { reason } : {}) });
    return true;
  }

  // ── 事件归一化 ──

  private _onSessionEvent(event: never): void {
    const e = event as { type?: string; payload?: Record<string, unknown> };
    const t = e?.type || "";
    const p = (e?.payload || {}) as Record<string, unknown>;
    const sid = String(p.sessionId || "");
    const info = this._sessions.get(sid);
    if (info) info.lastActivityTs = Date.now();
    switch (t) {
      case "agent_event": {
        this._onAgentEvent(sid, p.event as Record<string, unknown>);
        return;
      }
      case "chunk": {
        // stream=agent 是 agent_event 的 JSON 镜像（已由 agent_event 归一化透传），跳过防重
        if (p.stream === "agent") return;
        this._emit({
          type: "chunk", sessionId: sid, stream: p.stream,
          text: typeof p.chunk === "string" ? p.chunk : JSON.stringify(p.chunk),
        });
        return;
      }
      case "status": {
        if (info && typeof p.status === "string") info.status = p.status;
        this._emit({ type: "status", sessionId: sid, status: p.status });
        return;
      }
      case "ended": {
        if (info) {
          info.status = "ended";
          info.inflight = false;
        }
        this._emit({ type: "ended", sessionId: sid, reason: p.reason });
        return;
      }
      case "team_progress": {
        this._emit({ type: "team", sessionId: sid, payload: p });
        return;
      }
      case "pending_prompts":
      case "pending_prompt_submitted": {
        this._emit({ type: t, sessionId: sid, payload: p });
        return;
      }
      case "hook": {
        this._emit({ type: "hook", sessionId: sid, payload: p });
        return;
      }
      default:
        return; // session_snapshot 等高频/内部事件不透传
    }
  }

  private _onAgentEvent(sid: string, ev: Record<string, unknown> | undefined): void {
    if (!ev) return;
    const et = String(ev.type || "");
    const contentType = String(ev.contentType || "");
    switch (et) {
      case "content_start": {
        if (contentType === "tool") {
          this._emit({ type: "tool_start", sessionId: sid, toolName: ev.toolName, toolCallId: ev.toolCallId });
        } else if (typeof ev.text === "string" && ev.text) {
          this._emit({ type: "text", sessionId: sid, text: ev.text });
        }
        return;
      }
      case "content_update": {
        this._emit({ type: "tool_progress", sessionId: sid, toolName: ev.toolName, toolCallId: ev.toolCallId });
        return;
      }
      case "content_end": {
        if (contentType === "tool") {
          this._emit({ type: "tool_end", sessionId: sid, toolName: ev.toolName, toolCallId: ev.toolCallId });
        } else if (typeof ev.text === "string" && ev.text) {
          this._emit({ type: "text_end", sessionId: sid, text: ev.text });
        }
        return;
      }
      case "iteration_start": {
        this._emit({ type: "iteration", sessionId: sid, iteration: ev.iteration });
        return;
      }
      case "notice": {
        this._emit({
          type: "notice", sessionId: sid, noticeType: ev.noticeType,
          message: ev.message, reason: ev.reason ?? null,
        });
        return;
      }
      case "usage": {
        this._emit({
          type: "usage", sessionId: sid, inputTokens: ev.inputTokens,
          outputTokens: ev.outputTokens, cost: ev.cost ?? null,
        });
        return;
      }
      case "done": {
        this._emit({
          type: "done", sessionId: sid, reason: ev.reason,
          text: ev.text, iterations: ev.iterations,
        });
        return;
      }
      case "error": {
        const err = ev.error as { message?: string } | undefined;
        this._emit({
          type: "error", sessionId: sid,
          message: err?.message || String(ev.error || "unknown"),
          recoverable: ev.recoverable === true,
        });
        return;
      }
      default:
        return;
    }
  }

  // ── MCP 注入（P5）：每 server 独立降级，失败不影响会话启动 ──

  static normalizeMcpTransport(s: McpServerSpec): Record<string, unknown> {
    const t = s.transport
      || (s.command ? "stdio" : "streamableHttp");
    if (t === "stdio") {
      return { type: "stdio", command: s.command || "", ...(s.args ? { args: s.args } : {}),
               ...(s.cwd ? { cwd: s.cwd } : {}), ...(s.env ? { env: s.env } : {}) };
    }
    if (t === "sse") {
      return { type: "sse", url: s.url || "", ...(s.headers ? { headers: s.headers } : {}) };
    }
    return { type: "streamableHttp", url: s.url || "", ...(s.headers ? { headers: s.headers } : {}) };
  }

  private async _buildMcpTools(
    params: SessionStartParams,
    sessionId: string,
  ): Promise<unknown[]> {
    const servers = Array.isArray(params.mcpServers) ? params.mcpServers : [];
    if (!servers.length) return [];
    const { InMemoryMcpManager, createMcpTools, createDefaultMcpServerClientFactory } =
      await import("@cline/sdk");
    const manager = new InMemoryMcpManager({
      clientFactory: createDefaultMcpServerClientFactory({
        fetch: this._options.fetch,
      }),
    } as never);
    this._mcpManagers.push(manager);
    const tools: unknown[] = [];
    for (const s of servers) {
      const name = String(s?.name || "");
      if (!name) continue;
      try {
        const timeout = Math.max(60, Number(s.timeoutSeconds) || 60); // 冷启动坑: >=60s
        await (manager as unknown as {
          registerServer: (r: unknown) => Promise<void>;
        }).registerServer({
          name,
          transport: ClineCoreHost.normalizeMcpTransport(s),
          timeoutSeconds: timeout,
        });
        await (manager as unknown as {
          connectServer: (n: string) => Promise<void>;
        }).connectServer(name);
        const t = await createMcpTools({
          serverName: name,
          provider: manager,
          timeoutMs: timeout * 1000,
        } as never);
        tools.push(...(t as unknown[]));
        this._emit({ type: "mcp_ready", sessionId, server: name, tools: (t as unknown[]).length });
      } catch (e) {
        // 单 server 失败降级跳过（不拖垮会话启动）
        this._emit({
          type: "mcp_failed", sessionId, server: name,
          message: e instanceof Error ? e.message : String(e),
        });
        try {
          await (manager as unknown as {
            unregisterServer: (n: string) => Promise<void>;
          }).unregisterServer(name);
        } catch {
          /* 尽力而为 */
        }
      }
    }
    return tools;
  }

  // ── architect 资产工具 + 回合协议工具（T2）──

  /**
   * report_turn_outcome — 回合完成协议工具（lifecycle.completesRun）。
   *
   * 结构化承载 implement 协作契约：done=开发+单测+编译验收交付完成；
   * need_input=需要用户操作/确认/澄清/补充。模型显式调用 → run 立即收口，
   * 结局经 host 记录并随 TurnResult.turnOutcome 返回（文本 [[...]] 标记保留为兜底）。
   * 社区坑对齐：execute 永不 throw（异常会计入 mistake_limit 且完成信号失效）。
   */
  private _buildProtocolTools(getSid: () => string): unknown[] {
    return [
      createTool({
        name: "report_turn_outcome",
        description:
          "回合收尾时必须调用：汇报本回合结局。status=\"done\" 表示开发+单元测试+整体编译验收全部完成（附摘要：变更文件/单测结果/编译结果/遗留项）；"
          + "status=\"need_input\" 表示需要用户操作/确认/澄清/补充（附具体问题）。严禁三项交付未完成时汇报 done。除本工具外不要输出其他 [[...]] 标记。",
        inputSchema: {
          type: "object",
          properties: {
            status: { type: "string", enum: ["done", "need_input"], description: "回合结局" },
            summary: { type: "string", description: "摘要（done=交付内容；need_input=具体问题）" },
            changedFiles: { type: "array", items: { type: "string" }, description: "变更文件清单（done 时提供）" },
            notes: { type: "string", description: "备注/遗留项" },
          },
          required: ["status", "summary"],
        },
        timeoutMs: 5_000,
        lifecycle: { completesRun: true },
        execute: async (
          input: { status: string; summary: string; changedFiles?: string[]; notes?: string },
          ctx: { sessionId?: string },
        ) => {
          const status = input?.status === "done" ? "done" : "need_input";
          const outcome: TurnOutcome = {
            status,
            summary: String(input?.summary || ""),
            ...(Array.isArray(input?.changedFiles) ? { changedFiles: input.changedFiles } : {}),
            ...(input?.notes ? { notes: String(input.notes) } : {}),
          };
          this._turnOutcomes.set(ctx?.sessionId || getSid(), outcome);
          this._emit({ type: "turn_outcome", sessionId: ctx?.sessionId || getSid(), ...outcome });
          return {
            result: `outcome recorded: ${status}`,
            success: true,
          };
        },
      }),
    ];
  }

  private _buildExtraTools(params: SessionStartParams, getSid: () => string): unknown[] {
    const tools: unknown[] = [];
    if (params.archUrl && params.archToken) {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        Authorization: `Bearer ${params.archToken}`,
      };
      // 结构化错误返回（不 throw）：社区坑——工具异常会计入 mistake_limit
      tools.push(createTool({
        name: "topocode_asset_map",
        description:
          "查询本项目的组件架构资产地图（组件目录/语义资产/归属文件）。写码前先查，确保修改符合架构边界。query 支持组件名或关键词。",
        inputSchema: {
          type: "object",
          properties: {
            query: { type: "string", description: "组件名或关键词" },
            limit: { type: "number", description: "返回条数，默认 10" },
          },
          required: ["query"],
        },
        timeoutMs: 15000,
        execute: async (input: { query: string; limit?: number }, _ctx?: { sessionId?: string }) => {
          try {
            const resp = await fetch(`${params.archUrl}/api/architect/kb/assets/search`, {
              method: "POST",
              headers,
              body: JSON.stringify({
                query: input?.query || "",
                limit: input?.limit ?? 10,
                projectId: params.projectId ?? "",
              }),
            });
            const text = await resp.text();
            if (!resp.ok) {
              return {
                query: input?.query || "",
                result: `ASSET_SEARCH_ERROR http ${resp.status}: ${String(text).slice(0, 300)}`,
                success: false,
              };
            }
            return { query: input?.query || "", result: text, success: true };
          } catch (e) {
            return {
              query: input?.query || "",
              result: `ASSET_SEARCH_ERROR ${e instanceof Error ? e.message : String(e)}`,
              success: false,
            };
          }
        },
      }));
    }
    if (params.protocolTools !== false) {
      tools.push(...this._buildProtocolTools(getSid));
    }
    return tools;
  }

  // ── 释放 ──

  async dispose(): Promise<void> {
    for (const sid of [...this._sessions.keys()]) {
      try {
        await this.stop(sid);
      } catch {
        /* 尽力而为 */
      }
    }
    this._unsubscribe?.();
    this._unsubscribe = null;
    for (const mgr of this._mcpManagers.splice(0)) {
      try {
        await mgr.dispose();
      } catch {
        /* 尽力而为 */
      }
    }
    if (this._cline) {
      try {
        await this._cline.dispose();
      } catch {
        /* dispose 容错 */
      }
    }
    this._cline = null;
    this._createPromise = null;
    this._sessions.clear();
  }
}
