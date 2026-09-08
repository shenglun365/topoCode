/**
 * topoOne Cline Sidecar — architect 自主模式执行器的 Node 常驻进程。
 *
 * 协议：stdio 行分隔 JSON-RPC
 *   请求      {id, method, params} → 响应 {id, result} | {id, error:{message}}
 *   通知      {method:"event", params:{...}}（run 期间持续上报）
 * 方法：
 *   ping    {} → {ok, version}
 *   run     {taskId, prompt, cwd, providerId?, modelId?, apiKey?, baseUrl?,
 *            maxIterations?, systemPrompt?, archUrl?, archToken?, projectId?}
 *           → {success, output, changedFiles, error, iterations, usage}
 *   stop    {taskId} → {ok}
 *   dispose {} → {ok}（随后进程退出）
 * 事件（params.type）：
 *   status {taskId, stage, message?}   text-delta {taskId, text}
 *   tool   {taskId, tool, input?}      done    {taskId, success}
 */
import { createRequire } from "node:module";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import * as readline from "node:readline";
import { Agent, createTool, createBuiltinTools } from "@cline/sdk";

const execFileP = promisify(execFile);

// ── stdio JSON-RPC 基础设施 ──

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

// ── git 变更采集（cwd 前后对比，provider 无关） ──

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
    // XY PATH 或 XY ORIG -> PATH
    const p = line.slice(3);
    out.add(p.includes(" -> ") ? p.split(" -> ").pop()!.trim() : p.trim());
  }
  return [...out];
}

// ── 资产地图工具注入（architect 主 Agent 的架构资产能力直达 cline） ──

function buildAssetTools(params: RunParams) {
  const tools: unknown[] = [];
  if (params.archUrl && params.archToken) {
    const headers = {
      "Content-Type": "application/json",
      Authorization: `Bearer ${params.archToken}`,
    };
    tools.push(
      createTool({
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
        execute: async (input: { query: string; limit?: number }) => {
          const resp = await fetch(
            `${params.archUrl}/api/architect/kb/assets/search`,
            {
              method: "POST",
              headers,
              body: JSON.stringify({
                query: input.query,
                limit: input.limit ?? 10,
                projectId: params.projectId ?? "",
              }),
            },
          );
          const text = await resp.text();
          if (!resp.ok) throw new Error(`asset search ${resp.status}: ${text.slice(0, 300)}`);
          return text;
        },
      }),
    );
  }
  return tools;
}

// ── run 生命周期 ──

interface RunParams {
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

const running = new Map<string, Agent>(); // taskId → Agent

async function doRun(params: RunParams) {
  const { taskId, prompt } = params;
  const cwd = params.cwd || process.cwd();
  notify("event", { type: "status", taskId, stage: "start" });

  const before = await gitStatus(cwd);

  // 内置工具集(读/写/编辑/bash/搜索)——AgentRuntime 无任何默认工具,
  // 不注入则模型只能"读空气"交白卷; 资产地图工具按需附加
  const builtin = createBuiltinTools({ cwd }) as unknown[];
  const tools = [...builtin, ...buildAssetTools(params)];

  const agent = new Agent({
    providerId: params.providerId || process.env.CLINE_PROVIDER_ID || "cline",
    modelId: params.modelId || process.env.CLINE_MODEL_ID || undefined,
    apiKey: params.apiKey || process.env.CLINE_API_KEY || undefined,
    maxIterations: params.maxIterations ?? 40,
    ...(params.systemPrompt ? { systemPrompt: params.systemPrompt } : {}),
    ...(params.baseUrl ? { baseUrl: params.baseUrl } : {}),
    tools: tools as never,
  } as never);
  running.set(taskId, agent);

  let outputText = "";
  agent.subscribe((event: { type?: string; text?: string }) => {
    try {
      const t = event?.type || "";
      if (t === "assistant-text-delta" && event.text) {
        outputText += event.text;
        notify("event", { type: "text-delta", taskId, text: event.text });
      } else if (t && /^(status|state|error|tool)/.test(t)) {
        notify("event", { type: "tool", taskId, tool: t });
      }
    } catch {
      /* 事件容忍 */
    }
  });

  try {
    const result = (await agent.run(prompt)) as {
      status?: string;
      outputText?: string;
      error?: Error;
      iterations?: number;
      usage?: unknown;
    };
    const after = await gitStatus(cwd);
    // 状态行级 diff：新增/消失/变化的行 → 归属文件（排除 run 前就脏且状态未变的文件）
    const beforeSet = new Set(before);
    const afterSet = new Set(after);
    const changedLines = [
      ...after.filter((l: string) => !beforeSet.has(l)),
      ...before.filter((l: string) => !afterSet.has(l)),
    ];
    const changed = parseStatusPaths(changedLines);
    const success = !result?.error && result?.status !== "error";
    notify("event", { type: "done", taskId, success });
    return {
      success,
      output: result?.outputText || outputText || "",
      changedFiles: changed,
      error: result?.error ? String(result.error.message || result.error) : "",
      iterations: result?.iterations ?? 0,
      usage: result?.usage ?? null,
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    notify("event", { type: "done", taskId, success: false });
    return {
      success: false,
      output: outputText,
      changedFiles: [],
      error: message,
      iterations: 0,
      usage: null,
    };
  } finally {
    running.delete(taskId);
  }
}

// ── 分发 ──

const require_ = createRequire(import.meta.url);
let pkgVersion = "0.0.0";
try {
  pkgVersion = require_("../package.json").version;
} catch {
  /* noop */
}

const rl = readline.createInterface({ input: process.stdin });
rl.on("line", (line) => {
  const s = line.trim();
  if (!s) return;
  let msg: { id?: number; method?: string; params?: unknown };
  try {
    msg = JSON.parse(s);
  } catch {
    return;
  }
  const { id, method, params } = msg;
  if (!method) return;
  switch (method) {
    case "ping":
      reply(id ?? 0, { ok: true, version: pkgVersion, node: process.version });
      break;
    case "run":
      doRun((params ?? {}) as RunParams)
        .then((r) => reply(id ?? 0, r))
        .catch((e) => replyErr(id ?? 0, String(e)));
      break;
    case "stop": {
      const taskId = ((params ?? {}) as { taskId?: string }).taskId || "";
      const agent = running.get(taskId);
      if (agent) {
        try {
          (agent as unknown as { abort: (r?: string) => void }).abort("stopped by runner");
        } catch {
          /* noop */
        }
      }
      reply(id ?? 0, { ok: true });
      break;
    }
    case "dispose":
      reply(id ?? 0, { ok: true });
      setTimeout(() => process.exit(0), 50);
      break;
    default:
      replyErr(id ?? 0, `unknown method: ${method}`);
  }
});

process.stdin.on("end", () => process.exit(0));
notify("event", { type: "ready", taskId: "", version: pkgVersion });
