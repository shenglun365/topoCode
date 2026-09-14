/**
 * topoOne Cline Sidecar v2 — architect 核心 coding agent 执行器（ClineCore 会话宿主）。
 *
 * 协议：stdio 行分隔 JSON-RPC
 *   请求      {id, method, params} → 响应 {id, result} | {id, error:{message}}
 *   通知      {method:"event", params:{...}}（会话事件持续上报，携带 sessionId）
 *
 * v2 方法（ClineCore 会话宿主，见 host.ts）：
 *   session/start     {sessionId?, cwd, workspaceRoot?, model{providerId,modelId,apiKey?,baseUrl?,...},
 *                      systemPrompt?, mode?, toolPolicies?, enableTools?, enableAgentTeams?,
 *                      yolo?, checkpointEnabled?, compaction?, skills?, teamName?,
 *                      archUrl?, archToken?, projectId?} → {sessionId}
 *   turn/send         {sessionId, prompt, mode?, delivery?, timeoutMs?}
 *                     → {ok, status, outputText, iterations, usage, error}
 *   session/abort     {sessionId, reason?} → {ok}   中止当前回合（会话保留）
 *   session/stop      {sessionId} → {ok}            优雅终止会话
 *   session/get       {sessionId} → {ok, session}
 *   approval/respond  {requestId, approved, reason?} → {ok}
 *   dispose           {} → {ok}（stop 全部会话 + cline.dispose 后进程退出）
 *
 * v1 兼容方法（单回合 shim，会话保留以支撑 sessionRef 复活）：
 *   run               {taskId, prompt, cwd, providerId?, modelId?, apiKey?, baseUrl?,
 *                      maxIterations?, systemPrompt?, archUrl?, archToken?, projectId?}
 *                     → {success, output, changedFiles, error, iterations, usage}
 *   stop              {taskId} → {ok}（映射 session/abort）
 *
 * 事件（params.type）：
 *   ready | text | text_end | tool_start | tool_end | tool_progress | iteration
 *   | notice | usage | done | error | status | ended | team | pending_prompts
 *   | approval_request
 */
import * as readline from "node:readline";
import { ClineCoreHost } from "./host.js";

function send(obj: unknown) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

function reply(id: number, result: unknown) {
  send({ id, result });
}

function replyErr(id: number, message: string) {
  send({ id, error: { message } });
}

function notify(method: string, params: unknown) {
  send({ method, params });
}

// ── git 变更采集（v1 run 兼容：cwd 前后对比，provider 无关）──

import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileP = promisify(execFile);

async function gitStatus(cwd: string): Promise<string[]> {
  try {
    const { stdout } = await execFileP("git", ["status", "--porcelain", "-uall"], { cwd });
    return stdout.split("\n").filter(Boolean);
  } catch {
    return [];
  }
}

function parseStatusPaths(lines: string[]): string[] {
  const out = new Set<string>();
  for (const line of lines) {
    const p = line.slice(3);
    out.add(p.includes(" -> ") ? p.split(" -> ").pop()!.trim() : p.trim());
  }
  return [...out];
}

// ── 宿主 ──

const host = new ClineCoreHost({
  onEvent: (event) => notify("event", event),
});

const running = new Map<string, Promise<unknown>>(); // taskId → 进行中回合（v1）

// ── v1 兼容 shim ──

interface LegacyRunParams {
  taskId: string;
  prompt: string;
  cwd?: string;
  providerId?: string;
  modelId?: string;
  apiKey?: string;
  baseUrl?: string;
  maxIterations?: number;
  systemPrompt?: string;
  archUrl?: string;
  archToken?: string;
  projectId?: string;
}

async function legacyRun(params: LegacyRunParams) {
  const taskId = params.taskId || `task-${Date.now()}`;
  const cwd = params.cwd || process.cwd();
  const before = await gitStatus(cwd);
  const existing = host.sessions.get(taskId);
  if (!existing) {
    await host.startSession({
      sessionId: taskId,
      cwd,
      model: {
        providerId: params.providerId || process.env.CLINE_PROVIDER_ID || "cline",
        modelId: params.modelId || process.env.CLINE_MODEL_ID || "",
        apiKey: params.apiKey || process.env.CLINE_API_KEY || undefined,
        baseUrl: params.baseUrl || undefined,
      },
      maxIterations: params.maxIterations ?? 40,
      systemPrompt: params.systemPrompt,
      archUrl: params.archUrl,
      archToken: params.archToken,
      projectId: params.projectId,
    });
  }
  const result = await host.sendTurn({ sessionId: taskId, prompt: params.prompt });
  const after = await gitStatus(cwd);
  const beforeSet = new Set(before);
  const afterSet = new Set(after);
  const changedLines = [
    ...after.filter((l: string) => !beforeSet.has(l)),
    ...before.filter((l: string) => !afterSet.has(l)),
  ];
  // 协议工具结局 → v1 文本标记（旧 adapter 兼容；结构化 turnOutcome 随 v2 面交付）
  let output = result.outputText;
  if (result.turnOutcome?.status === "done" && !output.includes("[[IMPLEMENT_DONE]]")) {
    output += `\n[[IMPLEMENT_DONE]] ${result.turnOutcome.summary}`.trimEnd();
  } else if (result.turnOutcome?.status === "need_input" && !output.includes("[[NEED_INPUT]]")) {
    output += `\n[[NEED_INPUT]] ${result.turnOutcome.summary}`.trimEnd();
  }
  return {
    success: result.ok,
    output,
    changedFiles: parseStatusPaths(changedLines),
    error: result.error,
    iterations: result.iterations,
    usage: result.usage,
  };
}

