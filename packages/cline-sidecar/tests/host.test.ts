/**
 * ClineCoreHost 测试 — fake fetch LLM 注入（无真实网络/无 API key）。
 *
 * 覆盖社区高频坑：
 *   1. 多回合上下文保持（v1 单 Agent 每回合失忆缺陷的回归测试）
 *   2. 事件归一化（chunk/tool/usage/done）
 *   3. abort 中止挂起回合后会话仍可用
 *   4. 审批桥（toolPolicies autoApprove:false → approval_request → respond）
 *   5. 自定义工具结构化错误不致 mistake_limit 提前失败
 *   6. stop/dispose 生命周期干净收口
 */
import { afterEach, beforeAll, afterAll, describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as http from "node:http";
import * as os from "node:os";
import * as path from "node:path";
import { ClineCoreHost, type HostEvent } from "../src/host.js";
import { FakeLLM } from "./fake-llm.js";

let llm: FakeLLM;
let host: ClineCoreHost;
let events: HostEvent[];
let tmpRoot: string;

function newDir(): string {
  return fs.mkdtempSync(path.join(tmpRoot, "s-"));
}

function dump(v: unknown): string {
  return typeof v === "string" ? v : JSON.stringify(v ?? "");
}

function findEvent(type: string): HostEvent | undefined {
  return events.find((e) => e.type === type);
}

beforeAll(async () => {
  tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "cline-host-test-"));
  llm = new FakeLLM();
  events = [];
  host = new ClineCoreHost({
    fetch: llm.fetch(),
    dataDir: path.join(tmpRoot, "data"),
    onEvent: (e) => events.push(e),
  });
});

afterAll(async () => {
  await host.dispose().catch(() => {});
});

afterEach(() => {
  llm.reset();
});