// ── 分发 ──

import { createRequire } from "node:module";
const require_ = createRequire(import.meta.url);
let pkgVersion = "0.0.0";
try {
  pkgVersion = require_("../package.json").version;
} catch {
  /* noop */
}

const rl = readline.createInterface({ input: process.stdin });
let disposed = false;

async function dispatch(method: string, params: Record<string, unknown>): Promise<unknown> {
  switch (method) {
    case "ping":
      return { ok: true, version: pkgVersion, node: process.version };
    case "session/start":
      return host.startSession(params as never);
    case "turn/send": {
      const p = params as { sessionId: string } & Record<string, unknown>;
      const inflight = running.get(p.sessionId);
      if (inflight) throw new Error("turn already in flight for session");
      const task = host.sendTurn(p as never);
      running.set(p.sessionId, task);
      try {
        return await task;
      } finally {
        running.delete(p.sessionId);
      }
    }
    case "session/abort":
      return { ok: await host.abort(String(params.sessionId || ""), params.reason as string | undefined) };
    case "turn/steer": {
      const p = params as { sessionId: string; prompt: string };
      if (!p.sessionId || !String(p.prompt || "").trim()) {
        throw new Error("sessionId/prompt 为空");
      }
      return host.steerTurn(p.sessionId, p.prompt);
    }
    case "session/stop":
      return { ok: await host.stop(String(params.sessionId || "")) };
    case "session/get": {
      const info = host.getStatus(String(params.sessionId || ""));
      return info ? { ok: true, session: info } : { ok: false, error: "session not found" };
    }
    case "approval/respond":
      return { ok: host.respondApproval(
        String(params.requestId || ""),
        params.approved === true,
        params.reason as string | undefined) };
    case "session/messages":
      return { ok: true, messages: await host.readMessages(
        String(params.sessionId || ""), params.display !== false) };
    case "session/usage":
      return { ok: true, usage: await host.getUsage(String(params.sessionId || "")) };
    case "session/model":
      return { ok: await host.updateModel(
        String(params.sessionId || ""), String(params.modelId || "")) };
    case "session/connection":
      return { ok: await host.updateConnection(
        String(params.sessionId || ""),
        (params.updates || {}) as Record<string, never>) };
    case "history/list":
      return { ok: true, sessions: await host.listHistory(Number(params.limit || 50)) };
    case "checkpoint/compare":
      return { ok: true, compare: await host.compareCheckpoint(
        String(params.sessionId || ""), Number(params.runCount || 0)) };
    case "session/restore":
      return { ok: true, restore: await host.restoreCheckpoint(
        String(params.sessionId || ""), Number(params.runCount || 0),
        params.options as { messages?: boolean; workspace?: boolean } | undefined) };
    case "session/pending":
      return { ok: true, prompts: await host.listPendingPrompts(String(params.sessionId || "")) };
    case "session/proceed":
      return { ok: true, exitCode: await host.proceedWhileRunning(
        String(params.sessionId || ""),
        typeof params.toolCallId === "string" ? params.toolCallId : undefined) };
    case "run":
      return legacyRun(params as unknown as LegacyRunParams);
    case "stop":
      return { ok: await host.abort(String(params.taskId || ""), "stopped by runner") };
    case "dispose":
      disposed = true;
      await host.dispose();
      // 旧版语义保留：dispose 后进程退出（延迟让 stdout 响应先冲刷）
      setTimeout(() => process.exit(0), 50);
      return { ok: true };
    default:
      throw new Error(`unknown method: ${method}`);
  }
}

rl.on("line", (line) => {
  const s = line.trim();
  if (!s || disposed) return;
  let msg: { id?: number; method?: string; params?: Record<string, unknown> };
  try {
    msg = JSON.parse(s);
  } catch {
    return;
  }
  const { id, method, params } = msg;
  if (!method) return;
  dispatch(method, params || {})
    .then((r) => reply(id ?? 0, r))
    .catch((e) => replyErr(id ?? 0, e instanceof Error ? e.message : String(e)));
});

process.stdin.on("end", () => {
  // 通道关闭：尽力释放（不阻塞退出）
  host.dispose().finally(() => process.exit(0));
});

process.on("SIGTERM", () => {
  host.dispose().finally(() => process.exit(0));
});

process.on("SIGINT", () => {
  host.dispose().finally(() => process.exit(0));
});

notify("event", { type: "ready", taskId: "", version: pkgVersion });