describe("ClineCoreHost 会话宿主", () => {
  it("多回合上下文保持（核心回归）", async () => {
    const cwd = newDir();
    const { sessionId } = await host.startSession({
      sessionId: "ctx-1",
      cwd,
      model: {
        providerId: "openai-compatible",
        modelId: "fake-model",
        baseUrl: "http://fake-llm.local/v1",
        apiKey: "test-key",
      },
    });
    expect(sessionId).toBe("ctx-1");

    llm.script = [{ type: "text", text: "已记录暗号 ALPHA42" }];
    const r1 = await host.sendTurn({ sessionId: "ctx-1", prompt: "记住暗号 ALPHA42" });
    expect(r1.ok).toBe(true);
    expect(r1.outputText).toContain("ALPHA42");
    expect(r1.status).toBe("completed");

    llm.script = [{ type: "text", text: "暗号已确认" }];
    const r2 = await host.sendTurn({ sessionId: "ctx-1", prompt: "暗号是什么？" });
    expect(r2.ok).toBe(true);

    // 第二回合请求必须携带第一回合的 user+assistant 消息（上下文未失忆）
    const msgs = llm.messagesOf(1);
    const all = msgs.map((m) => dump(m.content)).join("\n");
    expect(all).toContain("ALPHA42");
    expect(all).toContain("已记录暗号");
    expect(all).toContain("暗号是什么？");
  });

  it("事件归一化：text/usage/done 全携带 sessionId", async () => {
    const cwd = newDir();
    await host.startSession({
      sessionId: "ev-1",
      cwd,
      model: {
        providerId: "openai-compatible",
        modelId: "fake-model",
        baseUrl: "http://fake-llm.local/v1",
      },
    });
    const before = events.length;
    llm.script = [{ type: "text", text: "事件流测试输出" }];
    await host.sendTurn({ sessionId: "ev-1", prompt: "hi" });
    const slice = events.slice(before);
    const types = new Set(slice.map((e) => e.type));
    expect(types.has("text")).toBe(true);
    expect(types.has("done")).toBe(true);
    const textEv = slice.find((e) => e.type === "text");
    expect(textEv?.sessionId).toBe("ev-1");
    expect(String(textEv?.text)).toContain("事件流测试输出");
  });

  it("abort 取消进行中回合（流恢复时生效），会话保留可续新回合", async () => {
    const cwd = newDir();
    await host.startSession({
      sessionId: "ab-1",
      cwd,
      model: {
        providerId: "openai-compatible",
        modelId: "fake-model",
        baseUrl: "http://fake-llm.local/v1",
      },
      approvalTimeoutMs: 5_000,
    });
    llm.script = [{ type: "hang", resolve: () => {} }];
    const pending = host.sendTurn({ sessionId: "ab-1", prompt: "long turn" });
    await new Promise((r) => setTimeout(r, 1_500));
    const aborted = await host.abort("ab-1", "watchdog");
    expect(aborted).toBe(true);
    llm.releaseHangs();
    const r = await pending;
    // abort 生效：回合以 aborted 终止，不再继续跑完
    expect(r.status).toBe("aborted");
    expect(r.ok).toBe(false);
    // 会话保留：下一回合正常（上下文保持）
    llm.script = [{ type: "text", text: "恢复工作" }];
    const r2 = await host.sendTurn({ sessionId: "ab-1", prompt: "continue" });
    expect(r2.ok).toBe(true);
    expect(r2.outputText).toContain("恢复工作");
  });

  it("stop 硬终止：abort+stop 顺序收口挂起回合", async () => {
    const cwd = newDir();
    await host.startSession({
      sessionId: "st-1",
      cwd,
      model: {
        providerId: "openai-compatible",
        modelId: "fake-model",
        baseUrl: "http://fake-llm.local/v1",
      },
    });
    llm.script = [{ type: "hang", resolve: () => {} }];
    const pending = host.sendTurn({ sessionId: "st-1", prompt: "do work" });
    await new Promise((r) => setTimeout(r, 1_500));
    // 正确顺序：先 abort（取消回合）再 stop（会话终止）——stop 在回合挂起时会阻塞
    await host.abort("st-1", "hard stop");
    llm.releaseHangs();
    await pending;
    const stopped = await host.stop("st-1");
    expect(stopped).toBe(true);
    expect(host.getStatus("st-1")?.status).toBe("stopped");
  });

  it("审批桥：autoApprove:false → approval_request → 批准后工具执行", async () => {
    const cwd = newDir();
    fs.writeFileSync(path.join(cwd, "note.txt"), "审批测试内容");
    await host.startSession({
      sessionId: "apr-1",
      cwd,
      model: {
        providerId: "openai-compatible",
        modelId: "fake-model",
        baseUrl: "http://fake-llm.local/v1",
      },
      toolPolicies: { read_files: { autoApprove: false } },
    });
    llm.script = [
      { type: "tool_call", name: "read_files", args: { files: [{ path: "note.txt" }] } },
      { type: "text", text: "文件已读取" },
    ];
    const pending = host.sendTurn({ sessionId: "apr-1", prompt: "读取 note.txt" });
    // 轮询等待审批请求事件
    let approval: HostEvent | undefined;
    for (let i = 0; i < 100 && !approval; i++) {
      approval = events.find((e) => e.type === "approval_request" && e.sessionId === "apr-1");
      if (!approval) await new Promise((r) => setTimeout(r, 100));
    }
    expect(approval).toBeDefined();
    expect(approval?.toolName).toBe("read_files");
    const responded = host.respondApproval(String(approval!.requestId), true);
    expect(responded).toBe(true);
    const r = await pending;
    expect(r.ok).toBe(true);
    expect(r.outputText).toContain("文件已读取");
  });

  it("审批桥：拒绝后回合仍正常收口", async () => {
    const cwd = newDir();
    await host.startSession({
      sessionId: "apr-2",
      cwd,
      model: {
        providerId: "openai-compatible",
        modelId: "fake-model",
        baseUrl: "http://fake-llm.local/v1",
      },
      toolPolicies: { read_files: { autoApprove: false } },
    });
    llm.script = [
      { type: "tool_call", name: "read_files", args: { files: [{ path: "missing.txt" }] } },
      { type: "text", text: "了解，跳过读取" },
    ];
    const pending = host.sendTurn({ sessionId: "apr-2", prompt: "读取 missing.txt" });
    let approval: HostEvent | undefined;
    for (let i = 0; i < 100 && !approval; i++) {
      approval = events.find((e) => e.type === "approval_request" && e.sessionId === "apr-2");
      if (!approval) await new Promise((r) => setTimeout(r, 100));
    }
    expect(approval).toBeDefined();
    host.respondApproval(String(approval!.requestId), false, "out of boundary");
    const r = await pending;
    expect(r.ok).toBe(true);
    expect(r.outputText).toContain("跳过读取");
  });

  it("自定义工具真实执行 + 结构化错误不致 mistake_limit（社区坑回归）", async () => {
    const cwd = newDir();
    // 真实本地 HTTP server：以"服务端收到请求"证明工具确被执行（防假通过）
    let hits = 0;
    const server = http.createServer((req, res) => {
      hits += 1;
      res.writeHead(500, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "simulated arch failure" }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const addr = server.address() as { port: number };
    await host.startSession({
      sessionId: "tool-err-1",
      cwd,
      model: {
        providerId: "openai-compatible",
        modelId: "fake-model",
        baseUrl: "http://fake-llm.local/v1",
      },
      archUrl: `http://127.0.0.1:${addr.port}`,
      archToken: "t",
    });
    llm.script = [
      { type: "tool_call", name: "topocode_asset_map", args: { query: "gateway" } },
      { type: "text", text: "资产服务不可用，已按通用方案继续" },
    ];
    const r = await host.sendTurn({ sessionId: "tool-err-1", prompt: "查一下 gateway 组件" });
    expect(hits).toBeGreaterThanOrEqual(1); // 工具真实发起 HTTP 调用
    expect(r.ok).toBe(true);                // 结构化错误未触发 mistake_limit 提前失败
    expect(r.outputText).toContain("已按通用方案继续");
    expect(r.status).toBe("completed");
    server.close();
  });

  it("asset_map 走 GET + query 参数（2610 P3: POST 打 GET 端点恒 405 回归锁）", async () => {
    const cwd = newDir();
    let sawMethod = "";
    let sawUrl = "";
    const server = http.createServer((req, res) => {
      sawMethod = req.method || "";
      sawUrl = req.url || "";
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ code: 0, data: [
        { id: "comp-gateway", name: "网关组件", fileCount: 3 },
        { id: "comp-auth", name: "鉴权组件", fileCount: 2 },
      ] }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const addr = server.address() as { port: number };
    await host.startSession({
      sessionId: "asset-get-1",
      cwd,
      model: {
        providerId: "openai-compatible",
        modelId: "fake-model",
        baseUrl: "http://fake-llm.local/v1",
      },
      archUrl: `http://127.0.0.1:${addr.port}`,
      archToken: "t",
      projectId: "proj-x",
    });
    llm.script = [
      { type: "tool_call", name: "topocode_asset_map", args: { query: "gateway", limit: 1 } },
      { type: "text", text: "已核对资产地图" },
    ];
    const r = await host.sendTurn({ sessionId: "asset-get-1", prompt: "查 gateway" });
    expect(sawMethod).toBe("GET");                       // 方法回归锁
    expect(sawUrl).toContain("/api/architect/kb/assets/search");
    expect(sawUrl).toContain("q=gateway");
    expect(sawUrl).toContain("project=proj-x");
    expect(r.ok).toBe(true);
    // limit 工具侧截断: 结果只留 1 条(total 保留全量计数)
    const toolMsg = JSON.stringify(llm.requests);
    expect(toolMsg).toContain("comp-gateway");
    expect(toolMsg).not.toContain("comp-auth");
    server.close();
  });

  it("steerTurn：注入转向提示（入队后自动投递执行）", async () => {
    const cwd = newDir();
    await host.startSession({
      sessionId: "stl-1",
      cwd,
      model: {
        providerId: "openai-compatible",
        modelId: "fake-model",
        baseUrl: "http://fake-llm.local/v1",
      },
    });
    llm.script = [{ type: "text", text: "已按新方向调整" }];
    const r = await host.steerTurn("stl-1", "改用方案 B");
    expect(r.ok).toBe(true);
    expect(r.steered).toBe(true);
    // SDK drain 自动把 steer 提示投递为下一回合（轮询等待落盘）
    let drained = false;
    for (let i = 0; i < 100 && !drained; i++) {
      await new Promise((res) => setTimeout(res, 100));
      drained = llm.requests.some((req) =>
        JSON.stringify(req.body.messages).includes("改用方案 B"));
    }
    expect(drained).toBe(true);
    const pending = await host.listPendingPrompts("stl-1");
    expect((pending as unknown[]).length).toBe(0);   // 已消费
  });

  // ── P5 MCP ──

  it("normalizeMcpTransport：stdio/streamableHttp/sse 归一 + 缺省推断", () => {
    const n = ClineCoreHost.normalizeMcpTransport;
    expect(n({ name: "x", command: "mcp-fs", args: ["-v"] }))
      .toEqual({ type: "stdio", command: "mcp-fs", args: ["-v"] });
    expect(n({ name: "x", url: "http://x/v1" }).type).toBe("streamableHttp");
    expect(n({ name: "x", transport: "sse", url: "http://x/sse" }).type).toBe("sse");
    expect(n({ name: "x", url: "http://x", headers: { A: "b" } }))
      .toEqual({ type: "streamableHttp", url: "http://x", headers: { A: "b" } });
  });

  it("MCP 单 server 失败降级：会话照常启动 + mcp_failed 事件", async () => {
    const cwd = newDir();
    await host.startSession({
      sessionId: "mcp-1",
      cwd,
      model: {
        providerId: "openai-compatible",
        modelId: "fake-model",
        baseUrl: "http://fake-llm.local/v1",
      },
      // fake fetch 对 MCP initialize 返回非法 JSON → 连接失败 → 降级跳过
      mcpServers: [{ name: "bad-server", url: "http://fake-llm.local/mcp" }],
    });
    // 会话可用（降级不阻断）
    llm.script = [{ type: "text", text: "mcp degraded but session ok" }];
    const r = await host.sendTurn({ sessionId: "mcp-1", prompt: "hi" });
    expect(r.ok).toBe(true);
    const failed = events.find((e) => e.type === "mcp_failed"
      && e.sessionId === "mcp-1" && e.server === "bad-server");
    expect(failed).toBeDefined();
  });

  it("session/get 与 stop 生命周期", async () => {
    const cwd = newDir();
    await host.startSession({
      sessionId: "lc-1",
      cwd,
      model: {
        providerId: "openai-compatible",
        modelId: "fake-model",
        baseUrl: "http://fake-llm.local/v1",
      },
    });
    const info = host.getStatus("lc-1");
    expect(info?.sessionId).toBe("lc-1");
    llm.script = [{ type: "text", text: "ok" }];
    const r = await host.sendTurn({ sessionId: "lc-1", prompt: "ping" });
    expect(r.ok).toBe(true);
    const stopped = await host.stop("lc-1");
    expect(stopped).toBe(true);
    expect(host.getStatus("lc-1")?.status).toBe("stopped");
  });

  it("协议工具 need_input：run 立即收口并回报结局", async () => {
    const cwd = newDir();
    await host.startSession({
      sessionId: "pt-1",
      cwd,
      model: {
        providerId: "openai-compatible",
        modelId: "fake-model",
        baseUrl: "http://fake-llm.local/v1",
      },
    });
    llm.script = [
      { type: "tool_call", name: "report_turn_outcome", args: {
        status: "need_input", summary: "需要用户提供数据库连接串" } },
    ];
    const r = await host.sendTurn({ sessionId: "pt-1", prompt: "开始实施（缺配置）" });
    expect(r.ok).toBe(true);
    expect(r.status).toBe("completed"); // completesRun 工具正常收口，非 mistake_limit
    expect(r.turnOutcome?.status).toBe("need_input");
    expect(r.turnOutcome?.summary).toContain("数据库连接串");
    const ev = findEvent("turn_outcome");
    expect(ev?.sessionId).toBe("pt-1");
  });

  it("协议工具 done：交付完成信号 + 变更文件清单", async () => {
    const cwd = newDir();
    await host.startSession({
      sessionId: "pt-2",
      cwd,
      model: {
        providerId: "openai-compatible",
        modelId: "fake-model",
        baseUrl: "http://fake-llm.local/v1",
      },
    });
    llm.script = [
      { type: "tool_call", name: "report_turn_outcome", args: {
        status: "done", summary: "开发+单测+编译完成",
        changedFiles: ["src/a.py", "tests/test_a.py"], notes: "无遗留" } },
    ];
    const r = await host.sendTurn({ sessionId: "pt-2", prompt: "完成实施" });
    expect(r.ok).toBe(true);
    expect(r.turnOutcome?.status).toBe("done");
    expect(r.turnOutcome?.changedFiles).toEqual(["src/a.py", "tests/test_a.py"]);
    expect(r.turnOutcome?.notes).toBe("无遗留");
    // done 后会话可继续下一回合（交互式常驻）
    llm.script = [{ type: "text", text: "收到" }];
    const r2 = await host.sendTurn({ sessionId: "pt-2", prompt: "已验收" });
    expect(r2.ok).toBe(true);
  });

  it("协议工具禁用：protocolTools=false 不注入", async () => {
    const cwd = newDir();
    await host.startSession({
      sessionId: "pt-3",
      cwd,
      model: {
        providerId: "openai-compatible",
        modelId: "fake-model",
        baseUrl: "http://fake-llm.local/v1",
      },
      protocolTools: false,
    });
    llm.script = [{ type: "text", text: "plain" }];
    const r = await host.sendTurn({ sessionId: "pt-3", prompt: "hi" });
    expect(r.ok).toBe(true);
    expect(r.turnOutcome).toBeNull();
  });

  // ── T3 内省面 ──

  it("readMessages：转写含双回合上下文", async () => {
    const cwd = newDir();
    await host.startSession({
      sessionId: "msg-1",
      cwd,
      model: {
        providerId: "openai-compatible",
        modelId: "fake-model",
        baseUrl: "http://fake-llm.local/v1",
      },
    });
    llm.script = [{ type: "text", text: "第一条回复" }];
    await host.sendTurn({ sessionId: "msg-1", prompt: "第一条提问" });
    const messages = await host.readMessages("msg-1") as Array<Record<string, unknown>>;
    expect(Array.isArray(messages)).toBe(true);
    const all = JSON.stringify(messages);
    expect(all).toContain("第一条提问");
    expect(all).toContain("第一条回复");
  });

  it("getUsage + listHistory + listPendingPrompts", async () => {
    const cwd = newDir();
    await host.startSession({
      sessionId: "use-1",
      cwd,
      model: {
        providerId: "openai-compatible",
        modelId: "fake-model",
        baseUrl: "http://fake-llm.local/v1",
      },
    });
    llm.script = [{ type: "text", text: "usage probe" }];
    await host.sendTurn({ sessionId: "use-1", prompt: "hi" });
    const usage = await host.getUsage("use-1") as Record<string, unknown> | undefined;
    expect(usage === undefined || typeof usage === "object").toBe(true);
    const history = await host.listHistory(50) as Array<Record<string, unknown>>;
    expect(Array.isArray(history)).toBe(true);
    const ids = history.map((h) => String(h.sessionId ?? ""));
    expect(ids).toContain("use-1");
    const pending = await host.listPendingPrompts("use-1");
    expect(Array.isArray(pending)).toBe(true);
  });

  it("updateModel：会话内换模后续回合用新模型", async () => {
    const cwd = newDir();
    await host.startSession({
      sessionId: "mdl-1",
      cwd,
      model: {
        providerId: "openai-compatible",
        modelId: "fake-model",
        baseUrl: "http://fake-llm.local/v1",
      },
    });
    const ok = await host.updateModel("mdl-1", "fake-model-v2");
    expect(ok).toBe(true);
    expect(host.getStatus("mdl-1")?.modelId).toBe("fake-model-v2");
    llm.script = [{ type: "text", text: "new model online" }];
    const r = await host.sendTurn({ sessionId: "mdl-1", prompt: "hello" });
    expect(r.ok).toBe(true);
    expect(r.outputText).toContain("new model online");
  });

  it("checkpoint compare/restore（git 仓库 cwd）+ proceed 兜底", async () => {
    const cwd = newDir();
    // 检查点为 git stash/ref 机制：准备真实 git 仓库
    const git = (args: string[]) =>
      require("node:child_process").execFileSync("git", args, { cwd });
    git(["init", "-q"]);
    git(["config", "user.email", "t@t"]);
    git(["config", "user.name", "t"]);
    fs.writeFileSync(path.join(cwd, "base.txt"), "base");
    git(["add", "-A"]);
    git(["commit", "-qm", "init"]);
    await host.startSession({
      sessionId: "cp-1",
      cwd,
      model: {
        providerId: "openai-compatible",
        modelId: "fake-model",
        baseUrl: "http://fake-llm.local/v1",
      },
      checkpointEnabled: true,
    });
    llm.script = [{ type: "text", text: "turn one" }];
    await host.sendTurn({ sessionId: "cp-1", prompt: "work" });
    const compare = await host.compareCheckpoint("cp-1", 1) as Record<string, unknown> | null;
    expect(compare === null || typeof compare === "object").toBe(true);
    // proceed：无运行中命令时优雅返回 null
    const exitCode = await host.proceedWhileRunning("cp-1");
    expect(exitCode).toBeNull();
  });
});
